# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from project_resolver import project_from_encoded_path, resolve_project_name
from time_utils import parse_optional_iso8601_utc

logger = logging.getLogger(__name__)

# Must comfortably exceed a real user's total *.jsonl file count. A cap at or
# below that count means every load_entries() call evicts and re-parses files
# that were just cached last refresh (LRU thrashing) — measured 512 capped at
# 640 real project files into a permanent 3+ second full-reparse every single
# call, even with per-file incremental caching working correctly in isolation.
_FILE_CACHE_MAXSIZE = 4096


@dataclass(slots=True)
class _FileCacheEntry:
    mtime: float
    size: int
    entries: list[UsageEntry]
    confirmed_offset: int
    confirmed_prefix_digest: bytes


_file_cache: OrderedDict[Path, _FileCacheEntry] = OrderedDict()

CLAUDE_PROJECTS_DIR = Path(os.path.expanduser("~/.claude/projects"))


@dataclass(slots=True)
class UsageEntry:
    timestamp: datetime
    session_id: str
    message_id: str
    request_id: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    cost_usd: float | None
    project: str

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_creation_tokens
            + self.cache_read_tokens
        )


def load_entries(
    hours_back: int = 0,
    *,
    jsonl_paths: Iterable[Path] | None = None,
) -> list[UsageEntry]:
    entries: list[UsageEntry] = []
    seen: set[str] = set()
    cutoff = datetime.now(UTC) - timedelta(hours=hours_back) if hours_back > 0 else None

    if jsonl_paths is None and not CLAUDE_PROJECTS_DIR.is_dir():
        return []

    cutoff_ts = cutoff.timestamp() if cutoff else None
    paths = (
        tuple(CLAUDE_PROJECTS_DIR.rglob("*.jsonl"))
        if jsonl_paths is None
        else tuple(jsonl_paths)
    )
    for jsonl_path in paths:
        if cutoff_ts is not None:
            try:
                if jsonl_path.stat().st_mtime < cutoff_ts:
                    continue
            except OSError as exc:
                logger.warning("failed to stat Claude project log %s: %s", jsonl_path, exc)
                continue
        project = _project_from_path(jsonl_path)
        _load_file(jsonl_path, project, cutoff, seen, entries)

    entries.sort(key=lambda entry: entry.timestamp)
    return entries


def _load_file(
    path: Path,
    project: str,
    cutoff: datetime | None,
    seen: set[str],
    entries: list[UsageEntry],
) -> None:
    try:
        st = path.stat()
    except OSError as exc:
        logger.warning("failed to stat Claude project log %s: %s", path, exc)
        return

    cached = _file_cache.get(path)
    if cached is not None and cached.mtime == st.st_mtime and cached.size == st.st_size:
        _file_cache.move_to_end(path)
        for entry in cached.entries:
            if cutoff is not None and entry.timestamp < cutoff:
                continue
            dedup_key = _dedup_key(entry)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            entries.append(entry)
        return

    refreshed = _refresh_cache(path, st, project, cached)
    if refreshed is None:
        return

    if path not in _file_cache and len(_file_cache) >= _FILE_CACHE_MAXSIZE:
        _file_cache.popitem(last=False)
    _file_cache[path] = refreshed

    for entry in refreshed.entries:
        if cutoff is not None and entry.timestamp < cutoff:
            continue
        dedup_key = _dedup_key(entry)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        entries.append(entry)


def _refresh_cache(
    path: Path,
    st: os.stat_result,
    project: str,
    cached: _FileCacheEntry | None,
) -> _FileCacheEntry | None:
    prefix_hasher = (
        _confirmed_prefix_hasher(path, cached)
        if cached is not None and st.st_size >= cached.confirmed_offset and st.st_size > cached.size
        else None
    )
    if prefix_hasher is not None:
        assert cached is not None
        incremental_entries = list(cached.entries)
        try:
            with path.open("rb") as file:
                file.seek(cached.confirmed_offset)
                confirmed_offset = _parse_complete_lines(
                    file,
                    project,
                    incremental_entries,
                    prefix_hasher,
                    cached.confirmed_offset,
                )
        except OSError as exc:
            logger.warning("failed to read Claude project log %s: %s", path, exc)
            return None
        return _FileCacheEntry(
            mtime=st.st_mtime,
            size=st.st_size,
            entries=incremental_entries,
            confirmed_offset=confirmed_offset,
            confirmed_prefix_digest=prefix_hasher.digest(),
        )

    parsed_entries: list[UsageEntry] = []
    digest = hashlib.blake2b(digest_size=16)
    try:
        with path.open("rb") as file:
            confirmed_offset = _parse_complete_lines(file, project, parsed_entries, digest, 0)
    except OSError as exc:
        logger.warning("failed to read Claude project log %s: %s", path, exc)
        return None
    return _FileCacheEntry(
        mtime=st.st_mtime,
        size=st.st_size,
        entries=parsed_entries,
        confirmed_offset=confirmed_offset,
        confirmed_prefix_digest=digest.digest(),
    )


def _confirmed_prefix_hasher(path: Path, cached: _FileCacheEntry) -> Any | None:
    if cached.confirmed_offset == 0:
        return hashlib.blake2b(digest_size=16)

    digest = hashlib.blake2b(digest_size=16)
    remaining = cached.confirmed_offset
    try:
        with path.open("rb") as file:
            while remaining > 0:
                chunk = file.read(min(remaining, 65536))
                if not chunk:
                    return None
                digest.update(chunk)
                remaining -= len(chunk)
    except OSError:
        return None
    if digest.digest() != cached.confirmed_prefix_digest:
        return None
    return digest


def _parse_complete_lines(
    file: Any,
    project: str,
    parsed_entries: list[UsageEntry],
    digest: Any,
    confirmed_offset: int,
) -> int:
    while True:
        line_start = int(file.tell())
        line = file.readline()
        if not line:
            return confirmed_offset
        parsed_entry = _parse_line(line.decode("utf-8", errors="replace"), project)
        if not line.endswith(b"\n") and parsed_entry is None:
            return line_start
        digest.update(line)
        confirmed_offset = int(file.tell())
        if parsed_entry is not None:
            parsed_entries.append(parsed_entry)


def _parse_line(line: str, project: str) -> UsageEntry | None:
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return None

    if not isinstance(data, dict) or data.get("type") != "assistant":
        return None

    message = data.get("message")
    if not isinstance(message, dict):
        return None

    usage = message.get("usage")
    if not isinstance(usage, dict):
        return None

    timestamp = _parse_timestamp(data.get("timestamp"))
    if timestamp is None:
        return None

    input_tokens = _as_int(usage.get("input_tokens"))
    output_tokens = _as_int(usage.get("output_tokens"))
    cache_creation_tokens = _as_int(usage.get("cache_creation_input_tokens"))
    cache_read_tokens = _as_int(usage.get("cache_read_input_tokens"))
    if input_tokens + output_tokens + cache_creation_tokens + cache_read_tokens == 0:
        return None

    cwd = data.get("cwd")
    if isinstance(cwd, str) and cwd:
        project = _project_from_cwd(cwd)

    return UsageEntry(
        timestamp=timestamp,
        session_id=_as_str(data.get("sessionId")),
        message_id=_as_str(message.get("id")),
        request_id=_as_str(data.get("requestId")),
        model=_as_str(message.get("model")) or "unknown",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_tokens=cache_creation_tokens,
        cache_read_tokens=cache_read_tokens,
        cost_usd=_as_optional_float(data.get("costUSD")),
        project=project,
    )


def _parse_timestamp(value: Any) -> datetime | None:
    return parse_optional_iso8601_utc(value)


def _project_from_path(jsonl_path: Path) -> str:
    return project_from_encoded_path(jsonl_path, CLAUDE_PROJECTS_DIR)


def _project_from_cwd(cwd: str) -> str:
    return resolve_project_name(cwd)


def _dedup_key(entry: UsageEntry) -> str:
    if entry.message_id or entry.request_id:
        return f"message:{entry.message_id}:{entry.request_id}"
    return (
        f"entry:{entry.session_id}:{entry.timestamp.isoformat()}:{entry.model}:"
        f"{entry.input_tokens}:{entry.output_tokens}:"
        f"{entry.cache_creation_tokens}:{entry.cache_read_tokens}"
    )


def _as_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(0, int(value))
    if isinstance(value, str):
        normalized = value.strip()
        if normalized.isascii() and (
            normalized.isdigit()
            or (normalized.startswith("+") and normalized[1:].isdigit())
        ):
            return int(normalized)
    return 0


def _as_str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _as_optional_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number

# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Disk persistence for codex_loader's in-memory JSONL parse caches.

The caches themselves, the on-disk path, the schema constant and the
seeded-once flag all live in codex_loader (tests monkeypatch them there);
callers pass everything in and these functions mutate the given caches
in place.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
from collections import OrderedDict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from codex_events import _SessionFileInfo, _TokenUsage
from history_loader import UsageEntry

logger = logging.getLogger(__name__)

_JsonlCache = OrderedDict[Path, Any]
_FileInfoCache = OrderedDict[Path, tuple[float, int, _SessionFileInfo]]


def _serialize_token_usage(value: _TokenUsage | None) -> dict[str, int] | None:
    if value is None:
        return None
    return {
        "input_tokens": value.input_tokens,
        "output_tokens": value.output_tokens,
        "cache_read_tokens": value.cache_read_tokens,
    }


def _deserialize_token_usage(value: Any) -> _TokenUsage | None:
    if not isinstance(value, dict):
        return None
    try:
        return _TokenUsage(
            input_tokens=int(value["input_tokens"]),
            output_tokens=int(value["output_tokens"]),
            cache_read_tokens=int(value["cache_read_tokens"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _serialize_usage_entry(entry: UsageEntry) -> dict[str, Any]:
    """Serialize UsageEntry to dict for JSON storage."""
    return {
        "timestamp": entry.timestamp.isoformat(),
        "session_id": entry.session_id,
        "message_id": entry.message_id,
        "request_id": entry.request_id,
        "model": entry.model,
        "input_tokens": entry.input_tokens,
        "output_tokens": entry.output_tokens,
        "cache_creation_tokens": entry.cache_creation_tokens,
        "cache_read_tokens": entry.cache_read_tokens,
        "cost_usd": entry.cost_usd,
        "project": entry.project,
    }


def _deserialize_usage_entry(data: dict[str, Any]) -> UsageEntry:
    """Deserialize dict from JSON back to UsageEntry."""
    return UsageEntry(
        timestamp=datetime.fromisoformat(data["timestamp"]),
        session_id=data["session_id"],
        message_id=data["message_id"],
        request_id=data["request_id"],
        model=data["model"],
        input_tokens=data["input_tokens"],
        output_tokens=data["output_tokens"],
        cache_creation_tokens=data["cache_creation_tokens"],
        cache_read_tokens=data["cache_read_tokens"],
        cost_usd=data["cost_usd"],
        project=data["project"],
    )


def seed_caches(
    cache_path: Path,
    schema_version: int,
    maxsize: int,
    jsonl_cache: _JsonlCache,
    file_info_cache: _FileInfoCache,
) -> None:
    """Seed the given in-memory caches from disk. Silently fails on any error."""
    from codex_loader import _JsonlCacheEntry, _JsonlParseState

    try:
        with cache_path.open(encoding="utf-8") as f:
            cache = json.load(f)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return

    if not isinstance(cache, dict):
        return
    if cache.get("schema_version") != schema_version:
        return

    files = cache.get("files")
    if not isinstance(files, dict):
        return

    for path_str, file_data in files.items():
        if not isinstance(file_data, dict):
            continue
        try:
            path = Path(path_str)
            mtime = file_data["mtime"]
            size = file_data["size"]
            session_id = file_data["session_id"]
            forked_from_id = file_data["forked_from_id"]
            entries_data = file_data["entries"]
            confirmed_offset = int(file_data.get("confirmed_offset", 0))
            digest_hex = file_data.get("confirmed_prefix_digest", "")
            parse_state_data = file_data.get("parse_state", {})
            if not isinstance(parse_state_data, dict):
                parse_state_data = {}

            # Seed file_info_cache
            if len(file_info_cache) >= maxsize:
                file_info_cache.popitem(last=False)
            file_info_cache[path] = (
                mtime,
                size,
                _SessionFileInfo(session_id=session_id, forked_from_id=forked_from_id),
            )

            # Seed jsonl_cache only for non-fork files (entries not null)
            if entries_data is not None:
                if not isinstance(entries_data, list):
                    continue
                if (
                    "confirmed_offset" not in file_data
                    or "confirmed_prefix_digest" not in file_data
                    or "parse_state" not in file_data
                ):
                    continue
                entries = [_deserialize_usage_entry(e) for e in entries_data]
                state = _JsonlParseState(
                    session_timestamp=str(parse_state_data.get("session_timestamp", "")),
                    project=str(parse_state_data.get("project", "unknown")),
                    session_model=str(parse_state_data.get("session_model", "unknown")),
                    previous_usage=_deserialize_token_usage(parse_state_data.get("previous_usage")),
                    token_count_index=int(parse_state_data.get("token_count_index", 0)),
                )
                if len(jsonl_cache) >= maxsize:
                    jsonl_cache.popitem(last=False)
                jsonl_cache[path] = _JsonlCacheEntry(
                    mtime=mtime,
                    size=size,
                    replay_cache_key=None,
                    entries=entries,
                    confirmed_offset=confirmed_offset,
                    confirmed_prefix_digest=bytes.fromhex(digest_hex)
                    if isinstance(digest_hex, str)
                    else b"",
                    state=state,
                )
        except (KeyError, TypeError, ValueError):
            # Skip malformed entry; continue with others
            continue


def flush_caches(
    cache_path: Path,
    schema_version: int,
    jsonl_cache: _JsonlCache,
    file_info_cache: _FileInfoCache,
) -> None:
    """Atomically write the given in-memory caches to disk."""
    tmp_path: str | None = None
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=cache_path.parent, suffix=".tmp")

        files: dict[str, Any] = {}
        # Write jsonl_cache entries
        for path, entry in jsonl_cache.items():
            path_str = str(path)
            mtime = entry.mtime
            size = entry.size
            replay_cache_key = entry.replay_cache_key
            entries = entry.entries
            # For fork files (replay_cache_key is not None), entries = null
            if replay_cache_key is not None:
                entries_data = None
                # Still need session_id/forked_from_id from file_info_cache
                info = file_info_cache.get(path)
                if info is None:
                    continue
                session_id = info[2].session_id
                forked_from_id = info[2].forked_from_id
            else:
                entries_data = [_serialize_usage_entry(e) for e in entries]
                if not entries:
                    # Empty entries list: get info from file_info_cache
                    info = file_info_cache.get(path)
                    if info is None:
                        continue
                    session_id = info[2].session_id
                    forked_from_id = info[2].forked_from_id
                else:
                    session_id = entries[0].session_id
                    forked_from_id = ""  # Not stored in UsageEntry

            files[path_str] = {
                "mtime": mtime,
                "size": size,
                "session_id": session_id,
                "forked_from_id": forked_from_id,
                "entries": entries_data,
                "confirmed_offset": entry.confirmed_offset,
                "confirmed_prefix_digest": entry.confirmed_prefix_digest.hex(),
                "parse_state": {
                    "session_timestamp": entry.state.session_timestamp,
                    "project": entry.state.project,
                    "session_model": entry.state.session_model,
                    "previous_usage": _serialize_token_usage(entry.state.previous_usage),
                    "token_count_index": entry.state.token_count_index,
                },
            }

        payload = {
            "schema_version": schema_version,
            "cached_at": datetime.now(UTC).timestamp(),
            "files": files,
        }

        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp_path, cache_path)
        tmp_path = None
    except Exception as exc:
        if os.environ.get("USAGE_DEBUG") == "1":
            logger.warning("failed to write codex jsonl cache %s: %s", cache_path, exc)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)

# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Sharded disk persistence for codex_loader's parse caches."""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import tempfile
from collections import OrderedDict
from pathlib import Path
from typing import Any

from codex_events import _SessionFileInfo, _TokenUsage
from history_disk_cache import _deserialize_usage_entry, _serialize_usage_entry

logger = logging.getLogger(__name__)

__all__ = [
    "_deserialize_usage_entry",
    "_serialize_usage_entry",
    "flush_caches",
    "seed_caches",
]

_JsonlCache = OrderedDict[Path, Any]
_FileInfoCache = OrderedDict[Path, tuple[float, int, _SessionFileInfo]]
_SHARD_COUNT = 32


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


def _cache_dir(cache_path: Path) -> Path:
    return cache_path.with_suffix(f"{cache_path.suffix}.d")


def _shard_index(path: Path) -> int:
    digest = hashlib.sha256(str(path).encode("utf-8", errors="surrogatepass")).digest()
    return digest[0] % _SHARD_COUNT


def _shard_path(cache_path: Path, index: int) -> Path:
    return _cache_dir(cache_path) / f"files-{index:02x}.json"


def _sqlite_log_path(cache_path: Path) -> Path:
    return _cache_dir(cache_path) / "sqlite-log.json"


def _remove_legacy_cache(cache_path: Path) -> None:
    with contextlib.suppress(OSError):
        cache_path.unlink()


def _load_payload(path: Path, schema_version: int) -> dict[str, Any] | None:
    try:
        with path.open(encoding="utf-8") as file:
            payload = json.load(file)
        if not isinstance(payload, dict) or payload.get("schema_version") != schema_version:
            path.unlink(missing_ok=True)
            return None
        return payload
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        with contextlib.suppress(OSError):
            path.unlink()
        return None


def _encoded_payload(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _write_if_changed(path: Path, payload: bytes) -> None:
    try:
        if path.read_bytes() == payload:
            return
    except OSError:
        pass

    tmp_path: str | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        with os.fdopen(fd, "wb") as file:
            file.write(payload)
            file.flush()
            os.fsync(file.fileno())
        os.replace(tmp_path, path)
        tmp_path = None
    finally:
        if tmp_path:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)


def seed_caches(
    cache_path: Path,
    schema_version: int,
    maxsize: int,
    jsonl_cache: _JsonlCache,
    file_info_cache: _FileInfoCache,
    sqlite_log_cache: Any,
) -> None:
    """Seed valid shards, skipping only corrupt or stale shards."""
    from codex_loader import _JsonlCacheEntry, _JsonlParseState

    _remove_legacy_cache(cache_path)
    sqlite_payload = _load_payload(_sqlite_log_path(cache_path), schema_version)
    if sqlite_payload is not None:
        try:
            watermark = sqlite_payload["watermark"]
            entries_data = sqlite_payload["entries"]
            if (
                isinstance(watermark, list)
                and len(watermark) == 3
                and isinstance(entries_data, list)
            ):
                sqlite_log_cache.watermark = tuple(int(item) for item in watermark)
                sqlite_log_cache.entries = [
                    _deserialize_usage_entry(entry) for entry in entries_data
                ]
        except (KeyError, TypeError, ValueError):
            pass

    for index in range(_SHARD_COUNT):
        payload = _load_payload(_shard_path(cache_path, index), schema_version)
        if payload is None:
            continue
        files = payload.get("files")
        if not isinstance(files, dict):
            continue
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

                if len(file_info_cache) >= maxsize:
                    file_info_cache.popitem(last=False)
                file_info_cache[path] = (
                    mtime,
                    size,
                    _SessionFileInfo(session_id=session_id, forked_from_id=forked_from_id),
                )
                if entries_data is None:
                    continue
                if not isinstance(entries_data, list):
                    continue
                if (
                    "confirmed_offset" not in file_data
                    or "confirmed_prefix_digest" not in file_data
                    or "parse_state" not in file_data
                ):
                    continue
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
                    entries=[_deserialize_usage_entry(entry) for entry in entries_data],
                    confirmed_offset=confirmed_offset,
                    confirmed_prefix_digest=bytes.fromhex(digest_hex)
                    if isinstance(digest_hex, str)
                    else b"",
                    state=state,
                )
            except (KeyError, TypeError, ValueError):
                continue


def flush_caches(
    cache_path: Path,
    schema_version: int,
    jsonl_cache: _JsonlCache,
    file_info_cache: _FileInfoCache,
    sqlite_log_cache: Any,
) -> None:
    """Atomically replace only shards whose serialized contents changed."""
    try:
        _remove_legacy_cache(cache_path)
        shards: list[dict[str, Any]] = [{} for _ in range(_SHARD_COUNT)]
        for path, entry in jsonl_cache.items():
            info = file_info_cache.get(path)
            if entry.replay_cache_key is not None:
                if info is None:
                    continue
                entries_data = None
                session_id = info[2].session_id
                forked_from_id = info[2].forked_from_id
            else:
                entries_data = [_serialize_usage_entry(item) for item in entry.entries]
                if entry.entries:
                    session_id = entry.entries[0].session_id
                    forked_from_id = ""
                elif info is not None:
                    session_id = info[2].session_id
                    forked_from_id = info[2].forked_from_id
                else:
                    continue
            shards[_shard_index(path)][str(path)] = {
                "mtime": entry.mtime,
                "size": entry.size,
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

        for index, files in enumerate(shards):
            path = _shard_path(cache_path, index)
            if files:
                _write_if_changed(
                    path,
                    _encoded_payload({"schema_version": schema_version, "files": files}),
                )
            else:
                path.unlink(missing_ok=True)

        sqlite_payload = {
            "schema_version": schema_version,
            "watermark": list(sqlite_log_cache.watermark)
            if sqlite_log_cache.watermark is not None
            else None,
            "entries": [
                _serialize_usage_entry(entry) for entry in sqlite_log_cache.entries
            ],
        }
        _write_if_changed(_sqlite_log_path(cache_path), _encoded_payload(sqlite_payload))
    except Exception as exc:
        if os.environ.get("USAGE_DEBUG") == "1":
            logger.warning("failed to write codex jsonl cache %s: %s", cache_path, exc)

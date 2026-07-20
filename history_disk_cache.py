# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Sharded disk persistence for history_loader's JSONL parse cache."""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import tempfile
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from history_loader import UsageEntry

logger = logging.getLogger(__name__)

_FileCache = OrderedDict[Path, Any]
_SHARD_COUNT = 32


def _serialize_usage_entry(entry: Any) -> dict[str, Any]:
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
    from history_loader import UsageEntry

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


def _cache_dir(cache_path: Path) -> Path:
    return cache_path.with_suffix(f"{cache_path.suffix}.d")


def _shard_index(path: Path) -> int:
    digest = hashlib.sha256(str(path).encode("utf-8", errors="surrogatepass")).digest()
    return digest[0] % _SHARD_COUNT


def _shard_path(cache_path: Path, index: int) -> Path:
    return _cache_dir(cache_path) / f"files-{index:02x}.json"


def _remove_legacy_cache(cache_path: Path) -> None:
    with contextlib.suppress(OSError):
        cache_path.unlink()


def _load_shard(path: Path, schema_version: int) -> dict[str, Any] | None:
    try:
        with path.open(encoding="utf-8") as file:
            payload = json.load(file)
        if not isinstance(payload, dict) or payload.get("schema_version") != schema_version:
            path.unlink(missing_ok=True)
            return None
        files = payload.get("files")
        if not isinstance(files, dict):
            path.unlink(missing_ok=True)
            return None
        return files
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        with contextlib.suppress(OSError):
            path.unlink()
        return None


def _encoded_payload(schema_version: int, files: dict[str, Any]) -> bytes:
    return json.dumps(
        {"schema_version": schema_version, "files": files},
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
    file_cache: _FileCache,
) -> None:
    from history_loader import _FileCacheEntry

    _remove_legacy_cache(cache_path)
    for index in range(_SHARD_COUNT):
        files = _load_shard(_shard_path(cache_path, index), schema_version)
        if files is None:
            continue
        for path_str, file_data in files.items():
            if not isinstance(file_data, dict):
                continue
            try:
                path = Path(path_str)
                entries_data = file_data["entries"]
                if not isinstance(entries_data, list):
                    continue
                if len(file_cache) >= maxsize:
                    file_cache.popitem(last=False)
                file_cache[path] = _FileCacheEntry(
                    mtime=float(file_data["mtime"]),
                    size=int(file_data["size"]),
                    entries=[_deserialize_usage_entry(entry) for entry in entries_data],
                    confirmed_offset=int(file_data["confirmed_offset"]),
                    confirmed_prefix_digest=bytes.fromhex(file_data["confirmed_prefix_digest"]),
                )
            except (KeyError, TypeError, ValueError):
                continue


def flush_caches(
    cache_path: Path,
    schema_version: int,
    file_cache: _FileCache,
) -> None:
    """Atomically replace only shards whose serialized contents changed."""
    try:
        _remove_legacy_cache(cache_path)
        shards: list[dict[str, Any]] = [{} for _ in range(_SHARD_COUNT)]
        for path, entry in file_cache.items():
            shards[_shard_index(path)][str(path)] = {
                "mtime": entry.mtime,
                "size": entry.size,
                "entries": [_serialize_usage_entry(item) for item in entry.entries],
                "confirmed_offset": entry.confirmed_offset,
                "confirmed_prefix_digest": entry.confirmed_prefix_digest.hex(),
            }

        for index, files in enumerate(shards):
            path = _shard_path(cache_path, index)
            if files:
                _write_if_changed(path, _encoded_payload(schema_version, files))
            else:
                path.unlink(missing_ok=True)
    except Exception as exc:
        if os.environ.get("USAGE_DEBUG") == "1":
            logger.warning("failed to write history jsonl cache %s: %s", cache_path, exc)

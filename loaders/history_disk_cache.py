# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Sharded disk persistence for history_loader's JSONL parse cache."""

from __future__ import annotations

import logging
import os
from collections import OrderedDict
from pathlib import Path
from typing import Any

from loaders.disk_cache_common import (
    _SHARD_COUNT,
    _deserialize_usage_entry,
    _encoded_payload,
    _load_payload,
    _remove_legacy_cache,
    _serialize_usage_entry,
    _shard_index,
    _shard_path,
    _write_if_changed,
)

logger = logging.getLogger(__name__)

__all__ = ["_shard_index", "_shard_path", "flush_caches", "seed_caches"]

_FileCache = OrderedDict[Path, Any]


def _load_shard(path: Path, schema_version: int) -> dict[str, Any] | None:
    payload = _load_payload(path, schema_version)
    if payload is None:
        return None
    files = payload.get("files")
    if not isinstance(files, dict):
        path.unlink(missing_ok=True)
        return None
    return files


def seed_caches(
    cache_path: Path,
    schema_version: int,
    maxsize: int,
    file_cache: _FileCache,
) -> None:
    from loaders.history_loader import _FileCacheEntry

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
                _write_if_changed(
                    path,
                    _encoded_payload({"schema_version": schema_version, "files": files}),
                )
            else:
                path.unlink(missing_ok=True)
    except Exception as exc:
        if os.environ.get("USAGE_DEBUG") == "1":
            logger.warning("failed to write history jsonl cache %s: %s", cache_path, exc)

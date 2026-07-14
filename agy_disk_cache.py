# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Disk persistence for agy_loader's in-memory SQLite parse cache."""

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

logger = logging.getLogger(__name__)

_FileCache = OrderedDict[Path, Any]


def _serialize_entry(entry: Any) -> dict[str, Any]:
    return {
        "timestamp": entry.timestamp.isoformat(),
        "model": entry.model,
        "input_tokens": entry.input_tokens,
        "output_tokens": entry.output_tokens,
        "cache_read_tokens": entry.cache_read_tokens,
        "thinking_tokens": entry.thinking_tokens,
        "dedup_key": entry.dedup_key,
        "session_id": entry.session_id,
    }


def _deserialize_entry(data: dict[str, Any]) -> Any:
    from agy_loader import AgyUsageEntry

    return AgyUsageEntry(
        timestamp=datetime.fromisoformat(data["timestamp"]),
        model=str(data["model"]),
        input_tokens=int(data["input_tokens"]),
        output_tokens=int(data["output_tokens"]),
        cache_read_tokens=int(data["cache_read_tokens"]),
        thinking_tokens=int(data["thinking_tokens"]),
        dedup_key=str(data["dedup_key"]),
        session_id=str(data["session_id"]),
    )


def seed_caches(
    cache_path: Path,
    schema_version: int,
    maxsize: int,
    file_cache: _FileCache,
) -> None:
    """Seed the given in-memory cache from disk. Silently fails on any error."""
    from agy_loader import _FileCacheEntry

    try:
        with cache_path.open(encoding="utf-8") as f:
            cache = json.load(f)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return
    if not isinstance(cache, dict) or cache.get("schema_version") != schema_version:
        return
    files = cache.get("files")
    if not isinstance(files, dict):
        return

    for path_str, file_data in files.items():
        if not isinstance(file_data, dict):
            continue
        try:
            entries_data = file_data["entries"]
            if not isinstance(entries_data, list):
                continue
            if len(file_cache) >= maxsize:
                file_cache.popitem(last=False)
            file_cache[Path(path_str)] = _FileCacheEntry(
                mtime=float(file_data["mtime"]),
                size=int(file_data["size"]),
                entries=[_deserialize_entry(entry) for entry in entries_data],
                skipped_missing_dedup_key=int(file_data["skipped_missing_dedup_key"]),
            )
        except (KeyError, TypeError, ValueError):
            continue


def flush_caches(
    cache_path: Path,
    schema_version: int,
    file_cache: _FileCache,
) -> None:
    """Atomically write the given in-memory cache to disk."""
    tmp_path: str | None = None
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=cache_path.parent, suffix=".tmp")
        payload = {
            "schema_version": schema_version,
            "cached_at": datetime.now(UTC).timestamp(),
            "files": {
                str(path): {
                    "mtime": entry.mtime,
                    "size": entry.size,
                    "entries": [_serialize_entry(item) for item in entry.entries],
                    "skipped_missing_dedup_key": entry.skipped_missing_dedup_key,
                }
                for path, entry in file_cache.items()
            },
        }
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp_path, cache_path)
        tmp_path = None
    except Exception as exc:
        if os.environ.get("USAGE_DEBUG") == "1":
            logger.warning("failed to write Antigravity database cache %s: %s", cache_path, exc)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)

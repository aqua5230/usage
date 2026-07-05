# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Disk persistence for history_loader's in-memory JSONL parse cache."""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
from collections import OrderedDict
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from history_loader import UsageEntry

logger = logging.getLogger(__name__)

_FileCache = OrderedDict[Path, Any]


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


def seed_caches(
    cache_path: Path,
    schema_version: int,
    maxsize: int,
    file_cache: _FileCache,
) -> None:
    from history_loader import _FileCacheEntry

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
    tmp_path: str | None = None
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=cache_path.parent, suffix=".tmp")

        files = {
            str(path): {
                "mtime": entry.mtime,
                "size": entry.size,
                "entries": [_serialize_usage_entry(item) for item in entry.entries],
                "confirmed_offset": entry.confirmed_offset,
                "confirmed_prefix_digest": entry.confirmed_prefix_digest.hex(),
            }
            for path, entry in file_cache.items()
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
            logger.warning("failed to write history jsonl cache %s: %s", cache_path, exc)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)

# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Common helpers for sharded JSON disk caches."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from loaders.cache_quarantine import quarantine

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


def _deserialize_usage_entry(data: dict[str, Any]) -> Any:
    from loaders.history_loader import UsageEntry

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


def _load_payload(path: Path, schema_version: int) -> dict[str, Any] | None:
    try:
        with path.open(encoding="utf-8") as file:
            payload = json.load(file)
        if not isinstance(payload, dict):
            quarantine(path, "not-a-mapping")
            path.unlink(missing_ok=True)
            return None
        if payload.get("schema_version") != schema_version:
            path.unlink(missing_ok=True)
            return None
        return payload
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        if isinstance(exc, UnicodeDecodeError):
            quarantine(path, "decode-error")
        else:
            quarantine(path, "json-error")
        with contextlib.suppress(OSError):
            path.unlink()
        return None
    except OSError:
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

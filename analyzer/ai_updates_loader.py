# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

AI_UPDATES_URL = "https://raw.githubusercontent.com/aqua5230/usage/main/ai_updates.json"
CACHE_PATH = Path(os.path.expanduser("~/.usage/ai_updates_cache.json"))
CACHE_TTL_SECONDS = 86400
USER_AGENT = "usage/0.9"


def load_ai_updates() -> list[dict[str, Any]] | None:
    try:
        cached = _read_cache()
        if cached is not None and _cache_is_fresh(CACHE_PATH):
            return cached

        fetched_payload = _fetch_payload()
        if fetched_payload is not None:
            fetched = _normalize_payload(fetched_payload)
            if fetched is not None:
                _write_cache(fetched_payload)
                return fetched

        if cached is not None:
            return cached
        return None
    except Exception:
        _debug_warning("failed to load AI updates")
        return None


def _cache_is_fresh(path: Path) -> bool:
    try:
        return (time.time() - path.stat().st_mtime) <= CACHE_TTL_SECONDS
    except OSError:
        return False


def _read_cache() -> list[dict[str, Any]] | None:
    try:
        with CACHE_PATH.open(encoding="utf-8") as file:
            payload = json.load(file)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        _debug_warning(f"failed to read AI updates cache {CACHE_PATH}")
        return None
    return _normalize_payload(payload)


def _fetch_payload() -> Any | None:
    request = urllib.request.Request(
        AI_UPDATES_URL,
        headers={"User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        urllib.error.URLError,
    ):
        _debug_warning(f"failed to fetch AI updates from {AI_UPDATES_URL}")
        return None


def _write_cache(payload: Any) -> None:
    tmp_path: str | None = None
    try:
        with contextlib.suppress(OSError):
            CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=CACHE_PATH.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
        os.replace(tmp_path, CACHE_PATH)
        tmp_path = None
    except OSError:
        _debug_warning(f"failed to write AI updates cache {CACHE_PATH}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)


def _normalize_payload(payload: Any) -> list[dict[str, Any]] | None:
    if not isinstance(payload, dict):
        return None

    raw_tools = payload.get("tools")
    if not isinstance(raw_tools, list):
        return None

    tools: list[dict[str, Any]] = []
    for raw_tool in raw_tools:
        if not isinstance(raw_tool, dict):
            continue
        required_keys = ("id", "name", "version", "period")
        if not all(isinstance(raw_tool.get(key), str) for key in required_keys):
            continue
        raw_items = raw_tool.get("items")
        if not isinstance(raw_items, list):
            continue

        items: list[dict[str, Any]] = []
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                continue

            title = raw_item.get("title")
            body = raw_item.get("body")
            original = raw_item.get("original")
            if not isinstance(title, dict) or not isinstance(body, dict):
                continue
            if not all(
                isinstance(key, str) and isinstance(value, str)
                for key, value in title.items()
            ):
                continue
            if not all(
                isinstance(key, str) and isinstance(value, str)
                for key, value in body.items()
            ):
                continue
            if not isinstance(original, str):
                continue
            items.append(
                {
                    "title": title,
                    "body": body,
                    "original": original,
                }
            )

        if not items:
            continue
        tools.append(
            {
                "id": raw_tool["id"],
                "name": raw_tool["name"],
                "version": raw_tool["version"],
                "period": raw_tool["period"],
                "items": items,
            }
        )
    return tools


def _debug_warning(message: str) -> None:
    if os.environ.get("USAGE_DEBUG") == "1":
        logger.warning(message, exc_info=True)

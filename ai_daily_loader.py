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
AI_DAILY_URL = "https://raw.githubusercontent.com/aqua5230/ai-updates/main/daily.json"
CACHE_PATH = Path(os.path.expanduser("~/.usage/ai_daily_cache.json"))
CACHE_TTL_SECONDS = 6 * 60 * 60
USER_AGENT = "usage/0.9"
LANGUAGES = frozenset({"zh-TW", "zh-CN", "en", "ja", "ko"})


def load_ai_daily() -> dict[str, Any] | None:
    try:
        cached = _read_cache()
        if cached is not None and _cache_is_fresh(CACHE_PATH):
            return cached
        payload = _fetch_payload()
        normalized = _normalize_payload(payload)
        if normalized is not None:
            _write_cache(payload)
            return normalized
        return cached
    except Exception:
        _debug_warning("failed to load AI daily updates")
        return None


def _cache_is_fresh(path: Path) -> bool:
    try:
        return (time.time() - path.stat().st_mtime) <= CACHE_TTL_SECONDS
    except OSError:
        return False


def _read_cache() -> dict[str, Any] | None:
    try:
        with CACHE_PATH.open(encoding="utf-8") as file:
            return _normalize_payload(json.load(file))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        _debug_warning(f"failed to read AI daily cache {CACHE_PATH}")
        return None


def _fetch_payload() -> Any | None:
    request = urllib.request.Request(AI_DAILY_URL, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, urllib.error.URLError):
        _debug_warning(f"failed to fetch AI daily updates from {AI_DAILY_URL}")
        return None


def _write_cache(payload: Any) -> None:
    tmp_path: str | None = None
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=CACHE_PATH.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
        os.replace(tmp_path, CACHE_PATH)
        tmp_path = None
    except OSError:
        _debug_warning(f"failed to write AI daily cache {CACHE_PATH}")
    finally:
        if tmp_path:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)


def _localized_dict(value: Any) -> bool:
    return isinstance(value, dict) and LANGUAGES.issubset(value) and all(
        isinstance(value[language], str) for language in LANGUAGES
    )


def _normalize_payload(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict) or not isinstance(payload.get("generated_at"), str):
        return None
    tools = payload.get("tools")
    if not isinstance(tools, list):
        return None
    for tool in tools:
        if not isinstance(tool, dict) or not all(
            isinstance(tool.get(key), str) for key in ("id", "name")
        ):
            return None
        versions = tool.get("versions")
        if not isinstance(versions, list):
            return None
        for version in versions:
            if (
                not isinstance(version, dict)
                or not all(isinstance(version.get(key), str) for key in ("version", "period"))
                or not isinstance(version.get("curated"), bool)
                or not isinstance(version.get("items"), list)
            ):
                return None
            for item in version["items"]:
                if not isinstance(item, dict) or not isinstance(item.get("original"), str):
                    return None
                if version["curated"]:
                    if set(item) != {"title", "body", "original"}:
                        return None
                    if not _localized_dict(item["title"]) or not _localized_dict(item["body"]):
                        return None
                elif set(item) != {"original"}:
                    return None
    return payload


def _debug_warning(message: str) -> None:
    if os.environ.get("USAGE_DEBUG") == "1":
        logger.warning(message, exc_info=True)

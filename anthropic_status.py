# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Read Claude's public service-status feed, never an LLM usage API.

This module only downloads the public Claude status page JSON. It does not call
an LLM usage API and therefore does not collect or infer account usage.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

STATUS_URL = "https://status.claude.com/api/v2/summary.json"
CACHE_PATH = Path(os.path.expanduser("~/.usage/anthropic_status_cache.json"))
CACHE_TTL_SECONDS = 300
FAILURE_RETRY_SECONDS = 60
USER_AGENT = "usage/0.9"
RELEVANT_COMPONENTS = ("Claude Code", "Claude API (api.anthropic.com)")

StatusSource = Literal["fetched", "cache", "stale", "fallback"]
_SEVERITY = {
    "operational": 0,
    "degraded_performance": 1,
    "partial_outage": 2,
    "major_outage": 3,
}
_last_failure_at: float | None = None


@dataclass(frozen=True)
class AnthropicStatus:
    """Service state relevant to Claude Code users."""

    is_abnormal: bool
    status: str
    description: str
    source: StatusSource


def get_anthropic_status() -> AnthropicStatus:
    """Return the worst status of Claude Code and its API dependency."""
    cached = _read_cache()
    if cached is not None:
        return _build_status(cached, "cache")

    stale_cached = _read_cache(allow_stale=True)
    if _retry_is_delayed():
        return _status_from_stale_or_fallback(stale_cached)

    payload = _fetch_status()
    if payload is not None:
        _write_cache(payload)
        _clear_failure_retry()
        return _build_status(payload, "fetched")

    _record_failure()
    return _status_from_stale_or_fallback(stale_cached)


def _status_from_stale_or_fallback(payload: dict[str, Any] | None) -> AnthropicStatus:
    if payload is not None:
        return _build_status(payload, "stale")
    return AnthropicStatus(False, "unknown", "Claude service status is unavailable.", "fallback")


def _build_status(payload: dict[str, Any], source: StatusSource) -> AnthropicStatus:
    components = payload.get("components")
    if not isinstance(components, list):
        return AnthropicStatus(False, "unknown", "Claude service status is unavailable.", source)

    component_statuses = {
        component.get("name"): component.get("status")
        for component in components
        if isinstance(component, dict)
        and isinstance(component.get("name"), str)
        and isinstance(component.get("status"), str)
    }
    statuses = tuple(component_statuses.get(name) for name in RELEVANT_COMPONENTS)
    valid_statuses = tuple(
        status for status in statuses if isinstance(status, str) and status in _SEVERITY
    )
    if len(valid_statuses) != len(RELEVANT_COMPONENTS):
        return AnthropicStatus(False, "unknown", "Claude service status is unavailable.", source)

    worst_status = max(valid_statuses, key=lambda status: _SEVERITY[status])
    affected = [
        name
        for name, status in zip(RELEVANT_COMPONENTS, valid_statuses, strict=True)
        if status != "operational"
    ]
    if not affected:
        return AnthropicStatus(
            False, worst_status, "Claude Code and Claude API are operational.", source
        )

    return AnthropicStatus(True, worst_status, f"{', '.join(affected)}: {worst_status}.", source)


def _read_cache(*, allow_stale: bool = False) -> dict[str, Any] | None:
    try:
        if not allow_stale and (time.time() - CACHE_PATH.stat().st_mtime) > CACHE_TTL_SECONDS:
            return None
        with CACHE_PATH.open(encoding="utf-8") as file:
            payload = json.load(file)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.debug("failed to read Anthropic status cache: %s", exc)
        return None
    return payload if isinstance(payload, dict) else None


def _fetch_status() -> dict[str, Any] | None:
    request = urllib.request.Request(STATUS_URL, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.warning("failed to fetch Anthropic status from %s: %s", STATUS_URL, exc)
        return None
    return payload if isinstance(payload, dict) else None


def _write_cache(payload: dict[str, Any]) -> None:
    tmp_path: str | None = None
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=CACHE_PATH.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp_path, CACHE_PATH)
        tmp_path = None
    except OSError as exc:
        logger.warning("failed to write Anthropic status cache: %s", exc)
    finally:
        if tmp_path is not None:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)


def _retry_is_delayed() -> bool:
    return (
        _last_failure_at is not None
        and time.monotonic() - _last_failure_at < FAILURE_RETRY_SECONDS
    )


def _record_failure() -> None:
    global _last_failure_at
    _last_failure_at = time.monotonic()


def _clear_failure_retry() -> None:
    global _last_failure_at
    _last_failure_at = None

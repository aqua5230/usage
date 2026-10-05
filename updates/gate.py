# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import threading
import time
from typing import Any

from updates import checker as update_checker

AUTO_CHECK_TTL_SECONDS = 24 * 60 * 60
UPDATE_DISMISS_SECONDS = 24 * 3600
UPDATE_RECHECK_SECONDS = 3600
UPDATE_RETRY_MAX_SECONDS = 6 * 3600


class AutoCheckSchedule:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._running = False
        self._failures = 0
        self._next_at = 0.0

    def try_begin(self, now: float) -> bool:
        with self._lock:
            if self._running or now < self._next_at:
                return False
            self._running = True
            return True

    def finish(self, now: float, *, failed: bool) -> None:
        with self._lock:
            self._failures = self._failures + 1 if failed else 0
            delay = min(
                UPDATE_RECHECK_SECONDS * 2 ** min(max(self._failures - 1, 0), 3),
                UPDATE_RETRY_MAX_SECONDS,
            )
            self._next_at = now + delay
            self._running = False


def dismissed_recently(prefs: dict[str, Any]) -> bool:
    dismissed_at = prefs.get("update_dismissed_at")
    if isinstance(dismissed_at, int | float):
        return (time.time() - float(dismissed_at)) < UPDATE_DISMISS_SECONDS
    return False


def auto_check_is_due(prefs: dict[str, Any]) -> bool:
    cached = prefs.get("last_update_check")
    checked_at = cached.get("checked_at") if isinstance(cached, dict) else None
    if not isinstance(checked_at, int | float):
        return True
    return (time.time() - float(checked_at)) >= AUTO_CHECK_TTL_SECONDS


def stale_cache_reset(prefs: dict[str, Any], current_version: str) -> dict[str, Any] | None:
    cached = prefs.get("last_update_check")
    if (
        isinstance(cached, dict)
        and isinstance(cached.get("latest_version"), str)
        and cached.get("current_version") != current_version
        and update_checker.compare_versions(current_version, cached["latest_version"]) >= 0
    ):
        return {
            **cached,
            "current_version": current_version,
            "latest_version": current_version,
        }
    return None


def build_check_cache_entry(
    current_version: str,
    release: update_checker.ReleaseInfo | None,
) -> dict[str, Any]:
    return {
        "checked_at": time.time(),
        "current_version": current_version,
        "latest_version": release.version if release else current_version,
        "release_url": release.html_url if release else None,
    }


def resolve_alert_choice(result_code: int, release_version: str) -> tuple[str, dict[str, str]]:
    if result_code == 1000:
        return ("open", {})
    if result_code == 1002:
        return ("skip", {"update_skipped_version": release_version})
    return ("dismiss", {})

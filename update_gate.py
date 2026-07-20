# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import time
from typing import Any

import update_checker

AUTO_CHECK_TTL_SECONDS = 24 * 60 * 60


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

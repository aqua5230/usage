# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

from collections.abc import Mapping

from prefs import _load_preferences


def _resolved_preferences(prefs: Mapping[str, object] | None = None) -> Mapping[str, object]:
    return _load_preferences() if prefs is None else prefs


def _auto_update_check_enabled(prefs: Mapping[str, object] | None = None) -> bool:
    data = _resolved_preferences(prefs)
    return data.get("auto_update_check") is not False


def _hide_claude_enabled(prefs: Mapping[str, object] | None = None) -> bool:
    data = _resolved_preferences(prefs)
    return data.get("hide_claude_section") is True


def _hide_codex_enabled(prefs: Mapping[str, object] | None = None) -> bool:
    data = _resolved_preferences(prefs)
    return data.get("hide_codex_section") is True


def _quota_notifications_enabled(prefs: Mapping[str, object] | None = None) -> bool:
    data = _resolved_preferences(prefs)
    return data.get("quota_notifications") is not False


def _quota_notification_thresholds(prefs: Mapping[str, object] | None = None) -> list[float]:
    data = _resolved_preferences(prefs)
    raw = data.get("quota_notification_thresholds")
    if not isinstance(raw, list):
        return [90.0]
    thresholds: list[float] = []
    for value in raw:
        if isinstance(value, int | float) and 0 < float(value) <= 100:
            thresholds.append(float(value))
    return thresholds or [90.0]

# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

import menubar_prefs


def test_quota_notification_thresholds_default() -> None:
    assert menubar_prefs._quota_notification_thresholds({}) == [90.0]


def test_quota_notification_thresholds_filters_invalid_values() -> None:
    prefs = {"quota_notification_thresholds": [95, 0, 120, "x", 50.5]}

    assert menubar_prefs._quota_notification_thresholds(prefs) == [95.0, 50.5]


def test_auto_update_check_enabled_defaults_true() -> None:
    assert menubar_prefs._auto_update_check_enabled({}) is True
    assert menubar_prefs._auto_update_check_enabled({"auto_update_check": False}) is False

# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

from pathlib import Path

import pytest

import menubar_prefs
import prefs


def test_quota_notification_thresholds_default() -> None:
    assert menubar_prefs._quota_notification_thresholds({}) == [90.0]


def test_quota_notification_thresholds_filters_invalid_values() -> None:
    prefs = {"quota_notification_thresholds": [95, 0, 120, "x", 50.5]}

    assert menubar_prefs._quota_notification_thresholds(prefs) == [95.0, 50.5]


def test_auto_update_check_enabled_defaults_true() -> None:
    assert menubar_prefs._auto_update_check_enabled({}) is True
    assert menubar_prefs._auto_update_check_enabled({"auto_update_check": False}) is False


@pytest.mark.parametrize(
    "preferences, enabled",
    [
        ({"window_keeper": True}, True),
        ({"agy_window_keeper": True}, True),
        ({}, False),
    ],
)
def test_window_keeper_enabled_uses_a_combined_migration_gate(
    preferences: dict[str, bool], enabled: bool
) -> None:
    assert menubar_prefs._window_keeper_enabled(preferences) is enabled
    assert menubar_prefs._agy_window_keeper_enabled(preferences) is enabled


def test_quota_card_order_validates_preferences() -> None:
    assert menubar_prefs._quota_card_order({"quota_card_order": ["agy", "claude", "codex"]}) == (
        "agy",
        "claude",
        "codex",
    )
    invalid_values = (
        None,
        "agy",
        ["agy", "claude"],
        ["agy", "claude", "claude"],
        ["agy", "claude", "unknown"],
    )
    for value in invalid_values:
        assert menubar_prefs._quota_card_order({"quota_card_order": value}) == (
            "claude",
            "codex",
            "agy",
        )


def test_save_quota_card_order_ignores_invalid_values(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    preferences_file = tmp_path / "usage-preferences.json"
    monkeypatch.setattr(prefs, "PREFERENCES_FILE", preferences_file)

    assert menubar_prefs._save_quota_card_order(["agy", "claude", "codex"]) is True
    assert prefs._load_preferences()["quota_card_order"] == ["agy", "claude", "codex"]
    assert menubar_prefs._save_quota_card_order(["agy", "claude", "claude"]) is False
    assert prefs._load_preferences()["quota_card_order"] == ["agy", "claude", "codex"]

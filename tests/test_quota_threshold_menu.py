# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>

from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any

import pytest

from menubar import prefs
from quota.notifications import QuotaNotifier
from usage_common.i18n import _t
from wintray import app as wintray
from wintray import menu as winmenu


def test_set_thresholds_keeps_observations_and_waits_for_crossing() -> None:
    notifier = QuotaNotifier()
    channel = "claude_session"
    assert notifier.update({channel: (85.0, True)}) == []
    state = notifier._channels[(channel, "")]
    notifier.set_thresholds([95.0, 70.0, 90.0, 70.0])
    assert notifier.thresholds == [70.0, 90.0, 95.0]
    assert notifier._channels[(channel, "")] is state
    assert state.last_percent == 85.0
    assert notifier.update({channel: (85.0, True)}) == []
    assert notifier.update({channel: (86.0, True)}) == []
    events = notifier.update({channel: (90.0, True)})
    assert [event.threshold for event in events] == [90.0]
    notifier.set_thresholds([70.0, 90.0])
    assert state.warned_thresholds == {90.0}
    assert notifier.update({channel: (90.0, True)}) == []
    assert notifier.update({channel: (20.0, True)}) == []
    assert [event.threshold for event in notifier.update({channel: (70.0, True)})] == [70.0]


def test_set_thresholds_preserves_depleted_state() -> None:
    notifier = QuotaNotifier()
    notifier.update({"codex_weekly": (100.0, True)})
    notifier.set_thresholds([50.0, 90.0])
    assert notifier.update({"codex_weekly": (100.0, True)}) == []
    assert [event.kind for event in notifier.update({"codex_weekly": (0.0, True)})] == ["restored"]


@pytest.fixture
def saved_prefs(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    data: dict[str, Any] = {}
    monkeypatch.setattr(prefs, "_load_preferences", lambda: data.copy())
    monkeypatch.setattr(prefs, "_save_preferences", lambda values: data.update(values))
    return data


def test_preset_toggle_updates_prefs_and_running_notifier(saved_prefs: dict[str, Any]) -> None:
    notifier = QuotaNotifier()
    notifier.update({"claude_session": (85.0, True)})
    assert prefs.toggle_quota_threshold(70, notifier)
    assert saved_prefs["quota_notification_thresholds"] == [70.0, 90.0]
    assert all(type(value) is float for value in saved_prefs["quota_notification_thresholds"])
    assert notifier.update({"claude_session": (86.0, True)}) == []
    assert prefs.toggle_quota_threshold(90, notifier)
    assert saved_prefs["quota_notification_thresholds"] == [70.0]
    assert notifier.thresholds == [70.0]


def test_last_threshold_cannot_be_unchecked(saved_prefs: dict[str, Any]) -> None:
    notifier = QuotaNotifier()
    assert not prefs.toggle_quota_threshold(90, notifier)
    assert saved_prefs == {}
    assert notifier.thresholds == [90.0]


def test_custom_thresholds_are_preserved(saved_prefs: dict[str, Any]) -> None:
    saved_prefs["quota_notification_thresholds"] = [92.5, 90.0, 42.0, 92.5]
    notifier = QuotaNotifier(prefs._quota_notification_thresholds())
    assert prefs.toggle_quota_threshold(90, notifier)
    assert saved_prefs["quota_notification_thresholds"] == [42.0, 92.5]
    assert prefs.toggle_quota_threshold(50, notifier)
    assert saved_prefs["quota_notification_thresholds"] == [42.0, 50.0, 92.5]


def test_disabled_notifications_ignore_threshold_changes(saved_prefs: dict[str, Any]) -> None:
    saved_prefs["quota_notifications"] = False
    notifier = QuotaNotifier()
    assert not prefs.toggle_quota_threshold(50, notifier)
    assert not prefs.toggle_quota_threshold(25, notifier)
    assert saved_prefs == {"quota_notifications": False}
    assert notifier.thresholds == [90.0]


class TrayMenu:
    SEPARATOR = object()

    def __init__(self, *items: Any) -> None:
        self.items = items


class TrayItem:
    def __init__(self, label: str, action: Any, **kwargs: Any) -> None:
        self.label = label
        self.action = action
        self.options = kwargs


@pytest.mark.parametrize("enabled", [True, False])
def test_windows_threshold_submenu(
    saved_prefs: dict[str, Any], monkeypatch: pytest.MonkeyPatch, enabled: bool
) -> None:
    saved_prefs["quota_notifications"] = enabled
    # Keep the tray's imported readers on the same isolated preferences.
    monkeypatch.setattr(wintray, "_quota_notifications_enabled", prefs._quota_notifications_enabled)
    monkeypatch.setattr(
        wintray, "_quota_notification_thresholds", prefs._quota_notification_thresholds
    )
    monkeypatch.setattr(wintray, "_load_preferences", lambda: saved_prefs.copy())
    monkeypatch.setattr(wintray, "_save_preferences", lambda values: saved_prefs.update(values))
    controller = wintray._WindowsTrayController(mock=True, interval=60)
    controller.language = "zh-TW"
    notifier = controller._quota_notifier
    group = next(
        entry
        for entry in winmenu.entries_for_surface(wintray._menu_model(), winmenu.TRAY)
        if isinstance(entry, winmenu.MenuGroup) and entry.i18n_key == "quota_notifications_menu"
    )
    parent = wintray._tray_menu_entry(
        SimpleNamespace(Menu=TrayMenu, MenuItem=TrayItem), controller, group
    )
    assert parent.options["checked"](None) is enabled
    toggle, separator, header, *items = parent.action.items
    assert toggle.label == "開啟通知"
    assert toggle.options["checked"](None) is enabled
    assert separator is TrayMenu.SEPARATOR
    assert header.label == "提醒門檻"
    assert header.options["enabled"] is False
    assert [item.label for item in items] == [
        f"用到 {percent}%" for percent in (50, 70, 80, 90, 95)
    ]
    assert [item.options["checked"](None) for item in items] == [False, False, False, True, False]
    assert all(item.options["enabled"](None) is enabled for item in items)
    if enabled:
        items[0].action(None, None)
        assert saved_prefs["quota_notification_thresholds"] == [50.0, 90.0]
        assert items[0].options["checked"](None)
    toggle.action(None, None)
    assert saved_prefs["quota_notifications"] is not enabled
    assert parent.options["checked"](None) is not enabled
    assert all(item.options["enabled"](None) is not enabled for item in items)
    assert controller._quota_notifier is notifier


@pytest.mark.skipif(sys.platform != "darwin", reason="requires PyObjC")
@pytest.mark.parametrize("enabled", [True, False])
def test_macos_threshold_submenu_and_selector(
    saved_prefs: dict[str, Any], monkeypatch: pytest.MonkeyPatch, enabled: bool
) -> None:
    from menubar import menu
    from tests.test_menubar import _FakeMenu, _FakeMenuItem

    saved_prefs["quota_notifications"] = enabled
    monkeypatch.setattr(menu, "NSMenu", _FakeMenu)
    monkeypatch.setattr(menu, "NSMenuItem", _FakeMenuItem)
    marks: list[bool] = []
    notifier = QuotaNotifier()
    app = SimpleNamespace(
        language="zh-TW",
        mock=True,
        _quota_notifier=notifier,
        _mark_switch_menu_action=lambda: marks.append(True),
    )
    parent = menu.build_quota_notifications_menu(app)
    assert parent.state == int(enabled)
    submenu = parent.submenu
    assert submenu.autoenables is False
    toggle, separator, header, *items = submenu.items
    assert toggle.title == "開啟通知"
    assert toggle.action == "toggleQuotaNotifications:"
    assert toggle.state == int(enabled)
    assert separator.title == "---"
    assert header.title == "提醒門檻"
    assert header.enabled is False
    assert [item.title for item in items] == [
        f"用到 {percent}%" for percent in (50, 70, 80, 90, 95)
    ]
    assert [item.state for item in items] == [0, 0, 0, 1, 0]
    assert all(item.enabled is enabled for item in items)
    assert all(item.action == "selectQuotaThreshold:" and item.target is app for item in items)
    menu.select_quota_threshold(app, items[3])
    assert items[3].state == 1
    if enabled:
        menu.select_quota_threshold(app, items[0])
        assert saved_prefs["quota_notification_thresholds"] == [50.0, 90.0]
        assert items[0].state == 1
    assert app._quota_notifier is notifier
    assert marks


@pytest.mark.parametrize("language", ["zh-TW", "zh-CN", "en", "ja", "ko"])
def test_threshold_labels_are_translated(language: str) -> None:
    assert _t(language, "quota_notifications_toggle") != "quota_notifications_toggle"
    assert _t(language, "quota_threshold_header") != "quota_threshold_header"
    assert "70%" in _t(language, "quota_threshold_item", percent=70)

# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>

from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any

import pytest

from usage_common.i18n import _t

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="requires PyObjC")


@pytest.fixture
def settings_callbacks(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    from menubar import notify

    callbacks: list[Any] = []
    center = SimpleNamespace(getNotificationSettingsWithCompletionHandler_=callbacks.append)
    monkeypatch.setattr(notify, "user_notification_center", lambda: (center, {}))
    return callbacks


@pytest.mark.parametrize("status", [None, 0, 1, 2, 3, 4])
@pytest.mark.parametrize("enabled", [True, False])
def test_permission_menu_uses_cached_status(
    monkeypatch: pytest.MonkeyPatch,
    settings_callbacks: list[Any],
    status: int | None,
    enabled: bool,
) -> None:
    from menubar import menu, prefs
    from tests.test_menubar import _FakeMenu, _FakeMenuItem

    monkeypatch.setattr(prefs, "_load_preferences", lambda: {"quota_notifications": enabled})
    monkeypatch.setattr(menu, "NSMenu", _FakeMenu)
    monkeypatch.setattr(menu, "NSMenuItem", _FakeMenuItem)
    app = SimpleNamespace(language="zh-TW", _notification_authorization_status=status, mock=False)
    parent = menu.build_quota_notifications_menu(app)
    warning = [item for item in parent.submenu.items if item.action == "openNotificationSettings:"]
    assert bool(warning) is (enabled and status == 1)
    if warning:
        assert parent.submenu.items[1] is warning[0]
        assert warning[0].title == "系統已關閉 usage 的通知 — 打開系統設定…"
        assert warning[0].enabled is True
        assert warning[0].target is app
    assert len(settings_callbacks) == 1
    assert app._notification_authorization_status == status


def test_permission_refresh_updates_next_menu(
    monkeypatch: pytest.MonkeyPatch, settings_callbacks: list[Any]
) -> None:
    from menubar import menu, prefs
    from tests.test_menubar import _FakeMenu, _FakeMenuItem

    monkeypatch.setattr(prefs, "_load_preferences", lambda: {})
    monkeypatch.setattr(menu, "NSMenu", _FakeMenu)
    monkeypatch.setattr(menu, "NSMenuItem", _FakeMenuItem)
    app = SimpleNamespace(language="en", mock=False)
    first = menu.build_quota_notifications_menu(app)
    assert all(item.action != "openNotificationSettings:" for item in first.submenu.items)
    settings_callbacks[0](SimpleNamespace(authorizationStatus=lambda: 1))
    assert app._notification_authorization_status == 1
    second = menu.build_quota_notifications_menu(app)
    assert second.submenu.items[1].action == "openNotificationSettings:"
    settings_callbacks[1](SimpleNamespace(authorizationStatus=lambda: 2))
    third = menu.build_quota_notifications_menu(app)
    assert all(item.action != "openNotificationSettings:" for item in third.submenu.items)
    assert len(settings_callbacks) == 3


def test_permission_refresh_at_startup(
    monkeypatch: pytest.MonkeyPatch, settings_callbacks: list[Any]
) -> None:
    from menubar import app as menubar_app

    class StopLaunch(Exception):
        pass

    def stop_launch(policy: Any) -> None:
        raise StopLaunch

    monkeypatch.setattr(menubar_app, "NSApp", SimpleNamespace(setActivationPolicy_=stop_launch))
    app = menubar_app.AppDelegate.alloc().initWithMock_interval_(True, 60)
    assert app._notification_authorization_status is None
    app.mock = False
    with pytest.raises(StopLaunch):
        app.applicationDidFinishLaunching_(None)
    assert len(settings_callbacks) == 1
    settings_callbacks[0](SimpleNamespace(authorizationStatus=lambda: 1))
    assert app._notification_authorization_status == 1


def test_permission_selector_opens_system_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    import AppKit
    import Foundation

    from menubar.app import AppDelegate

    opened: list[str] = []
    monkeypatch.setattr(
        AppKit,
        "NSWorkspace",
        SimpleNamespace(sharedWorkspace=lambda: SimpleNamespace(openURL_=opened.append)),
    )
    monkeypatch.setattr(Foundation, "NSURL", SimpleNamespace(URLWithString_=lambda url: url))
    app = AppDelegate.alloc().initWithMock_interval_(True, 60)
    app.openNotificationSettings_(None)
    assert opened == ["x-apple.systempreferences:com.apple.Notifications-Settings.extension"]
    assert app._switch_menu_action_taken is True


def test_permission_refresh_failure_keeps_cached_status(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from menubar import notify

    def unavailable() -> Any:
        raise RuntimeError("fake notification center unavailable")

    monkeypatch.setattr(notify, "user_notification_center", unavailable)
    app = SimpleNamespace(mock=False, _notification_authorization_status=1)
    notify.refresh_notification_permission(app)
    assert app._notification_authorization_status == 1
    assert "notification settings refresh failed" in caplog.text
    assert "fake notification center unavailable" in caplog.text


@pytest.mark.parametrize("language", ["zh-TW", "zh-CN", "en", "ja", "ko"])
def test_permission_warning_translated(language: str) -> None:
    key = "quota_notifications_permission_denied"
    assert _t(language, key) != key

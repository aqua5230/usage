# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import sys
import wave
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from menubar import notify

ROOT = Path(__file__).resolve().parents[1]


class _FakeSound:
    @staticmethod
    def defaultSound() -> str:
        return "default"

    @staticmethod
    def soundNamed_(name: str) -> str:
        return f"named:{name}"


def test_warn_and_depleted_use_uhoh_but_restored_keeps_default() -> None:
    assert notify.notification_sound(_FakeSound, "warn") == "named:usage_uhoh.wav"
    assert notify.notification_sound(_FakeSound, "depleted") == "named:usage_uhoh.wav"
    assert notify.notification_sound(_FakeSound, "restored") == "default"


def test_alert_sound_is_bundled_and_short() -> None:
    sound = ROOT / "assets" / notify.ALERT_SOUND
    assert f"assets/{notify.ALERT_SOUND}" in (ROOT / "setup_app.py").read_text()
    with wave.open(str(sound)) as w:
        assert w.getnframes() / w.getframerate() < 30


@pytest.mark.skipif(sys.platform != "darwin", reason="notification APIs require PyObjC")
@pytest.mark.parametrize(
    "status,alert,style,sent",
    [
        (1, 2, 1, False),
        (2, 2, 1, True),
        (3, 2, 2, True),
        (4, 2, 1, True),
        (2, 1, 1, False),
        (2, 2, 0, False),
    ],
)
def test_test_notification_settings(
    monkeypatch: pytest.MonkeyPatch, status: int, alert: int, style: int, sent: bool
) -> None:
    settings = SimpleNamespace(
        authorizationStatus=lambda: status, alertSetting=lambda: alert, alertStyle=lambda: style
    )
    center = SimpleNamespace(
        getNotificationSettingsWithCompletionHandler_=lambda callback: callback(settings)
    )
    requests: list[str] = []
    dialogs: list[str] = []
    monkeypatch.setattr(notify, "user_notification_center", lambda: (center, {}))
    monkeypatch.setattr(notify, "install_notification_delegate", lambda center: None)
    monkeypatch.setattr(
        notify, "_send_test_request", lambda center, language: requests.append(language)
    )
    monkeypatch.setattr(notify, "_test_dialog", lambda language, key: dialogs.append(key))
    notify.send_test_notification("en")
    assert requests == (["en"] if sent else [])
    assert dialogs == ([] if sent else ["notif_test_blocked"])


@pytest.mark.skipif(sys.platform != "darwin", reason="notification APIs require PyObjC")
@pytest.mark.parametrize("granted", [True, False])
def test_test_notification_requests_authorization(
    monkeypatch: pytest.MonkeyPatch, granted: bool, caplog: pytest.LogCaptureFixture
) -> None:
    pending = SimpleNamespace(authorizationStatus=lambda: 0)
    allowed = SimpleNamespace(
        authorizationStatus=lambda: 2, alertSetting=lambda: 2, alertStyle=lambda: 1
    )
    settings = iter([pending, allowed])
    center = SimpleNamespace(
        getNotificationSettingsWithCompletionHandler_=lambda callback: callback(next(settings)),
        requestAuthorizationWithOptions_completionHandler_=lambda options, callback: callback(
            granted, None
        ),
    )
    events: list[str] = []
    monkeypatch.setattr(
        notify, "user_notification_center", lambda: (center, {"badge": 1, "sound": 2, "alert": 4})
    )
    monkeypatch.setattr(notify, "install_notification_delegate", lambda center: None)
    monkeypatch.setattr(notify, "_send_test_request", lambda *args: events.append("sent"))
    monkeypatch.setattr(notify, "_test_dialog", lambda language, key: events.append(key))
    with caplog.at_level("INFO"):
        notify.send_test_notification("en")
    assert events == (["sent"] if granted else ["notif_test_blocked"])
    assert f"granted={granted} error=None" in caplog.text
    record = next(r for r in caplog.records if "granted=" in r.getMessage())
    assert record.levelname == ("INFO" if granted else "WARNING")


@pytest.mark.skipif(sys.platform != "darwin", reason="notification delegate requires PyObjC")
def test_foreground_delegate_is_reused_and_presents_banner_sound_list() -> None:
    delegates: list[Any] = []
    center = SimpleNamespace(setDelegate_=delegates.append)
    notify.install_notification_delegate(center)
    notify.install_notification_delegate(center)
    assert delegates[0] is delegates[1]
    options: list[int] = []
    delegates[0].userNotificationCenter_willPresentNotification_withCompletionHandler_(
        center, None, options.append
    )
    assert options == [0x10 | 0x8 | 0x2]


@pytest.mark.skipif(sys.platform != "darwin", reason="notification APIs require PyObjC")
def test_test_request_error_reports_description(monkeypatch: pytest.MonkeyPatch) -> None:
    content = SimpleNamespace(
        setTitle_=lambda value: None, setBody_=lambda value: None, setSound_=lambda value: None
    )
    content_cls = SimpleNamespace(alloc=lambda: SimpleNamespace(init=lambda: content))
    identifiers: list[str] = []

    def request(identifier: str, content: Any, trigger: Any) -> str:
        identifiers.append(identifier)
        assert trigger is None
        return identifier

    request_cls = SimpleNamespace(requestWithIdentifier_content_trigger_=request)
    center = SimpleNamespace(
        addNotificationRequest_withCompletionHandler_=lambda request, callback: callback(
            SimpleNamespace(localizedDescription=lambda: "delivery failed")
        )
    )
    dialogs: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        notify, "user_notification_classes", lambda: (content_cls, request_cls, _FakeSound)
    )
    monkeypatch.setattr(notify, "_test_dialog", lambda *args: dialogs.append(args))
    notify._send_test_request(center, "en")
    assert identifiers[0].startswith("usage.test.")
    assert dialogs == [("en", "notif_test_failed", "delivery failed")]


@pytest.mark.skipif(sys.platform != "darwin", reason="dialog dispatch requires PyObjC")
def test_notification_dialog_is_queued_on_main_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    from importlib import import_module

    AppHelper = import_module("PyObjCTools.AppHelper")
    calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(AppHelper, "callAfter", lambda *args: calls.append(args))
    notify._test_dialog("en", "notif_test_blocked")
    assert calls == [(notify._show_test_dialog, "en", "notif_test_blocked", "")]


@pytest.mark.skipif(sys.platform != "darwin", reason="notification settings dialog requires AppKit")
def test_blocked_dialog_opens_notification_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    import AppKit

    from menubar import chrome

    buttons: list[str] = []
    opened: list[str] = []
    alert = SimpleNamespace(
        setMessageText_=lambda text: None, addButtonWithTitle_=buttons.append, runModal=lambda: 1000
    )
    workspace = SimpleNamespace(openURL_=lambda url: opened.append(str(url.absoluteString())))
    monkeypatch.setattr(chrome, "_make_alert", lambda: alert)
    monkeypatch.setattr(AppKit, "NSWorkspace", SimpleNamespace(sharedWorkspace=lambda: workspace))
    notify._show_test_dialog("en", "notif_test_blocked")
    assert buttons == ["Open System Settings", "Close"]
    assert opened == ["x-apple.systempreferences:com.apple.preference.notifications"]


@pytest.mark.skipif(sys.platform != "darwin", reason="notification APIs require PyObjC")
def test_simple_notification_uses_default_sound(monkeypatch: pytest.MonkeyPatch) -> None:
    content: dict[str, str] = {}
    sent: list[object] = []

    class Content:
        @staticmethod
        def alloc() -> Any:
            return Content()

        def init(self) -> Content:
            return self

        def setTitle_(self, value: str) -> None:
            content["title"] = value

        def setBody_(self, value: str) -> None:
            content["body"] = value

        def setSound_(self, value: str) -> None:
            content["sound"] = value

    request_cls = SimpleNamespace(requestWithIdentifier_content_trigger_=lambda *args: args)
    center = SimpleNamespace(
        addNotificationRequest_withCompletionHandler_=lambda request, callback: sent.append(request)
    )
    monkeypatch.setattr(notify, "user_notification_center", lambda: (center, {}))
    monkeypatch.setattr(
        notify, "user_notification_classes", lambda: (Content, request_cls, _FakeSound)
    )
    notify.send_simple_notification("title", "body")
    assert content == {"title": "title", "body": "body", "sound": "default"}
    assert len(sent) == 1

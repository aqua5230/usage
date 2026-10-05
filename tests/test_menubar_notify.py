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

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
from menubar.state import PeriodTotal, PopoverState, QuotaRowState
from quota.notifications import QuotaNotifier
from usage_common.i18n import _t

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def quota_state() -> PopoverState:
    row = QuotaRowState("Session", 89.0, "89%", "", (0.0, 0.0, 0.0))
    return PopoverState(
        language="en",
        claude_session=row,
        claude_weekly=row,
        codex_session=row,
        codex_weekly=row,
        agy_session=row,
        agy_weekly=row,
        agy_group_name="",
        grok_weekly=row,
        projects=[],
        projects_yesterday=[],
        projects_7d=[],
        projects_30d=[],
        projects_all=[],
        rate_text="",
        status_text="",
        today_total=PeriodTotal(),
        yesterday_total=PeriodTotal(),
    )


@pytest.mark.parametrize("available", [False, True])
@pytest.mark.parametrize("stale", [False, True])
@pytest.mark.parametrize("hidden", [False, True])
def test_notification_channels_preserves_old_values(
    quota_state: PopoverState, available: bool, stale: bool, hidden: bool
) -> None:
    state = quota_state
    state.hide_claude = state.hide_codex = state.hide_agy = hidden
    state.agy_stale = {"ageText": "old"} if stale else None
    state.codex_stale = {"ageText": "old"} if stale else None
    names = (
        "claude_session",
        "claude_weekly",
        "codex_session",
        "codex_weekly",
        "agy_session",
        "agy_weekly",
    )
    expected = {}
    for index, name in enumerate(names):
        percent = None if index == 0 else float(index * 10)
        setattr(
            state,
            name,
            QuotaRowState(
                "", percent, "", "", (0.0, 0.0, 0.0), available=available, reset_done=True
            ),
        )
        expected[name] = (percent, available and (not stale or not name.startswith("agy_")))

    channels = notify.notification_channels(state)
    assert {name: channels[name] for name in names} == expected
    assert set(channels) == {*names, "muse_session", "muse_weekly"}


@pytest.mark.parametrize("channel", ["muse_session", "muse_weekly"])
@pytest.mark.parametrize("available", [False, True])
@pytest.mark.parametrize("stale", [False, True])
@pytest.mark.parametrize("hidden", [False, True])
def test_muse_channel_availability_and_text(
    quota_state: PopoverState, channel: str, available: bool, stale: bool, hidden: bool
) -> None:
    row = QuotaRowState("", 91.0, "", "", (0.0, 0.0, 0.0), available=available)
    setattr(quota_state, channel, row)
    quota_state.muse_stale = {"ageText": "old"} if stale else None
    quota_state.hide_muse = hidden

    assert notify.notification_channels(quota_state)[channel] == (91.0, available and not stale)
    assert notify.notification_row(quota_state, channel) is row
    assert notify.notification_tool(channel) == "Muse"
    key = "session_label" if channel.endswith("_session") else "weekly_label"
    assert notify.notification_scope("en", channel) == _t("en", key)


@pytest.mark.parametrize("channel", ["muse_session", "muse_weekly"])
def test_muse_stale_suppresses_events_without_losing_state(
    quota_state: PopoverState, channel: str
) -> None:
    notifier = QuotaNotifier()
    row = QuotaRowState("", 89.0, "", "", (0.0, 0.0, 0.0))
    setattr(quota_state, channel, row)
    assert notifier.update(notify.notification_channels(quota_state)) == []
    for percent, kind in [(90.0, "warn"), (100.0, "depleted"), (5.0, "restored")]:
        row.percent = percent
        quota_state.muse_stale = {"ageText": "old"}
        assert notifier.update(notify.notification_channels(quota_state)) == []
        quota_state.muse_stale = None
        events = notifier.update(notify.notification_channels(quota_state))
        assert [(event.channel, event.kind) for event in events] == [(channel, kind)]


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

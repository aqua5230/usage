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


@pytest.mark.parametrize(
    "channel",
    [
        "claude_session",
        "claude_weekly",
        "codex_session",
        "codex_weekly",
        "agy_session",
        "agy_weekly",
    ],
)
def test_expired_notification_window_ends_silently(channel: str) -> None:
    from menubar import state

    s = state._empty_state()
    notifier = QuotaNotifier()

    def observe(percent: float, reset: float, now: float) -> list[str]:
        setattr(s, channel, state._quota_row("", percent, reset, now, state.CLAUDE_COLOR, "en"))
        return [event.kind for event in notifier.update(notify.notification_channels(s))]

    assert observe(100.0, 999.0, 1000.0) == []
    assert observe(100.0, 1600.0, 1000.0) == ["depleted"]
    assert observe(100.0, 1600.0, 1700.0) == []
    assert observe(96.0, 20000.0, 2200.0) == ["warn"]


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
        active = available and (not stale or not name.startswith("agy_"))
        expected[name] = (None if active else percent, active)

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


def _macos_process_notifications(
    monkeypatch: pytest.MonkeyPatch,
    prefs_data: dict[str, object],
) -> tuple[Any, list[tuple[str, str, float | None]]]:
    from menubar import app as menubar_app
    from usage_common import prefs as common_prefs

    common_prefs._save_preferences(prefs_data)
    monkeypatch.setattr(menubar_app, "_quota_notifications_enabled", lambda: True)
    sent: list[tuple[str, str, float | None]] = []
    delegate = menubar_app.AppDelegate.alloc().initWithMock_interval_(False, 60)
    monkeypatch.setattr(
        delegate,
        "_send_quota_notification",
        lambda event, _state: sent.append((event.channel, event.kind, event.threshold)),
    )
    return delegate, sent


def test_macos_hidden_provider_suppresses_notifications_while_visible_sends(
    monkeypatch: pytest.MonkeyPatch, quota_state: PopoverState
) -> None:
    delegate, sent = _macos_process_notifications(monkeypatch, {"hide_claude_section": True})
    quota_state.claude_session = QuotaRowState("Session", 80.0, "80%", "", (0.0, 0.0, 0.0))
    quota_state.codex_session = QuotaRowState("Session", 80.0, "80%", "", (0.0, 0.0, 0.0))
    delegate._process_quota_notifications(quota_state)
    assert sent == []

    quota_state.claude_session = QuotaRowState("Session", 95.0, "95%", "", (0.0, 0.0, 0.0))
    quota_state.codex_session = QuotaRowState("Session", 95.0, "95%", "", (0.0, 0.0, 0.0))
    delegate._process_quota_notifications(quota_state)
    assert sent == [("codex_session", "warn", 90.0)]


def test_macos_unhiding_provider_does_not_replay_old_notifications(
    monkeypatch: pytest.MonkeyPatch, quota_state: PopoverState
) -> None:
    from usage_common import prefs as common_prefs

    delegate, sent = _macos_process_notifications(monkeypatch, {"hide_claude_section": True})
    for pct in (80.0, 95.0, 100.0, 5.0):
        quota_state.claude_session = QuotaRowState("Session", pct, f"{pct}%", "", (0.0, 0.0, 0.0))
        delegate._process_quota_notifications(quota_state)
    assert sent == []

    common_prefs._save_preferences({"hide_claude_section": False})
    quota_state.claude_session = QuotaRowState("Session", 10.0, "10%", "", (0.0, 0.0, 0.0))
    delegate._process_quota_notifications(quota_state)
    assert sent == []

    quota_state.claude_session = QuotaRowState("Session", 92.0, "92%", "", (0.0, 0.0, 0.0))
    delegate._process_quota_notifications(quota_state)
    assert sent == [("claude_session", "warn", 90.0)]


@pytest.mark.parametrize(
    ("channel", "hide_key"),
    [
        ("claude_session", "hide_claude_section"),
        ("claude_weekly", "hide_claude_section"),
        ("codex_session", "hide_codex_section"),
        ("codex_weekly", "hide_codex_section"),
        ("agy_session", "hide_agy_section"),
        ("agy_weekly", "hide_agy_section"),
        ("muse_session", "hide_muse_section"),
        ("muse_weekly", "hide_muse_section"),
    ],
)
def test_macos_all_provider_hide_prefs_suppress_quota_notifications(
    monkeypatch: pytest.MonkeyPatch,
    quota_state: PopoverState,
    channel: str,
    hide_key: str,
) -> None:
    delegate, sent = _macos_process_notifications(monkeypatch, {hide_key: True})
    setattr(quota_state, channel, QuotaRowState("Session", 80.0, "80%", "", (0.0, 0.0, 0.0)))
    delegate._process_quota_notifications(quota_state)
    setattr(quota_state, channel, QuotaRowState("Session", 95.0, "95%", "", (0.0, 0.0, 0.0)))
    delegate._process_quota_notifications(quota_state)
    assert sent == []

from __future__ import annotations

import sys
import threading
import time
from types import SimpleNamespace
from typing import Any

import pytest

import prefs
from menubar import new_badge

NOW = 1_800_000_000
DAY = 24 * 60 * 60


def test_first_shown_and_expiry() -> None:
    assert new_badge.should_show_badge("claude_pane", NOW + 0.9)
    assert prefs._load_preferences() == {
        "new_feature_badges": {"claude_pane": {"first_shown": NOW, "dismissed": False}}
    }
    assert new_badge.should_show_badge("claude_pane", NOW + 13 * DAY)
    assert new_badge.should_show_badge("claude_pane", NOW + 14 * DAY - 0.1)
    assert not new_badge.should_show_badge("claude_pane", NOW + 14 * DAY)


@pytest.mark.parametrize("already_shown", [False, True])
def test_dismiss(already_shown: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(time, "time", lambda: NOW)
    if already_shown:
        new_badge.should_show_badge("claude_pane", NOW - DAY)
    new_badge.dismiss_badge("claude_pane")
    assert not new_badge.should_show_badge("claude_pane", NOW)
    assert prefs._load_preferences()["new_feature_badges"]["claude_pane"]["dismissed"]


@pytest.mark.parametrize("raw", ['{"other": "keep",', '[]', 'null', '\xff'])
def test_corrupt_file_preserved(raw: str) -> None:
    prefs.PREFERENCES_FILE.parent.mkdir(parents=True, exist_ok=True)
    prefs.PREFERENCES_FILE.write_bytes(raw.encode("latin1"))
    before = prefs.PREFERENCES_FILE.read_bytes()
    assert new_badge.should_show_badge("claude_pane", NOW)
    new_badge.dismiss_badge("claude_pane")
    assert prefs.PREFERENCES_FILE.read_bytes() == before


@pytest.mark.parametrize("badges", [None, [], "invalid", {"claude_pane": []}])
def test_invalid_badges_preserve_preferences(badges: object) -> None:
    prefs._save_preferences({"other": {"keep": True}, "new_feature_badges": badges})
    assert new_badge.should_show_badge("claude_pane", NOW)
    new_badge.dismiss_badge("claude_pane")
    assert prefs._load_preferences()["other"] == {"keep": True}


@pytest.mark.parametrize("first_shown", ["1800000000", NOW + DAY, -1, True])
def test_timestamp_boundaries(first_shown: object) -> None:
    assert not new_badge._valid_first_shown(first_shown, NOW)
    prefs._save_preferences({"new_feature_badges": {
        "claude_pane": {"first_shown": first_shown, "dismissed": False},
        "other_feature": {"first_shown": NOW, "dismissed": True},
    }})
    assert new_badge.should_show_badge("claude_pane", NOW)
    saved = prefs._load_preferences()["new_feature_badges"]
    assert saved["claude_pane"] == {"first_shown": NOW, "dismissed": False}
    assert saved["other_feature"] == {"first_shown": NOW, "dismissed": True}


def test_apply_without_set_badge() -> None:
    new_badge.apply_badge(object(), "en", "claude_pane")
    assert not prefs.PREFERENCES_FILE.exists()


def test_apply_without_api(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "AppKit", SimpleNamespace())
    item = SimpleNamespace(setBadge_=lambda badge: pytest.fail("unexpected badge"))
    new_badge.apply_badge(item, "en", "claude_pane")
    assert not prefs.PREFERENCES_FILE.exists()


@pytest.mark.parametrize("language,label", [
    ("zh-TW", "新"), ("en", "New"), ("zh-CN", "新"), ("ja", "新規"), ("ko", "신규"),
])
def test_apply_native_badge(
    monkeypatch: pytest.MonkeyPatch, language: str, label: str
) -> None:
    calls: list[str] = []
    badge = SimpleNamespace(initWithString_=lambda text: text)
    monkeypatch.setitem(sys.modules, "AppKit", SimpleNamespace(
        NSMenuItemBadge=SimpleNamespace(alloc=lambda: badge),
    ))
    item = SimpleNamespace(setBadge_=calls.append)
    new_badge.apply_badge(item, language, "claude_pane")
    assert calls == [label]
    new_badge.dismiss_badge("claude_pane")
    new_badge.apply_badge(item, language, "claude_pane")
    assert calls == [label]


def test_write_failure_is_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(data: dict[str, Any]) -> None:
        raise OSError("test preferences unavailable")

    monkeypatch.setattr(new_badge, "_save_preferences", fail)
    assert new_badge.should_show_badge("claude_pane", NOW)
    new_badge.dismiss_badge("claude_pane")


@pytest.mark.skipif(sys.platform != "darwin", reason="menu actions require AppKit")
def test_toggle_dismisses(monkeypatch: pytest.MonkeyPatch) -> None:
    from menubar import actions

    calls: list[str] = []
    monkeypatch.setattr(threading, "Thread", lambda **kwargs: SimpleNamespace(
        start=lambda: calls.append("start"),
    ))
    monkeypatch.setattr(actions, "dismiss_badge", lambda feature: calls.append(feature))
    app = SimpleNamespace(_mark_switch_menu_action=lambda: calls.append("mark"))
    actions.toggle_claude_pane(app)
    assert calls == ["claude_pane", "mark", "start"]

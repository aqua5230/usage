# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

import codex_loader
import history_loader
import menubar
import menubar_state
import statusline_settings
from burn_rate import BurnRateTracker
from usage_client import PollOutcome, PollState, UsageSnapshot


class _FakeMenu:
    last: _FakeMenu | None = None
    instances: list[_FakeMenu] = []

    def __init__(self) -> None:
        self.items: list[_FakeMenuItem] = []
        _FakeMenu.last = self
        _FakeMenu.instances.append(self)

    @classmethod
    def alloc(cls) -> _FakeMenu:
        return cls()

    def initWithTitle_(self, title: str) -> _FakeMenu:
        self.title = title
        return self

    def addItem_(self, item: _FakeMenuItem) -> None:
        self.items.append(item)

    def popUpMenuPositioningItem_atLocation_inView_(
        self,
        item: object,
        location: object,
        view: object,
    ) -> None:
        return None


class _FakeMenuItem:
    def __init__(self) -> None:
        self.title = ""
        self.state = 0
        self.target: object | None = None
        self.represented: object | None = None
        self.enabled = True
        self.indentation = 0
        self.action = ""
        self.submenu: object | None = None
        self.tooltip: str | None = None

    @classmethod
    def alloc(cls) -> _FakeMenuItem:
        return cls()

    @classmethod
    def separatorItem(cls) -> _FakeMenuItem:
        item = cls()
        item.title = "---"
        return item

    def initWithTitle_action_keyEquivalent_(
        self,
        title: str,
        action: str,
        key: str,
    ) -> _FakeMenuItem:
        self.title = title
        self.action = action
        self.key = key
        return self

    def setTarget_(self, target: object) -> None:
        self.target = target

    def setRepresentedObject_(self, value: object) -> None:
        self.represented = value

    def representedObject(self) -> object:
        return self.represented

    def setState_(self, state: int) -> None:
        self.state = state

    def setEnabled_(self, enabled: bool) -> None:
        self.enabled = enabled

    def setIndentationLevel_(self, level: int) -> None:
        self.indentation = level

    def setSubmenu_(self, submenu: object) -> None:
        self.submenu = submenu

    def setToolTip_(self, tooltip: str) -> None:
        self.tooltip = tooltip


def _codex_rows(
    delegate: menubar.AppDelegate,
) -> tuple[
    tuple[menubar_state.QuotaRowState, menubar_state.QuotaRowState],
    float | None,
    str,
    menubar_state.CodexStaleState | None,
]:
    return menubar_state.codex_rows(
        mock=delegate.mock,
        language=delegate.language,
        burn_rate_trackers=delegate.burn_rate_trackers,
    )


def _build_popover_state(
    delegate: menubar.AppDelegate,
    outcome: PollOutcome,
    codex_rows: tuple[menubar_state.QuotaRowState, menubar_state.QuotaRowState],
) -> menubar_state.PopoverState:
    hide_claude = menubar._hide_claude_enabled()
    return menubar_state.build_popover_state(
        outcome=outcome,
        codex_rows=codex_rows,
        projects=[],
        projects_7d=[],
        projects_30d=[],
        projects_all=[],
        language=delegate.language,
        group=delegate.tracker.group(),
        burn_rate_trackers=delegate.burn_rate_trackers,
        today_text=menubar._today_title(delegate.mock, delegate.language),
        statusline=menubar._statusline_payload(delegate.language),
        show_install_button=(
            not hide_claude
            and outcome.state == PollState.TOKEN_ERROR
            and delegate._statusline_setup_available()
        ),
        hide_claude=hide_claude,
        hide_codex=menubar._hide_codex_enabled(),
        codex_stale=None,
    )


@pytest.fixture(scope="module")
def _cached_state_delegate() -> menubar.AppDelegate:
    delegate: menubar.AppDelegate = menubar.AppDelegate.alloc().initWithMock_interval_(False, 60)
    return delegate


def _reset_state_delegate(delegate: menubar.AppDelegate) -> menubar.AppDelegate:
    delegate.language = menubar._detect_language()
    delegate.latest_state = menubar._empty_state(delegate.language)
    delegate.codex_5h_pct = None
    delegate.codex_model = "unknown"
    delegate.burn_rate_trackers = {
        "claude_session": BurnRateTracker(),
        "claude_weekly": BurnRateTracker(),
        "codex_session": BurnRateTracker(),
        "codex_weekly": BurnRateTracker(),
    }
    return delegate


@pytest.fixture
def state_delegate(_cached_state_delegate: menubar.AppDelegate) -> menubar.AppDelegate:
    return _reset_state_delegate(_cached_state_delegate)


def test_format_human_time_zero_and_negative() -> None:
    assert menubar.format_human_time(0) == "0m"
    assert menubar.format_human_time(-1) == "0m"


def test_format_human_time_sub_minute() -> None:
    assert menubar.format_human_time(30) == "0m"


def test_format_human_time_minutes_hours_and_days() -> None:
    assert menubar.format_human_time(90) == "1m"
    assert menubar.format_human_time(3700) == "1h 1m"
    assert menubar.format_human_time(90000) == "1d 1h"


def test_format_percent() -> None:
    assert menubar._format_percent(50.0) == "50"
    assert menubar._format_percent(50.5) == "50.5"
    assert menubar._format_percent(0.0) == "0"


def test_bar_color_thresholds() -> None:
    brand = (0.1, 0.2, 0.3)

    assert menubar._bar_color(80, brand) == menubar.DANGER_COLOR
    assert menubar._bar_color(60, brand) == menubar.WARN_COLOR
    assert menubar._bar_color(49, brand) == brand


def test_quota_row_returns_missing_when_percent_is_none() -> None:
    row = menubar._quota_row("Session", None, 1_100.0, 1_000.0, menubar.CODEX_COLOR)

    assert row.available is False
    assert row.percent is None
    assert row.percent_text == "--"


def test_quota_row_returns_missing_when_reset_is_none() -> None:
    row = menubar._quota_row("Session", 50.0, None, 1_000.0, menubar.CODEX_COLOR)

    assert row.available is False
    assert row.percent is None
    assert row.percent_text == "--"


def test_quota_row_formats_available_row() -> None:
    row = menubar._quota_row(
        "Session", 50.5, 1_090.0, 1_000.0, menubar.CODEX_COLOR, language="zh-TW"
    )

    assert row.available is True
    assert row.percent == 50.5
    assert row.percent_text == "50.5% 已用"
    assert row.reset_text.startswith("重置 ")
    assert row.warning is False
    assert row.color == menubar.WARN_COLOR


def test_quota_row_clamps_percent_to_range() -> None:
    high = menubar._quota_row(
        "Session", 150.0, 1_090.0, 1_000.0, menubar.CODEX_COLOR, language="zh-TW"
    )
    low = menubar._quota_row(
        "Session", -10.0, 1_090.0, 1_000.0, menubar.CODEX_COLOR, language="zh-TW"
    )

    assert high.percent == 100.0
    assert high.percent_text == "100% 已用"
    assert low.percent == 0.0
    assert low.percent_text == "0% 已用"


def test_missing_row() -> None:
    row = menubar._missing_row("Weekly", menubar.CLAUDE_COLOR, language="zh-TW")

    assert row.available is False
    assert row.percent is None
    assert row.percent_text == "--"
    assert row.reset_text == "重置 --"
    assert row.warning is False


def test_quota_row_uses_burn_warning_when_forecast_exceeds_risk_threshold() -> None:
    row = menubar._quota_row(
        "Session",
        82.0,
        1_000.0 + (51 * 60),
        1_000.0,
        menubar.CODEX_COLOR,
        language="zh-TW",
        forecast_seconds=18 * 60,
    )

    assert row.warning is True
    assert row.reset_text == "⚠ 按目前速度 18分鐘 就會用完(重置還要 51分鐘)"

def test_quota_row_keeps_reset_text_when_forecast_is_not_before_reset() -> None:
    row = menubar._quota_row(
        "Session",
        82.0,
        1_000.0 + (18 * 60),
        1_000.0,
        menubar.CODEX_COLOR,
        language="zh-TW",
        forecast_seconds=51 * 60,
    )

    assert row.warning is False
    assert row.reset_text == "重置 18分鐘"


def test_quota_row_keeps_reset_text_when_forecast_exceeds_warning_max() -> None:
    row = menubar._quota_row(
        "Weekly",
        82.0,
        1_000.0 + (4 * 86400),
        1_000.0,
        menubar.CODEX_COLOR,
        language="zh-TW",
        forecast_seconds=25 * 3600,
        warning_max_seconds=24 * 3600,
    )

    assert row.warning is False
    assert row.reset_text == "重置 4天 0小時"


def test_quota_row_keeps_reset_text_when_percent_is_below_warning_floor() -> None:
    row = menubar._quota_row(
        "Session",
        30.0,
        1_000.0 + (51 * 60),
        1_000.0,
        menubar.CODEX_COLOR,
        language="zh-TW",
        forecast_seconds=18 * 60,
    )

    assert row.warning is False
    assert row.reset_text == "重置 51分鐘"


def test_today_title_mock() -> None:
    assert menubar._today_title(mock=True, language="zh-TW") == "今日：$45.20 (50,193,442 tokens)"


def test_today_title_returns_zero_fallback_when_loaders_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        menubar,
        "load_entries",
        lambda *, hours_back=24: (_ for _ in ()).throw(OSError),
    )

    assert menubar._today_title(mock=False, language="zh-TW") == "今日：$0.00 (0 tokens)"


def test_today_title_does_not_reload_codex_when_entries_are_provided(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = history_loader.UsageEntry(
        timestamp=datetime.now(tz=UTC),
        session_id="codex",
        message_id="m1",
        request_id="r1",
        model="gpt",
        input_tokens=100,
        output_tokens=50,
        cache_creation_tokens=0,
        cache_read_tokens=0,
        cost_usd=0.01,
        project="usage",
    )
    monkeypatch.setattr(
        "menubar.codex_loader.load_entries",
        lambda *, hours_back=24: pytest.fail("Codex should already be included"),
    )

    assert menubar._today_title(mock=False, language="en", entries=[entry]) == (
        "Today: $0.01 (150 tokens)"
    )


def test_empty_state() -> None:
    state = menubar._empty_state()
    rows = (
        state.claude_session,
        state.claude_weekly,
        state.codex_session,
        state.codex_weekly,
    )

    assert all(row.available is False for row in rows)
    assert state.projects == []
    assert state.projects_7d == []
    assert state.projects_30d == []
    assert state.projects_all == []
    assert isinstance(state.statusline["enabled"], bool)
    assert state.show_install_button is False


def test_switch_panel_menu_contains_update_items(monkeypatch: pytest.MonkeyPatch) -> None:
    delegate = menubar.AppDelegate.alloc().initWithMock_interval_(True, 60)
    delegate.language = "en"
    delegate.active_panel = SimpleNamespace(id="classic")
    delegate.critters_enabled = False
    panels = [
        SimpleNamespace(id="classic", i18n_key="panel_default_name"),
        SimpleNamespace(id="matrix", i18n_key="panel_matrix"),
    ]

    monkeypatch.setattr(menubar, "NSMenu", _FakeMenu)
    monkeypatch.setattr(menubar, "NSMenuItem", _FakeMenuItem)
    monkeypatch.setattr("menubar.panels.all_panels", lambda: panels)
    monkeypatch.setattr("menubar.login_item.is_enabled", lambda: False)
    monkeypatch.setattr(menubar, "_load_preferences", lambda: {"hide_codex_section": True})

    _FakeMenu.instances = []
    menubar.AppDelegate.switchPanel_(delegate, object())

    # Three menus are built: the main popup, the panel-themes submenu, and the
    # provider-visibility submenu.
    main_menu, panel_submenu, hide_submenu = (
        _FakeMenu.instances[0],
        _FakeMenu.instances[1],
        _FakeMenu.instances[2],
    )
    main_titles = [item.title for item in main_menu.items]

    # The auto-update row is gone — update checks just stay on by default.
    assert "Automatically Check for Updates" not in main_titles
    assert "Usage Alert Notifications" in main_titles
    critters = next(item for item in main_menu.items if item.action == "toggleCritters:")
    assert critters.title == "Summon Spirits"
    assert critters.state == 0

    # Panel themes are collapsed into a submenu, not listed inline on the main menu.
    assert "Default" not in main_titles
    assert [item.title for item in panel_submenu.items] == ["Default", "Matrix"]
    parent = next(item for item in main_menu.items if item.submenu is panel_submenu)
    assert parent.submenu is panel_submenu

    # Provider hide toggles are collapsed into one "Hide Sections" submenu, with
    # the checkmark reflecting the stored preference.
    assert "Hide Sections" in main_titles
    assert [item.title for item in hide_submenu.items] == ["Claude Code", "Codex"]
    hide_parent = next(item for item in main_menu.items if item.submenu is hide_submenu)
    assert hide_parent.title == "Hide Sections"
    claude_item, codex_item = hide_submenu.items
    assert claude_item.action == "toggleHideClaude:"
    assert claude_item.state == 0
    assert codex_item.action == "toggleHideCodex:"
    assert codex_item.state == 1

    # Resume Last Session is a single tooltip-backed toggle (no group header, no indent).
    butler = next(item for item in main_menu.items if item.action == "toggleSessionResume:")
    assert butler.title == "Resume Last Session"
    assert butler.indentation == 0
    assert butler.tooltip
    assert "Show in report" not in main_titles


def test_switch_panel_cancel_closes_visible_popover(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeController:
        def __init__(self) -> None:
            self.states: list[object] = []

        def setState_(self, state: object) -> None:
            self.states.append(state)

    class FakeButton:
        def bounds(self) -> str:
            return "button-bounds"

    class FakeStatusItem:
        def __init__(self) -> None:
            self._button = FakeButton()

        def button(self) -> FakeButton:
            return self._button

    class FakePopover:
        def __init__(self) -> None:
            self.closed = 0
            self.sizes: list[object] = []
            self.shown: list[tuple[object, object, object]] = []

        def isShown(self) -> bool:
            return True

        def performClose_(self, sender: object) -> None:
            self.closed += 1

        def setContentSize_(self, size: object) -> None:
            self.sizes.append(size)

        def showRelativeToRect_ofView_preferredEdge_(
            self,
            rect: object,
            view: object,
            edge: object,
        ) -> None:
            self.shown.append((rect, view, edge))

    class FakePanel:
        id = "classic"
        claude_card_height = 0.0
        codex_card_height = 0.0

        def preferred_size(self) -> tuple[float, float]:
            return (300.0, 400.0)

    delegate = menubar.AppDelegate.alloc().initWithMock_interval_(True, 60)
    delegate.language = "en"
    delegate.latest_state = menubar._empty_state(language="en")
    delegate.active_panel = FakePanel()
    delegate.popover_controller = FakeController()
    delegate.popover = FakePopover()
    delegate.status_item = FakeStatusItem()

    monkeypatch.setattr(menubar, "NSMenu", _FakeMenu)
    monkeypatch.setattr(menubar, "NSMenuItem", _FakeMenuItem)
    monkeypatch.setattr(
        "menubar.panels.all_panels",
        lambda: [SimpleNamespace(id="classic", i18n_key="panel_default_name")],
    )
    monkeypatch.setattr("menubar.login_item.is_enabled", lambda: False)

    menubar.AppDelegate.switchPanel_(delegate, object())

    assert delegate.popover.closed == 1
    assert delegate.popover_controller.states == []
    assert delegate.popover.sizes == []
    assert delegate.popover.shown == []


def test_auto_update_disabled_skips_background_check(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    def fake_check_latest_release(current_version: str) -> object:
        nonlocal called
        called = True
        return None

    monkeypatch.setattr(menubar, "_load_preferences", lambda: {"auto_update_check": False})
    monkeypatch.setattr("menubar.update_checker.check_latest_release", fake_check_latest_release)

    menubar.AppDelegate._check_update_in_background(
        cast(Any, object()),
        manual=False,
        ignore_cooldown=False,
        ignore_skipped=False,
    )

    assert called is False


def test_background_daily_maintenance_schedules_diagnosis_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []

    monkeypatch.setattr(
        "menubar.usage_diagnosis_snapshot.maybe_schedule_refresh",
        lambda: calls.append("snapshot"),
    )
    fake_self = SimpleNamespace(
        _check_update_in_background=lambda **kwargs: calls.append(kwargs),
    )

    menubar.AppDelegate._maybe_check_update_in_background(cast(Any, fake_self))

    assert calls == [
        "snapshot",
        {"manual": False, "ignore_cooldown": False, "ignore_skipped": False},
    ]


def test_check_update_writes_cache_when_release_found(monkeypatch: pytest.MonkeyPatch) -> None:
    saved: list[dict[str, Any]] = []
    monkeypatch.setattr(menubar, "_load_preferences", lambda: {"auto_update_check": True})
    monkeypatch.setattr(menubar, "_save_preferences", lambda d: saved.append(dict(d)))
    monkeypatch.setattr(menubar, "_current_version", lambda: "0.11.3")
    monkeypatch.setattr("update_gate.time.time", lambda: 1700000000.0)
    fake_release = SimpleNamespace(version="0.12.0", html_url="https://x/v0.12.0", body="")
    monkeypatch.setattr(
        "menubar.update_checker.check_latest_release_result",
        lambda v: SimpleNamespace(failed=False, release=fake_release),
    )
    fake_self = SimpleNamespace(
        performSelectorOnMainThread_withObject_waitUntilDone_=lambda *a: None,
    )

    menubar.AppDelegate._check_update_in_background(
        cast(Any, fake_self),
        manual=False,
        ignore_cooldown=False,
        ignore_skipped=True,
    )

    assert saved
    cache = saved[-1]["last_update_check"]
    assert cache["current_version"] == "0.11.3"
    assert cache["latest_version"] == "0.12.0"
    assert cache["release_url"] == "https://x/v0.12.0"
    assert cache["checked_at"] == 1700000000.0


def test_check_update_writes_cache_when_no_release(monkeypatch: pytest.MonkeyPatch) -> None:
    saved: list[dict[str, Any]] = []
    monkeypatch.setattr(menubar, "_load_preferences", lambda: {"auto_update_check": True})
    monkeypatch.setattr(menubar, "_save_preferences", lambda d: saved.append(dict(d)))
    monkeypatch.setattr(menubar, "_current_version", lambda: "0.11.3")
    monkeypatch.setattr("update_gate.time.time", lambda: 1700000000.0)
    monkeypatch.setattr(
        "menubar.update_checker.check_latest_release_result",
        lambda v: SimpleNamespace(failed=False, release=None),
    )

    menubar.AppDelegate._check_update_in_background(
        cast(Any, object()),
        manual=False,
        ignore_cooldown=False,
        ignore_skipped=False,
    )

    assert saved
    cache = saved[-1]["last_update_check"]
    assert cache["latest_version"] == "0.11.3"
    assert cache["release_url"] is None


def test_check_update_skips_cache_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    saved: list[dict[str, Any]] = []
    monkeypatch.setattr(menubar, "_load_preferences", lambda: {"auto_update_check": True})
    monkeypatch.setattr(menubar, "_save_preferences", lambda d: saved.append(dict(d)))
    monkeypatch.setattr(menubar, "_current_version", lambda: "0.11.3")
    monkeypatch.setattr(
        "menubar.update_checker.check_latest_release_result",
        lambda v: SimpleNamespace(failed=True, release=None),
    )

    menubar.AppDelegate._check_update_in_background(
        cast(Any, object()),
        manual=False,
        ignore_cooldown=False,
        ignore_skipped=False,
    )

    assert saved == []


def test_clear_stale_update_cache_clears_after_upgrade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved: list[dict[str, Any]] = []
    prefs = {
        "last_update_check": {
            "checked_at": 1700000000.0,
            "current_version": "0.14.3",
            "latest_version": "0.15.0",
            "release_url": "https://x/v0.15.0",
        }
    }
    monkeypatch.setattr(menubar, "_load_preferences", lambda: prefs)
    monkeypatch.setattr(menubar, "_save_preferences", lambda d: saved.append(dict(d)))
    monkeypatch.setattr(menubar, "_current_version", lambda: "0.15.0")

    menubar.AppDelegate._clear_stale_update_cache(cast(Any, object()))

    assert saved
    cache = saved[-1]["last_update_check"]
    assert cache["current_version"] == "0.15.0"
    assert cache["latest_version"] == "0.15.0"


def test_clear_stale_update_cache_keeps_pending_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved: list[dict[str, Any]] = []
    prefs = {
        "last_update_check": {
            "checked_at": 1700000000.0,
            "current_version": "0.15.0",
            "latest_version": "0.16.0",
            "release_url": "https://x/v0.16.0",
        }
    }
    monkeypatch.setattr(menubar, "_load_preferences", lambda: prefs)
    monkeypatch.setattr(menubar, "_save_preferences", lambda d: saved.append(dict(d)))
    monkeypatch.setattr(menubar, "_current_version", lambda: "0.15.0")

    menubar.AppDelegate._clear_stale_update_cache(cast(Any, object()))

    assert saved == []


def test_statusline_enabled_detects_usage_hook(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    settings = claude_dir / "settings.json"
    settings.write_text(
        json.dumps({"statusLine": {"type": "command", "command": "python3 usage-statusline.py"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr("menubar.os.path.expanduser", lambda value: str(settings))

    assert menubar._statusline_enabled() is True


def test_statusline_enabled_detects_external_hook(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    settings = claude_dir / "settings.json"
    legacy_name = "tt" + "-statusline.py"
    settings.write_text(
        json.dumps({"statusLine": {"type": "command", "command": f"python3 {legacy_name}"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr("menubar.os.path.expanduser", lambda value: str(settings))

    assert menubar._statusline_enabled() is True


def test_toggle_statusline_preserves_forwarder_settings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    settings = claude_dir / "settings.json"
    original = {
        "env": {"KEEP": "1"},
        "statusLine": {
            "type": "command",
            "command": "python3 ~/.claude/"
            + "tt"
            + "-statusline-usage-statusline-forward.py",
        },
    }
    settings.write_text(json.dumps(original, indent=2, ensure_ascii=False), encoding="utf-8")
    original_text = settings.read_text(encoding="utf-8")
    monkeypatch.setattr("menubar.os.path.expanduser", lambda value: str(settings))

    action, exit_code = menubar._toggle_statusline_settings()

    assert (action, exit_code) == ("uninstall", 0)
    disabled = json.loads(settings.read_text(encoding="utf-8"))
    assert "statusLine" not in disabled
    assert disabled["usage"]["previousStatusLine"] == original["statusLine"]

    action, exit_code = menubar._toggle_statusline_settings()

    assert (action, exit_code) == ("install", 0)
    assert settings.read_text(encoding="utf-8") == original_text


def test_forwarder_prompt_keep_sets_ack_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import setup_hook

    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    settings = claude_dir / "settings.json"
    settings.write_text(
        json.dumps({"statusLine": {"type": "command", "command": "python3 ccusage.py"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(setup_hook, "CLAUDE_SETTINGS", settings)
    calls = {"alerts": 0, "setup": 0}

    class FakeAlert:
        @classmethod
        def alloc(cls) -> type[FakeAlert]:
            return cls

        @classmethod
        def init(cls) -> FakeAlert:
            return cls()

        def setMessageText_(self, value: str) -> None:
            return None

        def setInformativeText_(self, value: str) -> None:
            return None

        def addButtonWithTitle_(self, value: str) -> None:
            return None

        def setIcon_(self, value: object) -> None:
            return None

        def runModal(self) -> int:
            calls["alerts"] += 1
            return 1001

    def fake_setup(*, force_forwarder: bool = False) -> int:
        calls["setup"] += 1
        return 0

    monkeypatch.setattr(menubar, "NSAlert", FakeAlert)
    monkeypatch.setattr(setup_hook, "setup", fake_setup)

    menubar.show_forwarder_mode_prompt_if_needed(language="en")
    menubar.show_forwarder_mode_prompt_if_needed(language="en")
    data = json.loads(settings.read_text(encoding="utf-8"))

    assert calls == {"alerts": 1, "setup": 0}
    assert data["usage"]["forwarderModePromptDismissed"] is True


def test_forwarder_prompt_enable_calls_forwarder_setup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import setup_hook

    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    settings = claude_dir / "settings.json"
    settings.write_text(
        json.dumps({"statusLine": {"type": "command", "command": "python3 lord-kali.py"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(setup_hook, "CLAUDE_SETTINGS", settings)
    calls: list[bool] = []

    class FakeAlert:
        @classmethod
        def alloc(cls) -> type[FakeAlert]:
            return cls

        @classmethod
        def init(cls) -> FakeAlert:
            return cls()

        def setMessageText_(self, value: str) -> None:
            return None

        def setInformativeText_(self, value: str) -> None:
            return None

        def addButtonWithTitle_(self, value: str) -> None:
            return None

        def setIcon_(self, value: object) -> None:
            return None

        def runModal(self) -> int:
            return 1000

    def fake_setup(*, force_forwarder: bool = False) -> int:
        calls.append(force_forwarder)
        return 0

    monkeypatch.setattr(menubar, "NSAlert", FakeAlert)
    monkeypatch.setattr(setup_hook, "setup", fake_setup)

    menubar.show_forwarder_mode_prompt_if_needed(language="en")
    data = json.loads(settings.read_text(encoding="utf-8"))

    assert calls == [True]
    assert data["usage"]["forwarderModePromptDismissed"] is True


def test_make_alert_falls_back_when_nsalert_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeAlert:
        @classmethod
        def alloc(cls) -> type[FakeAlert]:
            return cls

        @classmethod
        def init(cls) -> None:
            return None

    monkeypatch.setattr(menubar, "NSAlert", FakeAlert)

    alert = menubar._make_alert()

    alert.setMessageText_("ignored")
    alert.setInformativeText_("ignored")
    alert.addButtonWithTitle_("ignored")
    assert alert.runModal() == 0


def test_make_alert_ignores_icon_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeAlert:
        @classmethod
        def alloc(cls) -> type[FakeAlert]:
            return cls

        @classmethod
        def init(cls) -> FakeAlert:
            return cls()

        def setIcon_(self, value: object) -> None:
            raise RuntimeError("icon failed")

    monkeypatch.setattr(menubar, "NSAlert", FakeAlert)
    monkeypatch.setattr(menubar, "_alert_icon", lambda: object())

    assert isinstance(menubar._make_alert(), FakeAlert)


def test_statusline_action_in_background_returns_failure_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class Delegate:
        def performSelectorOnMainThread_withObject_waitUntilDone_(
            self, selector: str, result: dict[str, object], wait: bool
        ) -> None:
            captured["selector"] = selector
            captured["result"] = result
            captured["wait"] = wait

    monkeypatch.setattr(
        menubar,
        "_enable_statusline_settings",
        lambda: (_ for _ in ()).throw(RuntimeError("setup failed")),
    )

    menubar.AppDelegate._statusline_action_in_background(cast(Any, Delegate()), "install")

    result = captured["result"]
    assert isinstance(result, dict)
    assert result["ok"] is False
    assert result["action"] == "install"
    assert "RuntimeError: setup failed" in str(result["output"])


def test_enable_statusline_ignores_missing_previous_command(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import setup_hook

    settings = tmp_path / "settings.json"
    missing_hook = tmp_path / "missing-statusline.py"
    settings.write_text(
        json.dumps(
            {
                "env": {"KEEP": "1"},
                "usage": {
                    "previousStatusLine": {
                        "type": "command",
                        "command": f"python3 {missing_hook}",
                    }
                },
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    setup_called = False

    def fake_setup() -> int:
        nonlocal setup_called
        setup_called = True
        return 0

    monkeypatch.setattr(statusline_settings, "_claude_settings_path", lambda: settings)
    monkeypatch.setattr(setup_hook, "setup", fake_setup)

    assert menubar._enable_statusline_settings() == 0
    assert setup_called is True
    updated = json.loads(settings.read_text(encoding="utf-8"))
    assert updated == {"env": {"KEEP": "1"}}


def test_error_state_uses_message_and_mock_today_title() -> None:
    state = menubar._error_state("boom", mock=True, language="zh-TW")

    assert "boom" in state.status_text
    assert state.today_text == "今日：$45.20 (50,193,442 tokens)"


def test_popover_size_has_positive_dimensions() -> None:
    size = menubar._popover_size(menubar._empty_state())

    assert size.width > 0
    assert size.height > 0


def test_hide_claude_enabled_reads_preferences(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(menubar, "_load_preferences", lambda: {"hide_claude_section": True})

    assert menubar._hide_claude_enabled() is True
    assert menubar._hide_claude_enabled({"hide_claude_section": False}) is False
    assert menubar._hide_claude_enabled({}) is False


def test_popover_size_deducts_hidden_cards(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakePanel:
        id = "classic"
        i18n_key = "panel_default_name"
        claude_card_height = 100.0
        codex_card_height = 60.0

        def build_view(self, delegate: Any) -> Any:
            return object()

        def apply_state(self, view: Any, state: menubar_state.PopoverState) -> None:
            return None

        def preferred_size(self) -> tuple[float, float]:
            return (300.0, 500.0)

    monkeypatch.setattr(menubar, "_load_preferences", lambda: {})
    state = menubar._empty_state()
    panel = FakePanel()

    assert menubar._popover_size(state, panel).height == 500.0
    state.hide_claude = True
    assert menubar._popover_size(state, panel).height == 400.0
    state.hide_codex = True
    assert menubar._popover_size(state, panel).height == 340.0


def test_compose_title_hides_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(menubar, "_load_preferences", lambda: {})
    delegate = menubar.AppDelegate.alloc().initWithMock_interval_(True, 60)
    delegate.codex_5h_pct = 12.0
    state = menubar._empty_state()
    state.claude_session.percent = 50.0

    assert delegate._compose_title(state) == "🐾 50% · 📜 12%"
    state.hide_claude = True
    assert delegate._compose_title(state) == "📜 12%"
    state.hide_codex = True
    assert delegate._compose_title(state) == "🐾"
    state.hide_claude = False
    assert delegate._compose_title(state) == "🐾 50%"


def test_compose_title_codex_placeholder_when_claude_hidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(menubar, "_load_preferences", lambda: {})
    delegate = menubar.AppDelegate.alloc().initWithMock_interval_(True, 60)
    delegate.codex_5h_pct = None
    state = menubar._empty_state()
    state.hide_claude = True

    assert delegate._compose_title(state) == "📜 --"


def test_project_rows_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    delegate = menubar.AppDelegate.alloc().initWithMock_interval_(False, 60)
    monkeypatch.setattr(menubar, "load_entries", lambda *, hours_back=24: [])

    assert delegate._project_rows(hours_back=24) == []


def test_load_history_entries_includes_codex_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    delegate = menubar.AppDelegate.alloc().initWithMock_interval_(False, 60)
    claude_entry = history_loader.UsageEntry(
        timestamp=datetime(2026, 5, 21, tzinfo=UTC),
        session_id="claude",
        message_id="m1",
        request_id="r1",
        model="claude",
        input_tokens=1,
        output_tokens=2,
        cache_creation_tokens=3,
        cache_read_tokens=4,
        cost_usd=0.1,
        project="usage",
    )
    codex_entry = history_loader.UsageEntry(
        timestamp=datetime(2026, 5, 21, tzinfo=UTC),
        session_id="codex",
        message_id="m2",
        request_id="r2",
        model="gpt",
        input_tokens=5,
        output_tokens=6,
        cache_creation_tokens=7,
        cache_read_tokens=8,
        cost_usd=0.2,
        project="usage",
    )

    monkeypatch.setattr(menubar, "load_entries", lambda *, hours_back: [claude_entry])
    monkeypatch.setattr("menubar.codex_loader.load_entries", lambda *, hours_back: [codex_entry])

    assert delegate._load_history_entries() == [claude_entry, codex_entry]


def test_load_history_entries_reuses_cache_when_sources_do_not_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delegate = menubar.AppDelegate.alloc().initWithMock_interval_(False, 60)
    claude_entry = history_loader.UsageEntry(
        timestamp=datetime(2026, 5, 21, tzinfo=UTC),
        session_id="claude-session",
        message_id="claude-message",
        request_id="claude-request",
        model="claude",
        input_tokens=10,
        output_tokens=5,
        cache_creation_tokens=0,
        cache_read_tokens=0,
        cost_usd=0.01,
        project="ClaudeProject",
    )
    codex_entry = history_loader.UsageEntry(
        timestamp=datetime(2026, 5, 22, tzinfo=UTC),
        session_id="codex-session",
        message_id="codex-message",
        request_id="",
        model="gpt",
        input_tokens=20,
        output_tokens=7,
        cache_creation_tokens=0,
        cache_read_tokens=0,
        cost_usd=None,
        project="CodexProject",
    )
    calls = {"claude": 0, "codex": 0}

    def fake_claude_entries(*, hours_back: int = 0) -> list[history_loader.UsageEntry]:
        calls["claude"] += 1
        assert hours_back == 0
        return [claude_entry]

    def fake_codex_entries(*, hours_back: int = 0) -> list[history_loader.UsageEntry]:
        calls["codex"] += 1
        assert hours_back == 0
        return [codex_entry]

    monkeypatch.setattr(delegate, "_history_sources_fingerprint", lambda: (("same", 1, 1.0),))
    monkeypatch.setattr(menubar, "load_entries", fake_claude_entries)
    monkeypatch.setattr(codex_loader, "load_entries", fake_codex_entries)

    first = delegate._load_history_entries()
    second = delegate._load_history_entries()

    assert first == [claude_entry, codex_entry]
    assert second == first
    assert calls == {"claude": 1, "codex": 1}


def test_load_history_entries_refreshes_cache_when_sources_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delegate = menubar.AppDelegate.alloc().initWithMock_interval_(False, 60)
    entries = [
        history_loader.UsageEntry(
            timestamp=datetime(2026, 5, 22, tzinfo=UTC),
            session_id="codex-session",
            message_id="codex-message",
            request_id="",
            model="gpt",
            input_tokens=20,
            output_tokens=7,
            cache_creation_tokens=0,
            cache_read_tokens=0,
            cost_usd=None,
            project="CodexProject",
        )
    ]
    calls = 0
    fingerprints = iter(((("old", 1, 1.0),), (("new", 2, 2.0),)))

    def fake_codex_entries(*, hours_back: int = 0) -> list[history_loader.UsageEntry]:
        nonlocal calls
        calls += 1
        assert hours_back == 0
        return entries

    monkeypatch.setattr(delegate, "_history_sources_fingerprint", lambda: next(fingerprints))
    monkeypatch.setattr(menubar, "load_entries", lambda *, hours_back=0: [])
    monkeypatch.setattr(codex_loader, "load_entries", fake_codex_entries)

    assert delegate._load_history_entries() == entries
    assert delegate._load_history_entries() == entries
    assert calls == 2


def test_project_rows_top3(monkeypatch: pytest.MonkeyPatch) -> None:
    delegate = menubar.AppDelegate.alloc().initWithMock_interval_(False, 60)
    now = datetime.now(tz=UTC)

    entries = [
        history_loader.UsageEntry(
            timestamp=now,
            session_id="s1",
            message_id="m1",
            request_id="r1",
            model="claude",
            input_tokens=4_000_000,
            output_tokens=1_000_000,
            cache_creation_tokens=0,
            cache_read_tokens=0,
            cost_usd=2.0,
            project="usage",
        ),
        history_loader.UsageEntry(
            timestamp=now,
            session_id="s2",
            message_id="m2",
            request_id="r2",
            model="claude",
            input_tokens=2_000_000,
            output_tokens=500_000,
            cache_creation_tokens=0,
            cache_read_tokens=0,
            cost_usd=1.0,
            project="FinMind",
        ),
        history_loader.UsageEntry(
            timestamp=now,
            session_id="s3",
            message_id="m3",
            request_id="r3",
            model="claude",
            input_tokens=1_000_000,
            output_tokens=300_000,
            cache_creation_tokens=0,
            cache_read_tokens=0,
            cost_usd=0.5,
            project="AI客服",
        ),
        history_loader.UsageEntry(
            timestamp=now,
            session_id="s4",
            message_id="m4",
            request_id="r4",
            model="claude",
            input_tokens=600_000,
            output_tokens=100_000,
            cache_creation_tokens=0,
            cache_read_tokens=0,
            cost_usd=0.2,
            project="sidecar",
        ),
        history_loader.UsageEntry(
            timestamp=now,
            session_id="s5",
            message_id="m5",
            request_id="r5",
            model="claude",
            input_tokens=500_000,
            output_tokens=100_000,
            cache_creation_tokens=0,
            cache_read_tokens=0,
            cost_usd=None,
            project="ops",
        ),
    ]

    monkeypatch.setattr(menubar, "load_entries", lambda *, hours_back=24: entries)

    rows = delegate._project_rows(hours_back=24)

    assert len(rows) == 3
    assert rows[0] == ("usage", 5_000_000, 2.0)
    assert rows[1][0] == "FinMind"
    assert rows[2][0] == "AI客服"


def test_project_rows_today_uses_calendar_day() -> None:
    delegate = menubar.AppDelegate.alloc().initWithMock_interval_(False, 60)
    today_entry = history_loader.UsageEntry(
        timestamp=datetime.now(tz=UTC),
        session_id="today",
        message_id="today-msg",
        request_id="today-req",
        model="claude",
        input_tokens=100,
        output_tokens=50,
        cache_creation_tokens=0,
        cache_read_tokens=0,
        cost_usd=0.01,
        project="TodayProject",
    )
    old_entry = history_loader.UsageEntry(
        timestamp=datetime.now(tz=UTC) - timedelta(days=1),
        session_id="old",
        message_id="old-msg",
        request_id="old-req",
        model="claude",
        input_tokens=10_000,
        output_tokens=5_000,
        cache_creation_tokens=0,
        cache_read_tokens=0,
        cost_usd=1.0,
        project="OldProject",
    )

    assert delegate._project_rows(hours_back=24, entries=[today_entry, old_entry]) == [
        ("TodayProject", 150, 0.01)
    ]


def test_project_rows_7d_mock() -> None:
    delegate = menubar.AppDelegate.alloc().initWithMock_interval_(True, 60)

    rows = delegate._project_rows(hours_back=168)

    assert len(rows) == 3
    assert rows[0][1] == 78_400_000


def test_project_rows_30d_mock() -> None:
    delegate = menubar.AppDelegate.alloc().initWithMock_interval_(True, 60)

    rows = delegate._project_rows(hours_back=720)

    assert len(rows) == 3
    assert rows[0][1] == 312_000_000


def test_apply_refresh_result_pushes_state_only_when_popover_is_shown() -> None:
    class FakeController:
        def __init__(self) -> None:
            self.calls: list[menubar.PopoverState] = []
            self.content_view = object()

        def setState_(self, state: menubar.PopoverState) -> None:
            self.calls.append(state)

        def currentContentView(self) -> object:
            return self.content_view

    class FakePopover:
        def __init__(self, shown: bool) -> None:
            self.shown = shown
            self.sizes: list[object] = []

        def isShown(self) -> bool:
            return self.shown

        def setContentSize_(self, size: object) -> None:
            self.sizes.append(size)

    class FakeButton:
        def __init__(self) -> None:
            self.titles: list[str] = []

        def setTitle_(self, title: str) -> None:
            self.titles.append(title)

        def setAttributedTitle_(self, value: object) -> None:
            pass

    class FakeStatusItem:
        def __init__(self, button: FakeButton) -> None:
            self._button = button

        def button(self) -> FakeButton:
            return self._button

    delegate = menubar.AppDelegate.alloc().initWithMock_interval_(True, 60)
    state = menubar._empty_state(language="en")
    button = FakeButton()
    controller = FakeController()

    delegate.popover_controller = controller
    delegate.popover = FakePopover(shown=True)
    delegate.status_item = FakeStatusItem(button)
    delegate._refresh_in_flight = True
    delegate._refresh_queued = False

    delegate._applyRefreshResult_({"state": state, "codex_5h_pct": 12})

    assert controller.calls == [state]
    assert delegate.latest_state == state
    assert delegate.codex_5h_pct == 12
    assert delegate._refresh_in_flight is False
    assert button.titles

    controller.calls.clear()
    delegate.popover = FakePopover(shown=False)
    delegate._refresh_in_flight = True
    delegate._refresh_queued = False

    delegate._applyRefreshResult_({"state": state, "codex_5h_pct": 34})

    assert controller.calls == []
    assert delegate.latest_state == state
    assert delegate.codex_5h_pct == 34
    assert delegate._refresh_in_flight is False


def test_set_button_title_skips_unchanged_visible_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeButton:
        def __init__(self) -> None:
            self.titles: list[str] = []
            self.attributed_titles: list[object] = []

        def setTitle_(self, title: str) -> None:
            self.titles.append(title)

        def setAttributedTitle_(self, value: object) -> None:
            self.attributed_titles.append(value)

    class FakeStatusItem:
        def __init__(self, button: FakeButton) -> None:
            self._button = button

        def button(self) -> FakeButton:
            return self._button

    delegate = menubar.AppDelegate.alloc().initWithMock_interval_(True, 60)
    monkeypatch.setattr(menubar, "_hide_codex_enabled", lambda: False)
    monkeypatch.setattr(menubar, "_hide_claude_enabled", lambda: False)
    state = menubar._empty_state(language="en")
    button = FakeButton()
    delegate.status_item = FakeStatusItem(button)
    delegate.codex_5h_pct = 12
    monkeypatch.setattr(delegate, "_menubar_attributed_title", lambda current: object())

    delegate._set_button_title(state)
    delegate._set_button_title(state)

    assert len(button.titles) == 1
    assert len(button.attributed_titles) == 1

    delegate.codex_5h_pct = 13
    delegate._set_button_title(state)

    assert len(button.titles) == 2
    assert len(button.attributed_titles) == 2


def test_set_button_title_updates_for_animation_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeButton:
        def __init__(self) -> None:
            self.attributed_titles: list[object] = []

        def setTitle_(self, title: str) -> None:
            pass

        def setAttributedTitle_(self, value: object) -> None:
            self.attributed_titles.append(value)

    class FakeStatusItem:
        def __init__(self, button: FakeButton) -> None:
            self._button = button

        def button(self) -> FakeButton:
            return self._button

    delegate = menubar.AppDelegate.alloc().initWithMock_interval_(True, 60)
    monkeypatch.setattr(menubar, "_hide_codex_enabled", lambda: False)
    monkeypatch.setattr(menubar, "_hide_claude_enabled", lambda: False)
    state = menubar._empty_state(language="en")
    button = FakeButton()
    delegate.status_item = FakeStatusItem(button)
    delegate.critters_enabled = True
    delegate.codex_5h_pct = 12
    monkeypatch.setattr(delegate, "_menubar_attributed_title", lambda current: object())
    monkeypatch.setattr(delegate, "_sync_critter_timer", lambda: None)
    monkeypatch.setattr(delegate, "_sync_dragon_timer", lambda: None)

    delegate._set_button_title(state)
    delegate.dragon_frame += 1
    delegate._set_button_title(state)

    assert len(button.attributed_titles) == 2


def test_apply_codex_refresh_result_updates_quota_before_full_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeController:
        def __init__(self) -> None:
            self.calls: list[menubar.PopoverState] = []
            self.content_view = object()

        def setState_(self, state: menubar.PopoverState) -> None:
            self.calls.append(state)

    class FakePopover:
        def __init__(self) -> None:
            self.sizes: list[object] = []

        def isShown(self) -> bool:
            return True

        def setContentSize_(self, size: object) -> None:
            self.sizes.append(size)

    class FakeButton:
        def __init__(self) -> None:
            self.titles: list[str] = []

        def setTitle_(self, title: str) -> None:
            self.titles.append(title)

        def setAttributedTitle_(self, value: object) -> None:
            pass

    class FakeStatusItem:
        def __init__(self, button: FakeButton) -> None:
            self._button = button

        def button(self) -> FakeButton:
            return self._button

    monkeypatch.setattr(menubar, "_hide_codex_enabled", lambda: False)
    monkeypatch.setattr(menubar, "_hide_claude_enabled", lambda: False)
    delegate = menubar.AppDelegate.alloc().initWithMock_interval_(True, 60)
    controller = FakeController()
    button = FakeButton()
    session = menubar_state.QuotaRowState(
        title="Session",
        percent=18.5,
        percent_text="18.5% used",
        reset_text="Resets in 2h",
        color=menubar.CODEX_COLOR,
    )
    weekly = menubar_state.QuotaRowState(
        title="Weekly",
        percent=34.0,
        percent_text="34% used",
        reset_text="Resets in 6d",
        color=menubar.CODEX_COLOR,
    )
    delegate.popover_controller = controller
    delegate.popover = FakePopover()
    delegate.status_item = FakeStatusItem(button)

    delegate._applyCodexRefreshResult_(
        {
            "codex_rows": (session, weekly),
            "codex_5h_pct": 18.5,
            "codex_model": "gpt-test",
            "codex_stale": None,
        }
    )

    assert delegate.latest_state.codex_session == session
    assert delegate.latest_state.codex_weekly == weekly
    assert delegate.codex_5h_pct == 18.5
    assert delegate.codex_model == "gpt-test"
    assert controller.calls == [delegate.latest_state]
    assert button.titles[-1].endswith("18.5%")


def test_refresh_error_preserves_codex_quota() -> None:
    captured: dict[str, object] = {}
    calls: list[tuple[str, bool]] = []
    session = menubar_state.QuotaRowState(
        title="Session",
        percent=1.0,
        percent_text="1% used",
        reset_text="Resets in 4h",
        color=menubar.CODEX_COLOR,
    )
    weekly = menubar_state.QuotaRowState(
        title="Weekly",
        percent=37.0,
        percent_text="37% used",
        reset_text="Resets in 5d",
        color=menubar.CODEX_COLOR,
    )

    class Delegate:
        mock = False
        language = "en"

        def _load_codex_refresh_result(self) -> dict[str, object]:
            return {
                "codex_rows": (session, weekly),
                "codex_5h_pct": 1.0,
                "codex_model": "gpt-test",
                "codex_stale": None,
            }

        def performSelectorOnMainThread_withObject_waitUntilDone_(
            self, selector: str, result: dict[str, object], wait: bool
        ) -> None:
            calls.append((selector, wait))
            captured["selector"] = selector
            captured["result"] = result
            captured["wait"] = wait

        async def _fetch(self) -> PollOutcome:
            raise RuntimeError("fetch failed")

    menubar.AppDelegate._refresh_in_background(cast(Any, Delegate()))

    result = captured["result"]
    assert isinstance(result, dict)
    state = result["state"]
    assert isinstance(state, menubar_state.PopoverState)
    assert state.codex_session == session
    assert state.codex_weekly == weekly
    assert result["codex_5h_pct"] == 1.0
    assert result["codex_model"] == "gpt-test"
    assert calls == [
        ("_applyCodexRefreshResult:", True),
        ("_applyRefreshResult:", False),
    ]


def test_refresh_error_preserves_project_usage() -> None:
    captured: dict[str, object] = {}
    session = menubar_state.QuotaRowState(
        title="Session",
        percent=1.0,
        percent_text="1% used",
        reset_text="Resets in 4h",
        color=menubar.CODEX_COLOR,
    )
    weekly = menubar_state.QuotaRowState(
        title="Weekly",
        percent=37.0,
        percent_text="37% used",
        reset_text="Resets in 5d",
        color=menubar.CODEX_COLOR,
    )
    entries = [
        history_loader.UsageEntry(
            timestamp=datetime.now(tz=UTC),
            session_id="session",
            message_id="message",
            request_id="request",
            model="gpt-5-codex",
            input_tokens=100,
            output_tokens=50,
            cache_creation_tokens=10,
            cache_read_tokens=5,
            cost_usd=0.01,
            project="Eric-Tools",
        )
    ]

    class Delegate:
        mock = False
        language = "en"
        latest_state = menubar._empty_state(language="en")

        def _load_codex_refresh_result(self) -> dict[str, object]:
            return {
                "codex_rows": (session, weekly),
                "codex_5h_pct": 1.0,
                "codex_model": "gpt-test",
                "codex_stale": None,
            }

        def _load_history_entries(self) -> list[history_loader.UsageEntry]:
            return entries

        def _project_rows(
            self,
            hours_back: int = 24,
            entries: list[history_loader.UsageEntry] | None = None,
        ) -> list[tuple[str, int, float | None]]:
            return menubar.AppDelegate._project_rows(
                cast(Any, self),
                hours_back=hours_back,
                entries=entries,
            )

        def performSelectorOnMainThread_withObject_waitUntilDone_(
            self, selector: str, result: dict[str, object], wait: bool
        ) -> None:
            captured["selector"] = selector
            captured["result"] = result
            captured["wait"] = wait

        async def _fetch(self) -> PollOutcome:
            raise RuntimeError("fetch failed")

    menubar.AppDelegate._refresh_in_background(cast(Any, Delegate()))

    result = captured["result"]
    assert isinstance(result, dict)
    state = result["state"]
    assert isinstance(state, menubar_state.PopoverState)
    assert state.projects == [("Eric-Tools", 165, 0.01)]
    assert state.projects_7d == [("Eric-Tools", 165, 0.01)]
    assert state.projects_30d == [("Eric-Tools", 165, 0.01)]
    assert state.projects_all == [("Eric-Tools", 165, 0.01)]
    assert "165 tokens" in state.today_text


def test_refresh_now_queues_when_refresh_is_busy() -> None:
    delegate = menubar.AppDelegate.alloc().initWithMock_interval_(True, 60)
    delegate._refresh_in_flight = True
    delegate._refresh_queued = False

    delegate.refreshNow_(None)

    assert delegate._refresh_queued is True


def test_apply_refresh_result_clears_busy_flag_when_ui_update_fails() -> None:
    class FailingPopover:
        def isShown(self) -> bool:
            return False

        def setContentSize_(self, size: object) -> None:
            raise RuntimeError("size failed")

    delegate = menubar.AppDelegate.alloc().initWithMock_interval_(True, 60)
    delegate.popover = FailingPopover()
    delegate._refresh_in_flight = True
    delegate._refresh_queued = False

    with pytest.raises(RuntimeError, match="size failed"):
        delegate._applyRefreshResult_({"state": menubar._empty_state(), "codex_5h_pct": None})

    assert delegate._refresh_in_flight is False
    assert delegate._refresh_queued is False


def test_switching_visible_panel_reuses_popover(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeController:
        def __init__(self) -> None:
            self.switched: list[str] = []
            self.states: list[menubar.PopoverState] = []
            self._view = SimpleNamespace(window=lambda: FakeWindow())

        def switchToPanel_(self, panel: Any) -> None:
            self.switched.append(panel.id)

        def setState_(self, state: menubar.PopoverState) -> None:
            self.states.append(state)

        def view(self) -> object:
            return self._view

    class FakeWindow:
        def __init__(self) -> None:
            self.behavior = 0

        def collectionBehavior(self) -> int:
            return self.behavior

        def setCollectionBehavior_(self, behavior: int) -> None:
            self.behavior = behavior

        def orderFront_(self, sender: object) -> None:
            pass

    class FakeButton:
        def bounds(self) -> str:
            return "button-bounds"

    class FakeStatusItem:
        def __init__(self) -> None:
            self._button = FakeButton()

        def button(self) -> FakeButton:
            return self._button

    class FakePopover:
        def __init__(self) -> None:
            self.closed = 0
            self.shown: list[tuple[object, object, object]] = []
            self.sizes: list[object] = []

        def isShown(self) -> bool:
            return True

        def performClose_(self, sender: object) -> None:
            self.closed += 1

        def setContentSize_(self, size: object) -> None:
            self.sizes.append(size)

        def showRelativeToRect_ofView_preferredEdge_(
            self,
            rect: object,
            view: object,
            edge: object,
        ) -> None:
            self.shown.append((rect, view, edge))

    saved: list[str] = []
    monkeypatch.setattr(menubar, "save_active_panel_id", lambda panel_id: saved.append(panel_id))

    delegate = menubar.AppDelegate.alloc().initWithMock_interval_(True, 60)
    delegate.latest_state = menubar._empty_state(language="en")
    delegate.popover_controller = FakeController()
    delegate.popover = FakePopover()
    delegate.status_item = FakeStatusItem()

    delegate._set_active_panel_id("matrix")

    assert saved == ["matrix"]
    assert delegate.active_panel.id == "matrix"
    assert delegate.popover_controller.switched == ["matrix"]
    assert delegate.popover_controller.states == []
    assert delegate.popover.closed == 0
    assert len(delegate.popover.sizes) == 1
    assert delegate.popover.shown == []


def test_state_from_outcome_replaces_claude_reset_with_warning(
    monkeypatch: pytest.MonkeyPatch,
    state_delegate: menubar.AppDelegate,
) -> None:
    delegate = state_delegate
    delegate.language = "zh-TW"
    monkeypatch.setattr("time.time", lambda: 1_600.0)
    delegate.burn_rate_trackers["claude_session"].record(1_000.0, 72.0)
    delegate.burn_rate_trackers["claude_session"].record(1_150.0, 74.5)
    delegate.burn_rate_trackers["claude_session"].record(1_300.0, 77.0)
    delegate.burn_rate_trackers["claude_session"].record(1_450.0, 79.5)
    delegate.burn_rate_trackers["claude_session"].record(1_600.0, 82.0)

    outcome = PollOutcome(
        state=PollState.SUCCESS,
        snapshot=UsageSnapshot(
            current_percent=82,
            current_reset_at=1_600.0 + (51 * 60),
            weekly_percent=20,
            weekly_reset_at=1_600.0 + (2 * 86400),
            current_status="ok",
            polled_at=1_600.0,
        ),
    )

    state = _build_popover_state(delegate, outcome, _codex_rows(delegate)[0])

    assert state.claude_session.warning is True
    assert state.claude_session.reset_text == "⚠ 按目前速度 18分鐘 就會用完(重置還要 51分鐘)"


def test_codex_rows_ignores_invalid_stale_timestamp(
    monkeypatch: pytest.MonkeyPatch,
    state_delegate: menubar.AppDelegate,
) -> None:
    delegate = state_delegate
    monkeypatch.setattr("time.time", lambda: 1_700_000_000.0)
    monkeypatch.setattr(
        codex_loader,
        "load_rate_limits",
        lambda: codex_loader.CodexRateLimits(
            five_hour_pct=12.0,
            five_hour_resets_at=1_700_003_600.0,
            seven_day_pct=34.0,
            seven_day_resets_at=1_700_086_400.0,
            model="gpt-test",
            updated_at="not-a-timestamp",
        ),
    )

    rows, codex_5h_pct, model, stale = _codex_rows(delegate)

    assert rows[0].available is True
    assert codex_5h_pct == 12
    assert model == "gpt-test"
    assert stale is None


def test_codex_window_label_key_maps_window_to_label() -> None:
    assert menubar_state._codex_window_label_key(300.0) == "session_label"
    assert menubar_state._codex_window_label_key(10080.0) == "weekly_label"
    assert menubar_state._codex_window_label_key(43200.0) == "monthly_label"
    assert menubar_state._codex_window_label_key(None) is None


def test_codex_rows_free_plan_labels_window_as_monthly(
    monkeypatch: pytest.MonkeyPatch,
    state_delegate: menubar.AppDelegate,
) -> None:
    delegate = state_delegate
    delegate.language = "en"
    monkeypatch.setattr("time.time", lambda: 1_700_000_000.0)
    monkeypatch.setattr(
        codex_loader,
        "load_rate_limits",
        lambda: codex_loader.CodexRateLimits(
            five_hour_pct=100.0,
            five_hour_resets_at=1_702_000_000.0,
            seven_day_pct=None,
            seven_day_resets_at=None,
            five_hour_window_minutes=43200.0,
            seven_day_window_minutes=None,
            model="gpt-5",
            updated_at="2026-06-23T15:16:48+00:00",
        ),
    )

    rows, _codex_5h_pct, _model, _stale = _codex_rows(delegate)

    # 30-day window must read as "Monthly", not the hard-coded "Session".
    assert rows[0].title == "Monthly"
    assert rows[0].available is True
    # Free plan has no weekly window — second row stays blank, not "Weekly".
    assert rows[1].title == ""
    assert rows[1].available is False


def test_state_from_outcome_keeps_reset_when_burn_rate_is_not_positive(
    monkeypatch: pytest.MonkeyPatch,
    state_delegate: menubar.AppDelegate,
) -> None:
    delegate = state_delegate
    delegate.language = "zh-TW"
    monkeypatch.setattr("time.time", lambda: 1_600.0)
    delegate.burn_rate_trackers["claude_session"].record(1_000.0, 82.0)
    delegate.burn_rate_trackers["claude_session"].record(1_150.0, 79.0)
    delegate.burn_rate_trackers["claude_session"].record(1_300.0, 76.0)
    delegate.burn_rate_trackers["claude_session"].record(1_450.0, 73.0)
    delegate.burn_rate_trackers["claude_session"].record(1_600.0, 70.0)

    outcome = PollOutcome(
        state=PollState.SUCCESS,
        snapshot=UsageSnapshot(
            current_percent=70,
            current_reset_at=1_600.0 + (51 * 60),
            weekly_percent=20,
            weekly_reset_at=1_600.0 + (2 * 86400),
            current_status="ok",
            polled_at=1_600.0,
        ),
    )

    state = _build_popover_state(delegate, outcome, _codex_rows(delegate)[0])

    assert state.claude_session.warning is False
    assert state.claude_session.reset_text == "重置 51分鐘"


def test_state_from_outcome_translates_awaiting_rate_limits_message(
    monkeypatch: pytest.MonkeyPatch,
    state_delegate: menubar.AppDelegate,
) -> None:
    delegate = state_delegate
    delegate.language = "zh-TW"
    monkeypatch.setattr(menubar, "_hide_claude_enabled", lambda: False)

    state = _build_popover_state(
        delegate,
        PollOutcome(state=PollState.LOADING, message="awaiting_rate_limits"),
        _codex_rows(delegate)[0],
    )

    assert state.status_text == "狀態：請對 Claude Code 發送一句訊息以同步配額"


def test_state_from_outcome_translates_hook_broken_message(
    monkeypatch: pytest.MonkeyPatch,
    state_delegate: menubar.AppDelegate,
) -> None:
    delegate = state_delegate
    delegate.language = "en"
    monkeypatch.setattr(menubar, "_hide_claude_enabled", lambda: False)

    state = _build_popover_state(
        delegate,
        PollOutcome(
            state=PollState.SUCCESS,
            message="hook_broken_restart",
            snapshot=UsageSnapshot(
                current_percent=70,
                current_reset_at=1_600.0 + (51 * 60),
                weekly_percent=20,
                weekly_reset_at=1_600.0 + (2 * 86400),
                current_status="ok",
                polled_at=1_600.0,
            ),
        ),
        _codex_rows(delegate)[0],
    )

    assert (
        state.status_text
        == "Status: ⚠ Status line hook is not running. Restart Claude Code once."
    )


def test_state_from_outcome_hides_setup_button_when_no_statusline_target_exists(
    monkeypatch: pytest.MonkeyPatch,
    state_delegate: menubar.AppDelegate,
) -> None:
    delegate = state_delegate
    monkeypatch.setattr(delegate, "_statusline_setup_available", lambda: False)

    state = _build_popover_state(
        delegate,
        PollOutcome(state=PollState.TOKEN_ERROR, message="missing"),
        _codex_rows(delegate)[0],
    )

    assert state.show_install_button is False


def test_state_from_outcome_hides_claude_error_and_setup_button(
    monkeypatch: pytest.MonkeyPatch,
    state_delegate: menubar.AppDelegate,
) -> None:
    delegate = state_delegate
    delegate.language = "zh-TW"
    monkeypatch.setattr(delegate, "_statusline_setup_available", lambda: True)
    monkeypatch.setattr(menubar, "_hide_claude_enabled", lambda: True)

    state = _build_popover_state(
        delegate,
        PollOutcome(state=PollState.TOKEN_ERROR, message="missing"),
        _codex_rows(delegate)[0],
    )

    assert state.show_install_button is False
    assert "--setup" not in state.status_text
    assert state.status_text == "狀態：✓ 已同步"


def test_state_from_outcome_shows_setup_button_for_codex_only(
    monkeypatch: pytest.MonkeyPatch,
    state_delegate: menubar.AppDelegate,
) -> None:
    delegate = state_delegate
    monkeypatch.setattr(delegate, "_statusline_setup_available", lambda: True)
    monkeypatch.setattr(menubar, "_hide_claude_enabled", lambda: False)

    state = _build_popover_state(
        delegate,
        PollOutcome(state=PollState.TOKEN_ERROR, message="missing"),
        _codex_rows(delegate)[0],
    )

    assert state.show_install_button is True

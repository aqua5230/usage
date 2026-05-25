from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

import history_loader
import menubar
from usage_client import PollOutcome, PollState, UsageSnapshot


class _FakeMenu:
    last: _FakeMenu | None = None

    def __init__(self) -> None:
        self.items: list[_FakeMenuItem] = []
        _FakeMenu.last = self

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
    assert row.reset_text == "⚠ 剩 18分鐘 用完(重置還要 51分鐘)"


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
    assert isinstance(state.statusline["enabled"], bool)
    assert state.show_install_button is False


def test_switch_panel_menu_contains_update_items(monkeypatch: pytest.MonkeyPatch) -> None:
    delegate = menubar.AppDelegate.alloc().initWithMock_interval_(True, 60)
    delegate.language = "en"
    delegate.active_panel = SimpleNamespace(id="classic")
    panels = [
        SimpleNamespace(id="classic", i18n_key="panel_default_name"),
        SimpleNamespace(id="bento", i18n_key="panel_bento"),
    ]

    monkeypatch.setattr(menubar, "NSMenu", _FakeMenu)
    monkeypatch.setattr(menubar, "NSMenuItem", _FakeMenuItem)
    monkeypatch.setattr("menubar.panels.all_panels", lambda: panels)
    monkeypatch.setattr("menubar.login_item.is_enabled", lambda: False)
    monkeypatch.setattr(menubar, "_load_preferences", lambda: {"auto_update_check": True})

    menubar.AppDelegate.switchPanel_(delegate, object())

    assert _FakeMenu.last is not None
    titles = [item.title for item in _FakeMenu.last.items]
    assert "Automatically Check for Updates" in titles
    assert "Check for Updates Now" in titles
    auto_item = next(
        item for item in _FakeMenu.last.items if item.title == "Automatically Check for Updates"
    )
    assert auto_item.state == 1


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


def test_check_update_writes_cache_when_release_found(monkeypatch: pytest.MonkeyPatch) -> None:
    saved: list[dict[str, Any]] = []
    monkeypatch.setattr(menubar, "_load_preferences", lambda: {"auto_update_check": True})
    monkeypatch.setattr(menubar, "_save_preferences", lambda d: saved.append(dict(d)))
    monkeypatch.setattr(menubar, "_current_version", lambda: "0.11.3")
    monkeypatch.setattr("menubar.time.time", lambda: 1700000000.0)
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
    monkeypatch.setattr("menubar.time.time", lambda: 1700000000.0)
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

    monkeypatch.setattr(menubar, "_claude_settings_path", lambda: settings)
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


def test_project_rows_top3(monkeypatch: pytest.MonkeyPatch) -> None:
    delegate = menubar.AppDelegate.alloc().initWithMock_interval_(False, 60)

    entries = [
        history_loader.UsageEntry(
            timestamp=datetime(2026, 5, 21, tzinfo=UTC),
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
            timestamp=datetime(2026, 5, 21, tzinfo=UTC),
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
            timestamp=datetime(2026, 5, 21, tzinfo=UTC),
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
            timestamp=datetime(2026, 5, 21, tzinfo=UTC),
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
            timestamp=datetime(2026, 5, 21, tzinfo=UTC),
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

    delegate._applyRefreshResult_({"state": state, "codex_5h_pct": 12})

    assert controller.calls == [state]
    assert delegate.latest_state == state
    assert delegate.codex_5h_pct == 12
    assert button.titles

    controller.calls.clear()
    delegate.popover = FakePopover(shown=False)
    delegate._refresh_in_flight = True

    delegate._applyRefreshResult_({"state": state, "codex_5h_pct": 34})

    assert controller.calls == []
    assert delegate.latest_state == state
    assert delegate.codex_5h_pct == 34


def test_switching_visible_panel_reopens_popover(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeController:
        def __init__(self) -> None:
            self.rebuilt: list[str] = []
            self.states: list[menubar.PopoverState] = []

        def rebuildWithPanel_(self, panel: Any) -> None:
            self.rebuilt.append(panel.id)

        def setState_(self, state: menubar.PopoverState) -> None:
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
    assert delegate.popover_controller.rebuilt == ["matrix"]
    assert delegate.popover_controller.states == [delegate.latest_state]
    assert delegate.popover.closed == 1
    assert len(delegate.popover.sizes) == 1
    assert len(delegate.popover.shown) == 1
    assert delegate.popover.shown[0][0] == "button-bounds"


def test_state_from_outcome_replaces_claude_reset_with_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delegate = menubar.AppDelegate.alloc().initWithMock_interval_(False, 60)
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

    state = delegate._state_from_outcome(outcome, delegate._codex_rows()[0], [], [], [])

    assert state.claude_session.warning is True
    assert state.claude_session.reset_text == "⚠ 剩 18分鐘 用完(重置還要 51分鐘)"


def test_state_from_outcome_keeps_reset_when_burn_rate_is_not_positive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delegate = menubar.AppDelegate.alloc().initWithMock_interval_(False, 60)
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

    state = delegate._state_from_outcome(outcome, delegate._codex_rows()[0], [], [], [])

    assert state.claude_session.warning is False
    assert state.claude_session.reset_text == "重置 51分鐘"


def test_state_from_outcome_translates_awaiting_rate_limits_message() -> None:
    delegate = menubar.AppDelegate.alloc().initWithMock_interval_(False, 60)
    delegate.language = "zh-TW"

    state = delegate._state_from_outcome(
        PollOutcome(state=PollState.LOADING, message="awaiting_rate_limits"),
        delegate._codex_rows()[0],
        [],
        [],
        [],
    )

    assert state.status_text == "狀態：請對 Claude Code 發送一句訊息以同步配額"

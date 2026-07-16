# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

import menubar_prefs
import menubar_state
import prefs
import win_login_item
import wintray
from usage_notifications import NotificationEvent


class _Key:
    def __enter__(self) -> _Key:
        return self

    def __exit__(self, *args: object) -> None:
        return None


class FakeWinreg:
    HKEY_CURRENT_USER = object()

    def __init__(self, value: int = 1, error: Exception | None = None) -> None:
        self.value = value
        self.error = error

    def OpenKey(self, *args: object) -> _Key:  # noqa: N802 - winreg contract
        if self.error is not None:
            raise self.error
        return _Key()

    def QueryValueEx(self, key: object, name: str) -> tuple[int, int]:  # noqa: N802
        return (self.value, 4)


def _state() -> menubar_state.PopoverState:
    row = menubar_state.QuotaRowState(
        title="Session",
        percent=25.0,
        percent_text="25% used",
        reset_text="Resets in 1h",
        color=menubar_state.CLAUDE_COLOR,
    )
    weekly = menubar_state.QuotaRowState(
        title="Weekly",
        percent=60.0,
        percent_text="60% used",
        reset_text="Resets in 1d",
        color=menubar_state.CLAUDE_COLOR,
    )
    return menubar_state.PopoverState(
        language="en",
        claude_session=row,
        claude_weekly=weekly,
        codex_session=row,
        codex_weekly=weekly,
        agy_session=row,
        agy_weekly=weekly,
        agy_group_name="",
        projects=[],
        projects_7d=[],
        projects_30d=[],
        projects_all=[],
        rate_text="",
        status_text="",
        today_text="",
        statusline={},
    )


@pytest.mark.parametrize(
    ("used", "text", "color"),
    [
        (None, "--", (110, 118, 129, 255)),
        (0.0, "100", (244, 145, 100, 255)),
        (60.0, "40", (255, 196, 57, 255)),
        (95.0, "5", (255, 69, 58, 255)),
        (150.0, "0", (255, 69, 58, 255)),
    ],
)
def test_tray_icon_style(used: float | None, text: str, color: tuple[int, ...]) -> None:
    assert wintray.tray_icon_style(used) == (text, color)


def test_draw_tray_icon_and_tooltip(monkeypatch: pytest.MonkeyPatch) -> None:
    image = SimpleNamespace(size=(64, 64))
    draw = SimpleNamespace(
        rounded_rectangle=lambda *args, **kwargs: None,
        textbbox=lambda *args, **kwargs: (0, 0, 24, 12),
        text=lambda *args, **kwargs: None,
    )
    fake_pil = SimpleNamespace(
        Image=SimpleNamespace(new=lambda *args, **kwargs: image),
        ImageDraw=SimpleNamespace(Draw=lambda value: draw),
        ImageFont=SimpleNamespace(load_default=lambda **kwargs: object()),
    )
    monkeypatch.setitem(sys.modules, "PIL", fake_pil)

    icon_image = wintray.draw_tray_icon(25.0)

    assert icon_image.size == (64, 64)
    assert wintray.build_tooltip(_state()).splitlines() == [
        "Claude Session: 75%",
        "Claude Weekly: 40%",
        "Codex Session: 75% · Weekly: 40%",
    ]


def test_windows_panels_exclude_talent_market() -> None:
    ids = [panel[0] for panel in wintray.available_panels()]

    assert "classic" in ids
    assert "talent_market" not in ids


def test_system_background_color_dark(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wintray, "_winreg", lambda: FakeWinreg(value=0))

    assert wintray._system_background_color() == "#080d12"


def test_system_background_color_light(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wintray, "_winreg", lambda: FakeWinreg(value=1))

    assert wintray._system_background_color() == "#eef2f7"


def test_system_background_color_falls_back_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        wintray,
        "_winreg",
        lambda: FakeWinreg(error=OSError("registry unavailable")),
    )

    assert wintray._system_background_color() == "#eef2f7"


def test_panel_html_installs_webkit_shim_without_changing_asset() -> None:
    html = wintray.panel_html("classic.html")

    assert "window.webkit.messageHandlers.usage" in html
    assert "window.pywebview.api.postMessage(message)" in html
    assert "pywebview-drag-region" in html
    assert "usage-window-drag-handle" in html
    assert "post('open_menu')" in html
    assert "usage-panel-menu-backdrop" in html
    assert "usage-panel-menu-accordion" in html
    assert "max-height: 80vh" in html
    assert "overflow-y: auto" in html
    assert "event.stopImmediatePropagation()" in html
    assert "[data-card=\"claude\"]" in html
    assert "usage-card-window-dragging" in html
    assert "card.classList.add('pywebview-drag-region'" in html
    assert "button, a, input, select, textarea, label, summary" in html
    assert "cursor: grab" in html
    assert "cursor: grabbing" in html


def test_panel_position_is_clamped_and_persisted_on_hide(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    preferences_path = tmp_path / "usage-preferences.json"
    preferences_path.write_text(
        json.dumps({"usage.windowPosition": {"x": 5000, "y": -100}}), encoding="utf-8"
    )
    monkeypatch.setattr(prefs, "PREFERENCES_FILE", preferences_path)
    moves: list[tuple[int, int]] = []
    window = SimpleNamespace(
        x=0,
        y=0,
        resize=lambda *args: None,
        move=lambda x, y: moves.append((x, y)),
        hide=lambda: None,
    )
    controller = wintray._WindowsTrayController(mock=True, interval=60)
    controller.window = window
    controller.visible = True
    monkeypatch.setattr(controller, "_working_area", lambda: (0, 0, 1000, 1080))

    controller._place_window()

    assert moves == [(608, 12)]
    window.x, window.y = 123, 234
    controller.show_panel()
    assert prefs._load_preferences()["usage.windowPosition"] == {"x": 123, "y": 234}


def test_reset_panel_position_clears_preference_and_repositions_visible_window(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    preferences_path = tmp_path / "usage-preferences.json"
    preferences_path.write_text(
        json.dumps({"usage.windowPosition": {"x": 123, "y": 234}}), encoding="utf-8"
    )
    monkeypatch.setattr(prefs, "PREFERENCES_FILE", preferences_path)
    controller = wintray._WindowsTrayController(mock=True, interval=60)
    controller.visible = True
    calls: list[bool] = []
    monkeypatch.setattr(
        controller, "_place_window", lambda *, force_default=False: calls.append(force_default)
    )

    controller.reset_panel_position()

    assert prefs._load_preferences() == {}
    assert calls == [True]


def test_js_api_forwards_panel_message() -> None:
    received: list[object] = []
    controller = SimpleNamespace(handle_panel_message=received.append)

    wintray._JSApi(controller).postMessage("refresh")  # type: ignore[arg-type]

    assert received == ["refresh"]


def test_js_api_returns_panel_menu_data() -> None:
    menu = [{"label": "Menu"}]
    controller = SimpleNamespace(handle_panel_message=lambda _message: menu)

    result = wintray._JSApi(controller).postMessage("open_menu")  # type: ignore[arg-type]

    assert result == menu


def test_switch_panel_message_returns_menu_instead_of_cycling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = wintray._WindowsTrayController(mock=True, interval=60)
    switched_to: list[str] = []
    monkeypatch.setattr(controller, "switch_panel", switched_to.append)

    menu = controller.handle_panel_message("switch")

    assert isinstance(menu, list)
    assert menu[2]["i18nKey"] == "switch_panel"
    assert switched_to == []


def test_selected_panel_switch_waits_for_bridge_promise_and_debounces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scheduled: list[FakeTimer] = []

    class FakeTimer:
        def __init__(self, delay: float, callback: object) -> None:
            self.delay = delay
            self.callback = callback
            scheduled.append(self)

        def start(self) -> None:
            return None

        def fire(self) -> None:
            assert callable(self.callback)
            self.callback()

    controller = wintray._WindowsTrayController(mock=True, interval=60)
    switched_to: list[str] = []
    monkeypatch.setattr(controller, "switch_panel", switched_to.append)
    monkeypatch.setattr(threading, "Timer", FakeTimer)

    controller.handle_panel_message(json.dumps({"action": "switch_panel", "panel_id": "matrix"}))
    controller.handle_panel_message(json.dumps({"action": "switch_panel", "panel_id": "win95"}))

    assert len(scheduled) == 1
    assert scheduled[0].delay == 0.05
    scheduled[0].fire()

    assert switched_to == ["matrix"]


def test_panel_menu_data_is_localized_and_reads_current_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = wintray._WindowsTrayController(mock=True, interval=60)
    controller.language = "en"
    controller.active_panel_id = "matrix"
    monkeypatch.setattr(wintray, "_hide_claude_enabled", lambda: True)
    monkeypatch.setattr(wintray, "_hide_codex_enabled", lambda: False)
    monkeypatch.setattr(wintray, "_hide_agy_enabled", lambda: True)
    monkeypatch.setattr(win_login_item, "is_enabled", lambda: True)
    monkeypatch.setattr(wintray, "_quota_notifications_enabled", lambda: False)
    monkeypatch.setattr(wintray, "_session_resume_enabled", lambda: True)
    monkeypatch.setattr(wintray, "_terse_mode_enabled", lambda: False)

    menu = controller._panel_menu_data()

    assert menu[0] == {
        "i18nKey": "panel_ai_daily",
        "label": "AI Update Daily",
        "action": "open_ai_daily",
    }
    assert [entry.get("i18nKey", entry.get("type")) for entry in menu] == [
        "panel_ai_daily",
        "separator",
        "switch_panel",
        "hide_sections_menu",
        "separator",
        "launch_at_login",
        "quota_notifications_menu",
        "separator",
        "project_butler",
        "terse_mode_menu",
        "separator",
        "refresh_now",
    ]
    panels = cast(list[dict[str, object]], menu[2]["children"])
    hidden_sections = cast(list[dict[str, object]], menu[3]["children"])
    assert panels[1]["panelId"] == "matrix"
    assert panels[1]["checked"] is True
    assert [item["checked"] for item in hidden_sections] == [True, False, True]
    assert menu[5]["checked"] is True
    assert menu[6]["checked"] is False
    assert menu[8]["checked"] is True
    assert menu[9]["checked"] is False


@pytest.mark.parametrize(
    ("payload", "method", "expected"),
    [
        ({"action": "open_ai_daily"}, "open_ai_daily", ()),
        ({"action": "reset_panel_position"}, "reset_panel_position", ()),
        ({"action": "switch_panel", "panel_id": "matrix"}, "_schedule_panel_switch", ("matrix",)),
        (
            {"action": "toggle_hide_section", "preference_key": "hide_codex_section"},
            "toggle_hide_section",
            ("hide_codex_section",),
        ),
        ({"action": "refresh"}, "refresh", ()),
        ({"action": "toggle_login"}, "toggle_login", ()),
        ({"action": "toggle_quota_notifications"}, "toggle_quota_notifications", ()),
        ({"action": "toggle_session_resume"}, "toggle_session_resume", ()),
        ({"action": "toggle_terse_mode"}, "toggle_terse_mode", ()),
        ({"action": "check_update"}, "check_update", ()),
        ({"action": "quit"}, "quit", ()),
    ],
)
def test_panel_menu_actions_dispatch_to_controller_methods(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, str],
    method: str,
    expected: tuple[str, ...],
) -> None:
    controller = wintray._WindowsTrayController(mock=True, interval=60)
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(controller, method, lambda *args: calls.append(args))

    controller.handle_panel_message(json.dumps(payload))

    assert calls == [expected]


@pytest.mark.parametrize("panel_id", ["matrix", "aquarium", "win95"])
def test_card_order_persists_into_the_next_loaded_panel(
    monkeypatch: pytest.MonkeyPatch,
    panel_id: str,
) -> None:
    preferences: dict[str, object] = {}
    injected: list[str] = []
    loaded: list[str] = []
    window = SimpleNamespace(
        evaluate_js=injected.append,
        load_html=loaded.append,
    )
    controller = wintray._WindowsTrayController(mock=True, interval=60)
    controller.window = window
    controller.visible = True
    order = ["codex", "claude", "agy"]

    monkeypatch.setattr(wintray, "_load_preferences", lambda: preferences.copy())
    monkeypatch.setattr(menubar_prefs, "_load_preferences", lambda: preferences.copy())
    monkeypatch.setattr(
        wintray,
        "_save_preferences",
        lambda updated: preferences.update(updated),
    )
    monkeypatch.setattr(controller, "_place_window", lambda: None)

    controller.handle_panel_message(
        json.dumps({"action": "set_card_order", "order": order})
    )
    controller.switch_panel(panel_id)
    controller.on_loaded()

    assert preferences["quota_card_order"] == order
    assert controller.latest_state.card_order == tuple(order)
    assert len(loaded) == 1
    payload = injected[-1].removeprefix("window.usageApplyState(").removesuffix(")")
    assert json.loads(payload)["cardOrder"] == order


def test_run_app_wires_pystray_and_pywebview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[object] = []

    class FakeMenuItem:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.args = args

    class FakeMenu:
        def __init__(self, *items: object) -> None:
            self.items = items

    class FakeIcon:
        def __init__(self, *args: object) -> None:
            events.append(("icon", args[0]))

        def run_detached(self) -> None:
            events.append("run_detached")

    class Event:
        def __iadd__(self, callback: object) -> Event:
            events.append("loaded_handler")
            return self

    window = SimpleNamespace(events=SimpleNamespace(loaded=Event()))

    def create_window(*args: object, **kwargs: object) -> object:
        events.append(
            ("window", args[0], kwargs["hidden"], kwargs["background_color"])
        )
        return window

    FakeMenu.SEPARATOR = object()  # type: ignore[attr-defined]
    fake_pystray = SimpleNamespace(Icon=FakeIcon, Menu=FakeMenu, MenuItem=FakeMenuItem)
    fake_webview = SimpleNamespace(
        create_window=create_window,
        start=lambda **kwargs: events.append(("start", kwargs["gui"])),
    )
    monkeypatch.setitem(sys.modules, "pystray", fake_pystray)
    monkeypatch.setitem(sys.modules, "webview", fake_webview)
    monkeypatch.setattr(wintray, "draw_tray_icon", lambda value: object())
    monkeypatch.setattr(wintray, "_system_background_color", lambda: "#eef2f7")
    monkeypatch.setattr(wintray._WindowsTrayController, "attach", lambda self, icon, view: None)
    # A tray may genuinely be running on the machine executing the tests.
    monkeypatch.setattr(wintray, "_acquire_single_instance_lock", lambda: True)

    wintray.run_app(mock=True, interval=60)

    assert events == [
        ("window", "usage", True, "#eef2f7"),
        "loaded_handler",
        ("icon", "usage"),
        "run_detached",
        ("start", "edgechromium"),
    ]


def test_on_loaded_does_not_place_hidden_window() -> None:
    # Regression: pywebview's resize()/move() call SetWindowPos with
    # SWP_SHOWWINDOW, so placing the window at document load dragged the bare
    # unrendered panel onto the screen at every launch.
    controller = wintray._WindowsTrayController(mock=True, interval=60)
    calls: list[str] = []
    controller.window = SimpleNamespace(
        resize=lambda *args: calls.append("resize"),
        move=lambda *args: calls.append("move"),
        show=lambda: calls.append("show"),
        evaluate_js=lambda code: calls.append("evaluate_js"),
    )

    controller.on_loaded()

    assert calls == []


def test_show_panel_places_window_before_showing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = wintray._WindowsTrayController(mock=True, interval=60)
    calls: list[str] = []
    monkeypatch.setattr(controller, "_place_window", lambda: calls.append("place"))
    monkeypatch.setattr(controller, "inject_state", lambda: calls.append("inject"))
    monkeypatch.setattr(controller, "refresh", lambda: calls.append("refresh"))
    controller.window = SimpleNamespace(
        show=lambda: calls.append("show"), hide=lambda: calls.append("hide")
    )

    controller.show_panel()

    assert controller.visible is True
    assert calls == ["place", "show", "inject", "refresh"]


def test_hide_section_updates_preferences_and_visible_panel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preferences: dict[str, object] = {}
    saved: list[dict[str, object]] = []
    controller = wintray._WindowsTrayController(mock=True, interval=60)
    controller.visible = True
    injected: list[str] = []
    monkeypatch.setattr(wintray, "_load_preferences", lambda: preferences)
    monkeypatch.setattr(wintray, "_save_preferences", lambda value: saved.append(dict(value)))
    monkeypatch.setattr(wintray, "_hide_claude_enabled", lambda: True)
    monkeypatch.setattr(wintray, "_hide_codex_enabled", lambda: False)
    monkeypatch.setattr(wintray, "_hide_agy_enabled", lambda: False)
    monkeypatch.setattr(controller, "inject_state", lambda: injected.append("state"))

    controller.toggle_hide_section("hide_claude_section")

    assert preferences == {"hide_claude_section": True}
    assert saved == [preferences]
    assert controller.latest_state.hide_claude is True
    assert injected == ["state"]


def test_quota_notifications_use_pystray_notify_and_existing_i18n(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = wintray._WindowsTrayController(mock=False, interval=60)
    controller.language = "en"
    notices: list[tuple[str, str]] = []
    controller.icon = SimpleNamespace(
        notify=lambda message, title: notices.append((message, title))
    )
    monkeypatch.setattr(wintray, "_quota_notifications_enabled", lambda: True)
    state = _state()

    controller._send_quota_notification(
        NotificationEvent("warn", "claude_session", 90.0), state
    )

    assert notices == [("Claude Session is 25% used. Time to wrap up?", "🐾 Almost out")]


def test_session_hook_toggles_run_in_background_helpers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def record(name: str) -> int:
        calls.append(name)
        return 0

    hooks = SimpleNamespace(
        is_resume_enabled=lambda: False,
        enable_session_resume=lambda: record("enable_resume"),
        disable_session_resume=lambda: record("disable_resume"),
        is_terse_mode_enabled=lambda: True,
        enable_terse_mode=lambda: record("enable_terse"),
        disable_terse_mode=lambda: record("disable_terse"),
    )
    monkeypatch.setitem(sys.modules, "session_hooks", hooks)
    controller = wintray._WindowsTrayController(mock=True, interval=60)

    controller._toggle_session_resume_in_background()
    controller._toggle_terse_mode_in_background()

    assert calls == ["enable_resume", "disable_terse"]


def test_run_app_bails_out_when_another_instance_holds_the_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Regression: a second tray instance used to fight the first over the
    # WebView2 user-data directory and linger as a bare white window.
    notices: list[str] = []
    monkeypatch.setattr(wintray, "_acquire_single_instance_lock", lambda: False)
    monkeypatch.setattr(wintray, "_show_already_running_notice", lambda: notices.append("shown"))
    fake_webview = SimpleNamespace(
        create_window=lambda *args, **kwargs: pytest.fail("window must not be created"),
        start=lambda **kwargs: pytest.fail("webview must not start"),
    )
    monkeypatch.setitem(sys.modules, "webview", fake_webview)

    wintray.run_app(mock=True, interval=60)

    assert notices == ["shown"]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows named mutex")
def test_single_instance_lock_blocks_second_acquire_until_released(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Use a test-specific mutex name so a real tray running on this machine
    # cannot interfere.
    monkeypatch.setattr(
        wintray, "_SINGLE_INSTANCE_MUTEX", "usage-tray-single-instance-pytest"
    )
    assert wintray._acquire_single_instance_lock() is True
    try:
        assert wintray._acquire_single_instance_lock() is False
    finally:
        wintray._release_single_instance_lock()
    assert wintray._acquire_single_instance_lock() is True
    wintray._release_single_instance_lock()


def test_menu_actions_pass_real_pystray_signature_validation() -> None:
    # Regression: pystray validates every action's co_argcount when a MenuItem
    # is constructed, and the panel-switch lambda used to carry a third
    # defaulted positional parameter, raising ValueError before the tray icon
    # ever appeared. Build the menu against the real pystray to catch that.
    pytest.importorskip("pystray", reason="pystray is a Windows-only extra")
    controller = SimpleNamespace(
        language="en",
        active_panel_id="classic",
        switch_panel=lambda panel_id: None,
        show_panel=lambda: None,
        reset_panel_position=lambda: None,
        refresh=lambda: None,
        toggle_login=lambda: None,
        open_ai_daily=lambda: None,
        toggle_hide_section=lambda key: None,
        toggle_quota_notifications=lambda: None,
        toggle_session_resume=lambda: None,
        toggle_terse_mode=lambda: None,
        check_update=lambda: None,
        quit=lambda: None,
    )

    menu = wintray._menu(controller)  # type: ignore[arg-type]

    assert menu is not None

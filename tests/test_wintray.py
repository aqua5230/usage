# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>

from __future__ import annotations

import json
import sys
import threading
from types import SimpleNamespace

import pytest

import menubar_prefs
import menubar_state
import wintray


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


def test_js_api_forwards_panel_message() -> None:
    received: list[object] = []
    controller = SimpleNamespace(handle_panel_message=received.append)

    wintray._JSApi(controller).postMessage("refresh")  # type: ignore[arg-type]

    assert received == ["refresh"]


def test_switch_panel_waits_for_bridge_promise_to_resolve(
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
    controller.active_panel_id = "classic"
    switched_to: list[str] = []
    monkeypatch.setattr(controller, "switch_panel", switched_to.append)
    monkeypatch.setattr(threading, "Timer", FakeTimer)

    controller.handle_panel_message("switch")

    assert len(scheduled) == 1
    assert scheduled[0].delay == 0.05
    assert switched_to == []

    controller.active_panel_id = "matrix"
    scheduled[0].fire()

    assert switched_to == ["win95"]


def test_switch_panel_ignores_second_click_while_switch_is_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scheduled: list[object] = []

    class FakeTimer:
        def __init__(self, delay: float, callback: object) -> None:
            scheduled.append((delay, callback))

        def start(self) -> None:
            return None

    controller = wintray._WindowsTrayController(mock=True, interval=60)
    monkeypatch.setattr(threading, "Timer", FakeTimer)

    controller.handle_panel_message("switch")
    controller.handle_panel_message("switch")

    assert len(scheduled) == 1


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
        refresh=lambda: None,
        toggle_login=lambda: None,
        check_update=lambda: None,
        quit=lambda: None,
    )

    menu = wintray._menu(controller)  # type: ignore[arg-type]

    assert menu is not None

# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>

from __future__ import annotations

import json
import sys
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

import codex_loader
import menubar_agy
import menubar_prefs
import menubar_state
import panels
import prefs
import service_status
import update_checker
import win_login_item
import windows_watch
import wintray
import wintray_menu
from i18n import _t
from usage_client import PollOutcome, PollState
from usage_notifications import NotificationEvent


class _Key:
    def __enter__(self) -> _Key:
        return self

    def __exit__(self, *args: object) -> None:
        return None


class FakeWinreg:
    HKEY_CURRENT_USER = object()
    REG_DWORD = 4

    def __init__(self, value: object = 1, error: Exception | None = None) -> None:
        self.value = value
        self.error = error

    def OpenKey(self, *args: object) -> _Key:  # noqa: N802 - winreg contract
        if self.error is not None:
            raise self.error
        return _Key()

    def QueryValueEx(self, key: object, name: str) -> tuple[object, int]:  # noqa: N802
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


@pytest.mark.parametrize(
    ("used", "state"),
    [
        (None, wintray.TaskbarProgressState.NO_PROGRESS),
        (0.0, wintray.TaskbarProgressState.NORMAL),
        (49.4, wintray.TaskbarProgressState.NORMAL),
        (49.5, wintray.TaskbarProgressState.PAUSED),
        (79.4, wintray.TaskbarProgressState.PAUSED),
        (79.5, wintray.TaskbarProgressState.ERROR),
        (150.0, wintray.TaskbarProgressState.ERROR),
    ],
)
def test_taskbar_progress_state(
    used: float | None, state: wintray.TaskbarProgressState
) -> None:
    assert wintray.taskbar_progress_state(used) == state


@pytest.mark.parametrize(("show_in_taskbar", "expected"), [(True, 1234), (False, None)])
def test_taskbar_window_handle_requires_real_taskbar_button(
    show_in_taskbar: bool, expected: int | None
) -> None:
    window = SimpleNamespace(
        native=SimpleNamespace(
            ShowInTaskbar=show_in_taskbar,
            Handle=SimpleNamespace(ToInt64=lambda: 1234),
        )
    )

    assert wintray._taskbar_window_handle(window) == expected


@pytest.mark.skipif(sys.platform != "win32", reason="ITaskbarList3 is a Windows shell interface")
def test_taskbar_list3_interface_is_creatable() -> None:
    """Catch a wrong IID/CLSID, which every mocked taskbar test happily accepts.

    A transposed GUID digit still passes the seam-level tests above but makes
    CoCreateInstance return E_NOINTERFACE at runtime, silently disabling the
    progress bar. Only really asking the shell for the interface proves it.
    """
    import ctypes

    library_name = "WinDLL"
    win_dll: Any = getattr(ctypes, library_name)
    ole32: Any = win_dll("ole32", use_last_error=True)
    function_type_name = "WINFUNCTYPE"
    win_function_type: Any = getattr(ctypes, function_type_name)
    ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    ole32.CoInitializeEx.restype = ctypes.c_long
    ole32.CoCreateInstance.argtypes = [
        ctypes.POINTER(wintray._GUID),
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.POINTER(wintray._GUID),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    ole32.CoCreateInstance.restype = ctypes.c_long

    initialize_result = int(ole32.CoInitializeEx(None, 0x2))
    taskbar = ctypes.c_void_p()
    try:
        result = int(
            ole32.CoCreateInstance(
                ctypes.byref(wintray._CLSID_TASKBAR_LIST),
                None,
                0x1,
                ctypes.byref(wintray._IID_ITASKBAR_LIST3),
                ctypes.byref(taskbar),
            )
        )
        assert result == 0, f"CoCreateInstance(ITaskbarList3) returned 0x{result & 0xFFFFFFFF:08X}"
        assert taskbar.value
    finally:
        if taskbar.value:
            vtable = ctypes.cast(
                taskbar, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))
            ).contents
            win_function_type(ctypes.c_ulong, ctypes.c_void_p)(vtable[2])(taskbar)
        if initialize_result in {0, 1}:
            ole32.CoUninitialize()


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


def test_system_accent_color_reads_dwm_dword(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wintray, "_winreg", lambda: FakeWinreg(value=0xFFD77800))

    assert wintray._system_accent_color() == "#0078d7"


def test_system_accent_color_returns_none_for_missing_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        wintray,
        "_winreg",
        lambda: FakeWinreg(error=FileNotFoundError("missing DWM key")),
    )

    assert wintray._system_accent_color() is None


def test_system_accent_color_returns_none_for_malformed_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wintray, "_winreg", lambda: FakeWinreg(value="not-a-dword"))

    assert wintray._system_accent_color() is None


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
    assert "usageApplyStateWithDynamicHeight" in html


def test_content_height_message_resizes_visible_panel_with_work_area_clamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = wintray._WindowsTrayController(mock=True, interval=60)
    controller.visible = True
    controller.window = SimpleNamespace(x=0, y=0)
    calls: list[str] = []
    monkeypatch.setattr(controller, "_working_area", lambda: (0, 0, 1000, 800))
    monkeypatch.setattr(
        controller, "_work_area_for_point", lambda _point: (0, 0, 1000, 800)
    )
    monkeypatch.setattr(controller, "_place_window_on_ui_thread", lambda: calls.append("place"))

    controller.handle_panel_message(
        json.dumps({"action": "content_height", "height": 510.4})
    )
    controller.handle_panel_message(
        json.dumps({"action": "content_height", "height": 5000})
    )

    assert controller.panel_height() == 776
    assert calls == ["place", "place"]


def test_invalid_content_height_keeps_registered_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = wintray._WindowsTrayController(mock=True, interval=60)
    fallback = wintray.PANEL_HEIGHTS[controller.active_panel_id]
    monkeypatch.setattr(controller, "_working_area", lambda: (0, 0, 1000, 800))

    controller.handle_panel_message(
        json.dumps({"action": "content_height", "height": "510"})
    )

    assert controller.panel_height() == fallback


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
    monkeypatch.setattr(controller, "_work_area_for_point", lambda point: (0, 0, 1000, 1080))

    controller._place_window()

    assert moves == [(608, 12)]
    window.x, window.y = 123, 234
    controller.show_panel()
    assert prefs._load_preferences()["usage.windowPosition"] == {"x": 123, "y": 234}


def test_dpi_scaled_monitor_placement_uses_logical_coordinates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    screens = [
        SimpleNamespace(
            x=0,
            y=0,
            width=1536,
            height=864,
            frame=SimpleNamespace(Left=0, Top=0, Right=1536, Bottom=824),
            scale=1.25,
        ),
        SimpleNamespace(
            x=1536,
            y=0,
            width=1280,
            height=720,
            frame=SimpleNamespace(Left=1536, Top=0, Right=2816, Bottom=680),
            scale=1.5,
        ),
    ]
    monkeypatch.setitem(sys.modules, "webview", SimpleNamespace(screens=screens))
    mutations: list[tuple[str, int, int]] = []
    window = SimpleNamespace(
        x=2700,
        y=600,
        resize=lambda width, height: mutations.append(("resize", width, height)),
        move=lambda x, y: mutations.append(("move", x, y)),
    )
    controller = wintray._WindowsTrayController(mock=True, interval=60)
    controller.window = window
    controller._content_height = 400
    controller._positioned_this_show = True

    controller._place_window()

    assert mutations == [("resize", 380, 400), ("move", 2424, 268)]


def test_content_height_clamps_to_panels_current_monitor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    screens = [
        SimpleNamespace(
            x=0,
            y=0,
            width=1536,
            height=1080,
            frame=SimpleNamespace(Left=0, Top=0, Right=1536, Bottom=1040),
        ),
        SimpleNamespace(
            x=1536,
            y=0,
            width=1280,
            height=720,
            frame=SimpleNamespace(Left=1536, Top=0, Right=2816, Bottom=700),
        ),
    ]
    monkeypatch.setitem(sys.modules, "webview", SimpleNamespace(screens=screens))
    controller = wintray._WindowsTrayController(mock=True, interval=60)
    controller.window = SimpleNamespace(x=1700, y=100)

    controller._apply_content_height(1000)

    assert controller.panel_height() == 676


def test_background_window_mutation_is_dispatched_to_ui_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main_thread_id = threading.get_ident()
    mutation_threads: list[int] = []
    scheduling_threads: list[int] = []
    scheduled_drains: list[Callable[[], None]] = []

    def begin_invoke(callback: Callable[[], None]) -> None:
        scheduling_threads.append(threading.get_ident())
        scheduled_drains.append(callback)

    native = SimpleNamespace(InvokeRequired=True, BeginInvoke=begin_invoke)
    controller = wintray._WindowsTrayController(mock=True, interval=60)
    controller.window = SimpleNamespace(
        native=native,
        resize=lambda _width, _height: mutation_threads.append(threading.get_ident()),
        move=lambda _x, _y: mutation_threads.append(threading.get_ident()),
    )
    monkeypatch.setitem(sys.modules, "System", SimpleNamespace(Action=lambda callback: callback))
    monkeypatch.setattr(controller, "_working_area", lambda: (0, 0, 1000, 800))
    monkeypatch.setattr(
        controller, "_work_area_for_point", lambda _point: (0, 0, 1000, 800)
    )
    worker = threading.Thread(target=controller._place_window)
    worker.start()
    worker.join()

    assert mutation_threads == []
    assert len(scheduling_threads) == 1
    assert scheduling_threads[0] != main_thread_id
    scheduled_drains.pop()()
    assert mutation_threads == [main_thread_id, main_thread_id]


def test_load_preferences_non_utf8(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    preferences_path = tmp_path / "usage-preferences.json"
    preferences_path.write_bytes(b"\xff\xfe\x00bad")
    monkeypatch.setattr(prefs, "PREFERENCES_FILE", preferences_path)

    assert prefs._load_preferences() == {}


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


def test_switch_panel_keeps_dragged_position_before_new_height_is_measured(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Regression: switch_panel() used to reset _content_height to None, so
    # on_loaded() clamped the just-dragged position against PANEL_HEIGHTS'
    # near-fullscreen placeholder for the new panel before its real height
    # was measured, snapping a dragged window back up to the top of the
    # screen on every switch.
    moves: list[tuple[int, int]] = []
    window = SimpleNamespace(
        x=0,
        y=0,
        resize=lambda *args: None,
        move=lambda x, y: moves.append((x, y)),
        show=lambda: None,
        hide=lambda: None,
        load_html=lambda html: None,
        evaluate_js=lambda code: None,
    )
    controller = wintray._WindowsTrayController(mock=True, interval=60)
    monkeypatch.setattr(prefs, "PREFERENCES_FILE", tmp_path / "usage-preferences.json")
    controller.window = window
    controller.visible = True
    controller.active_panel_id = "world_cup"
    monkeypatch.setattr(controller, "_working_area", lambda: (0, 0, 1920, 1080))
    monkeypatch.setattr(controller, "_work_area_for_point", lambda point: (0, 0, 1920, 1080))

    controller._place_window()
    controller.handle_panel_message(json.dumps({"action": "content_height", "height": 700}))
    window.x, window.y = 300, 200  # simulates the user dragging the window here

    controller.switch_panel("cloud_observation")  # PANEL_HEIGHTS[...] == 1006
    controller.on_loaded()

    assert moves[-1] == (300, 200)

    controller.handle_panel_message(json.dumps({"action": "content_height", "height": 650}))

    assert moves[-1] == (300, 200)


def test_switch_panel_keeps_dragged_position_on_secondary_monitor(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Regression: _working_area() only ever reports the *primary* monitor's
    # work area (that's what SPI_GETWORKAREA returns). Clamping a dragged
    # window against it snapped the window back onto the primary monitor on
    # every panel switch, even when the user deliberately dragged it onto a
    # secondary display.
    primary = (0, 0, 1920, 1080)
    secondary = (1920, 0, 4480, 1400)  # a monitor to the right of the primary

    def work_area_for_point(point: tuple[int, int] | None) -> tuple[int, int, int, int]:
        if point is not None and point[0] >= 1920:
            return secondary
        return primary

    moves: list[tuple[int, int]] = []
    window = SimpleNamespace(
        x=0,
        y=0,
        resize=lambda *args: None,
        move=lambda x, y: moves.append((x, y)),
        show=lambda: None,
        hide=lambda: None,
        load_html=lambda html: None,
        evaluate_js=lambda code: None,
    )
    controller = wintray._WindowsTrayController(mock=True, interval=60)
    monkeypatch.setattr(prefs, "PREFERENCES_FILE", tmp_path / "usage-preferences.json")
    controller.window = window
    controller.visible = True
    controller.active_panel_id = "world_cup"
    monkeypatch.setattr(controller, "_working_area", lambda: primary)
    monkeypatch.setattr(controller, "_work_area_for_point", work_area_for_point)

    controller._place_window()
    controller.handle_panel_message(json.dumps({"action": "content_height", "height": 700}))
    window.x, window.y = 2200, 300  # simulates dragging the window onto the secondary monitor

    controller.switch_panel("cloud_observation")
    controller.on_loaded()

    assert moves[-1] == (2200, 300)


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
    monkeypatch.setattr(win_login_item, "is_enabled", lambda: True)

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
    monkeypatch.setattr(wintray, "_window_keeper_enabled", lambda: True)
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
        "window_keeper_menu",
        "project_butler",
        "terse_mode_menu",
        "separator",
        "check_update",
    ]
    panels = cast(list[dict[str, object]], menu[2]["children"])
    hidden_sections = cast(list[dict[str, object]], menu[3]["children"])
    assert panels[1]["panelId"] == "matrix"
    assert panels[1]["checked"] is True
    assert [item["checked"] for item in hidden_sections] == [True, False, True]
    assert menu[5]["checked"] is True
    assert menu[6]["checked"] is False
    assert menu[7]["checked"] is True
    assert menu[8]["checked"] is True
    assert menu[9]["checked"] is False


def test_panel_and_tray_menus_render_the_shared_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeMenuItem:
        def __init__(self, label: str, action: object, **kwargs: object) -> None:
            self.label = label
            self.action = action
            self.kwargs = kwargs

    class FakeMenu:
        SEPARATOR = object()

        def __init__(self, *items: object) -> None:
            self.items = items

    fake_pystray = SimpleNamespace(Menu=FakeMenu, MenuItem=FakeMenuItem)
    monkeypatch.setitem(sys.modules, "pystray", fake_pystray)
    controller = wintray._WindowsTrayController(mock=True, interval=60)
    controller.language = "en"
    quit_calls: list[str] = []
    monkeypatch.setattr(controller, "quit", lambda *_args: quit_calls.append("quit"))
    # The panel payload resolves every check eagerly (it is serialized JSON, not
    # a callback), so building it reaches win_login_item -> winreg. Stub it the
    # way the other panel-menu test does, or this cannot run on the macOS CI.
    monkeypatch.setattr(win_login_item, "is_enabled", lambda: True)

    model = wintray._menu_model()
    panel_model = wintray_menu.entries_for_surface(model, wintray_menu.PANEL)
    tray_model = wintray_menu.entries_for_surface(model, wintray_menu.TRAY)
    panel_payload = controller._panel_menu_data()
    tray_menu = wintray._menu(controller)

    def model_keys(entries: tuple[wintray_menu.MenuEntry, ...]) -> list[str]:
        return [
            "separator"
            if isinstance(entry, wintray_menu.MenuSeparator)
            else entry.i18n_key
            for entry in entries
        ]

    assert [entry.get("i18nKey", entry.get("type")) for entry in panel_payload] == model_keys(
        panel_model
    )
    assert [
        "separator" if item is FakeMenu.SEPARATOR else item.label
        for item in tray_menu.items[1:]
    ] == [
        "separator"
        if isinstance(entry, wintray_menu.MenuSeparator)
        else _t("en", entry.i18n_key)
        for entry in tray_model
    ]
    assert model_keys(tray_model) == ["reset_panel_position", "separator", "quit"]
    assert tray_menu.items[0].kwargs == {"default": True, "visible": False}
    tray_menu.items[-1].action(None, None)
    assert quit_calls == ["quit"]


@pytest.mark.parametrize("_panel_id,_key,filename", wintray.available_panels())
def test_panel_body_keeps_refresh_and_quit_escape_controls(
    _panel_id: str, _key: str, filename: str
) -> None:
    html = wintray.panel_html(filename)

    assert 'data-action="refresh"' in html
    assert 'data-action="quit"' in html


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
        ({"action": "toggle_window_keeper"}, "toggle_window_keeper", ()),
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
    monkeypatch.setattr(
        controller, "inject_state", lambda *, force=False: calls.append(f"inject:{force}")
    )
    monkeypatch.setattr(controller, "refresh", lambda: calls.append("refresh"))
    controller.window = SimpleNamespace(
        show=lambda: calls.append("show"), hide=lambda: calls.append("hide")
    )

    controller.show_panel()

    assert controller.visible is True
    assert calls == ["place", "show", "inject:True", "refresh"]


def test_attach_schedules_startup_maintenance_after_tray_is_visible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = wintray._WindowsTrayController(mock=True, interval=60)
    events: list[object] = []
    threads: list[SimpleNamespace] = []

    class FakeThread:
        def __init__(
            self,
            *,
            target: object,
            daemon: bool,
            kwargs: dict[str, object] | None = None,
        ) -> None:
            self.target = target
            self.kwargs = kwargs or {}
            self.daemon = daemon
            threads.append(cast(SimpleNamespace, self))

        def start(self) -> None:
            target = cast(Callable[..., object], self.target)
            events.append(("thread", target.__name__, self.daemon))

    monkeypatch.setattr("wintray.threading.Thread", FakeThread)
    monkeypatch.setattr(controller, "_update_tray", lambda: events.append("tray"))
    monkeypatch.setattr(controller, "refresh", lambda: events.append("refresh"))
    monkeypatch.setattr(
        "wintray.usage_diagnosis_snapshot.maybe_schedule_refresh",
        lambda: events.append("diagnosis"),
    )
    monkeypatch.setattr(
        controller,
        "_clear_stale_update_cache",
        lambda: events.append("clear-update-cache"),
    )
    monkeypatch.setattr(
        controller,
        "_check_update_in_background",
        lambda **kwargs: events.append(("update", kwargs)),
    )

    controller.attach(SimpleNamespace(), SimpleNamespace())

    assert events == [
        "tray",
        ("thread", "_startup_maintenance", True),
        ("thread", "_poll_loop", True),
        "refresh",
    ]
    startup = next(thread for thread in threads if thread.target == controller._startup_maintenance)
    startup.target(**startup.kwargs)
    assert events[-3:] == [
        "diagnosis",
        "clear-update-cache",
        (
            "update",
            {"manual": False, "ignore_cooldown": False, "ignore_skipped": False},
        ),
    ]


def test_refresh_requested_while_busy_runs_once_after_current_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = wintray._WindowsTrayController(mock=True, interval=60)
    first_started = threading.Event()
    release_first = threading.Event()
    second_finished = threading.Event()
    calls = 0

    def build_state(**_kwargs: object) -> menubar_state.PopoverState:
        nonlocal calls
        calls += 1
        if calls == 1:
            first_started.set()
            assert release_first.wait(2)
        elif calls == 2:
            second_finished.set()
        return _state()

    monkeypatch.setattr(controller, "_build_state", build_state)
    monkeypatch.setattr(controller, "_process_quota_notifications", lambda _state: None)
    monkeypatch.setattr(controller, "_update_tray", lambda: None)

    controller.refresh()
    assert first_started.wait(2)
    controller.refresh()
    controller.refresh()
    controller.refresh()
    release_first.set()

    assert second_finished.wait(2)
    for _ in range(200):
        with controller.refresh_lock:
            if not controller._refresh_in_flight:
                break
        time.sleep(0.01)

    assert calls == 2
    assert controller._refresh_in_flight is False
    assert controller._refresh_queued is False


def test_windows_usage_watch_specs_are_limited_to_usage_sources(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    claude_root = tmp_path / ".claude"
    claude_projects = claude_root / "projects"
    sessions = tmp_path / ".codex" / "sessions"
    archived = tmp_path / ".codex" / "archived_sessions"
    for path in (claude_projects, sessions, archived):
        path.mkdir(parents=True)
    monkeypatch.setattr(
        "windows_watch.rate_limits.STATUS_FILE",
        str(claude_root / "usage-status.json"),
    )
    monkeypatch.setattr(
        "windows_watch.rate_limits.LEGACY_STATUS_FILE",
        str(claude_root / "usag-status.json"),
    )
    monkeypatch.setattr(
        "windows_watch.rate_limits.TT_STATUS_FILE",
        str(claude_root / "tt-status.json"),
    )
    monkeypatch.setattr(
        "windows_watch.history_loader.CLAUDE_PROJECTS_DIR", claude_projects
    )
    monkeypatch.setattr("windows_watch.codex_loader.SESSIONS_DIR", sessions)
    monkeypatch.setattr("windows_watch.codex_loader.ARCHIVED_SESSIONS_DIR", archived)

    specs = windows_watch.usage_watch_specs()

    assert [spec.root for spec in specs] == [
        claude_root,
        claude_projects,
        sessions,
        archived,
    ]
    assert specs[0].recursive is False
    assert specs[0].filenames == frozenset(
        {"usage-status.json", "usag-status.json", "tt-status.json"}
    )
    assert all(spec.recursive and spec.history_jsonl for spec in specs[1:])


@pytest.mark.skipif(sys.platform != "win32", reason="requires ReadDirectoryChangesW")
def test_windows_watcher_observes_real_filesystem_change_and_refreshes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sessions = tmp_path / "sessions"
    nested = sessions / "2026" / "08" / "13"
    nested.mkdir(parents=True)
    target = nested / "session.jsonl"
    controller = wintray._WindowsTrayController(mock=True, interval=60)
    received: list[windows_watch.WindowsFileEventChanges] = []
    changed = threading.Event()
    refreshed = threading.Event()

    monkeypatch.setattr(controller, "refresh", refreshed.set)

    def on_change(changes: windows_watch.WindowsFileEventChanges) -> None:
        received.append(changes)
        controller._refresh_from_file_event(changes)
        if target in changes.paths:
            changed.set()

    watcher = windows_watch.setup_windows_watcher(
        on_change,
        specs=[
            windows_watch.WindowsWatchSpec(
                sessions,
                recursive=True,
                history_jsonl=True,
            )
        ],
    )
    assert watcher is not None
    try:
        target.write_text('{"type":"event"}\n', encoding="utf-8")
        assert changed.wait(5.0)
        assert refreshed.wait(5.0)
    finally:
        watcher.stop()
        controller.quit()

    assert any(target in changes.paths for changes in received)
    assert all(
        runtime.thread is None or not runtime.thread.is_alive()
        for runtime in watcher._runtimes
    )


def test_file_event_storm_coalesces_to_one_trailing_refresh(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    controller = wintray._WindowsTrayController(mock=True, interval=60)
    refreshes: list[str] = []
    timers: list[FakeTimer] = []
    dirty = tmp_path / ".codex" / "sessions" / "session.jsonl"

    class FakeTimer:
        def __init__(self, delay: float, callback: object) -> None:
            self.delay = delay
            self.callback = cast(Any, callback)
            self.daemon = False
            self.started = False
            self.cancelled = False
            timers.append(self)

        def start(self) -> None:
            self.started = True

        def cancel(self) -> None:
            self.cancelled = True

    monkeypatch.setattr("wintray.threading.Timer", FakeTimer)
    monkeypatch.setattr("wintray.time.monotonic", lambda: 100.0)
    monkeypatch.setattr(controller, "refresh", lambda: refreshes.append("refresh"))
    changes = windows_watch.WindowsFileEventChanges(frozenset({dirty}))

    controller._refresh_from_file_event(changes)
    for _ in range(50):
        controller._refresh_from_file_event(changes)

    assert refreshes == ["refresh"]
    assert len(timers) == 1
    assert timers[0].started is True
    assert timers[0].delay == menubar_state.FILE_EVENT_REFRESH_MIN_INTERVAL_S

    timers[0].callback()

    assert refreshes == ["refresh", "refresh"]
    assert controller._file_event_refresh_timer is None


def test_windows_history_watcher_uses_dirty_paths_and_full_scan_fallback(
    tmp_path: Path,
) -> None:
    spec = windows_watch.WindowsWatchSpec(
        tmp_path / "sessions",
        recursive=True,
        history_jsonl=True,
    )
    dirty = spec.root / "nested" / "session.jsonl"

    changed = spec.classify(dirty, windows_watch._FILE_ACTION_MODIFIED)
    removed_directory = spec.classify(
        spec.root / "removed-directory",
        windows_watch._FILE_ACTION_REMOVED,
    )

    assert changed == windows_watch.WindowsFileEventChanges(frozenset({dirty}))
    assert removed_directory == windows_watch.WindowsFileEventChanges(
        frozenset(),
        needs_full_scan=True,
    )


def test_quit_cancels_file_timer_stops_watcher_and_joins_workers() -> None:
    controller = wintray._WindowsTrayController(mock=True, interval=60)
    calls: list[str] = []
    controller._file_event_refresh_timer = cast(
        Any,
        SimpleNamespace(cancel=lambda: calls.append("cancel_timer")),
    )
    controller._windows_watcher = cast(
        Any,
        SimpleNamespace(stop=lambda: calls.append("stop_watcher")),
    )
    controller._poll_thread = cast(
        Any,
        SimpleNamespace(join=lambda timeout: calls.append(f"join_poll:{timeout}")),
    )
    controller._refresh_thread = cast(
        Any,
        SimpleNamespace(join=lambda timeout: calls.append(f"join_refresh:{timeout}")),
    )
    controller.icon = SimpleNamespace(stop=lambda: calls.append("stop_icon"))
    controller.window = SimpleNamespace(destroy=lambda: calls.append("destroy_window"))

    controller.quit()

    assert controller.stopping.is_set()
    assert calls == [
        "cancel_timer",
        "stop_watcher",
        "join_poll:3.0",
        "join_refresh:3.0",
        "stop_icon",
        "destroy_window",
    ]


def test_tray_update_skips_unchanged_values(monkeypatch: pytest.MonkeyPatch) -> None:
    controller = wintray._WindowsTrayController(mock=True, interval=60)
    controller.latest_state = _state()
    icon = SimpleNamespace(icon=None, title=None)
    controller.icon = icon
    images: list[float | None] = []

    def fake_draw_tray_icon(percent: float | None) -> object:
        images.append(percent)
        return object()

    monkeypatch.setattr(wintray, "draw_tray_icon", fake_draw_tray_icon)

    controller._update_tray()
    first_image = icon.icon
    controller._update_tray()
    controller.latest_state.claude_session.percent = 26.0
    controller._update_tray()

    assert images == [25.0, 26.0]
    assert icon.icon is not first_image


def test_tray_update_passes_same_percent_to_taskbar_seam(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = wintray._WindowsTrayController(mock=True, interval=60)
    controller.latest_state = _state()
    controller.icon = SimpleNamespace(icon=None, title=None)
    controller.visible = True
    controller.window = SimpleNamespace(
        native=SimpleNamespace(
            ShowInTaskbar=True,
            Handle=SimpleNamespace(ToInt64=lambda: 4321),
        )
    )
    calls: list[tuple[int, int, int, wintray.TaskbarProgressState]] = []
    monkeypatch.setattr(wintray, "draw_tray_icon", lambda percent: object())
    monkeypatch.setattr(
        wintray,
        "_set_taskbar_progress",
        lambda hwnd, completed, total, state: calls.append((hwnd, completed, total, state)),
    )

    controller._update_tray()

    assert calls == [(4321, 25, 100, wintray.TaskbarProgressState.NORMAL)]


def test_taskbar_progress_failure_is_nonfatal(monkeypatch: pytest.MonkeyPatch) -> None:
    controller = wintray._WindowsTrayController(mock=True, interval=60)
    controller.visible = True
    controller.window = SimpleNamespace(
        native=SimpleNamespace(
            ShowInTaskbar=True,
            Handle=SimpleNamespace(ToInt64=lambda: 4321),
        )
    )
    monkeypatch.delenv("USAGE_DEBUG", raising=False)

    def fail(*args: object) -> None:
        raise OSError("taskbar unavailable")

    monkeypatch.setattr(wintray, "_set_taskbar_progress", fail)

    controller._update_taskbar_progress(60.0)


def test_inject_state_skips_duplicate_but_forces_after_panel_reopens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = wintray._WindowsTrayController(mock=True, interval=60)
    injected: list[str] = []
    controller.window = SimpleNamespace(
        evaluate_js=injected.append,
        show=lambda: None,
        hide=lambda: None,
    )
    monkeypatch.setattr(controller, "_place_window", lambda: None)
    monkeypatch.setattr(controller, "refresh", lambda: None)
    monkeypatch.setattr(wintray, "_system_accent_color", lambda: "#0078d7")

    controller.inject_state()
    controller.inject_state()
    controller.show_panel()
    controller.on_loaded()
    controller.show_panel()
    controller.show_panel()

    assert len(injected) == 4
    assert '"system_accent_color":"#0078d7"' in injected[0]


def test_build_state_reuses_history_until_fingerprint_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = wintray._WindowsTrayController(mock=True, interval=60)
    fingerprints = iter([(("history", 1, 10.0),), (("history", 2, 11.0),)])
    monkeypatch.setattr(
        menubar_state,
        "history_source_scan",
        lambda: menubar_state.HistorySourceScan(next(fingerprints), (), ()),
    )
    calls: list[int] = []
    original = controller._load_entries

    def counting_load_entries(scan: menubar_state.HistorySourceScan) -> wintray._RefreshData:
        calls.append(1)
        return original(scan)

    monkeypatch.setattr(controller, "_load_entries", counting_load_entries)
    monkeypatch.setattr(
        service_status,
        "get_service_status",
        lambda config: service_status.ServiceStatus(
            config.service_name,
            False,
            "operational",
            "Relevant components are operational.",
            "cache",
        ),
    )
    now = 100.0
    monkeypatch.setattr("wintray.time.monotonic", lambda: now)

    controller._build_state()
    controller._build_state()
    now += wintray.HISTORY_SCAN_CACHE_SECONDS
    controller._build_state()

    assert calls == [1, 1]


def test_build_state_reuses_history_scan_for_codex_rate_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = wintray._WindowsTrayController(mock=False, interval=60)
    candidates = ((Path("C:/codex/sessions/session.jsonl"), 123.0),)
    scan = menubar_state.HistorySourceScan(
        (("history", 1, 10.0),),
        (),
        (),
        candidates,
    )
    history_scan_calls = 0
    rate_limit_scans: list[tuple[tuple[Path, float], ...] | None] = []

    def history_source_scan() -> menubar_state.HistorySourceScan:
        nonlocal history_scan_calls
        history_scan_calls += 1
        return scan

    def recent_jsonl_files(
        *, jsonl_candidates: tuple[tuple[Path, float], ...] | None = None
    ) -> list[Path]:
        rate_limit_scans.append(jsonl_candidates)
        return []

    async def fetch() -> PollOutcome:
        return PollOutcome(state=PollState.LOADING)

    monkeypatch.setattr(controller, "_history_source_scan", history_source_scan)
    monkeypatch.setattr(controller, "_load_entries", lambda _scan: wintray._RefreshData([], None))
    monkeypatch.setattr(controller, "_fetch", fetch)
    monkeypatch.setattr(codex_loader, "_load_sqlite_rate_limits", lambda: None)
    monkeypatch.setattr(codex_loader, "_load_thread_models", lambda: {})
    monkeypatch.setattr(codex_loader, "_recent_jsonl_files", recent_jsonl_files)
    monkeypatch.setattr(
        menubar_agy,
        "load_refresh_result",
        lambda _language: menubar_agy.AgyRefreshResult(None, True),
    )
    monkeypatch.setattr("wintray.agy_window_keeper.maybe_ping", lambda *_args: None)

    controller._build_state()

    assert history_scan_calls == 1
    assert rate_limit_scans == [candidates]


def test_build_state_fetches_relevant_service_feeds_and_builds_banner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = wintray._WindowsTrayController(mock=True, interval=60)
    controller.language = "en"
    row = _state().codex_session
    projection = menubar_agy.AgyQuotaProjection(
        group_name="Gemini",
        session=row,
        weekly=row,
        stale=None,
        five_hour=None,
    )
    calls: list[service_status.ServiceStatusConfig] = []

    def fake_status(
        config: service_status.ServiceStatusConfig,
    ) -> service_status.ServiceStatus:
        calls.append(config)
        return service_status.ServiceStatus(
            config.service_name,
            config.service_name == "Claude",
            "major_outage" if config.service_name == "Claude" else "operational",
            "test",
            "fetched",
        )

    monkeypatch.setattr(
        menubar_state,
        "codex_rows",
        lambda **kwargs: ((row, row), 25.0, "codex", None, None),
    )
    monkeypatch.setattr(
        menubar_agy,
        "load_refresh_result",
        lambda language: menubar_agy.AgyRefreshResult(projection, False),
    )
    monkeypatch.setattr(
        controller,
        "_history_source_scan",
        lambda: menubar_state.HistorySourceScan((), (), ()),
    )
    monkeypatch.setattr(
        controller,
        "_load_entries",
        lambda scan: wintray._RefreshData([], None),
    )
    monkeypatch.setattr("wintray.window_keeper.maybe_ping", lambda *args: None)
    monkeypatch.setattr("wintray.agy_window_keeper.maybe_ping", lambda *args: None)
    monkeypatch.setattr(service_status, "get_service_status", fake_status)
    monkeypatch.setattr(wintray, "_hide_claude_enabled", lambda: False)
    monkeypatch.setattr(wintray, "_hide_codex_enabled", lambda: False)

    state = controller._build_state()

    assert calls == [
        service_status.CLAUDE_STATUS,
        service_status.CODEX_STATUS,
    ]
    # components.json, not summary.json — the summary payload is truncated to the
    # first 25 components and silently omits Codex API. See test_service_status.py.
    assert calls[0].status_url == "https://status.claude.com/api/v2/components.json"
    assert calls[0].component_names == ("Claude Code", "Claude API (api.anthropic.com)")
    assert calls[1].status_url == "https://status.openai.com/api/v2/components.json"
    assert calls[1].component_names == ("Codex API",)
    assert state.service_alerts == ("⚠ Claude service issue: Major outage",)


def test_history_source_scan_is_cached_between_tray_ticks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = wintray._WindowsTrayController(mock=True, interval=60)
    scan = menubar_state.HistorySourceScan((("history", 1, 10.0),), (), ())
    calls: list[int] = []
    now = 100.0
    monkeypatch.setattr("wintray.time.monotonic", lambda: now)

    def scan_history() -> menubar_state.HistorySourceScan:
        calls.append(1)
        return scan

    monkeypatch.setattr(
        menubar_state,
        "history_source_scan",
        scan_history,
    )

    assert controller._history_source_scan() is scan
    assert controller._history_source_scan() is scan
    now += wintray.HISTORY_SCAN_CACHE_SECONDS
    assert controller._history_source_scan() is scan

    assert calls == [1, 1]


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


@pytest.mark.parametrize(
    ("event", "expected_title", "expected_body"),
    [
        (
            NotificationEvent("warn", "claude_session", 90.0),
            "🐾 Almost out",
            "Claude Session is 25% used. Time to wrap up?",
        ),
        (
            NotificationEvent("depleted", "codex_weekly", None),
            "🐾 Quota is empty",
            "Codex Weekly quota is drained. Back after Resets in 1d",
        ),
        (
            NotificationEvent("restored", "claude_weekly", None),
            "🐾 Quota is back",
            "Claude Weekly is ready to go again 🚀",
        ),
    ],
)
def test_quota_notifications_use_interactive_toast_and_existing_i18n(
    monkeypatch: pytest.MonkeyPatch,
    event: NotificationEvent,
    expected_title: str,
    expected_body: str,
) -> None:
    class FakeToast:
        def __init__(self, *, text_fields: list[str]) -> None:
            self.text_fields = text_fields
            self.actions: list[object] = []
            self.on_activated: object | None = None

        def AddAction(self, action: object) -> None:  # noqa: N802 - library contract
            self.actions.append(action)

    class FakeToastButton:
        def __init__(self, *, content: str, arguments: str) -> None:
            self.content = content
            self.arguments = arguments

    shown: list[FakeToast] = []
    fake_toaster = SimpleNamespace(show_toast=shown.append)
    monkeypatch.setitem(
        sys.modules,
        "windows_toasts",
        SimpleNamespace(Toast=FakeToast, ToastButton=FakeToastButton),
    )
    monkeypatch.setattr(wintray, "_create_toast_backend", lambda: fake_toaster)
    controller = wintray._WindowsTrayController(mock=False, interval=60)
    controller.language = "en"
    controller.icon = SimpleNamespace(notify=lambda *_args: pytest.fail("unexpected fallback"))

    controller._send_quota_notification(event, _state())

    assert len(shown) == 1
    assert shown[0].text_fields == [expected_title, expected_body]
    assert len(shown[0].actions) == 1
    action = cast(FakeToastButton, shown[0].actions[0])
    assert action.content == "Usage"
    assert action.arguments == wintray._TOAST_OPEN_PANEL_ACTION


def test_quota_toast_action_activates_panel(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeToast:
        def __init__(self, *, text_fields: list[str]) -> None:
            self.text_fields = text_fields
            self.on_activated: object | None = None

        def AddAction(self, action: object) -> None:  # noqa: N802 - library contract
            return None

    shown: list[FakeToast] = []
    fake_module = SimpleNamespace(
        Toast=FakeToast,
        ToastButton=lambda **kwargs: SimpleNamespace(**kwargs),
    )
    monkeypatch.setitem(sys.modules, "windows_toasts", fake_module)
    monkeypatch.setattr(
        wintray,
        "_create_toast_backend",
        lambda: SimpleNamespace(show_toast=shown.append),
    )
    controller = wintray._WindowsTrayController(mock=False, interval=60)
    activated: list[str] = []
    monkeypatch.setattr(controller, "_activate_panel", lambda: activated.append("panel"))

    controller._send_quota_notification(
        NotificationEvent("warn", "claude_session", 90.0), _state()
    )
    callback = shown[0].on_activated
    assert callable(callback)
    callback(SimpleNamespace(arguments=wintray._TOAST_OPEN_PANEL_ACTION))

    assert activated == ["panel"]


def test_quota_notification_falls_back_to_pystray_when_toast_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable() -> object:
        raise ModuleNotFoundError("windows_toasts")

    monkeypatch.setattr(wintray, "_create_toast_backend", unavailable)
    controller = wintray._WindowsTrayController(mock=False, interval=60)
    controller.language = "en"
    notices: list[tuple[str, str]] = []
    controller.icon = SimpleNamespace(
        notify=lambda message, title: notices.append((message, title))
    )
    state = _state()

    controller._send_quota_notification(
        NotificationEvent("warn", "claude_session", 90.0), state
    )

    assert notices == [("Claude Session is 25% used. Time to wrap up?", "🐾 Almost out")]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows toast registration and WinRT")
def test_real_windows_toast_backend_registers_aumid_and_creates_notifier() -> None:
    import uuid
    import winreg

    pytest.importorskip("windows_toasts", reason="Windows toast extra is not installed")
    aumid = f"com.lollapalooza.usage.pytest.{uuid.uuid4().hex}"
    key_path = rf"Software\Classes\AppUserModelId\{aumid}"
    key_name = "HKEY_CURRENT_USER"
    hkey_current_user: Any = getattr(winreg, key_name)
    open_key_name = "OpenKey"
    open_key: Any = getattr(winreg, open_key_name)
    query_value_name = "QueryValueEx"
    query_value: Any = getattr(winreg, query_value_name)
    delete_key_name = "DeleteKey"
    delete_key: Any = getattr(winreg, delete_key_name)
    try:
        backend = wintray._create_toast_backend(aumid)
        with open_key(hkey_current_user, key_path) as key:
            display_name, _value_type = query_value(key, "DisplayName")

        assert display_name == "usage"
        assert backend.notifierAUMID == aumid
        assert backend.toastNotifier is not None
    finally:
        with suppress(FileNotFoundError):
            delete_key(hkey_current_user, key_path)


@pytest.mark.parametrize(
    "preferences",
    [
        {"auto_update_check": False},
        {"last_update_check": {"checked_at": 2_000_000_000.0}},
        {"update_dismissed_at": 2_000_000_000.0},
    ],
)
def test_automatic_update_check_honors_toggle_cache_and_cooldown(
    monkeypatch: pytest.MonkeyPatch,
    preferences: dict[str, object],
) -> None:
    controller = wintray._WindowsTrayController(mock=True, interval=60)
    monkeypatch.setattr(wintray, "_load_preferences", lambda: preferences.copy())
    monkeypatch.setattr("wintray.update_gate.time.time", lambda: 2_000_000_000.0)
    monkeypatch.setattr(
        update_checker,
        "check_latest_release_result",
        lambda version: pytest.fail("automatic update gate must skip the network"),
    )

    controller._check_update_in_background(
        manual=False,
        ignore_cooldown=False,
        ignore_skipped=False,
    )


def test_automatic_update_check_persists_cache_and_honors_skipped_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = update_checker.ReleaseInfo(
        version="99.0.0",
        html_url="https://github.com/aqua5230/usage/releases/tag/v99.0.0",
        body="release notes",
    )
    preferences: dict[str, object] = {"update_skipped_version": release.version}
    saved: list[dict[str, object]] = []
    controller = wintray._WindowsTrayController(mock=True, interval=60)
    monkeypatch.setattr(wintray, "_current_version", lambda: "1.0.0")
    monkeypatch.setattr(wintray, "_load_preferences", lambda: preferences.copy())
    monkeypatch.setattr(wintray, "_save_preferences", lambda data: saved.append(dict(data)))
    monkeypatch.setattr("wintray.update_gate.time.time", lambda: 2_000_000_000.0)
    monkeypatch.setattr(
        update_checker,
        "check_latest_release_result",
        lambda version: update_checker.ReleaseCheckResult(release),
    )
    monkeypatch.setattr(
        controller,
        "_show_update_alert",
        lambda value: pytest.fail("a skipped release must not show an automatic dialog"),
    )

    controller._check_update_in_background(
        manual=False,
        ignore_cooldown=False,
        ignore_skipped=False,
    )

    assert saved == [
        {
            "update_skipped_version": "99.0.0",
            "last_update_check": {
                "checked_at": 2_000_000_000.0,
                "current_version": "1.0.0",
                "latest_version": "99.0.0",
                "release_url": release.html_url,
            },
        }
    ]


def test_manual_update_check_bypasses_gates_and_keeps_windows_yes_no_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = update_checker.ReleaseInfo(
        version="99.0.0",
        html_url="https://github.com/aqua5230/usage/releases/tag/v99.0.0",
        body="release notes",
    )
    preferences: dict[str, object] = {
        "auto_update_check": False,
        "update_skipped_version": release.version,
        "update_dismissed_at": 2_000_000_000.0,
        "last_update_check": {"checked_at": 2_000_000_000.0},
    }
    saved: list[dict[str, object]] = []
    messages: list[tuple[str, int]] = []
    opened: list[str] = []
    controller = wintray._WindowsTrayController(mock=True, interval=60)
    controller.language = "en"
    monkeypatch.setattr(wintray, "_current_version", lambda: "1.0.0")
    monkeypatch.setattr(wintray, "_load_preferences", lambda: preferences.copy())
    monkeypatch.setattr(wintray, "_save_preferences", lambda data: saved.append(dict(data)))
    monkeypatch.setattr("wintray.update_gate.time.time", lambda: 2_000_000_000.0)
    monkeypatch.setattr(
        update_checker,
        "check_latest_release_result",
        lambda version: update_checker.ReleaseCheckResult(release),
    )
    def message_box(text: str, *, style: int = 0x40) -> int:
        messages.append((text, style))
        return 6

    monkeypatch.setattr(controller, "_message_box", message_box)
    monkeypatch.setattr("wintray.webbrowser.open", lambda url: opened.append(url))

    controller._check_update_in_background(
        manual=True,
        ignore_cooldown=True,
        ignore_skipped=True,
    )

    assert saved[-1]["last_update_check"] == {
        "checked_at": 2_000_000_000.0,
        "current_version": "1.0.0",
        "latest_version": "99.0.0",
        "release_url": release.html_url,
    }
    assert messages == [("New Version 99.0.0 Available\n\nrelease notes", 0x44)]
    assert opened == [release.html_url]


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
        toggle_window_keeper=lambda: None,
        toggle_session_resume=lambda: None,
        toggle_terse_mode=lambda: None,
        check_update=lambda: None,
        quit=lambda: None,
    )

    menu = wintray._menu(controller)  # type: ignore[arg-type]

    assert menu is not None


@pytest.mark.skipif(
    sys.platform != "darwin",
    reason="panels.panel_ids() lazily imports the PyObjC-backed HTMLPanel",
)
def test_windows_panel_registry_stays_in_sync_with_macos() -> None:
    # Regression: stained_glass and origami landed in panels/__init__.py
    # without being added here, so Windows users couldn't select them and
    # PANEL_HEIGHTS[panel_id] would have raised KeyError on first use.
    mac_ids = {p for p in panels.panel_ids() if p != "talent_market"}
    assert {panel[0] for panel in wintray.WINDOWS_PANELS} == mac_ids
    assert set(wintray.PANEL_HEIGHTS) == mac_ids

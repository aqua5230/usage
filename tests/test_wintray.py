# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

import menubar_state
import wintray


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

    image = wintray.draw_tray_icon(25.0)

    assert image.size == (64, 64)
    assert wintray.build_tooltip(_state()).splitlines() == [
        "Claude Session: 75%",
        "Claude Weekly: 40%",
        "Codex Session: 75% · Weekly: 40%",
    ]


def test_windows_panels_exclude_talent_market() -> None:
    ids = [panel[0] for panel in wintray.available_panels()]

    assert "classic" in ids
    assert "talent_market" not in ids


def test_panel_html_installs_webkit_shim_without_changing_asset() -> None:
    html = wintray.panel_html("classic.html")

    assert "window.webkit.messageHandlers.usage" in html
    assert "window.pywebview.api.postMessage(message)" in html


def test_js_api_forwards_panel_message() -> None:
    received: list[object] = []
    controller = SimpleNamespace(handle_panel_message=received.append)

    wintray._JSApi(controller).postMessage("refresh")  # type: ignore[arg-type]

    assert received == ["refresh"]


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
        events.append(("window", args[0], kwargs["hidden"]))
        return window

    fake_pystray = SimpleNamespace(Icon=FakeIcon, Menu=FakeMenu, MenuItem=FakeMenuItem)
    fake_webview = SimpleNamespace(
        create_window=create_window,
        start=lambda **kwargs: events.append(("start", kwargs["gui"])),
    )
    monkeypatch.setitem(sys.modules, "pystray", fake_pystray)
    monkeypatch.setitem(sys.modules, "webview", fake_webview)
    monkeypatch.setattr(wintray, "draw_tray_icon", lambda value: object())
    monkeypatch.setattr(wintray._WindowsTrayController, "attach", lambda self, icon, view: None)

    wintray.run_app(mock=True, interval=60)

    assert events == [
        ("window", "usage", True),
        "loaded_handler",
        ("icon", "usage"),
        "run_detached",
        ("start", "edgechromium"),
    ]

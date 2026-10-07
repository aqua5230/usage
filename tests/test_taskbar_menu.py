from __future__ import annotations

import ctypes as C
import importlib
import os
import sys
import threading
import time
from ctypes import wintypes as W
from types import SimpleNamespace
from typing import Any

import pytest

from wintray import taskbar_menu
from wintray.taskbar_overlay import TaskbarLayout, TaskbarOverlay, intersects


def _layout(rect: tuple[int, int, int, int], scale: float = 1.0) -> TaskbarLayout:
    return TaskbarLayout(42, rect, rect, (0, 0, 1920, 1080), (0, 0, 1920, 1080), scale, True)


@pytest.mark.parametrize(
    ("rect", "point", "scale", "expected"),
    [
        ((0, 1040, 1920, 1080), (1500, 1060), 1, (1500, 1036, 0x28)),
        ((0, 0, 1920, 40), (1500, 20), 1, (1500, 44, 0x08)),
        ((0, 0, 48, 1080), (24, 900), 1, (52, 900, 0x20)),
        ((1872, 0, 1920, 1080), (1890, 900), 1, (1868, 900, 0x28)),
        ((0, 1020, 1920, 1080), (1500, 1050), 1.5, (1500, 1014, 0x28)),
        ((0, 1078, 1920, 1118), (1500, 1079), 1, (1500, 1074, 0x28)),
    ],
)
def test_menu_anchor_is_outside_each_taskbar_edge(
    rect: tuple[int, int, int, int],
    point: tuple[int, int],
    scale: float,
    expected: tuple[int, int, int],
) -> None:
    position = taskbar_menu.menu_position(_layout(rect, scale), point)
    assert position == expected
    x, y, flags = position
    left = x - 240 if flags & 8 else x
    top = y - 300 if flags & 32 else y
    assert not intersects((left, top, left + 240, top + 300), rect)


def test_menu_anchor_supports_negative_screen_coordinates() -> None:
    layout = TaskbarLayout(
        42,
        (-1920, 1040, 0, 1080),
        (-300, 1040, 0, 1080),
        (-1920, 0, 0, 1040),
        (-1920, 0, 0, 1080),
        1.5,
        True,
    )
    assert taskbar_menu.menu_position(layout, (-450, 1060)) == (-450, 1034, 0x28)


class _Params(C.Structure):
    _fields_ = [("cbSize", W.UINT), ("rcExclude", W.RECT)]


@pytest.mark.parametrize("layout_available", [True, False])
@pytest.mark.parametrize("selected", [0, 1, 2])
def test_popup_uses_existing_menu_owner_and_callbacks(
    monkeypatch: pytest.MonkeyPatch,
    layout_available: bool,
    selected: int,
) -> None:
    events: list[Any] = []
    icon = SimpleNamespace(
        _menu_hwnd=123, _menu_handle=(456, [lambda received: events.append(("callback", received))])
    )

    def cursor(pointer: Any) -> None:
        pointer._obj.x, pointer._obj.y = 1500, 1060

    def popup(menu: int, flags: int, x: int, y: int, owner: int, pointer: Any) -> int:
        assert (menu, owner) == (456, 123)
        assert flags & 0x140 == 0x140  # Native selection return and exclusion placement.
        if layout_available:
            assert (x, y) == (1500, 1036)
            params = C.cast(pointer, C.POINTER(_Params)).contents
            assert params.cbSize == C.sizeof(_Params)
            assert (
                params.rcExclude.left,
                params.rcExclude.top,
                params.rcExclude.right,
                params.rcExclude.bottom,
            ) == (0, 1040, 1920, 1080)
        else:
            assert (x, y, pointer) == (1500, 1060, None)
        events.append("popup")
        return selected

    native = SimpleNamespace(
        GetCursorPos=cursor,
        TPMPARAMS=_Params,
        TPM_VERTICAL=0x40,
        TPM_RETURNCMD=0x100,
        SetForegroundWindow=lambda owner: events.append(("foreground", owner)),
        TrackPopupMenuEx=popup,
        PostMessage=lambda *args: events.append(("post", args)),
    )
    monkeypatch.setattr(importlib, "import_module", lambda _: native)
    monkeypatch.setattr(
        taskbar_menu,
        "TaskbarOverlay",
        lambda: SimpleNamespace(
            layout=lambda: _layout((0, 1040, 1920, 1080)) if layout_available else None
        ),
    )
    taskbar_menu._show_tray_menu(icon)
    assert events[:3] == [("foreground", 123), "popup", ("post", (123, 0, 0, 0))]
    assert events[3:] == ([("callback", icon)] if selected == 1 else [])


def test_popup_handles_shutdown_without_touching_native_functions() -> None:
    taskbar_menu._show_tray_menu(SimpleNamespace(_menu_handle=None, _menu_hwnd=123))
    taskbar_menu._show_tray_menu(SimpleNamespace(_menu_handle=(456, []), _menu_hwnd=None))


@pytest.mark.skipif(
    sys.platform != "win32" or os.environ.get("USAGE_TEST_NATIVE_MENU") != "1",
    reason="opt-in Windows interactive native menu placement test",
)
def test_native_popup_does_not_overlap_taskbar_and_dismisses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise the real TrackPopupMenuEx; inspect only this test's own menu."""
    if sys.platform != "win32":
        pytest.skip("Windows native menu")
    from PIL import Image
    from pystray import Menu, MenuItem
    from pystray._util import win32
    from pystray._win32 import Icon

    layout = TaskbarOverlay().layout()
    assert layout is not None
    icon = Icon(
        "usage-menu-placement-test",
        Image.new("RGBA", (16, 16)),
        menu=Menu(*(MenuItem(f"Test item {i}", lambda *_: None) for i in range(6))),
    )
    ready, entered, closed = threading.Event(), threading.Event(), threading.Event()
    real_popup = win32.TrackPopupMenuEx

    def track(*args: Any) -> int:
        entered.set()
        try:
            return int(real_popup(*args))
        finally:
            closed.set()

    monkeypatch.setattr(win32, "TrackPopupMenuEx", track)
    user = C.WinDLL("user32", use_last_error=True)
    user.GetMenuItemRect.argtypes = [W.HWND, W.HMENU, W.UINT, C.POINTER(W.RECT)]
    user.GetMenuItemRect.restype = W.BOOL
    tray_thread = threading.Thread(target=lambda: icon.run(setup=lambda _: ready.set()))
    tray_thread.start()
    try:
        assert ready.wait(3)
        taskbar_menu.request_tray_menu(icon)
        assert entered.wait(3)
        first, last = W.RECT(), W.RECT()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            menu = icon._menu_handle[0]
            if (
                user.GetMenuItemRect(None, menu, 0, C.byref(first))
                and user.GetMenuItemRect(None, menu, 5, C.byref(last))
                and first.bottom > first.top
            ):
                break
            time.sleep(0.02)
        else:
            pytest.fail("Native menu did not appear")
        menu_rect = (first.left - 2, first.top - 2, last.right + 2, last.bottom + 2)
        assert not intersects(menu_rect, layout.rect), (menu_rect, layout.rect)
        assert win32.PostMessage(icon._menu_hwnd, 0x1F, 0, 0)  # WM_CANCELMODE
        assert closed.wait(3)
    finally:
        if icon._menu_hwnd:
            win32.PostMessage(icon._menu_hwnd, 0x1F, 0, 0)
        icon.stop()
        tray_thread.join(3)
    assert not tray_thread.is_alive()

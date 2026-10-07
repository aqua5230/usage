# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>

"""Open the existing tray menu outside the taskbar, on the tray thread."""

from __future__ import annotations

import ctypes as C
import importlib
import logging
from ctypes import wintypes as W
from typing import Any

from wintray.taskbar_overlay import TaskbarLayout, TaskbarOverlay

logger = logging.getLogger(__name__)
WM_LABEL_MENU = 0x8051  # Private WM_APP message; leave tray-icon clicks unchanged.
TPM_RIGHTALIGN = 0x0008
TPM_BOTTOMALIGN = 0x0020


def menu_position(layout: TaskbarLayout, point: tuple[int, int]) -> tuple[int, int, int]:
    """Anchor on the desktop-facing edge, using physical screen coordinates."""
    left, top, right, bottom = layout.rect
    screen_left, screen_top, screen_right, screen_bottom = layout.monitor
    gap = max(1, round(4 * layout.scale))
    x = max(screen_left + gap, min(point[0], screen_right - gap))
    y = max(screen_top + gap, min(point[1], screen_bottom - gap))
    if right - left >= bottom - top:
        if abs(top - screen_top) <= abs(screen_bottom - bottom):
            return x, bottom + gap, TPM_RIGHTALIGN
        return x, top - gap, TPM_RIGHTALIGN | TPM_BOTTOMALIGN
    if abs(left - screen_left) <= abs(screen_right - right):
        return right + gap, y, TPM_BOTTOMALIGN
    return left - gap, y, TPM_RIGHTALIGN | TPM_BOTTOMALIGN


def _show_tray_menu(icon: Any) -> None:
    menu = getattr(icon, "_menu_handle", None)
    owner = getattr(icon, "_menu_hwnd", None)
    if not menu or not owner:
        return
    win32 = importlib.import_module("pystray._util.win32")
    try:
        point = W.POINT()
        win32.GetCursorPos(C.byref(point))
        x, y, flags = point.x, point.y, TPM_RIGHTALIGN | TPM_BOTTOMALIGN
        params = None
        try:
            layout = TaskbarOverlay().layout()
        except Exception:
            logger.exception("Unable to find the taskbar for the label menu")
            layout = None
        if layout is not None:
            x, y, flags = menu_position(layout, (point.x, point.y))
            params = win32.TPMPARAMS()
            params.cbSize = C.sizeof(params)
            params.rcExclude = W.RECT(*layout.rect)
        # The menu owner must be foreground so an outside click dismisses it.
        # This does not make the application or menu permanently topmost.
        win32.SetForegroundWindow(owner)
        hmenu, callbacks = menu
        selected = win32.TrackPopupMenuEx(
            hmenu,
            flags | win32.TPM_VERTICAL | win32.TPM_RETURNCMD,
            x,
            y,
            owner,
            C.byref(params) if params is not None else None,
        )
        win32.PostMessage(owner, 0, 0, 0)
        if 0 < selected <= len(callbacks):
            callbacks[selected - 1](icon)
    except Exception:
        logger.exception("Unable to open the menu from the taskbar label")


def request_tray_menu(icon: Any) -> None:
    hwnd = getattr(icon, "_hwnd", None)
    if not hwnd:
        return
    win32 = importlib.import_module("pystray._util.win32")
    icon._message_handlers.setdefault(WM_LABEL_MENU, lambda _w, _l: _show_tray_menu(icon))
    # Do not block the WinForms/WebView UI thread with TrackPopupMenuEx.
    if not win32.PostMessage(hwnd, WM_LABEL_MENU, 0, 0):
        raise OSError("Unable to request the tray menu")

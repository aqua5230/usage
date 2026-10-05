# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>

"""Win32 placement and per-pixel transparency for the taskbar quota label.

Taskbar anchoring follows Codex Usage Widget; see THIRD_PARTY_NOTICES.md.
All coordinates here are physical pixels, including those returned by UIA.
"""

from __future__ import annotations

import ctypes as C
import os
import sys
from ctypes import wintypes as W
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from PIL.Image import Image

type Rect = tuple[int, int, int, int]


def intersects(a: Rect, b: Rect) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def covers_monitor(window: Rect, monitor: Rect) -> bool:
    return all(
        (
            window[0] <= monitor[0] + 1,
            window[1] <= monitor[1] + 1,
            window[2] >= monitor[2] - 1,
            window[3] >= monitor[3] - 1,
        )
    )


def label_position(
    taskbar: Rect,
    tray: Rect,
    work: Rect,
    size: tuple[int, int],
    occupied: tuple[Rect, ...] = (),
    gap: int = 4,
) -> tuple[int, int]:
    """Fit left of the notification area and obstacles, or outside a crowded bar."""
    width, height = size
    horizontal = taskbar[2] - taskbar[0] >= taskbar[3] - taskbar[1]
    x = tray[0] - width - gap
    y = taskbar[1] + (taskbar[3] - taskbar[1] - height) // 2
    if horizontal and y >= taskbar[1] and y + height <= taskbar[3]:
        inside_x = x
        while inside_x >= taskbar[0]:
            candidate = (inside_x, y, inside_x + width, y + height)
            collisions = [rect for rect in occupied if intersects(candidate, rect)]
            if not collisions:
                return inside_x, y
            inside_x = min(rect[0] for rect in collisions) - width - max(0, gap)
    if horizontal:
        y = work[1] + gap if taskbar[1] <= work[1] else work[3] - height - gap
    else:
        x = work[0] + gap if taskbar[2] <= work[0] else work[2] - width - gap
        y = tray[1] - height - gap
    return (max(work[0], min(x, work[2] - width)), max(work[1], min(y, work[3] - height)))


class _MonitorInfo(C.Structure):
    _fields_ = [("size", W.DWORD), ("monitor", W.RECT), ("work", W.RECT), ("flags", W.DWORD)]


class _BitmapInfo(C.Structure):
    _fields_ = [
        ("size", W.DWORD),
        ("width", W.LONG),
        ("height", W.LONG),
        ("planes", W.WORD),
        ("bits", W.WORD),
        ("compression", W.DWORD),
        ("image_size", W.DWORD),
        ("x_ppm", W.LONG),
        ("y_ppm", W.LONG),
        ("colors", W.DWORD),
        ("important", W.DWORD),
    ]


class _Blend(C.Structure):
    _fields_ = [("op", W.BYTE), ("flags", W.BYTE), ("alpha", W.BYTE), ("format", W.BYTE)]


def _rect(rect: W.RECT) -> Rect:
    return rect.left, rect.top, rect.right, rect.bottom


@dataclass(frozen=True)
class TaskbarLayout:
    hwnd: int
    rect: Rect
    tray: Rect
    work: Rect
    monitor: Rect
    scale: float
    visible: bool


class TaskbarOverlay:
    # WinDLL inherits CDLL, whose type is available on every platform.
    user: C.CDLL
    gdi: C.CDLL
    dwm: C.CDLL

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise RuntimeError("Taskbar overlay requires Windows")
        self.user = C.WinDLL("user32", use_last_error=True)
        self.gdi = C.WinDLL("gdi32", use_last_error=True)
        self.dwm = C.WinDLL("dwmapi", use_last_error=True)
        ptr = C.c_void_p
        signatures = {
            "FindWindowW": ([W.LPCWSTR, W.LPCWSTR], ptr),
            "FindWindowExW": ([ptr, ptr, W.LPCWSTR, W.LPCWSTR], ptr),
            "GetWindowRect": ([ptr, C.POINTER(W.RECT)], W.BOOL),
            "GetDpiForWindow": ([ptr], W.UINT),
            "GetWindowLongPtrW": ([ptr, C.c_int], C.c_ssize_t),
            "SetWindowLongPtrW": ([ptr, C.c_int, C.c_ssize_t], C.c_ssize_t),
            "SetWindowPos": ([ptr, ptr, C.c_int, C.c_int, C.c_int, C.c_int, W.UINT], W.BOOL),
            "ShowWindow": ([ptr, C.c_int], W.BOOL),
            "IsWindowVisible": ([ptr], W.BOOL),
            "IsIconic": ([ptr], W.BOOL),
            "GetForegroundWindow": ([], ptr),
            "GetShellWindow": ([], ptr),
            "GetWindowThreadProcessId": ([ptr, C.POINTER(W.DWORD)], W.DWORD),
            "GetClassNameW": ([ptr, W.LPWSTR, C.c_int], C.c_int),
            "MonitorFromWindow": ([ptr, W.DWORD], ptr),
            "GetMonitorInfoW": ([ptr, C.POINTER(_MonitorInfo)], W.BOOL),
            "GetDC": ([ptr], ptr),
            "ReleaseDC": ([ptr, ptr], C.c_int),
            "UpdateLayeredWindow": (
                [
                    ptr,
                    ptr,
                    C.POINTER(W.POINT),
                    C.POINTER(W.SIZE),
                    ptr,
                    C.POINTER(W.POINT),
                    W.DWORD,
                    C.POINTER(_Blend),
                    W.DWORD,
                ],
                W.BOOL,
            ),
        }
        for name, (args, result) in signatures.items():
            self._bind(self.user, name, args, result)
        self._bind(self.dwm, "DwmGetWindowAttribute", [ptr, W.DWORD, ptr, W.DWORD], C.c_long)
        self._bind(self.gdi, "CreateCompatibleDC", [ptr], ptr)
        self._bind(self.gdi, "DeleteDC", [ptr], W.BOOL)
        self._bind(
            self.gdi,
            "CreateDIBSection",
            [ptr, C.POINTER(_BitmapInfo), W.UINT, C.POINTER(ptr), ptr, W.DWORD],
            ptr,
        )
        self._bind(self.gdi, "SelectObject", [ptr, ptr], ptr)
        self._bind(self.gdi, "DeleteObject", [ptr], W.BOOL)

    @staticmethod
    def _bind(library: Any, name: str, args: Any, result: Any) -> None:
        function = getattr(library, name)
        function.argtypes, function.restype = args, result

    def window_rect(self, hwnd: int) -> Rect | None:
        rect = W.RECT()
        return _rect(rect) if self.user.GetWindowRect(hwnd, C.byref(rect)) else None

    def widget_rects(self, taskbar: int) -> tuple[Rect, ...]:
        """Windows 10 News and interests is a window, not a UIA Button/ListItem."""
        rects: list[Rect] = []
        child = None
        while child := self.user.FindWindowExW(taskbar, child, None, None):
            name = C.create_unicode_buffer(128)
            self.user.GetClassNameW(child, name, len(name))
            if name.value.startswith("DynamicContent") and self.user.IsWindowVisible(child):
                rect = self.window_rect(child)
                if rect is not None and rect[0] < rect[2] and rect[1] < rect[3]:
                    rects.append(rect)
        return tuple(rects)

    def layout(self) -> TaskbarLayout | None:
        taskbar = self.user.FindWindowW("Shell_TrayWnd", None)
        rect = self.window_rect(taskbar) if taskbar else None
        if rect is None:
            return None
        info = _MonitorInfo(size=C.sizeof(_MonitorInfo))
        monitor = self.user.MonitorFromWindow(taskbar, 2)
        if not self.user.GetMonitorInfoW(monitor, C.byref(info)):
            return None
        tray = self.user.FindWindowExW(taskbar, None, "TrayNotifyWnd", None)
        scale = (self.user.GetDpiForWindow(taskbar) or 96) / 96
        tray_rect = self.window_rect(tray) if tray else None
        if tray_rect is None:
            tray_rect = (rect[2] - round(240 * scale), rect[1], rect[2], rect[3])
        # Auto-hidden taskbars expose only a narrow strip of their full rectangle.
        screen = _rect(info.monitor)
        visible_width = min(rect[2], screen[2]) - max(rect[0], screen[0])
        visible_height = min(rect[3], screen[3]) - max(rect[1], screen[1])
        visible = bool(self.user.IsWindowVisible(taskbar)) and (
            visible_width >= rect[2] - rect[0] - 2 and visible_height >= rect[3] - rect[1] - 2
        )
        return TaskbarLayout(taskbar, rect, tray_rect, _rect(info.work), screen, scale, visible)

    def fullscreen(self, taskbar: TaskbarLayout) -> bool:
        hwnd = self.user.GetForegroundWindow()
        if not hwnd or hwnd == self.user.GetShellWindow():
            return False
        if not self.user.IsWindowVisible(hwnd) or self.user.IsIconic(hwnd):
            return False
        pid = W.DWORD()
        self.user.GetWindowThreadProcessId(hwnd, C.byref(pid))
        if pid.value == os.getpid():
            return False
        name = C.create_unicode_buffer(128)
        self.user.GetClassNameW(hwnd, name, len(name))
        if name.value in ("Shell_TrayWnd", "Shell_SecondaryTrayWnd", "Progman", "WorkerW"):
            return False
        if self.user.MonitorFromWindow(hwnd, 2) != self.user.MonitorFromWindow(taskbar.hwnd, 2):
            return False
        bounds = W.RECT()
        if self.dwm.DwmGetWindowAttribute(hwnd, 9, C.byref(bounds), C.sizeof(bounds)) != 0:
            rect = self.window_rect(hwnd)
        else:
            rect = _rect(bounds)
        return rect is not None and covers_monitor(rect, taskbar.monitor)

    def configure(self, hwnd: int, owner: int) -> None:
        styles = self.user.GetWindowLongPtrW(hwnd, -20)
        # WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_LAYERED
        self.user.SetWindowLongPtrW(hwnd, -20, styles | 0x80 | 0x08000000 | 0x80000)
        if self.user.GetWindowLongPtrW(hwnd, -8) != owner:
            self.user.SetWindowLongPtrW(hwnd, -8, owner)

    def show(self, hwnd: int, position: tuple[int, int], size: tuple[int, int]) -> None:
        # HWND_TOPMOST, SWP_NOACTIVATE: clicking the label must not activate it.
        self.user.SetWindowPos(hwnd, -1, *position, *size, 0x10)
        if not self.user.IsWindowVisible(hwnd):
            self.user.ShowWindow(hwnd, 4)

    def hide(self, hwnd: int) -> None:
        if self.user.IsWindowVisible(hwnd):
            self.user.ShowWindow(hwnd, 0)

    def paint(self, hwnd: int, image: Image, position: tuple[int, int]) -> None:
        """Upload premultiplied pixels, preserving smooth text without a color-key halo."""
        # Pillow's RGBa mode premultiplies RGB channels by alpha, as Win32 requires.
        data = image.convert("RGBa").tobytes("raw", "BGRa")
        desktop = self.user.GetDC(None)
        dc = self.gdi.CreateCompatibleDC(desktop)
        bitmap = previous = None
        try:
            info = _BitmapInfo(
                size=C.sizeof(_BitmapInfo),
                width=image.width,
                height=-image.height,
                planes=1,
                bits=32,
            )
            pixels = C.c_void_p()
            bitmap = self.gdi.CreateDIBSection(dc, C.byref(info), 0, C.byref(pixels), None, 0)
            if not dc or not bitmap or not pixels:
                raise OSError("Cannot create taskbar label bitmap")
            C.memmove(pixels, data, len(data))
            previous = self.gdi.SelectObject(dc, bitmap)
            dest, size, source = W.POINT(*position), W.SIZE(*image.size), W.POINT(0, 0)
            blend = _Blend(0, 0, 255, 1)
            if not self.user.UpdateLayeredWindow(
                hwnd,
                desktop,
                C.byref(dest),
                C.byref(size),
                dc,
                C.byref(source),
                0,
                C.byref(blend),
                2,
            ):
                raise OSError("Cannot paint taskbar label")
        finally:
            if previous:
                self.gdi.SelectObject(dc, previous)
            if bitmap:
                self.gdi.DeleteObject(bitmap)
            if dc:
                self.gdi.DeleteDC(dc)
            self.user.ReleaseDC(None, desktop)

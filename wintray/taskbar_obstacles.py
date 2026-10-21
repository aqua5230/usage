# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>

"""Read taskbar button bounds off the UI thread to avoid covering applications."""

from __future__ import annotations

import ctypes as C
import importlib
import logging
import threading
from functools import cache
from pathlib import Path

from wintray.taskbar_overlay import Rect

logger = logging.getLogger(__name__)


class _WTSINFOEX_LEVEL1_W(C.Structure):
    # Windows WCHAR and LONG stay 16/32 bits even on hosts with wider C types.
    _fields_ = [
        ("SessionId", C.c_uint32),
        ("SessionState", C.c_int32),
        ("SessionFlags", C.c_int32),
        ("WinStationName", C.c_uint16 * 33),
        ("UserName", C.c_uint16 * 21),
        ("DomainName", C.c_uint16 * 18),
        ("LogonTime", C.c_int64),
        ("ConnectTime", C.c_int64),
        ("DisconnectTime", C.c_int64),
        ("LastInputTime", C.c_int64),
        ("CurrentTime", C.c_int64),
        ("IncomingBytes", C.c_uint32),
        ("OutgoingBytes", C.c_uint32),
        ("IncomingFrames", C.c_uint32),
        ("OutgoingFrames", C.c_uint32),
        ("IncomingCompressedBytes", C.c_uint32),
        ("OutgoingCompressedBytes", C.c_uint32),
    ]


class _WTSINFOEX_LEVEL_W(C.Union):
    _fields_ = [("WTSInfoExLevel1", _WTSINFOEX_LEVEL1_W)]


class _WTSINFOEXW(C.Structure):
    _fields_ = [("Level", C.c_uint32), ("Data", _WTSINFOEX_LEVEL_W)]


@cache
def _wts_api() -> C.CDLL:
    # WinDLL is absent from ctypes and its stubs on non-Windows hosts.
    loader = getattr(C, "WinDLL")  # noqa: B009
    wts: C.CDLL = loader("wtsapi32", use_last_error=True)
    wts.WTSQuerySessionInformationW.argtypes = [
        C.c_void_p,
        C.c_uint32,
        C.c_int,
        C.POINTER(C.c_void_p),
        C.POINTER(C.c_uint32),
    ]
    wts.WTSQuerySessionInformationW.restype = C.c_int
    wts.WTSFreeMemory.argtypes = [C.c_void_p]
    wts.WTSFreeMemory.restype = None
    return wts


def _session_locked() -> bool:
    try:
        wts = _wts_api()
        buffer = C.c_void_p()
        size = C.c_uint32()
        try:
            if not wts.WTSQuerySessionInformationW(
                None, 0xFFFFFFFF, 25, C.byref(buffer), C.byref(size)
            ):
                return False
            if not buffer or size.value < C.sizeof(_WTSINFOEXW):
                return False
            info = C.cast(buffer, C.POINTER(_WTSINFOEXW)).contents
            return bool(info.Level == 1 and info.Data.WTSInfoExLevel1.SessionFlags == 0)
        finally:
            if buffer:
                wts.WTSFreeMemory(buffer)
    except (OSError, AttributeError):
        return False


class TaskbarObstacles:
    def __init__(self) -> None:
        self.hwnd = 0
        self.snapshot: tuple[int, tuple[Rect, ...]] = (0, ())
        self._stop = threading.Event()
        threading.Thread(target=self._watch, name="usage-taskbar-layout", daemon=True).start()

    def _watch(self) -> None:
        try:
            clr = importlib.import_module("clr")
            runtime = importlib.import_module("System.Runtime.InteropServices")
            framework = Path(runtime.RuntimeEnvironment.GetRuntimeDirectory())
            for assembly in ("UIAutomationTypes", "UIAutomationClient"):
                clr.AddReference(str(framework / "WPF" / (assembly + ".dll")))
            automation = importlib.import_module("System.Windows.Automation")
            system = importlib.import_module("System")
            element = automation.AutomationElement
            condition = automation.OrCondition(
                automation.PropertyCondition(
                    element.ControlTypeProperty, automation.ControlType.Button
                ),
                automation.PropertyCondition(
                    element.ControlTypeProperty, automation.ControlType.ListItem
                ),
            )
            while not self._stop.is_set():
                hwnd = self.hwnd
                if hwnd and not _session_locked():
                    try:
                        root = element.FromHandle(system.IntPtr(hwnd))
                        buttons = root.FindAll(automation.TreeScope.Descendants, condition)
                        rects: list[Rect] = []
                        for button in buttons:
                            current = button.Current
                            bounds = current.BoundingRectangle
                            if not current.IsOffscreen and not bounds.IsEmpty:
                                rects.append(
                                    (
                                        round(bounds.Left),
                                        round(bounds.Top),
                                        round(bounds.Right),
                                        round(bounds.Bottom),
                                    )
                                )
                        self.snapshot = (hwnd, tuple(rects))
                    except Exception:
                        # Explorer may be rebuilding its accessibility tree.
                        self.snapshot = (0, ())
                self._stop.wait(2)
        except Exception:
            logger.warning("Taskbar button bounds unavailable", exc_info=True)

    def close(self) -> None:
        self._stop.set()

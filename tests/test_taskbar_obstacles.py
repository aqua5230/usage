# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>

from __future__ import annotations

import ctypes as C
import importlib
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from wintray import taskbar_obstacles as obstacles


@pytest.fixture(autouse=True)
def clear_wts_api_cache() -> Iterator[None]:
    obstacles._wts_api.cache_clear()
    yield
    obstacles._wts_api.cache_clear()


def test_session_flags_offset() -> None:
    assert (
        obstacles._WTSINFOEXW.Data.offset + obstacles._WTSINFOEX_LEVEL1_W.SessionFlags.offset == 16
    )
    assert C.sizeof(obstacles._WTSINFOEXW) == 232


@pytest.mark.parametrize("flags, locked", [(0, True), (1, False), (-1, False)])
def test_session_locked_reads_buffer(
    monkeypatch: pytest.MonkeyPatch, flags: int, locked: bool
) -> None:
    info = obstacles._WTSINFOEXW(Level=1)
    info.Data.WTSInfoExLevel1.SessionFlags = flags

    def query(server: object, session: int, kind: int, buffer: Any, size: Any) -> int:
        assert (server, session, kind) == (None, 0xFFFFFFFF, 25)
        C.cast(buffer, C.POINTER(C.c_void_p))[0] = C.addressof(info)
        C.cast(size, C.POINTER(C.c_uint32))[0] = C.sizeof(info)
        return 1

    wts = SimpleNamespace(WTSQuerySessionInformationW=Mock(side_effect=query), WTSFreeMemory=Mock())
    load = Mock(return_value=wts)
    monkeypatch.setattr(C, "WinDLL", load, raising=False)

    assert obstacles._session_locked() is locked
    load.assert_called_once_with("wtsapi32", use_last_error=True)
    assert wts.WTSQuerySessionInformationW.restype is C.c_int
    assert len(wts.WTSQuerySessionInformationW.argtypes) == 5
    wts.WTSFreeMemory.assert_called_once()
    assert wts.WTSFreeMemory.call_args.args[0].value == C.addressof(info)


def test_session_locked_api_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    wts = SimpleNamespace(WTSQuerySessionInformationW=Mock(return_value=0), WTSFreeMemory=Mock())
    monkeypatch.setattr(C, "WinDLL", Mock(return_value=wts), raising=False)
    assert obstacles._session_locked() is False
    wts.WTSFreeMemory.assert_not_called()


@pytest.mark.parametrize("error", [OSError("unavailable"), AttributeError("WinDLL")])
def test_session_locked_unavailable(monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    monkeypatch.setattr(C, "WinDLL", Mock(side_effect=error), raising=False)
    assert obstacles._session_locked() is False


def test_watch_preserves_snapshot_while_locked_then_refreshes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bounds = SimpleNamespace(Left=1.2, Top=2.3, Right=30.4, Bottom=40.5, IsEmpty=False)
    button = SimpleNamespace(Current=SimpleNamespace(BoundingRectangle=bounds, IsOffscreen=False))
    find_all = Mock(return_value=[button])
    element = SimpleNamespace(
        ControlTypeProperty="control",
        FromHandle=Mock(return_value=SimpleNamespace(FindAll=find_all)),
    )
    modules = {
        "clr": SimpleNamespace(AddReference=Mock()),
        "System.Runtime.InteropServices": SimpleNamespace(
            RuntimeEnvironment=SimpleNamespace(GetRuntimeDirectory=lambda: "/framework")
        ),
        "System.Windows.Automation": SimpleNamespace(
            AutomationElement=element,
            OrCondition=Mock(),
            PropertyCondition=Mock(),
            ControlType=SimpleNamespace(Button="button", ListItem="item"),
            TreeScope=SimpleNamespace(Descendants="descendants"),
        ),
        "System": SimpleNamespace(IntPtr=lambda hwnd: hwnd),
    }
    monkeypatch.setattr(importlib, "import_module", lambda name: modules[name])
    monkeypatch.setattr(obstacles, "_session_locked", Mock(side_effect=[True, False]))
    worker = obstacles.TaskbarObstacles.__new__(obstacles.TaskbarObstacles)
    worker.hwnd = 123
    worker.snapshot = (123, ((5, 6, 7, 8),))
    stop = Mock()
    stop.is_set.side_effect = [False, False, True]
    worker._stop = stop

    def wait(seconds: int) -> None:
        assert seconds == 2
        if stop.wait.call_count == 1:
            find_all.assert_not_called()
            element.FromHandle.assert_not_called()
            assert worker.snapshot == (123, ((5, 6, 7, 8),))
        else:
            find_all.assert_called_once_with(
                "descendants", modules["System.Windows.Automation"].OrCondition.return_value
            )
            assert worker.snapshot == (123, ((1, 2, 30, 40),))

    stop.wait.side_effect = wait
    worker._watch()
    assert stop.wait.call_count == 2
    assert worker.snapshot == (123, ((1, 2, 30, 40),))

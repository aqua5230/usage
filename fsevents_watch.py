# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import contextlib
import ctypes
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# --- FSEvents (ctypes) for event-driven UI refresh ---
_FSEVENTS_AVAILABLE = False
_fs_callback_ref: Any = None  # prevent GC of ctypes callback

try:
    _cs_lib = ctypes.cdll.LoadLibrary(
        "/System/Library/Frameworks/CoreServices.framework/CoreServices",
    )
    _cf_lib = ctypes.cdll.LoadLibrary(
        "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation",
    )
    _FSEventStreamCallback = ctypes.CFUNCTYPE(
        None,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(ctypes.c_uint64),
    )
    _cs_lib.FSEventStreamCreate.restype = ctypes.c_void_p
    _cs_lib.FSEventStreamCreate.argtypes = [
        ctypes.c_void_p,
        _FSEventStreamCallback,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint64,
        ctypes.c_double,
        ctypes.c_uint32,
    ]
    _cs_lib.FSEventStreamScheduleWithRunLoop.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    _cs_lib.FSEventStreamStart.restype = ctypes.c_int
    _cs_lib.FSEventStreamStart.argtypes = [ctypes.c_void_p]
    _cs_lib.FSEventStreamStop.argtypes = [ctypes.c_void_p]
    _cs_lib.FSEventStreamInvalidate.argtypes = [ctypes.c_void_p]
    _cs_lib.FSEventStreamRelease.argtypes = [ctypes.c_void_p]
    _cf_lib.CFRunLoopGetCurrent.restype = ctypes.c_void_p
    _cf_lib.CFArrayCreate.restype = ctypes.c_void_p
    _cf_lib.CFArrayCreate.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_long,
        ctypes.c_void_p,
    ]
    _cf_lib.CFStringCreateWithCString.restype = ctypes.c_void_p
    _cf_lib.CFStringCreateWithCString.argtypes = [
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.c_uint32,
    ]
    _kCFStringEncodingUTF8 = 0x08000100
    _kFSEventStreamCreateFlagNoDefer = 0x00000002
    _kFSEventStreamEventIdSinceNow = 0xFFFFFFFFFFFFFFFF
    _FSEVENTS_AVAILABLE = True
except (OSError, AttributeError):
    pass


def usage_watch_paths() -> list[Path]:
    """Return existing agent directories that contain usage history records."""
    home = Path.home()
    return [
        path
        for path in (
            home / ".claude" / "projects",
            home / ".codex" / "sessions",
            home / ".codex" / "archived_sessions",
        )
        if path.exists()
    ]


def setup_fsevents(delegate: Any) -> Any:
    """Start FSEventStream watching agent usage directories; returns a handle or None."""
    global _fs_callback_ref
    if not _FSEVENTS_AVAILABLE:
        return None
    try:
        watch_paths = usage_watch_paths()
        if not watch_paths:
            return None
        cf_path_values = [
            _cf_lib.CFStringCreateWithCString(
                None,
                str(path).encode("utf-8"),
                _kCFStringEncodingUTF8,
            )
            for path in watch_paths
        ]
        paths_arr = (ctypes.c_void_p * len(cf_path_values))(*cf_path_values)
        cf_paths = _cf_lib.CFArrayCreate(None, paths_arr, len(cf_path_values), None)

        def _on_fs_event(
            _stream: Any,
            _info: Any,
            _num: Any,
            _paths: Any,
            _flags: Any,
            _ids: Any,
        ) -> None:
            delegate.performSelectorOnMainThread_withObject_waitUntilDone_(
                "refreshFromFileEvent:",
                None,
                False,
            )

        _fs_callback_ref = _FSEventStreamCallback(_on_fs_event)
        stream = _cs_lib.FSEventStreamCreate(
            None,
            _fs_callback_ref,
            None,
            cf_paths,
            _kFSEventStreamEventIdSinceNow,
            0.5,
            _kFSEventStreamCreateFlagNoDefer,
        )
        if not stream:
            return None
        rl = _cf_lib.CFRunLoopGetCurrent()
        mode = _cf_lib.CFStringCreateWithCString(
            None,
            b"kCFRunLoopDefaultMode",
            _kCFStringEncodingUTF8,
        )
        _cs_lib.FSEventStreamScheduleWithRunLoop(stream, rl, mode)
        _cs_lib.FSEventStreamStart(stream)
        return stream
    except Exception:
        if os.environ.get("USAGE_DEBUG") == "1":
            logger.warning("FSEvents setup failed", exc_info=True)
        return None


def cleanup_fsevents(stream: Any) -> None:
    """Stop and release an FSEventStream."""
    if not _FSEVENTS_AVAILABLE or not stream:
        return
    with contextlib.suppress(Exception):
        _cs_lib.FSEventStreamStop(stream)
        _cs_lib.FSEventStreamInvalidate(stream)
        _cs_lib.FSEventStreamRelease(stream)

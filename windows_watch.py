# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Native Windows file notifications for tray usage refreshes."""

from __future__ import annotations

import ctypes
import logging
import os
import struct
import sys
import threading
import time
from collections.abc import Callable
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import codex_loader
import history_loader
from adapters import rate_limits

logger = logging.getLogger(__name__)

# Values verified against the Windows SDK documentation for CreateFileW,
# ReadDirectoryChangesW, WaitForMultipleObjects, and GetOverlappedResult.
_FILE_LIST_DIRECTORY = 0x0001
_FILE_SHARE_READ = 0x00000001
_FILE_SHARE_WRITE = 0x00000002
_FILE_SHARE_DELETE = 0x00000004
_OPEN_EXISTING = 3
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_FILE_FLAG_OVERLAPPED = 0x40000000
_FILE_NOTIFY_CHANGE_FILE_NAME = 0x00000001
_FILE_NOTIFY_CHANGE_DIR_NAME = 0x00000002
_FILE_NOTIFY_CHANGE_SIZE = 0x00000008
_FILE_NOTIFY_CHANGE_LAST_WRITE = 0x00000010
_FILE_NOTIFY_CHANGE_CREATION = 0x00000040
_NOTIFY_FILTER = (
    _FILE_NOTIFY_CHANGE_FILE_NAME
    | _FILE_NOTIFY_CHANGE_DIR_NAME
    | _FILE_NOTIFY_CHANGE_SIZE
    | _FILE_NOTIFY_CHANGE_LAST_WRITE
    | _FILE_NOTIFY_CHANGE_CREATION
)
_ERROR_OPERATION_ABORTED = 995
_ERROR_IO_PENDING = 997
_ERROR_NOTIFY_ENUM_DIR = 1022
_WAIT_OBJECT_0 = 0
_WAIT_FAILED = 0xFFFFFFFF
_INFINITE = 0xFFFFFFFF
_WATCH_BUFFER_BYTES = 64 * 1024

_FILE_ACTION_ADDED = 1
_FILE_ACTION_REMOVED = 2
_FILE_ACTION_MODIFIED = 3
_FILE_ACTION_RENAMED_OLD_NAME = 4
_FILE_ACTION_RENAMED_NEW_NAME = 5
_REMOVAL_ACTIONS = frozenset({_FILE_ACTION_REMOVED, _FILE_ACTION_RENAMED_OLD_NAME})


class _Overlapped(ctypes.Structure):
    _fields_ = [
        ("Internal", ctypes.c_size_t),
        ("InternalHigh", ctypes.c_size_t),
        ("Offset", wintypes.DWORD),
        ("OffsetHigh", wintypes.DWORD),
        ("hEvent", wintypes.HANDLE),
    ]


_kernel32: Any = None
if sys.platform == "win32":
    try:
        _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        _kernel32.CreateFileW.restype = wintypes.HANDLE
        _kernel32.CreateFileW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        _kernel32.ReadDirectoryChangesW.restype = wintypes.BOOL
        _kernel32.ReadDirectoryChangesW.argtypes = [
            wintypes.HANDLE,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
            wintypes.LPVOID,
            ctypes.POINTER(_Overlapped),
            wintypes.LPVOID,
        ]
        _kernel32.CreateEventW.restype = wintypes.HANDLE
        _kernel32.CreateEventW.argtypes = [
            wintypes.LPVOID,
            wintypes.BOOL,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        ]
        _kernel32.SetEvent.restype = wintypes.BOOL
        _kernel32.SetEvent.argtypes = [wintypes.HANDLE]
        _kernel32.ResetEvent.restype = wintypes.BOOL
        _kernel32.ResetEvent.argtypes = [wintypes.HANDLE]
        _kernel32.WaitForMultipleObjects.restype = wintypes.DWORD
        _kernel32.WaitForMultipleObjects.argtypes = [
            wintypes.DWORD,
            ctypes.POINTER(wintypes.HANDLE),
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        _kernel32.GetOverlappedResult.restype = wintypes.BOOL
        _kernel32.GetOverlappedResult.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(_Overlapped),
            ctypes.POINTER(wintypes.DWORD),
            wintypes.BOOL,
        ]
        _kernel32.CancelIoEx.restype = wintypes.BOOL
        _kernel32.CancelIoEx.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(_Overlapped),
        ]
        _kernel32.CloseHandle.restype = wintypes.BOOL
        _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    except (AttributeError, OSError):
        _kernel32 = None

_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


@dataclass(frozen=True, slots=True)
class WindowsFileEventChanges:
    paths: frozenset[Path]
    needs_full_scan: bool = False


@dataclass(frozen=True, slots=True)
class WindowsWatchSpec:
    root: Path
    recursive: bool
    filenames: frozenset[str] = frozenset()
    history_jsonl: bool = False

    def classify(self, path: Path, action: int) -> WindowsFileEventChanges:
        if self.filenames:
            if path.name.casefold() in self.filenames:
                return WindowsFileEventChanges(frozenset({path}))
            return WindowsFileEventChanges(frozenset())

        if self.history_jsonl and path.suffix.casefold() == ".jsonl":
            return WindowsFileEventChanges(frozenset({path}))
        if self.history_jsonl:
            # FILE_NOTIFY_INFORMATION does not carry a file-vs-directory bit.
            # Existing directories and removed/old-name entries may represent
            # a whole subtree, so match FSEvents by requesting a full scan.
            try:
                is_directory = path.is_dir()
            except OSError:
                is_directory = False
            if is_directory or action in _REMOVAL_ACTIONS:
                return WindowsFileEventChanges(frozenset(), needs_full_scan=True)
        return WindowsFileEventChanges(frozenset())


def usage_watch_specs() -> list[WindowsWatchSpec]:
    """Return only the existing directories that contain tray usage sources."""
    status_paths = tuple(
        Path(path)
        for path in (
            rate_limits.STATUS_FILE,
            rate_limits.LEGACY_STATUS_FILE,
            rate_limits.TT_STATUS_FILE,
        )
    )
    specs: list[WindowsWatchSpec] = []
    status_root = status_paths[0].parent
    if status_root.is_dir():
        specs.append(
            WindowsWatchSpec(
                status_root,
                recursive=False,
                filenames=frozenset(path.name.casefold() for path in status_paths),
            )
        )

    for root in (
        history_loader.CLAUDE_PROJECTS_DIR,
        codex_loader.SESSIONS_DIR,
        codex_loader.ARCHIVED_SESSIONS_DIR,
    ):
        if root.is_dir():
            specs.append(WindowsWatchSpec(root, recursive=True, history_jsonl=True))
    return specs


def _parse_notifications(
    spec: WindowsWatchSpec,
    buffer: ctypes.Array[ctypes.c_char],
    byte_count: int,
) -> WindowsFileEventChanges:
    if byte_count == 0:
        return WindowsFileEventChanges(frozenset(), needs_full_scan=True)

    dirty_paths: set[Path] = set()
    needs_full_scan = False
    offset = 0
    while True:
        if byte_count - offset < 12:
            return WindowsFileEventChanges(frozenset(), needs_full_scan=True)
        next_offset, action, name_bytes = struct.unpack_from("<III", buffer, offset)
        name_start = offset + 12
        name_end = name_start + name_bytes
        if name_bytes % 2 or name_end > byte_count:
            return WindowsFileEventChanges(frozenset(), needs_full_scan=True)
        try:
            relative_name = buffer.raw[name_start:name_end].decode("utf-16-le")
        except UnicodeDecodeError:
            return WindowsFileEventChanges(frozenset(), needs_full_scan=True)
        classified = spec.classify(spec.root / Path(relative_name), action)
        dirty_paths.update(classified.paths)
        needs_full_scan = needs_full_scan or classified.needs_full_scan

        if next_offset == 0:
            break
        if next_offset < 12 or offset + next_offset >= byte_count:
            return WindowsFileEventChanges(frozenset(), needs_full_scan=True)
        offset += next_offset
    return WindowsFileEventChanges(frozenset(dirty_paths), needs_full_scan)


@dataclass(slots=True)
class _WatchRuntime:
    spec: WindowsWatchSpec
    directory_handle: Any
    io_event: Any
    ready: threading.Event
    thread: threading.Thread | None = None


class WindowsUsageWatcher:
    """Own ReadDirectoryChangesW workers and stop them without blocking the tray."""

    def __init__(
        self,
        specs: list[WindowsWatchSpec],
        callback: Callable[[WindowsFileEventChanges], None],
    ) -> None:
        self._specs = specs
        self._callback = callback
        self._stop_handle: Any = None
        self._runtimes: list[_WatchRuntime] = []
        self._stop_lock = threading.Lock()
        self._stopped = False

    def start(self) -> bool:
        if _kernel32 is None or not self._specs:
            return False
        self._stop_handle = _kernel32.CreateEventW(None, True, False, None)
        if not self._stop_handle:
            return False

        for spec in self._specs:
            directory_handle = _kernel32.CreateFileW(
                str(spec.root),
                _FILE_LIST_DIRECTORY,
                _FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE,
                None,
                _OPEN_EXISTING,
                _FILE_FLAG_BACKUP_SEMANTICS | _FILE_FLAG_OVERLAPPED,
                None,
            )
            if directory_handle in (None, _INVALID_HANDLE_VALUE):
                self._debug_warning("Could not open Windows usage watch path %s", spec.root)
                continue
            io_event = _kernel32.CreateEventW(None, True, False, None)
            if not io_event:
                _kernel32.CloseHandle(directory_handle)
                continue
            runtime = _WatchRuntime(spec, directory_handle, io_event, threading.Event())
            runtime.thread = threading.Thread(
                target=self._watch_directory,
                args=(runtime,),
                name=f"usage-watch-{spec.root.name}",
                daemon=True,
            )
            self._runtimes.append(runtime)
            runtime.thread.start()

        for runtime in self._runtimes:
            runtime.ready.wait(2.0)
        if any(
            runtime.thread is not None and runtime.thread.is_alive()
            for runtime in self._runtimes
        ):
            return True
        self.stop()
        return False

    def stop(self, timeout: float = 3.0) -> None:
        with self._stop_lock:
            if self._stopped:
                return
            self._stopped = True
            stop_handle = self._stop_handle
            if stop_handle:
                _kernel32.SetEvent(stop_handle)

        deadline = time.monotonic() + timeout
        current = threading.current_thread()
        for runtime in self._runtimes:
            thread = runtime.thread
            if thread is not None and thread is not current:
                thread.join(max(0.0, deadline - time.monotonic()))

        if any(
            runtime.thread is not None and runtime.thread.is_alive()
            for runtime in self._runtimes
        ):
            self._debug_warning("Windows usage watcher did not stop cleanly")
            return
        if stop_handle:
            _kernel32.CloseHandle(stop_handle)
            self._stop_handle = None

    def _watch_directory(self, runtime: _WatchRuntime) -> None:
        buffer = ctypes.create_string_buffer(_WATCH_BUFFER_BYTES)
        overlapped = _Overlapped()
        overlapped.hEvent = runtime.io_event
        wait_handles = (wintypes.HANDLE * 2)(self._stop_handle, runtime.io_event)
        try:
            while True:
                _kernel32.ResetEvent(runtime.io_event)
                ctypes.set_last_error(0)
                submitted = _kernel32.ReadDirectoryChangesW(
                    runtime.directory_handle,
                    buffer,
                    len(buffer),
                    runtime.spec.recursive,
                    _NOTIFY_FILTER,
                    None,
                    ctypes.byref(overlapped),
                    None,
                )
                error = ctypes.get_last_error()
                if not submitted and error != _ERROR_IO_PENDING:
                    runtime.ready.set()
                    if error == _ERROR_NOTIFY_ENUM_DIR:
                        self._dispatch(WindowsFileEventChanges(frozenset(), True))
                    else:
                        self._debug_warning(
                            "ReadDirectoryChangesW failed for %s (error %s)",
                            runtime.spec.root,
                            error,
                        )
                    return
                runtime.ready.set()

                wait_result = _kernel32.WaitForMultipleObjects(
                    2,
                    wait_handles,
                    False,
                    _INFINITE,
                )
                if wait_result == _WAIT_OBJECT_0:
                    _kernel32.CancelIoEx(runtime.directory_handle, ctypes.byref(overlapped))
                    transferred = wintypes.DWORD()
                    _kernel32.GetOverlappedResult(
                        runtime.directory_handle,
                        ctypes.byref(overlapped),
                        ctypes.byref(transferred),
                        True,
                    )
                    return
                if wait_result != _WAIT_OBJECT_0 + 1:
                    if wait_result == _WAIT_FAILED:
                        self._debug_warning(
                            "WaitForMultipleObjects failed for %s (error %s)",
                            runtime.spec.root,
                            ctypes.get_last_error(),
                        )
                    return

                transferred = wintypes.DWORD()
                ctypes.set_last_error(0)
                completed = _kernel32.GetOverlappedResult(
                    runtime.directory_handle,
                    ctypes.byref(overlapped),
                    ctypes.byref(transferred),
                    False,
                )
                if not completed:
                    error = ctypes.get_last_error()
                    if error == _ERROR_OPERATION_ABORTED and self._stopped:
                        return
                    self._dispatch(WindowsFileEventChanges(frozenset(), True))
                    continue
                changes = _parse_notifications(runtime.spec, buffer, transferred.value)
                if changes.paths or changes.needs_full_scan:
                    self._dispatch(changes)
        finally:
            runtime.ready.set()
            _kernel32.CloseHandle(runtime.io_event)
            _kernel32.CloseHandle(runtime.directory_handle)

    def _dispatch(self, changes: WindowsFileEventChanges) -> None:
        if self._stopped:
            return
        try:
            self._callback(changes)
        except Exception:
            self._debug_warning("Windows usage watcher callback failed", exc_info=True)

    @staticmethod
    def _debug_warning(
        message: str,
        *args: object,
        exc_info: bool = False,
    ) -> None:
        if os.environ.get("USAGE_DEBUG") == "1":
            logger.warning(message, *args, exc_info=exc_info)


def setup_windows_watcher(
    callback: Callable[[WindowsFileEventChanges], None],
    *,
    specs: list[WindowsWatchSpec] | None = None,
) -> WindowsUsageWatcher | None:
    """Start native usage-source watchers, returning None when unavailable."""
    watcher = WindowsUsageWatcher(usage_watch_specs() if specs is None else specs, callback)
    return watcher if watcher.start() else None

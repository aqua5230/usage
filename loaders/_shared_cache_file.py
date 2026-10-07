# SPDX-License-Identifier: AGPL-3.0-only

"""Read a cache file while Chromium holds it open, without changing the file."""

from __future__ import annotations

import ctypes as C
import sys
from ctypes import wintypes as W
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def _kernel() -> C.CDLL:
    if sys.platform != "win32":
        raise OSError("Windows shared cache reader is unavailable")
    kernel = C.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [
        W.LPCWSTR,
        W.DWORD,
        W.DWORD,
        C.c_void_p,
        W.DWORD,
        W.DWORD,
        C.c_void_p,
    ]
    kernel.CreateFileW.restype = W.HANDLE
    kernel.SetFilePointerEx.argtypes = [W.HANDLE, C.c_longlong, C.c_void_p, W.DWORD]
    kernel.SetFilePointerEx.restype = W.BOOL
    kernel.ReadFile.argtypes = [W.HANDLE, C.c_void_p, W.DWORD, C.POINTER(W.DWORD), C.c_void_p]
    kernel.ReadFile.restype = W.BOOL
    kernel.CloseHandle.argtypes = [W.HANDLE]
    kernel.CloseHandle.restype = W.BOOL
    return kernel


def read_range(path: Path, offset: int, length: int) -> bytes:
    if offset < 0 or length < 0 or length > 16 * 1024 * 1024:
        raise ValueError("Invalid cache read bounds")
    if sys.platform != "win32":
        with path.open("rb") as file:
            file.seek(offset)
            return file.read(length)
    kernel = _kernel()
    # GENERIC_READ, FILE_SHARE_READ | WRITE | DELETE, OPEN_EXISTING. Chromium
    # requests delete access; ordinary CRT opens do not always share that access.
    handle = kernel.CreateFileW(str(path), 0x80000000, 7, None, 3, 0, None)
    if handle == C.c_void_p(-1).value:
        raise OSError("Cannot open the cache file for reading")
    try:
        if not kernel.SetFilePointerEx(handle, offset, None, 0):
            raise OSError("Cannot seek in the cache file")
        buffer = C.create_string_buffer(length)
        count = W.DWORD()
        if not kernel.ReadFile(handle, buffer, length, C.byref(count), None):
            raise OSError("Cannot read the cache file")
        return buffer.raw[: count.value]
    finally:
        kernel.CloseHandle(handle)


def read_bounded(path: Path, limit: int) -> bytes:
    size = path.stat().st_size
    if size > limit:
        raise ValueError("Cache file exceeds the size limit")
    return read_range(path, 0, size)

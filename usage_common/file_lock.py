# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Cross-process exclusive file locking for POSIX and Windows."""

from __future__ import annotations

import errno
import os
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any

_fcntl: Any = None
_msvcrt: Any = None
if sys.platform == "win32":
    try:
        import msvcrt as _win_msvcrt
    except ImportError:
        pass
    else:
        _msvcrt = _win_msvcrt
else:
    try:
        import fcntl as _posix_fcntl
    except ImportError:
        pass
    else:
        _fcntl = _posix_fcntl

fcntl = _fcntl
msvcrt = _msvcrt

_LOCK_TIMEOUT_S = 10.0
_LOCK_POLL_INTERVAL_S = 0.001
_POSIX_CONTENDED_ERRNOS = frozenset((errno.EACCES, errno.EAGAIN))
_MSVCRT_CONTENDED_ERRNOS = frozenset(
    (errno.EACCES, getattr(errno, "EDEADLOCK", errno.EDEADLK), errno.EDEADLK)
)


def _acquire_posix_lock(lock_fd: int, timeout_s: float) -> bool:
    """Poll non-blocking flock until acquired, unsupported, or deadline."""
    if fcntl is None:
        return False
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError as exc:
            if exc.errno not in _POSIX_CONTENDED_ERRNOS:
                return False
            if time.monotonic() >= deadline:
                return False
            time.sleep(_LOCK_POLL_INTERVAL_S)


def _acquire_msvcrt_lock(lock_fd: int, timeout_s: float) -> bool:
    """Poll non-blocking 1-byte msvcrt lock until acquired, unsupported, or deadline."""
    if msvcrt is None:
        return False
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            if os.fstat(lock_fd).st_size == 0:
                os.write(lock_fd, b"\0")
            os.lseek(lock_fd, 0, os.SEEK_SET)
            msvcrt.locking(lock_fd, msvcrt.LK_NBLCK, 1)
            return True
        except OSError as exc:
            if exc.errno not in _MSVCRT_CONTENDED_ERRNOS:
                return False
            if time.monotonic() >= deadline:
                return False
            time.sleep(_LOCK_POLL_INTERVAL_S)


@contextmanager
def exclusive_file_lock(
    lock_path: Path,
    timeout_s: float = _LOCK_TIMEOUT_S,
) -> Iterator[None]:
    """Acquire an exclusive cross-process lock on ``lock_path``.

    Falls back to yielding without a lock if native locking is unavailable or
    unsupported on the filesystem, preserving atomic file-replacement behavior.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    locked_posix = False
    locked_msvcrt = False
    try:
        if fcntl is not None:
            locked_posix = _acquire_posix_lock(lock_fd, timeout_s)
        elif msvcrt is not None:
            locked_msvcrt = _acquire_msvcrt_lock(lock_fd, timeout_s)
        yield
    finally:
        if locked_posix and fcntl is not None:
            with suppress(OSError):
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
        elif locked_msvcrt and msvcrt is not None:
            with suppress(OSError):
                os.lseek(lock_fd, 0, os.SEEK_SET)
                msvcrt.locking(lock_fd, msvcrt.LK_UNLCK, 1)
        os.close(lock_fd)

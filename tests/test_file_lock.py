# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import errno
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

from usage_common import file_lock


def test_exclusive_file_lock_creates_parent_dir_and_lock_file(tmp_path: Path) -> None:
    lock_path = tmp_path / "nested" / "year_ledger.json.lock"
    with file_lock.exclusive_file_lock(lock_path):
        assert lock_path.exists()


def test_exclusive_file_lock_works_without_fcntl_or_msvcrt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(file_lock, "fcntl", None)
    monkeypatch.setattr(file_lock, "msvcrt", None)
    lock_path = tmp_path / "year_ledger.json.lock"

    entered = False
    with file_lock.exclusive_file_lock(lock_path):
        entered = True

    assert entered is True
    assert lock_path.exists()


@pytest.mark.skipif(file_lock.fcntl is None, reason="requires POSIX fcntl")
def test_exclusive_file_lock_times_out_when_another_process_holds_it(tmp_path: Path) -> None:
    lock_path = tmp_path / "year_ledger.json.lock"
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import fcntl, os, sys\n"
            "fd = os.open(sys.argv[1], os.O_CREAT | os.O_RDWR, 0o600)\n"
            "fcntl.flock(fd, fcntl.LOCK_EX)\n"
            "print('locked', flush=True)\n"
            "sys.stdin.read()\n",
            str(lock_path),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )
    assert holder.stdin is not None and holder.stdout is not None
    try:
        assert holder.stdout.readline() == b"locked\n"
        started = time.monotonic()
        with pytest.raises(TimeoutError), file_lock.exclusive_file_lock(lock_path, timeout_s=0.02):
            pytest.fail("entered the context while another process held the lock")
        elapsed = time.monotonic() - started
        assert 0.015 <= elapsed < 0.5
    finally:
        holder.stdin.close()
        holder.wait(timeout=5)
        holder.stdout.close()


@pytest.mark.skipif(file_lock.fcntl is None, reason="requires POSIX fcntl")
def test_exclusive_file_lock_waits_for_holder_to_release(tmp_path: Path) -> None:
    lock_path = tmp_path / "year_ledger.json.lock"
    target = tmp_path / "counter.txt"
    target.write_text("0", encoding="utf-8")
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import fcntl, os, pathlib, sys, time\n"
            "fd = os.open(sys.argv[1], os.O_CREAT | os.O_RDWR, 0o600)\n"
            "fcntl.flock(fd, fcntl.LOCK_EX)\n"
            "print('locked', flush=True)\n"
            "time.sleep(0.15)\n"
            "pathlib.Path(sys.argv[2]).write_text('from-holder', encoding='utf-8')\n"
            "fcntl.flock(fd, fcntl.LOCK_UN)\n"
            "os.close(fd)\n",
            str(lock_path),
            str(target),
        ],
        stdout=subprocess.PIPE,
    )
    assert holder.stdout is not None
    try:
        assert holder.stdout.readline() == b"locked\n"
        with file_lock.exclusive_file_lock(lock_path, timeout_s=2.0):
            assert target.read_text(encoding="utf-8") == "from-holder"
            target.write_text("from-waiter", encoding="utf-8")
        assert target.read_text(encoding="utf-8") == "from-waiter"
    finally:
        holder.wait(timeout=5)
        holder.stdout.close()


def test_acquire_posix_lock_does_not_spin_when_unsupported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[int] = []

    class FakeFcntl:
        LOCK_EX = 2
        LOCK_NB = 4
        LOCK_UN = 8

        def flock(self, fd: int, op: int) -> None:
            attempts.append(op)
            raise OSError(errno.ENOLCK, "No locks available")

    monkeypatch.setattr(file_lock, "fcntl", FakeFcntl())
    monkeypatch.setattr(file_lock, "_LOCK_POLL_INTERVAL_S", 0.0)

    with tempfile.TemporaryFile() as handle:
        assert file_lock._acquire_posix_lock(handle.fileno(), 1.0) is False

    assert len(attempts) == 1


def test_acquire_msvcrt_lock_waits_out_a_contended_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[int] = []

    class FakeMsvcrt:
        LK_NBLCK = 1
        LK_UNLCK = 0

        def locking(self, fd: int, mode: int, nbytes: int) -> None:
            attempts.append(mode)
            if len(attempts) < 3:
                raise OSError(errno.EACCES, "Permission denied")

    monkeypatch.setattr(file_lock, "msvcrt", FakeMsvcrt())
    monkeypatch.setattr(file_lock, "_LOCK_POLL_INTERVAL_S", 0.0)

    with tempfile.TemporaryFile() as handle:
        assert file_lock._acquire_msvcrt_lock(handle.fileno(), 1.0) is True

    assert len(attempts) == 3


def test_acquire_msvcrt_lock_gives_up_at_the_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeMsvcrt:
        LK_NBLCK = 1
        LK_UNLCK = 0

        def locking(self, fd: int, mode: int, nbytes: int) -> None:
            raise OSError(errno.EACCES, "Permission denied")

    monkeypatch.setattr(file_lock, "msvcrt", FakeMsvcrt())
    monkeypatch.setattr(file_lock, "_LOCK_POLL_INTERVAL_S", 0.0)

    with tempfile.TemporaryFile() as handle, pytest.raises(TimeoutError):
        file_lock._acquire_msvcrt_lock(handle.fileno(), 0.01)


def test_acquire_msvcrt_lock_does_not_spin_when_locking_is_unsupported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[int] = []

    class FakeMsvcrt:
        LK_NBLCK = 1
        LK_UNLCK = 0

        def locking(self, fd: int, mode: int, nbytes: int) -> None:
            attempts.append(mode)
            raise OSError(errno.EINVAL, "Invalid argument")

    monkeypatch.setattr(file_lock, "msvcrt", FakeMsvcrt())
    monkeypatch.setattr(file_lock, "_LOCK_POLL_INTERVAL_S", 0.0)

    with tempfile.TemporaryFile() as handle:
        assert file_lock._acquire_msvcrt_lock(handle.fileno(), 1.0) is False

    assert len(attempts) == 1


def test_exclusive_file_lock_unlocks_msvcrt_on_exit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[tuple[int, int]] = []

    class FakeMsvcrt:
        LK_NBLCK = 1
        LK_UNLCK = 0

        def locking(self, fd: int, mode: int, nbytes: int) -> None:
            calls.append((mode, nbytes))

    monkeypatch.setattr(file_lock, "fcntl", None)
    monkeypatch.setattr(file_lock, "msvcrt", FakeMsvcrt())

    with file_lock.exclusive_file_lock(tmp_path / "year_ledger.json.lock"):
        assert calls == [(FakeMsvcrt.LK_NBLCK, 1)]

    assert calls == [(FakeMsvcrt.LK_NBLCK, 1), (FakeMsvcrt.LK_UNLCK, 1)]

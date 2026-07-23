# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Sweep orphaned ``mkstemp`` remnants out of ``~/.usage/``.

Every atomic write in this project has the same shape: ``mkstemp`` beside the
target, write, ``os.replace``, and a ``finally`` that unlinks the temp file if
anything went wrong. That cleanup cannot run when the process is SIGKILLed or
crashes mid-write, so the ``.tmp`` outlives it — one real install accumulated
40 MB of them over twelve days, mostly from the large JSONL caches whose long
writes are the likeliest to be interrupted.

Those write paths are correct and stay untouched. This module only collects
what a killed process left behind, once, at startup.
"""

from __future__ import annotations

import logging
import os
import stat
import time
from contextlib import suppress
from pathlib import Path

USAGE_DIR = Path(os.path.expanduser("~/.usage"))
# Another usage process (for example, the menu bar app and TUI together) may
# still be writing a large cache. Twenty-four hours is far longer than any
# single write, so one process cannot remove another process's active temp file.
STALE_TEMP_AGE_SECONDS = 24 * 3600

logger = logging.getLogger(__name__)


def _debug_warning(message: str, *args: object) -> None:
    with suppress(Exception):
        if os.environ.get("USAGE_DEBUG") == "1":
            logger.warning(message, *args, exc_info=True)


def _is_real_directory(path: Path) -> bool:
    try:
        return stat.S_ISDIR(path.lstat().st_mode)
    except OSError:
        return False


def _sweep_directory(directory: Path, now: float) -> int:
    deleted = 0
    try:
        entries = directory.iterdir()
        for path in entries:
            if not (path.name.startswith("tmp") and path.name.endswith(".tmp")):
                continue
            try:
                file_stat = path.lstat()
                if not stat.S_ISREG(file_stat.st_mode):
                    continue
                if now - file_stat.st_mtime < STALE_TEMP_AGE_SECONDS:
                    continue
                path.unlink()
                deleted += 1
            except OSError:
                _debug_warning("failed to inspect or remove stale temp file %s", path)
    except OSError:
        _debug_warning("failed to scan usage directory %s", directory)
    return deleted


def sweep_stale_temp_files(root: Path | None = None, *, now: float | None = None) -> int:
    """Remove stale mkstemp remnants from the usage directory.

    Scans ``root`` plus its direct ``*.d`` children (where the sharded caches
    put their temp files) and no deeper. Symlinks and directories are never
    touched no matter how well their name matches. Returns the number deleted;
    never raises.
    """
    deleted = 0
    try:
        scan_root = USAGE_DIR if root is None else root
        current_time = time.time() if now is None else now
        if not _is_real_directory(scan_root):
            return 0

        directories = [scan_root]
        try:
            for child in scan_root.iterdir():
                if child.name.endswith(".d") and _is_real_directory(child):
                    directories.append(child)
        except OSError:
            _debug_warning("failed to inspect usage subdirectories in %s", scan_root)

        for directory in directories:
            deleted += _sweep_directory(directory, current_time)
    except Exception:
        _debug_warning("unexpected failure while sweeping stale usage temp files")
    return deleted

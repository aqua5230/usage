# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Best-effort quarantine for corrupt disk cache files."""

from __future__ import annotations

import errno
import logging
import os
import shutil
import time
from pathlib import Path

logger = logging.getLogger(__name__)

QUARANTINE_DIR = Path.home() / ".usage" / "quarantine"
_MAX_FILE_SIZE = 5 * 1024 * 1024
_MAX_BACKUPS = 10


def quarantine(path: Path, reason: str) -> None:
    """Best-effort move of a corrupt cache file into the quarantine directory."""
    try:
        if path.stat().st_size > _MAX_FILE_SIZE:
            return

        quarantine_dir = QUARANTINE_DIR
        quarantine_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        timestamp_ms = time.time_ns() // 1_000_000
        backup_path = quarantine_dir / f"{path.name}.{timestamp_ms}.bak"
        try:
            os.replace(path, backup_path)
        except OSError as exc:
            if exc.errno != errno.EXDEV:
                raise
            shutil.copy2(path, backup_path)
            path.unlink()

        backups = sorted(
            quarantine_dir.glob("*.bak"), key=lambda candidate: candidate.stat().st_mtime
        )
        for backup in backups[:-_MAX_BACKUPS]:
            backup.unlink()
    except Exception as exc:
        if os.environ.get("USAGE_DEBUG") == "1":
            logger.warning("failed to quarantine cache file %s (%s): %s", path, reason, exc)

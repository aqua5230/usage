# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Application logging with bounded rotating file output."""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

# macOS keeps app logs under ~/Library/Logs; every other platform reuses the
# ~/.usage directory that already holds the disk caches and the quarantine.
LOG_DIR = (
    Path.home() / "Library" / "Logs" / "usage"
    if sys.platform == "darwin"
    else Path.home() / ".usage" / "logs"
)
LOG_FILENAME = "usage-app.log"
MAX_BYTES = 2 * 1024 * 1024
BACKUP_COUNT = 3
LOG_FORMAT = "%(asctime)s %(name)s %(levelname)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_GLOBAL_DEBUG_FLAGS = {"1", "all", "*"}


def parse_debug_flags(raw: str | None) -> tuple[bool, list[str]]:
    """Return whether debug is global and the requested logger names."""
    flags = [flag.strip().lower() for flag in raw.split(",") if flag.strip()] if raw else []
    if any(flag in _GLOBAL_DEBUG_FLAGS for flag in flags):
        return True, []
    return False, flags


def setup_logging() -> None:
    """Configure console output and best-effort rotating file logging."""
    global_debug, debug_loggers = parse_debug_flags(os.environ.get("USAGE_DEBUG"))
    level = logging.DEBUG if global_debug else logging.WARNING
    logging.basicConfig(level=level, format=LOG_FORMAT, datefmt=DATE_FORMAT)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    for name in debug_loggers:
        logging.getLogger(name).setLevel(logging.DEBUG)

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            LOG_DIR / LOG_FILENAME,
            maxBytes=MAX_BYTES,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
        )
    except OSError:
        return

    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
    root_logger.addHandler(file_handler)

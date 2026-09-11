# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Shared paths for Claude Code's local data directories."""

from __future__ import annotations

import os
import subprocess
import sys
from functools import lru_cache
from pathlib import Path


def _configured_value() -> str:
    value = os.environ.get("CLAUDE_CONFIG_DIR", "")
    if value.strip():
        return value
    if sys.platform != "darwin":
        return ""
    try:
        result = subprocess.run(
            ["launchctl", "getenv", "CLAUDE_CONFIG_DIR"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=2,
            stdin=subprocess.DEVNULL,
        )
    except Exception:
        return ""
    return result.stdout if result.returncode == 0 else ""


@lru_cache(maxsize=1)
def _configured_dirs() -> tuple[Path, ...]:
    return tuple(
        Path(part.strip()).expanduser()
        for part in _configured_value().split(",")
        if part.strip()
    )


cache_clear = _configured_dirs.cache_clear


def claude_config_dirs() -> list[Path]:
    """Return Claude Code's configured data directories in priority order."""
    return list(_configured_dirs()) or [Path(os.path.expanduser("~/.claude"))]


def claude_home() -> Path:
    """Return Claude Code's primary data directory."""
    return claude_config_dirs()[0]


def claude_json_path() -> Path:
    """Return ``.claude.json``: inside the config dir only when one is set, like Claude Code."""
    configured = _configured_dirs()
    if configured:
        return configured[0] / ".claude.json"
    return Path.home() / ".claude.json"

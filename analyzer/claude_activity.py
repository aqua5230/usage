# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Read Claude Code activity dates, never its cached token estimates."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from loaders import claude_paths

_MAX_BYTES = 5 * 1024 * 1024


def _read_dates(path: Path) -> frozenset[date]:
    try:
        if path.stat().st_size > _MAX_BYTES:
            return frozenset()
        with path.open("rb") as file:
            content = file.read(_MAX_BYTES + 1)
        if len(content) > _MAX_BYTES:
            return frozenset()
        data = json.loads(content.decode("utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("dailyActivity"), list):
            return frozenset()
        dates = set()
        for row in data["dailyActivity"]:
            if not isinstance(row, dict):
                return frozenset()
            day, messages = row.get("date"), row.get("messageCount")
            if not isinstance(day, str) or type(messages) is not int:
                return frozenset()
            parsed = date.fromisoformat(day)
            if parsed.isoformat() != day:
                return frozenset()
            # Treat this as a local calendar date; Claude Code's day boundary is unverified.
            if messages > 0:
                dates.add(parsed)
        return frozenset(dates)
    except (OSError, UnicodeDecodeError, ValueError, RecursionError):
        # This is Claude Code's file, not a usage cache: never quarantine or modify it.
        return frozenset()


def activity_dates() -> frozenset[date]:
    """Union days with a positive dailyActivity messageCount across config directories."""
    return frozenset(
        day
        for directory in claude_paths.claude_config_dirs()
        for day in _read_dates(directory / "stats-cache.json")
    )

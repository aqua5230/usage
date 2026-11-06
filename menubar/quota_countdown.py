# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Shared quota recovery countdown formatting, without platform UI imports."""

from __future__ import annotations

import math

from menubar.state import QuotaRowState


def _format_countdown(seconds: float) -> str:
    minutes = math.ceil(seconds / 60)
    if minutes >= 1440:
        return f"{minutes // 1440}d{minutes % 1440 // 60}h"
    if minutes >= 60:
        return f"{minutes // 60}h{minutes % 60}m"
    return f"{minutes}m"


def _quota_countdown(rows: tuple[QuotaRowState, ...], now: float) -> str | None:
    full = [row for row in rows if row.display_percent is not None and row.display_percent >= 100]
    if not full:
        return None
    resets = []
    for row in full:
        if row.resets_at is None or row.resets_at <= now:
            return None
        resets.append(row.resets_at)
    return _format_countdown(max(resets) - now)

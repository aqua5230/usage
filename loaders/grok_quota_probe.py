# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Read the most recent current-week Grok CLI quota snapshot from its local log.

The Grok CLI appends billing snapshots to ``~/.grok/logs/unified.jsonl``.  This
module only reads that file; it never starts the CLI or contacts a network API.
"""

from __future__ import annotations

import json
import math
import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from usage_common.time_utils import parse_iso8601_utc_or_raise

GROK_HOME = Path(os.path.expanduser("~/.grok"))
GROK_LOG_PATH = GROK_HOME / "logs" / "unified.jsonl"
_BILLING_MESSAGE = "billing: fetched credits config"
_MAX_TAIL_LINES = 10_000
_MAX_TAIL_BYTES = 4 * 1024 * 1024
_TAIL_CHUNK_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True)
class GrokQuotaResult:
    """One current-week Grok CLI billing snapshot from the local debug log."""

    used_percent: float
    period_end: str
    fetched_at: str
    subscription_tier: str | None


def find_grok() -> Path | None:
    """Return Grok CLI's data directory when it exists locally."""
    return GROK_HOME if GROK_HOME.is_dir() else None


def load_quota(now: datetime | None = None) -> GrokQuotaResult | None:
    """Return the latest current-week local billing snapshot, if one is available."""
    if find_grok() is None:
        return None
    current_time = datetime.now(UTC) if now is None else now.astimezone(UTC)
    try:
        lines = _tail_lines(GROK_LOG_PATH)
        for line in lines:
            result = _result_from_line(line)
            if result is None:
                continue
            try:
                period_end = parse_iso8601_utc_or_raise(result.period_end)
            except (TypeError, ValueError):
                continue
            if period_end >= current_time:
                return result
            # The latest valid billing snapshot belongs to the preceding weekly
            # period.  Older snapshots cannot be newer data for this week.
            return None
    except OSError:
        return None
    return None


def _tail_lines(path: Path) -> Iterator[bytes]:
    """Yield recent JSONL lines newest first without buffering the entire log."""
    with path.open("rb") as log_file:
        log_file.seek(0, os.SEEK_END)
        position = log_file.tell()
        remaining = b""
        scanned_bytes = 0
        scanned_lines = 0
        while position > 0 and scanned_bytes < _MAX_TAIL_BYTES and scanned_lines < _MAX_TAIL_LINES:
            chunk_size = min(_TAIL_CHUNK_BYTES, position, _MAX_TAIL_BYTES - scanned_bytes)
            position -= chunk_size
            log_file.seek(position)
            chunk = log_file.read(chunk_size)
            scanned_bytes += len(chunk)
            parts = (chunk + remaining).split(b"\n")
            remaining = parts[0]
            for line in reversed(parts[1:]):
                scanned_lines += 1
                if line:
                    yield line
                if scanned_lines >= _MAX_TAIL_LINES:
                    return
        if remaining and scanned_lines < _MAX_TAIL_LINES:
            yield remaining


def _result_from_line(line: bytes) -> GrokQuotaResult | None:
    try:
        payload: object = json.loads(line)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        return None
    if not isinstance(payload, dict) or payload.get("msg") != _BILLING_MESSAGE:
        return None
    fetched_at = payload.get("ts")
    context = payload.get("ctx")
    if not isinstance(fetched_at, str) or not isinstance(context, dict):
        return None
    config = context.get("config")
    if not isinstance(config, dict):
        return None
    used_percent = config.get("creditUsagePercent")
    period = config.get("currentPeriod")
    if (
        isinstance(used_percent, bool)
        or not isinstance(used_percent, int | float)
        or not math.isfinite(float(used_percent))
        or not 0.0 <= float(used_percent) <= 100.0
        or not isinstance(period, dict)
        or not isinstance(period_end := period.get("end"), str)
    ):
        return None
    try:
        parse_iso8601_utc_or_raise(fetched_at)
        parse_iso8601_utc_or_raise(period_end)
    except (TypeError, ValueError):
        return None
    tier = context.get("subscriptionTier")
    return GrokQuotaResult(
        used_percent=float(used_percent),
        period_end=period_end,
        fetched_at=fetched_at,
        subscription_tier=tier if isinstance(tier, str) else None,
    )

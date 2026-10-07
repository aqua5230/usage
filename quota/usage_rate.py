# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import os
import statistics
import time
from collections.abc import Callable
from datetime import datetime, timezone

from loaders.history_loader import UsageEntry, load_entries

# Fallback until there is enough history to compare against.
BURN_RATE_THRESH_NORMAL = 500.0  # tokens/min
BURN_RATE_THRESH_ACTIVE = 2500.0
BURN_RATE_THRESH_HEAVY = 6000.0

# Levels are measured against the user's own hours with any usage in the last
# 30 days: below p25 is Idle, p25-p75 Normal, p75-p95 Active, p95 and up Heavy.
# Fixed limits labelled a normal Opus session Heavy all the time.
BASELINE_HOURS = 30 * 24
BASELINE_MIN_HOURS = 24
BASELINE_TTL_SECONDS = 3600

GROUP_NAMES = ["Idle", "Normal", "Active", "Heavy"]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)  # noqa: UP017 - keep timezone.utc explicit.


def baseline_thresholds(entries: list[UsageEntry]) -> tuple[float, float, float]:
    tokens_by_hour: dict[datetime, int] = {}
    for entry in entries:
        hour = entry.timestamp.replace(minute=0, second=0, microsecond=0)
        tokens_by_hour[hour] = tokens_by_hour.get(hour, 0) + entry.active_tokens
    rates = [tokens / 60.0 for tokens in tokens_by_hour.values() if tokens > 0]
    if len(rates) < BASELINE_MIN_HOURS:
        return BURN_RATE_THRESH_NORMAL, BURN_RATE_THRESH_ACTIVE, BURN_RATE_THRESH_HEAVY
    cuts = statistics.quantiles(rates, n=100, method="inclusive")
    return cuts[24], cuts[74], cuts[94]


class UsageRateTracker:
    def __init__(
        self,
        forced_group: int | None = None,
        mock: bool = False,
        load: Callable[[int], list[UsageEntry]] | None = None,
    ) -> None:
        self.forced_group = forced_group
        self.mock = mock
        self._load = load
        self._cached_group: int | None = None
        self._cache_expires_at = 0.0
        self._thresholds: tuple[float, float, float] | None = None
        self._thresholds_expire_at = 0.0

    def group(self) -> int:
        forced_group = self._forced_group()
        if forced_group is not None:
            return forced_group
        if self.mock:
            return 0

        now = time.monotonic()
        if self._cached_group is not None and now < self._cache_expires_at:
            return self._cached_group

        entries = self._load(1) if self._load is not None else load_entries(hours_back=1)
        if not entries:
            result = 0
            self._cached_group = result
            self._cache_expires_at = time.monotonic() + 30
            return result

        active_tokens = sum(entry.active_tokens for entry in entries)
        elapsed_seconds = (_utc_now() - entries[0].timestamp).total_seconds()
        # Match burn_rate's 5-minute floor: a single cache-creation burst should
        # not trigger Heavy on its own.
        elapsed_minutes = max(elapsed_seconds / 60.0, 5.0)
        burn_rate = active_tokens / min(elapsed_minutes, 60.0)

        normal, active, heavy = self._baseline()
        if burn_rate < normal:
            result = 0
        elif burn_rate < active:
            result = 1
        elif burn_rate < heavy:
            result = 2
        else:
            result = 3

        self._cached_group = result
        self._cache_expires_at = time.monotonic() + 30
        return result

    def _baseline(self) -> tuple[float, float, float]:
        now = time.monotonic()
        if self._thresholds is None or now >= self._thresholds_expire_at:
            entries = (
                self._load(BASELINE_HOURS)
                if self._load is not None
                else load_entries(hours_back=BASELINE_HOURS)
            )
            self._thresholds = baseline_thresholds(entries)
            self._thresholds_expire_at = now + BASELINE_TTL_SECONDS
        return self._thresholds

    def _forced_group(self) -> int | None:
        if self.forced_group is not None:
            return self.forced_group

        raw_value = os.environ.get("USAGE_FORCE_GROUP")
        if raw_value is None:
            return None

        try:
            group = int(raw_value)
        except ValueError:
            return None

        if 0 <= group < len(GROUP_NAMES):
            return group
        return None

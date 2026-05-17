from __future__ import annotations

import os
import time

from history_loader import load_entries

BURN_RATE_THRESH_NORMAL = 50.0    # tokens/min
BURN_RATE_THRESH_ACTIVE = 250.0
BURN_RATE_THRESH_HEAVY = 1000.0

GROUP_NAMES = ["Idle", "Normal", "Active", "Heavy"]


class UsageRateTracker:
    def __init__(self, forced_group: int | None = None, mock: bool = False) -> None:
        self.forced_group = forced_group
        self.mock = mock
        self._cached_group: int | None = None
        self._cache_expires_at = 0.0

    def sample(self, session_pct: float) -> None:
        _ = session_pct

    def group(self) -> int:
        forced_group = self._forced_group()
        if forced_group is not None:
            return forced_group
        if self.mock:
            return 0

        now = time.monotonic()
        if self._cached_group is not None and now < self._cache_expires_at:
            return self._cached_group

        entries = load_entries(hours_back=1)
        if not entries:
            result = 0
            self._cached_group = result
            self._cache_expires_at = time.monotonic() + 30
            return result

        total_tokens = sum(entry.total_tokens for entry in entries)
        elapsed_seconds = (entries[-1].timestamp - entries[0].timestamp).total_seconds()
        elapsed_minutes = max(elapsed_seconds / 60.0, 1.0)
        burn_rate = total_tokens / min(elapsed_minutes, 60.0)

        if burn_rate < BURN_RATE_THRESH_NORMAL:
            result = 0
        elif burn_rate < BURN_RATE_THRESH_ACTIVE:
            result = 1
        elif burn_rate < BURN_RATE_THRESH_HEAVY:
            result = 2
        else:
            result = 3

        self._cached_group = result
        self._cache_expires_at = time.monotonic() + 30
        return result

    def _forced_group(self) -> int | None:
        if self.forced_group is not None:
            return self.forced_group

        raw_value = os.environ.get("USAG_FORCE_GROUP")
        if raw_value is None:
            return None

        try:
            group = int(raw_value)
        except ValueError:
            return None

        if 0 <= group < len(GROUP_NAMES):
            return group
        return None

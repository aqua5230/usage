# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

ROLLING_WINDOW_SECONDS = 60 * 60
FORECAST_WINDOW_SECONDS = 10 * 60
RESET_DROP_PERCENT = 5.0
MIN_FORECAST_SAMPLES = 5
MIN_FORECAST_SPAN_SECONDS = 5 * 60
WARNING_PERCENT_FLOOR = 50.0
WEEKLY_WINDOW_SECONDS = 7 * 86400
URGENT_WARNING_SECONDS = 60 * 60


@dataclass(slots=True)
class BurnSample:
    timestamp: float
    percent: float


def assess_weekly_quota(
    percent: float,
    reset_seconds: float,
    window_seconds: float,
    forecast_seconds: float | None,
    warning_max_seconds: float | None,
) -> bool:
    """Assess a weekly quota using short-term and whole-window burn rates."""
    time_valid = window_seconds > 0 and 0 < reset_seconds <= window_seconds
    warning_candidate = (
        forecast_seconds is not None
        and 0 < forecast_seconds < reset_seconds
        and percent >= WARNING_PERCENT_FLOOR
    )
    if warning_candidate and forecast_seconds is not None:
        if forecast_seconds <= URGENT_WARNING_SECONDS:
            return True
        if (
            time_valid
            and percent > 0
            and (warning_max_seconds is None or forecast_seconds < warning_max_seconds)
        ):
            elapsed_seconds = window_seconds - reset_seconds
            return (
                elapsed_seconds > 0
                and (100.0 - percent) * elapsed_seconds / percent < reset_seconds
            )
    return False


class BurnRateTracker:
    def __init__(self) -> None:
        self._samples: deque[BurnSample] = deque()

    @property
    def last_timestamp(self) -> float | None:
        return self._samples[-1].timestamp if self._samples else None

    def record(self, now: float, percent: float) -> None:
        sample = BurnSample(timestamp=float(now), percent=float(percent))
        previous = self._samples[-1] if self._samples else None
        if previous is not None and (previous.percent - sample.percent) > RESET_DROP_PERCENT:
            self._samples.clear()
        self._samples.append(sample)
        self._prune(now=sample.timestamp)

    def forecast_seconds(
        self,
        window_seconds: float | None = None,
        min_span_seconds: float | None = None,
    ) -> float | None:
        if len(self._samples) < 2:
            return None

        latest = self._samples[-1]
        window = window_seconds if window_seconds is not None else FORECAST_WINDOW_SECONDS
        cutoff = latest.timestamp - window
        selected = [sample for sample in self._samples if sample.timestamp >= cutoff]
        if len(selected) < MIN_FORECAST_SAMPLES:
            return None

        first = selected[0]
        elapsed = latest.timestamp - first.timestamp
        span_threshold = (
            min_span_seconds if min_span_seconds is not None else MIN_FORECAST_SPAN_SECONDS
        )
        if elapsed < span_threshold:
            return None
        if elapsed <= 0:
            return None

        slope_per_second = (latest.percent - first.percent) / elapsed
        if slope_per_second <= 0:
            return None

        remaining_percent = 100.0 - latest.percent
        if remaining_percent <= 0:
            return 0.0
        return remaining_percent / slope_per_second

    def _prune(self, now: float) -> None:
        cutoff = now - ROLLING_WINDOW_SECONDS
        while self._samples and self._samples[0].timestamp < cutoff:
            self._samples.popleft()

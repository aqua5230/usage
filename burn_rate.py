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
# A 0.5 alpha gives the newest interval meaningful influence while still
# dampening single-interval endpoint noise in the irregular polling stream.
BURN_EMA_ALPHA = 0.5


@dataclass(slots=True)
class BurnSample:
    timestamp: float
    percent: float


class BurnRateTracker:
    def __init__(self) -> None:
        self._samples: deque[BurnSample] = deque()

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

        ema_rate: float | None = None
        for previous, current in zip(selected, selected[1:], strict=False):
            interval_seconds = current.timestamp - previous.timestamp
            if interval_seconds <= 0:
                continue
            rate = (current.percent - previous.percent) / interval_seconds
            if ema_rate is None:
                ema_rate = rate
            else:
                ema_rate = (
                    BURN_EMA_ALPHA * rate + (1.0 - BURN_EMA_ALPHA) * ema_rate
                )
        slope_per_second = ema_rate if ema_rate is not None else 0.0
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

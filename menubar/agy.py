# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Background-safe Antigravity quota projection for the menu-bar panel."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import cast

import burn_rate
from burn_rate import WARNING_PERCENT_FLOOR, BurnRateTracker
from i18n import _t
from loaders.agy_quota_probe import (
    AgyQuotaGroup,
    AgyQuotaResult,
    AgyQuotaWindow,
    load_quota,
)
from loaders.agy_quota_probe import (
    find_agy as find_agy,
)
from menubar.state import (
    AGY_COLOR,
    AgyStaleState,
    QuotaRowState,
    _bar_color,
    _format_percent,
    format_human_time,
)
from time_utils import parse_iso8601_utc_or_raise

AGY_STALE_SECONDS = 20 * 60
AGY_SESSION_FORECAST_MIN_SPAN_SECONDS = 15 * 60
AGY_WEEKLY_FORECAST_MIN_SPAN_SECONDS = 30 * 60
AGY_WEEKLY_WARNING_MAX_SECONDS = 24 * 3600


@dataclass(frozen=True, slots=True)
class AgyQuotaProjection:
    """Panel-ready data for Antigravity's Gemini group by default."""

    group_name: str
    session: QuotaRowState
    weekly: QuotaRowState
    stale: AgyStaleState | None
    five_hour: AgyQuotaWindow | None


@dataclass(frozen=True, slots=True)
class AgyRefreshResult:
    """One background probe/load outcome, including card visibility."""

    projection: AgyQuotaProjection | None
    hide_agy: bool


def project_quota(
    quota: AgyQuotaResult | None,
    language: str,
    now: float | None = None,
    burn_rate_trackers: dict[str, BurnRateTracker] | None = None,
) -> AgyQuotaProjection | None:
    """Select and convert the Gemini quota group without I/O when available."""
    if quota is None or not quota.groups:
        return None
    selected = next(
        (group for group in quota.groups if "gemini" in group.name.lower()),
        min(quota.groups, key=_group_remaining_percent),
    )
    current_time = time.time() if now is None else now
    age_minutes = _cache_age_minutes(quota.fetched_at, current_time)
    stale = _stale_state(quota.fetched_at, current_time, language)
    session_forecast: float | None = None
    weekly_forecast: float | None = None
    if stale is None and burn_rate_trackers is not None:
        try:
            sample_ts = parse_iso8601_utc_or_raise(quota.fetched_at).timestamp()
        except (TypeError, ValueError):
            pass
        else:
            session_tracker = burn_rate_trackers["agy_session"]
            weekly_tracker = burn_rate_trackers["agy_weekly"]
            if session_tracker.last_timestamp is None or sample_ts > session_tracker.last_timestamp:
                session_tracker.record(sample_ts, 100.0 - _remaining_percent(selected.five_hour))
            if weekly_tracker.last_timestamp is None or sample_ts > weekly_tracker.last_timestamp:
                weekly_tracker.record(sample_ts, 100.0 - _remaining_percent(selected.weekly))
            # agy samples arrive every 5 minutes, so the default 10-minute window
            # cannot collect MIN_FORECAST_SAMPLES; this wider window reacts more slowly.
            session_forecast = session_tracker.forecast_seconds(
                window_seconds=burn_rate.ROLLING_WINDOW_SECONDS,
                min_span_seconds=AGY_SESSION_FORECAST_MIN_SPAN_SECONDS,
            )
            weekly_forecast = weekly_tracker.forecast_seconds(
                window_seconds=burn_rate.ROLLING_WINDOW_SECONDS,
                min_span_seconds=AGY_WEEKLY_FORECAST_MIN_SPAN_SECONDS,
            )
    return AgyQuotaProjection(
        group_name=selected.name,
        session=_window_row(
            _t(language, "session_label"),
            selected.five_hour,
            language,
            age_minutes,
            forecast_seconds=session_forecast,
        ),
        weekly=_window_row(
            _t(language, "weekly_label"),
            selected.weekly,
            language,
            age_minutes,
            forecast_seconds=weekly_forecast,
            warning_max_seconds=AGY_WEEKLY_WARNING_MAX_SECONDS,
        ),
        stale=stale,
        five_hour=selected.five_hour,
    )


def load_refresh_result(
    language: str,
    burn_rate_trackers: dict[str, BurnRateTracker] | None = None,
) -> AgyRefreshResult:
    """Load/probe quota for a worker thread; never call this on the main thread."""
    if find_agy() is None:
        return AgyRefreshResult(projection=None, hide_agy=True)
    try:
        projection = project_quota(
            load_quota(), language, burn_rate_trackers=burn_rate_trackers
        )
    except Exception:
        projection = None
    return AgyRefreshResult(projection=projection, hide_agy=projection is None)


def fallback_projection(language: str) -> AgyQuotaProjection:
    """Return inert rows while the card is hidden after an unavailable probe."""
    return AgyQuotaProjection(
        group_name="",
        session=QuotaRowState(
            title=_t(language, "session_label"),
            percent=None,
            percent_text="--",
            reset_text=_t(language, "reset_placeholder"),
            color=AGY_COLOR,
            available=False,
        ),
        weekly=QuotaRowState(
            title=_t(language, "weekly_label"),
            percent=None,
            percent_text="--",
            reset_text=_t(language, "reset_placeholder"),
            color=AGY_COLOR,
            available=False,
        ),
        stale=None,
        five_hour=None,
    )


def _group_remaining_percent(group: AgyQuotaGroup) -> float:
    return min(
        _remaining_percent(group.five_hour),
        _remaining_percent(group.weekly),
    )


def _remaining_percent(window: AgyQuotaWindow) -> float:
    return max(0.0, min(100.0, float(window.remaining_percent)))


def _cache_age_minutes(fetched_at: str, now: float) -> int:
    """Whole minutes since the cached snapshot was taken (never negative)."""
    try:
        age_seconds = now - parse_iso8601_utc_or_raise(fetched_at).timestamp()
    except (TypeError, ValueError):
        return 0
    return max(0, int(age_seconds // 60))


def _window_row(
    title: str,
    window: AgyQuotaWindow,
    language: str,
    age_minutes: int = 0,
    forecast_seconds: float | None = None,
    warning_max_seconds: float | None = None,
) -> QuotaRowState:
    remaining = _remaining_percent(window)
    used = 100.0 - remaining
    warning = False
    if remaining == 100.0:
        reset_text = _t(language, "agy_quota_full")
    elif window.resets_in_minutes is None:
        reset_text = _t(language, "reset_placeholder")
    else:
        minutes_left = max(1, window.resets_in_minutes - max(0, age_minutes))
        time_to_reset = minutes_left * 60
        warning_seconds: float | None = None
        if (
            forecast_seconds is not None
            and 0 < forecast_seconds < time_to_reset
            and (warning_max_seconds is None or forecast_seconds < warning_max_seconds)
            and used >= WARNING_PERCENT_FLOOR
        ):
            warning_seconds = forecast_seconds
        warning = warning_seconds is not None
        if warning_seconds is not None:
            reset_text = _t(
                language,
                "burn_warning",
                empty=format_human_time(warning_seconds, language),
                reset=format_human_time(time_to_reset, language),
            )
        else:
            reset_text = _t(
                language,
                "reset_in",
                time=format_human_time(time_to_reset, language),
            )
    return QuotaRowState(
        title=title,
        percent=used,
        percent_text=_t(language, "percent_used", value=_format_percent(used)),
        reset_text=reset_text,
        color=_bar_color(used, AGY_COLOR),
        warning=warning,
        available=True,
    )


def _stale_state(fetched_at: str, now: float, language: str) -> AgyStaleState | None:
    try:
        age_seconds = now - parse_iso8601_utc_or_raise(fetched_at).timestamp()
    except (TypeError, ValueError):
        return None
    if age_seconds <= AGY_STALE_SECONDS:
        return None
    if age_seconds < 3600:
        return cast(
            AgyStaleState,
            {
                "ageText": _t(
                    language,
                    "agy_stale_minutes",
                    minutes=max(1, int(age_seconds // 60)),
                )
            },
        )
    return cast(
        AgyStaleState,
        {"ageText": _t(language, "agy_stale_hours", hours=max(1, int(age_seconds // 3600)))}
    )

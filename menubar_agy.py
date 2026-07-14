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

from agy_quota_probe import (
    AgyQuotaGroup,
    AgyQuotaResult,
    AgyQuotaWindow,
    load_quota,
)
from agy_quota_probe import (
    find_agy as find_agy,
)
from i18n import _t
from menubar_state import (
    AGY_COLOR,
    AgyStaleState,
    QuotaRowState,
    _bar_color,
    _format_percent,
    format_human_time,
)
from time_utils import parse_iso8601_utc_or_raise

AGY_STALE_SECONDS = 20 * 60


@dataclass(frozen=True, slots=True)
class AgyQuotaProjection:
    """Panel-ready data for Antigravity's Gemini group by default."""

    group_name: str
    session: QuotaRowState
    weekly: QuotaRowState
    stale: AgyStaleState | None


@dataclass(frozen=True, slots=True)
class AgyRefreshResult:
    """One background probe/load outcome, including card visibility."""

    projection: AgyQuotaProjection | None
    hide_agy: bool


def project_quota(
    quota: AgyQuotaResult | None,
    language: str,
    now: float | None = None,
) -> AgyQuotaProjection | None:
    """Select and convert the Gemini quota group without I/O when available."""
    if quota is None or not quota.groups:
        return None
    selected = next(
        (group for group in quota.groups if "gemini" in group.name.lower()),
        min(quota.groups, key=_group_remaining_percent),
    )
    group_label = _t(
        language,
        "agy_group_gemini" if "gemini" in selected.name.lower() else "agy_group_claude_gpt",
    )
    current_time = time.time() if now is None else now
    age_minutes = _cache_age_minutes(quota.fetched_at, current_time)
    return AgyQuotaProjection(
        group_name=selected.name,
        session=_window_row(
            f"{_t(language, 'session_label')} · {group_label}",
            selected.five_hour,
            language,
            age_minutes,
        ),
        weekly=_window_row(
            f"{_t(language, 'weekly_label')} · {group_label}",
            selected.weekly,
            language,
            age_minutes,
        ),
        stale=_stale_state(quota.fetched_at, current_time, language),
    )


def load_refresh_result(language: str) -> AgyRefreshResult:
    """Load/probe quota for a worker thread; never call this on the main thread."""
    if find_agy() is None:
        return AgyRefreshResult(projection=None, hide_agy=True)
    try:
        projection = project_quota(load_quota(), language)
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
    title: str, window: AgyQuotaWindow, language: str, age_minutes: int = 0
) -> QuotaRowState:
    remaining = _remaining_percent(window)
    used = 100.0 - remaining
    if remaining == 100.0 and window.resets_in_minutes is None:
        reset_text = _t(language, "agy_quota_full")
    elif window.resets_in_minutes is None:
        reset_text = _t(language, "reset_placeholder")
    else:
        minutes_left = max(1, window.resets_in_minutes - max(0, age_minutes))
        reset_text = _t(
            language,
            "reset_in",
            time=format_human_time(minutes_left * 60, language),
        )
    return QuotaRowState(
        title=title,
        percent=used,
        percent_text=_t(language, "percent_used", value=_format_percent(used)),
        reset_text=reset_text,
        color=_bar_color(used, AGY_COLOR),
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

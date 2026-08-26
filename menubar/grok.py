# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Background-safe Grok CLI quota projection for the menu-bar panel."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import cast

from i18n import _t
from loaders.grok_quota_probe import GrokQuotaResult, find_grok, load_quota
from menubar.state import (
    GROK_COLOR,
    GrokStaleState,
    QuotaRowState,
    _bar_color,
    _format_percent,
    format_human_time,
)
from usage_common.time_utils import parse_iso8601_utc_or_raise

GROK_STALE_SECONDS = 20 * 60


@dataclass(frozen=True, slots=True)
class GrokQuotaProjection:
    """Panel-ready data for Grok CLI's single weekly quota."""

    weekly: QuotaRowState
    stale: GrokStaleState | None


@dataclass(frozen=True, slots=True)
class GrokRefreshResult:
    """One local Grok quota load outcome, including card visibility."""

    projection: GrokQuotaProjection | None
    hide_grok: bool


def project_quota(
    quota: GrokQuotaResult | None,
    language: str,
    now: float | None = None,
) -> GrokQuotaProjection | None:
    """Convert one local Grok snapshot into the single panel quota row."""
    if quota is None:
        return None
    current_time = time.time() if now is None else now
    try:
        period_end = parse_iso8601_utc_or_raise(quota.period_end).timestamp()
    except (TypeError, ValueError):
        return None
    if period_end < current_time:
        return None
    stale = _stale_state(quota.fetched_at, current_time, language)
    used = max(0.0, min(100.0, quota.used_percent))
    return GrokQuotaProjection(
        weekly=QuotaRowState(
            title=_t(language, "weekly_label"),
            percent=used,
            percent_text=_t(language, "percent_used", value=_format_percent(used)),
            reset_text=_t(
                language,
                "reset_in",
                time=format_human_time(max(0.0, period_end - current_time), language),
            ),
            color=_bar_color(used, GROK_COLOR),
            available=True,
        ),
        stale=stale,
    )


def load_refresh_result(language: str) -> GrokRefreshResult:
    """Read Grok's local log on a worker thread and decide card visibility."""
    if find_grok() is None:
        return GrokRefreshResult(projection=None, hide_grok=True)
    try:
        projection = project_quota(load_quota(), language)
    except Exception:
        projection = None
    return GrokRefreshResult(projection=projection, hide_grok=projection is None)


def fallback_projection(language: str) -> GrokQuotaProjection:
    """Return an inert row while the unavailable Grok card stays hidden."""
    return GrokQuotaProjection(
        weekly=QuotaRowState(
            title=_t(language, "weekly_label"),
            percent=None,
            percent_text="--",
            reset_text=_t(language, "reset_placeholder"),
            color=GROK_COLOR,
            available=False,
        ),
        stale=None,
    )


def _stale_state(fetched_at: str, now: float, language: str) -> GrokStaleState | None:
    try:
        age_seconds = now - parse_iso8601_utc_or_raise(fetched_at).timestamp()
    except (TypeError, ValueError):
        return None
    if age_seconds <= GROK_STALE_SECONDS:
        return None
    if age_seconds < 3600:
        return cast(
            GrokStaleState,
            {
                "ageText": _t(
                    language,
                    "grok_stale_minutes",
                    minutes=max(1, int(age_seconds // 60)),
                )
            },
        )
    return cast(
        GrokStaleState,
        {"ageText": _t(language, "grok_stale_hours", hours=max(1, int(age_seconds // 3600)))}
    )

# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>

"""Background-safe Muse quota projection for the menu-bar panel."""

from __future__ import annotations

import time
from dataclasses import dataclass

from loaders import muse_quota_probe as probe
from menubar.state import MUSE_COLOR, MuseStaleState, QuotaRowState, _missing_row, _quota_row
from usage_common.i18n import _t


@dataclass(frozen=True, slots=True)
class MuseQuotaProjection:
    session: QuotaRowState
    weekly: QuotaRowState
    stale: MuseStaleState | None


@dataclass(frozen=True, slots=True)
class MuseRefreshResult:
    projection: MuseQuotaProjection | None
    hide_muse: bool


def project_quota(
    quota: probe.MuseQuotaResult | None,
    language: str,
    now: float | None = None,
    *,
    latest_session: float | None = None,
) -> MuseQuotaProjection | None:
    if quota is None:
        return None
    current = time.time() if now is None else now
    stale: MuseStaleState | None = None
    if probe.is_stale(quota, latest_session, current):
        age = current - quota["checked_at"]
        # The existing age-only translations are shared with Grok.
        stale = (
            {"ageText": _t(language, "grok_stale_minutes", minutes=int(age // 60))}
            if age < 3600
            else {"ageText": _t(language, "grok_stale_hours", hours=int(age // 3600))}
        )
    rows = [
        _quota_row(
            _t(language, label),
            window["used_percent"],
            window["resets_at"],
            current,
            MUSE_COLOR,
            language,
        )
        for window, label in ((quota["window"], "session_label"), (quota["weekly"], "weekly_label"))
    ]
    return MuseQuotaProjection(session=rows[0], weekly=rows[1], stale=stale)


def load_refresh_result(language: str, *, allow_probe: bool = True) -> MuseRefreshResult:
    quota, latest = probe.load_quota_snapshot(allow_probe=allow_probe)
    projection = project_quota(quota, language, latest_session=latest)
    return MuseRefreshResult(projection=projection, hide_muse=projection is None)


def fallback_projection(language: str) -> MuseQuotaProjection:
    return MuseQuotaProjection(
        session=_missing_row(_t(language, "session_label"), MUSE_COLOR, language),
        weekly=_missing_row(_t(language, "weekly_label"), MUSE_COLOR, language),
        stale=None,
    )

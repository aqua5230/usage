# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Background-safe refresh loading and popover-state construction."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Coroutine
from dataclasses import dataclass
from typing import Any, Protocol

import agy_window_keeper
import talent_market_bridge
import window_keeper
from burn_rate import BurnRateTracker
from history_loader import UsageEntry
from menubar import agy as menubar_agy
from menubar import state as menubar_state
from menubar.prefs import (
    _hide_agy_enabled,
    _hide_claude_enabled,
    _hide_codex_enabled,
    _quota_card_order,
)
from service_status import CLAUDE_STATUS, CODEX_STATUS, get_service_status
from usage_client import PollOutcome, PollState
from usage_rate import UsageRateTracker

logger = logging.getLogger(__name__)

type ProjectRows = list[tuple[str, int, float | None]]


class _RefreshApp(Protocol):
    language: str
    mock: bool
    tracker: UsageRateTracker
    codex_tracker: UsageRateTracker
    agy_tracker: UsageRateTracker
    burn_rate_trackers: dict[str, BurnRateTracker]
    latest_state: menubar_state.PopoverState
    active_panel: Any
    _history_load_error_key: str | None

    def _fetch(self) -> Coroutine[Any, Any, PollOutcome]: ...

    def _load_codex_refresh_result(self) -> dict[str, Any]: ...

    def _load_history_entries(
        self, *, scan: menubar_state.HistorySourceScan | None = None
    ) -> list[UsageEntry]: ...

    def _project_rows(
        self, hours_back: int = 24, entries: list[UsageEntry] | None = None
    ) -> ProjectRows: ...

    def _statusline_setup_available(self) -> bool: ...


@dataclass(slots=True)
class RefreshSources:
    codex_result: dict[str, Any]
    history_scan: menubar_state.HistorySourceScan | None
    agy_result: menubar_agy.AgyRefreshResult
    agy_projection: menubar_agy.AgyQuotaProjection
    animation_groups: tuple[int, int, int]
    debug_timing: bool

    def measure(self, stage: str, started_at: float) -> None:
        if self.debug_timing:
            elapsed_ms = (time.monotonic() - started_at) * 1000
            logger.debug("refresh_timing stage=%s elapsed_ms=%.1f", stage, elapsed_ms)


def load_sources(app: _RefreshApp) -> RefreshSources:
    debug_timing = os.environ.get("USAGE_DEBUG") == "1"
    animation_groups = (
        int(getattr(app, "critter_group", 0)),
        int(getattr(app, "dragon_group", 0)),
        int(getattr(app, "lion_group", 0)),
    )
    started_at = time.monotonic() if debug_timing else 0.0
    codex_result = app._load_codex_refresh_result()
    history_scan = codex_result.get("_history_scan")
    if debug_timing:
        elapsed_ms = (time.monotonic() - started_at) * 1000
        logger.debug("refresh_timing stage=%s elapsed_ms=%.1f", "codex_load", elapsed_ms)
    started_at = time.monotonic() if debug_timing else 0.0
    agy_result = menubar_agy.load_refresh_result(app.language)
    if debug_timing:
        elapsed_ms = (time.monotonic() - started_at) * 1000
        logger.debug("refresh_timing stage=%s elapsed_ms=%.1f", "agy_load", elapsed_ms)
    agy_projection = agy_result.projection or menubar_agy.fallback_projection(app.language)
    return RefreshSources(
        codex_result=codex_result,
        history_scan=(
            history_scan if isinstance(history_scan, menubar_state.HistorySourceScan) else None
        ),
        agy_result=agy_result,
        agy_projection=agy_projection,
        animation_groups=animation_groups,
        debug_timing=debug_timing,
    )


def build_result(app: _RefreshApp, sources: RefreshSources) -> dict[str, Any]:
    codex_result = sources.codex_result
    agy_result = sources.agy_result
    agy_projection = sources.agy_projection
    animation_groups = sources.animation_groups
    fallback_state = getattr(app, "latest_state", menubar_state._empty_state(app.language))
    project_rows = list(fallback_state.projects)
    project_rows_yesterday = list(fallback_state.projects_yesterday)
    project_rows_7d = list(fallback_state.projects_7d)
    project_rows_30d = list(fallback_state.projects_30d)
    project_rows_all = list(fallback_state.projects_all)
    today_text = fallback_state.today_text
    yesterday_text = fallback_state.yesterday_text
    statusline = fallback_state.statusline
    hide_claude = fallback_state.hide_claude
    hide_codex = fallback_state.hide_codex
    hide_agy = agy_result.hide_agy or _hide_agy_enabled()
    card_order = _quota_card_order()
    try:
        started_at = time.monotonic() if sources.debug_timing else 0.0
        if sources.history_scan is not None:
            all_entries = app._load_history_entries(scan=sources.history_scan)
        else:
            all_entries = app._load_history_entries()
        sources.measure("history_load", started_at)
        started_at = time.monotonic() if sources.debug_timing else 0.0
        if app.mock:
            project_rows = app._project_rows(hours_back=24, entries=all_entries)
            project_rows_yesterday = project_rows
            project_rows_7d = app._project_rows(hours_back=168, entries=all_entries)
            project_rows_30d = app._project_rows(hours_back=720, entries=all_entries)
            project_rows_all = app._project_rows(hours_back=0, entries=all_entries)
        else:
            (
                project_rows,
                project_rows_yesterday,
                project_rows_7d,
                project_rows_30d,
                project_rows_all,
            ) = menubar_state.project_rows_for_windows(all_entries)
        sources.measure("project_rows_windows", started_at)
        today_text = menubar_state._today_title(app.mock, app.language, entries=all_entries)
        yesterday_text = menubar_state._yesterday_title(
            app.mock, app.language, entries=all_entries
        )
        statusline = menubar_state._statusline_payload(app.language)
        hide_claude = _hide_claude_enabled()
        hide_codex = _hide_codex_enabled()
        hide_agy = agy_result.hide_agy or _hide_agy_enabled()
    except Exception:
        if os.environ.get("USAGE_DEBUG") == "1":
            logger.warning("local usage refresh failed", exc_info=True)
    try:
        started_at = time.monotonic() if sources.debug_timing else 0.0
        outcome = asyncio.run(app._fetch())
        sources.measure("fetch", started_at)
        codex_rows = codex_result["codex_rows"]
        codex_5h_pct = codex_result["codex_5h_pct"]
        codex_model = codex_result.get("codex_model", "unknown")
        codex_stale = codex_result.get("codex_stale")
        codex_credits = codex_result.get("codex_credits")
        show_install_button = (
            not hide_claude
            and outcome.state == PollState.TOKEN_ERROR
            and app._statusline_setup_available()
        )
        service_statuses = (
            get_service_status(CLAUDE_STATUS),
            get_service_status(CODEX_STATUS),
        )
        group = int(app.tracker.group())
        try:
            codex_group = int(app.codex_tracker.group())
        except Exception:
            codex_group = 0
            if os.environ.get("USAGE_DEBUG") == "1":
                logger.warning("Codex animation group load failed", exc_info=True)
        try:
            agy_group = int(app.agy_tracker.group())
        except Exception:
            agy_group = 0
            if os.environ.get("USAGE_DEBUG") == "1":
                logger.warning("Antigravity animation group load failed", exc_info=True)
        animation_groups = (
            group,
            codex_group,
            agy_group,
        )
        state = menubar_state.build_popover_state(
            outcome=outcome,
            codex_rows=codex_rows,
            agy_rows=(agy_projection.session, agy_projection.weekly),
            agy_group_name=agy_projection.group_name,
            projects=project_rows,
            projects_yesterday=project_rows_yesterday,
            projects_7d=project_rows_7d,
            projects_30d=project_rows_30d,
            projects_all=project_rows_all,
            language=app.language,
            group=group,
            burn_rate_trackers=app.burn_rate_trackers,
            today_text=today_text,
            yesterday_text=yesterday_text,
            statusline=statusline,
            show_install_button=show_install_button,
            hide_claude=hide_claude,
            hide_codex=hide_codex,
            hide_agy=hide_agy,
            codex_stale=codex_stale,
            codex_credits=codex_credits,
            agy_stale=agy_projection.stale,
            card_order=card_order,
            history_error=menubar_state.history_load_error_state(
                app._history_load_error_key, app.language
            ),
            service_statuses=service_statuses,
        )
        if outcome.snapshot is not None:
            window_keeper.maybe_ping(
                outcome.snapshot.current_reset_at,
                outcome.snapshot.current_percent,
                outcome.snapshot.data_source,
                app.mock,
            )
        agy_window_keeper.maybe_ping(agy_result, app.mock)
    except Exception as exc:
        if os.environ.get("USAGE_DEBUG") == "1":
            logger.warning("refresh failed", exc_info=True)
        codex_rows = codex_result["codex_rows"]
        codex_5h_pct = codex_result["codex_5h_pct"]
        codex_model = codex_result.get("codex_model", "unknown")
        state = menubar_state._error_state(type(exc).__name__, app.mock, app.language)
        state.codex_session = codex_rows[0]
        state.codex_weekly = codex_rows[1]
        state.codex_stale = codex_result.get("codex_stale")
        state.agy_session = agy_projection.session
        state.agy_weekly = agy_projection.weekly
        state.agy_group_name = agy_projection.group_name
        state.agy_stale = agy_projection.stale
        state.history_error = menubar_state.history_load_error_state(
            app._history_load_error_key, app.language
        )
        state.projects = project_rows
        state.projects_yesterday = project_rows_yesterday
        state.projects_7d = project_rows_7d
        state.projects_30d = project_rows_30d
        state.projects_all = project_rows_all
        state.today_text = today_text
        state.yesterday_text = yesterday_text
        state.statusline = statusline
        state.hide_claude = hide_claude
        state.hide_codex = hide_codex
        state.hide_agy = hide_agy
        state.card_order = card_order

    # Talent-market data is panel-local (no quota numbers). Fetch it
    # only when that panel is active so classic/matrix users never pay
    # the subprocess cost. list_state already swallows CLI errors and
    # returns {ok:False,...}, so the panel shows its empty state.
    active_panel = getattr(app, "active_panel", None)
    if active_panel is not None and active_panel.id == "talent_market":
        try:
            state.talent = talent_market_bridge.list_state(app.language)
        except Exception:
            if os.environ.get("USAGE_DEBUG") == "1":
                logger.warning("talent market state load failed", exc_info=True)

    return {
        "state": state,
        "codex_5h_pct": codex_5h_pct,
        "codex_model": codex_model,
        "animation_groups": animation_groups,
    }

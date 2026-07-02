# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

import codex_loader
from burn_rate import WARNING_PERCENT_FLOOR, BurnRateTracker
from history_loader import CLAUDE_PROJECTS_DIR, UsageEntry
from i18n import _t
from pricing import calculate_cost
from time_utils import parse_iso8601_utc_or_raise
from usage_client import PollOutcome, PollState
from usage_rate import GROUP_NAMES

logger = logging.getLogger(__name__)

CLAUDE_COLOR = (244 / 255, 145 / 255, 100 / 255)
CODEX_COLOR = (88 / 255, 214 / 255, 230 / 255)
WARN_COLOR = (255 / 255, 196 / 255, 57 / 255)
DANGER_COLOR = (255 / 255, 69 / 255, 58 / 255)
WEEKLY_FORECAST_WINDOW_SECONDS = 30 * 60
WEEKLY_FORECAST_MIN_SPAN_SECONDS = 30 * 60
SESSION_WINDOW_SECONDS = 5 * 3600
WEEKLY_WINDOW_SECONDS = 7 * 86400


def _bar_color(pct: float, brand: tuple[float, float, float]) -> tuple[float, float, float]:
    if pct >= 80:
        return DANGER_COLOR
    if pct >= 50:
        return WARN_COLOR
    return brand


@dataclass(slots=True)
class QuotaRowState:
    title: str
    percent: float | None
    percent_text: str
    reset_text: str
    color: tuple[float, float, float]
    warning: bool = False
    available: bool = True


class CodexStaleState(TypedDict):
    ageText: str


class HistoryLoadErrorState(TypedDict):
    reasonText: str


@dataclass(slots=True)
class PopoverState:
    language: str
    claude_session: QuotaRowState
    claude_weekly: QuotaRowState
    codex_session: QuotaRowState
    codex_weekly: QuotaRowState
    projects: list[tuple[str, int, float | None]]
    projects_7d: list[tuple[str, int, float | None]]
    projects_30d: list[tuple[str, int, float | None]]
    projects_all: list[tuple[str, int, float | None]]
    rate_text: str
    status_text: str
    today_text: str
    statusline: dict[str, object]
    show_install_button: bool = False
    hide_claude: bool = False
    hide_codex: bool = False
    codex_stale: CodexStaleState | None = None
    history_error: HistoryLoadErrorState | None = None


@dataclass(frozen=True, slots=True)
class HistorySourceScan:
    fingerprint: tuple[tuple[str, int, float], ...]
    claude_paths: tuple[Path, ...]
    codex_paths: tuple[Path, ...]


def _jsonl_paths(root: Path) -> tuple[Path, ...]:
    if not root.exists():
        return ()
    try:
        return tuple(root.rglob("*.jsonl"))
    except OSError:
        return ()


def _fingerprint_source(
    source: Path,
    *,
    jsonl_paths: tuple[Path, ...] | None = None,
) -> tuple[str, int, float]:
    newest_mtime = 0.0
    file_count = 0
    try:
        if source.is_file():
            stat = source.stat()
            file_count = 1
            newest_mtime = stat.st_mtime
        elif source.exists():
            paths = _jsonl_paths(source) if jsonl_paths is None else jsonl_paths
            for path in paths:
                try:
                    stat = path.stat()
                except OSError:
                    continue
                file_count += 1
                newest_mtime = max(newest_mtime, stat.st_mtime)
    except OSError:
        pass
    return (str(source), file_count, newest_mtime)


def history_source_scan() -> HistorySourceScan:
    claude_paths = _jsonl_paths(CLAUDE_PROJECTS_DIR)
    codex_session_paths = _jsonl_paths(codex_loader.SESSIONS_DIR)
    codex_archived_paths = _jsonl_paths(codex_loader.ARCHIVED_SESSIONS_DIR)
    fingerprint = (
        _fingerprint_source(CLAUDE_PROJECTS_DIR, jsonl_paths=claude_paths),
        _fingerprint_source(codex_loader.SESSIONS_DIR, jsonl_paths=codex_session_paths),
        _fingerprint_source(
            codex_loader.ARCHIVED_SESSIONS_DIR,
            jsonl_paths=codex_archived_paths,
        ),
        _fingerprint_source(codex_loader.LOGS_DB),
        _fingerprint_source(Path.home() / ".codex" / "logs_2.sqlite-wal"),
        _fingerprint_source(codex_loader.STATE_DB),
        _fingerprint_source(Path.home() / ".codex" / "state_5.sqlite-wal"),
    )
    return HistorySourceScan(
        fingerprint=fingerprint,
        claude_paths=claude_paths,
        codex_paths=codex_session_paths + codex_archived_paths,
    )


def history_sources_fingerprint() -> tuple[tuple[str, int, float], ...]:
    return history_source_scan().fingerprint


def project_rows(entries: list[UsageEntry]) -> list[tuple[str, int, float | None]]:
    aggregates: dict[str, list[float]] = {}
    for entry in entries:
        bucket = aggregates.setdefault(entry.project, [0.0, 0.0])
        bucket[0] += entry.total_tokens
        bucket[1] += calculate_cost(entry)

    ranked = sorted(
        aggregates.items(),
        key=lambda item: (int(item[1][0]), item[0]),
        reverse=True,
    )
    rows: list[tuple[str, int, float | None]] = []
    for project, (tokens, cost) in ranked[:3]:
        rows.append(
            (
                project,
                int(tokens),
                cost,
            )
        )
    return rows


def _group_name(group: int, language: str) -> str:
    return _t(language, f"group_{GROUP_NAMES[group].lower()}")


def _status_message_value(outcome: PollOutcome, fallback_key: str, language: str) -> str:
    if outcome.message == "awaiting_rate_limits":
        return _t(language, "awaiting_rate_limits")
    if outcome.message in {"hook_broken_not_installed", "hook_broken_restart"}:
        return _t(language, outcome.message)
    return outcome.message or _t(language, fallback_key)


def format_human_time(seconds: float, language: str = "en") -> str:
    if seconds <= 0:
        return _t(language, "duration_minutes", minutes=0)
    days, remainder = divmod(int(seconds), 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)

    if days > 0:
        return _t(language, "duration_days", days=days, hours=hours)
    if hours > 0:
        return _t(language, "duration_hours", hours=hours, minutes=minutes)
    return _t(language, "duration_minutes", minutes=minutes)


def codex_stale_state(updated_at: str, now: float, language: str) -> CodexStaleState | None:
    if not updated_at:
        return None
    timestamp = parse_iso8601_utc_or_raise(updated_at)
    age_seconds = now - timestamp.timestamp()
    if age_seconds <= 900:
        return None
    if age_seconds < 3600:
        minutes = max(1, int(age_seconds // 60))
        return {"ageText": _t(language, "codex_stale_minutes", minutes=minutes)}
    hours = max(1, int(age_seconds // 3600))
    return {"ageText": _t(language, "codex_stale_hours", hours=hours)}


def history_load_error_state(
    reason_key: str | None, language: str
) -> HistoryLoadErrorState | None:
    if reason_key is None:
        return None
    return {"reasonText": _t(language, reason_key)}


# Codex reports each quota slot's window length in minutes. Map it to a label so
# the row name follows the plan instead of being hard-coded: ~300m → Session,
# ~10080m → Weekly, ~43200m → Monthly (free plan). Thresholds are generous so
# minor drift in Codex's reported minutes still lands on the right label.
_CODEX_SESSION_MAX_MINUTES = 600.0  # ≤10h counts as the 5-hour session window
_CODEX_WEEKLY_MAX_MINUTES = 20160.0  # ≤14d counts as the weekly window


def _codex_window_label_key(window_minutes: float | None) -> str | None:
    if window_minutes is None:
        return None
    if window_minutes <= _CODEX_SESSION_MAX_MINUTES:
        return "session_label"
    if window_minutes <= _CODEX_WEEKLY_MAX_MINUTES:
        return "weekly_label"
    return "monthly_label"


def _codex_window_title(
    window_minutes: float | None,
    slot_default_key: str,
    language: str,
) -> str:
    # Fall back to the slot's historical label when Codex omits window_minutes,
    # so older logs / header-only sources keep their previous behaviour.
    key = _codex_window_label_key(window_minutes) or slot_default_key
    return _t(language, key)


def codex_rows(
    *,
    mock: bool,
    language: str,
    burn_rate_trackers: dict[str, BurnRateTracker],
) -> tuple[tuple[QuotaRowState, QuotaRowState], float | None, str, CodexStaleState | None]:
    if mock:
        now = time.time()
        burn_rate_trackers["codex_session"].record(now, 12.0)
        burn_rate_trackers["codex_weekly"].record(now, 28.0)
        rows = (
            _quota_row(
                _t(language, "session_label"),
                12.0,
                now + (4 * 3600) + (15 * 60),
                now,
                CODEX_COLOR,
                language,
                forecast_seconds=burn_rate_trackers["codex_session"].forecast_seconds(),
            ),
            _quota_row(
                _t(language, "weekly_label"),
                28.0,
                now + (4 * 86400),
                now,
                CODEX_COLOR,
                language,
                forecast_seconds=burn_rate_trackers["codex_weekly"].forecast_seconds(),
                warning_max_seconds=24 * 3600,
            ),
        )
        return rows, 12, "gpt-5", None

    try:
        rate_limits = codex_loader.load_rate_limits()
    except Exception:
        if os.environ.get("USAGE_DEBUG") == "1":
            logger.warning("codex rate limits load failed", exc_info=True)
        rate_limits = None

    if rate_limits is None:
        rows = (
            _missing_row(_t(language, "session_label"), CODEX_COLOR, language),
            _missing_row(_t(language, "weekly_label"), CODEX_COLOR, language),
        )
        return rows, None, "unknown", None
    model = rate_limits.model or "unknown"

    now = time.time()
    try:
        codex_stale = codex_stale_state(
            rate_limits.updated_at,
            now,
            language,
        )
    except Exception:
        codex_stale = None
    codex_5h_pct = rate_limits.five_hour_pct
    if rate_limits.five_hour_pct is not None:
        burn_rate_trackers["codex_session"].record(now, rate_limits.five_hour_pct)
    if rate_limits.seven_day_pct is not None:
        burn_rate_trackers["codex_weekly"].record(now, rate_limits.seven_day_pct)
    session_title = _codex_window_title(
        rate_limits.five_hour_window_minutes, "session_label", language
    )
    # A slot with neither usage nor a window is absent (the free plan has no
    # weekly window) — leave its label blank rather than mislabel it "Weekly".
    weekly_absent = (
        rate_limits.seven_day_pct is None and rate_limits.seven_day_window_minutes is None
    )
    weekly_title = (
        ""
        if weekly_absent
        else _codex_window_title(
            rate_limits.seven_day_window_minutes, "weekly_label", language
        )
    )
    rows = (
        _quota_row(
            session_title,
            rate_limits.five_hour_pct,
            rate_limits.five_hour_resets_at,
            now,
            CODEX_COLOR,
            language,
            forecast_seconds=burn_rate_trackers["codex_session"].forecast_seconds(),
        ),
        _quota_row(
            weekly_title,
            rate_limits.seven_day_pct,
            rate_limits.seven_day_resets_at,
            now,
            CODEX_COLOR,
            language,
            forecast_seconds=burn_rate_trackers["codex_weekly"].forecast_seconds(
                window_seconds=WEEKLY_FORECAST_WINDOW_SECONDS,
                min_span_seconds=WEEKLY_FORECAST_MIN_SPAN_SECONDS,
            ),
            warning_max_seconds=24 * 3600,
        ),
    )
    return rows, codex_5h_pct, model, codex_stale


def build_popover_state(
    *,
    outcome: PollOutcome,
    codex_rows: tuple[QuotaRowState, QuotaRowState],
    projects: list[tuple[str, int, float | None]],
    projects_7d: list[tuple[str, int, float | None]],
    projects_30d: list[tuple[str, int, float | None]],
    projects_all: list[tuple[str, int, float | None]],
    language: str,
    group: int,
    burn_rate_trackers: dict[str, BurnRateTracker],
    today_text: str,
    statusline: dict[str, object],
    show_install_button: bool,
    hide_claude: bool,
    hide_codex: bool,
    codex_stale: CodexStaleState | None,
    history_error: HistoryLoadErrorState | None = None,
) -> PopoverState:
    now = time.time()
    group_name = _group_name(group, language)
    status_text = _t(
        language,
        "status_text",
        value=_status_message_value(outcome, "status_loading", language),
    )

    if outcome.state == PollState.SUCCESS and outcome.snapshot is not None:
        snapshot = outcome.snapshot
        if snapshot.current_percent is not None:
            burn_rate_trackers["claude_session"].record(
                snapshot.polled_at,
                float(snapshot.current_percent),
            )
        if snapshot.weekly_percent is not None:
            burn_rate_trackers["claude_weekly"].record(
                snapshot.polled_at,
                float(snapshot.weekly_percent),
            )
        claude_session = _quota_row(
            _t(language, "session_label"),
            float(snapshot.current_percent) if snapshot.current_percent is not None else None,
            snapshot.current_reset_at,
            now,
            CLAUDE_COLOR,
            language,
            forecast_seconds=burn_rate_trackers["claude_session"].forecast_seconds(),
        )
        claude_weekly = _quota_row(
            _t(language, "weekly_label"),
            float(snapshot.weekly_percent) if snapshot.weekly_percent is not None else None,
            snapshot.weekly_reset_at,
            now,
            CLAUDE_COLOR,
            language,
            forecast_seconds=burn_rate_trackers["claude_weekly"].forecast_seconds(
                window_seconds=WEEKLY_FORECAST_WINDOW_SECONDS,
                min_span_seconds=WEEKLY_FORECAST_MIN_SPAN_SECONDS,
            ),
            warning_max_seconds=24 * 3600,
        )
        status_value = _status_message_value(outcome, "status_synced", language)
        if snapshot.is_stale or snapshot.data_source != "hook":
            status_value = _status_message_value(outcome, "data_stale_hint", language)
        status_text = _t(
            language,
            "status_text",
            value=status_value,
        )
    else:
        claude_session = _missing_row(_t(language, "session_label"), CLAUDE_COLOR, language)
        claude_weekly = _missing_row(_t(language, "weekly_label"), CLAUDE_COLOR, language)
        if hide_claude:
            status_value = _t(language, "status_synced")
        else:
            status_value = _status_message_value(outcome, "status_no_data", language)
        status_text = _t(language, "status_text", value=status_value)

    return PopoverState(
        language=language,
        claude_session=claude_session,
        claude_weekly=claude_weekly,
        codex_session=codex_rows[0],
        codex_weekly=codex_rows[1],
        projects=projects,
        projects_7d=projects_7d,
        projects_30d=projects_30d,
        projects_all=projects_all,
        rate_text=_t(language, "rate_text", value=group_name),
        status_text=status_text,
        today_text=today_text,
        statusline=statusline,
        show_install_button=show_install_button,
        hide_claude=hide_claude,
        hide_codex=hide_codex,
        codex_stale=codex_stale,
        history_error=history_error,
    )


def _quota_row(
    title: str,
    pct: float | None,
    resets_at: float | None,
    now: float,
    color: tuple[float, float, float],
    language: str = "en",
    forecast_seconds: float | None = None,
    warning_max_seconds: float | None = None,
) -> QuotaRowState:
    if pct is None or resets_at is None:
        return _missing_row(title, color, language)
    pct = max(0.0, min(100.0, float(pct)))
    time_to_reset = resets_at - now
    warning_seconds: float | None = None
    if (
        forecast_seconds is not None
        and 0 < forecast_seconds < time_to_reset
        and (warning_max_seconds is None or forecast_seconds < warning_max_seconds)
        and pct >= WARNING_PERCENT_FLOOR
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
        reset_text = _t(language, "reset_in", time=format_human_time(time_to_reset, language))
    return QuotaRowState(
        title=title,
        percent=pct,
        percent_text=_t(language, "percent_used", value=_format_percent(pct)),
        reset_text=reset_text,
        color=_bar_color(pct, color),
        warning=warning,
        available=True,
    )


def _missing_row(
    title: str,
    color: tuple[float, float, float],
    language: str = "en",
) -> QuotaRowState:
    return QuotaRowState(
        title=title,
        percent=None,
        percent_text="--",
        reset_text=_t(language, "reset_placeholder"),
        color=color,
        available=False,
    )


def _format_percent(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return f"{value:.1f}"

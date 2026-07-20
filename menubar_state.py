# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from datetime import time as datetime_time
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

FILE_EVENT_REFRESH_MIN_INTERVAL_S = 30.0
HISTORY_FULL_SCAN_INTERVAL_S = 15 * 60.0


@dataclass(frozen=True, slots=True)
class FileEventRefreshDecision:
    refresh_now: bool
    trailing_delay: float | None


def file_event_refresh_decision(
    now: float,
    last_refresh_started_at: float | None,
    trailing_scheduled: bool,
    *,
    min_interval: float = FILE_EVENT_REFRESH_MIN_INTERVAL_S,
) -> FileEventRefreshDecision:
    """Decide whether a file event refreshes now or joins one trailing refresh."""
    if last_refresh_started_at is None or now - last_refresh_started_at >= min_interval:
        return FileEventRefreshDecision(refresh_now=True, trailing_delay=None)
    if trailing_scheduled:
        return FileEventRefreshDecision(refresh_now=False, trailing_delay=None)
    return FileEventRefreshDecision(
        refresh_now=False,
        trailing_delay=max(0.0, min_interval - (now - last_refresh_started_at)),
    )

logger = logging.getLogger(__name__)

CLAUDE_COLOR = (244 / 255, 145 / 255, 100 / 255)
CODEX_COLOR = (88 / 255, 214 / 255, 230 / 255)
AGY_COLOR = (107 / 255, 154 / 255, 1.0)
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


class AgyStaleState(TypedDict):
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
    agy_session: QuotaRowState
    agy_weekly: QuotaRowState
    agy_group_name: str
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
    hide_agy: bool = True
    codex_stale: CodexStaleState | None = None
    agy_stale: AgyStaleState | None = None
    card_order: tuple[str, ...] = ("claude", "codex", "agy")
    history_error: HistoryLoadErrorState | None = None
    # Talent-market panel payload (None for non-talent panels). Fetched from the
    # external instate-cli by talent_market_bridge, only when the active panel
    # is "talent_market", so classic/matrix users never spawn that subprocess.
    talent: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class HistorySourceScan:
    fingerprint: tuple[tuple[str, int, float], ...]
    claude_paths: tuple[Path, ...]
    codex_paths: tuple[Path, ...]


@dataclass(slots=True)
class HistorySourceIndex:
    file_stats: dict[Path, tuple[int, int]]
    last_full_scan_at: float


class HistorySourceTracker:
    """Maintain the history source index without depending on PyObjC."""

    def __init__(self, *, incremental_enabled: bool = False) -> None:
        self._incremental_enabled = incremental_enabled
        self._index: HistorySourceIndex | None = None
        self._dirty_paths: set[Path] = set()
        self._needs_full_scan = False
        self._lock = threading.Lock()

    def set_incremental_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._incremental_enabled = enabled

    def record_changes(
        self,
        paths: set[Path] | frozenset[Path],
        *,
        needs_full_scan: bool = False,
    ) -> None:
        with self._lock:
            self._dirty_paths.update(paths)
            self._needs_full_scan = self._needs_full_scan or needs_full_scan

    def scan(self, *, now: float | None = None) -> HistorySourceScan:
        current_time = time.monotonic() if now is None else now
        with self._lock:
            incremental_enabled = self._incremental_enabled
            dirty_paths = set(self._dirty_paths)
            needs_full_scan = self._needs_full_scan
            self._dirty_paths.difference_update(dirty_paths)
            if needs_full_scan:
                self._needs_full_scan = False
            index = self._index

        if (
            not incremental_enabled
            or index is None
            or needs_full_scan
            or current_time - index.last_full_scan_at >= HISTORY_FULL_SCAN_INTERVAL_S
        ):
            index = _build_history_source_index(current_time)
        else:
            # The sqlite sources live outside the FSEvents-watched directories,
            # so re-stat them every scan to keep their fingerprint fresh.
            index = _update_history_source_index(
                index,
                dirty_paths | set(_history_file_sources()),
            )

        with self._lock:
            self._index = index
        return _history_scan_from_index(index)


def history_cache_needs_reload(
    previous_fingerprint: tuple[tuple[str, int, float], ...] | None,
    current_fingerprint: tuple[tuple[str, int, float], ...],
    *,
    has_cached_result: bool,
) -> bool:
    """Decide whether Windows history projections need to be rebuilt."""
    return not has_cached_result or previous_fingerprint != current_fingerprint


def _jsonl_paths(root: Path) -> tuple[Path, ...]:
    if not root.exists():
        return ()
    try:
        return tuple(root.rglob("*.jsonl"))
    except OSError:
        return ()


def _history_directory_sources() -> tuple[Path, Path, Path]:
    return (
        CLAUDE_PROJECTS_DIR,
        codex_loader.SESSIONS_DIR,
        codex_loader.ARCHIVED_SESSIONS_DIR,
    )


def _history_file_sources() -> tuple[Path, Path, Path, Path]:
    return (
        codex_loader.LOGS_DB,
        Path.home() / ".codex" / "logs_2.sqlite-wal",
        codex_loader.STATE_DB,
        Path.home() / ".codex" / "state_5.sqlite-wal",
    )


def _stat_index_entry(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


def _build_history_source_index(now: float) -> HistorySourceIndex:
    file_stats: dict[Path, tuple[int, int]] = {}
    for root in _history_directory_sources():
        for path in _jsonl_paths(root):
            entry = _stat_index_entry(path)
            if entry is not None:
                file_stats[path] = entry
    for path in _history_file_sources():
        entry = _stat_index_entry(path)
        if entry is not None:
            file_stats[path] = entry
    return HistorySourceIndex(file_stats=file_stats, last_full_scan_at=now)


def _is_indexed_history_path(path: Path) -> bool:
    if path in _history_file_sources():
        return True
    if path.suffix != ".jsonl":
        return False
    return any(path == root or root in path.parents for root in _history_directory_sources())


def _update_history_source_index(
    index: HistorySourceIndex,
    dirty_paths: set[Path],
) -> HistorySourceIndex:
    file_stats = dict(index.file_stats)
    for path in dirty_paths:
        if not _is_indexed_history_path(path):
            continue
        entry = _stat_index_entry(path)
        if entry is None:
            file_stats.pop(path, None)
        else:
            file_stats[path] = entry
    return HistorySourceIndex(file_stats, index.last_full_scan_at)


def _source_fingerprint_from_index(
    source: Path,
    file_stats: dict[Path, tuple[int, int]],
) -> tuple[str, int, float]:
    if source in _history_file_sources():
        entry = file_stats.get(source)
        return (str(source), int(entry is not None), 0.0 if entry is None else entry[0] / 1e9)
    mtimes = [
        entry[0]
        for path, entry in file_stats.items()
        if path == source or source in path.parents
    ]
    return (str(source), len(mtimes), max(mtimes, default=0) / 1e9)


def _history_scan_from_index(index: HistorySourceIndex) -> HistorySourceScan:
    directory_sources = _history_directory_sources()
    file_sources = _history_file_sources()
    source_fingerprint = tuple(
        _source_fingerprint_from_index(source, index.file_stats)
        for source in (*directory_sources, *file_sources)
    )
    file_fingerprint = tuple(
        (str(path), entry[1], entry[0] / 1e9)
        for path, entry in sorted(index.file_stats.items(), key=lambda item: str(item[0]))
    )
    fingerprint = source_fingerprint + file_fingerprint
    claude_root, sessions_root, archived_root = directory_sources
    claude_paths = tuple(
        path
        for path in index.file_stats
        if path.suffix == ".jsonl" and (path == claude_root or claude_root in path.parents)
    )
    codex_paths = tuple(
        path
        for path in index.file_stats
        if path.suffix == ".jsonl"
        and any(path == root or root in path.parents for root in (sessions_root, archived_root))
    )
    return HistorySourceScan(fingerprint, claude_paths, codex_paths)


def history_source_scan() -> HistorySourceScan:
    return _history_scan_from_index(_build_history_source_index(time.monotonic()))


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


def project_rows_for_windows(
    entries: list[UsageEntry],
    *,
    now: datetime | None = None,
) -> tuple[
    list[tuple[str, int, float | None]],
    list[tuple[str, int, float | None]],
    list[tuple[str, int, float | None]],
    list[tuple[str, int, float | None]],
]:
    """Aggregate the four project windows in one pass over the history."""
    current_time = datetime.now(UTC) if now is None else now
    local_now = current_time.astimezone()
    local_today = local_now.date()
    local_tz = local_now.tzinfo
    assert local_tz is not None
    today_start = datetime.combine(local_today, datetime_time.min, tzinfo=local_tz).astimezone(
        UTC
    )
    tomorrow_start = datetime.combine(
        local_today + timedelta(days=1), datetime_time.min, tzinfo=local_tz
    ).astimezone(UTC)
    cutoff_7d = current_time - timedelta(hours=168)
    cutoff_30d = current_time - timedelta(hours=720)
    aggregates_24h: dict[str, list[float]] = {}
    aggregates_7d: dict[str, list[float]] = {}
    aggregates_30d: dict[str, list[float]] = {}
    aggregates_all: dict[str, list[float]] = {}

    for entry in entries:
        tokens = entry.total_tokens
        cost = calculate_cost(entry)
        _add_project_usage(aggregates_all, entry.project, tokens, cost)
        if entry.timestamp >= cutoff_30d:
            _add_project_usage(aggregates_30d, entry.project, tokens, cost)
        if entry.timestamp >= cutoff_7d:
            _add_project_usage(aggregates_7d, entry.project, tokens, cost)
        if today_start <= entry.timestamp < tomorrow_start:
            _add_project_usage(aggregates_24h, entry.project, tokens, cost)

    return (
        _rank_project_rows(aggregates_24h),
        _rank_project_rows(aggregates_7d),
        _rank_project_rows(aggregates_30d),
        _rank_project_rows(aggregates_all),
    )


def _add_project_usage(
    aggregates: dict[str, list[float]], project: str, tokens: int, cost: float
) -> None:
    bucket = aggregates.setdefault(project, [0.0, 0.0])
    bucket[0] += tokens
    bucket[1] += cost


def _rank_project_rows(
    aggregates: dict[str, list[float]],
) -> list[tuple[str, int, float | None]]:
    ranked = sorted(
        aggregates.items(),
        key=lambda item: (int(item[1][0]), item[0]),
        reverse=True,
    )
    return [(project, int(tokens), cost) for project, (tokens, cost) in ranked[:3]]


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
    codex_5h_pct = (
        rate_limits.five_hour_pct
        if rate_limits.five_hour_pct is not None
        else rate_limits.seven_day_pct
    )
    if rate_limits.five_hour_pct is not None:
        burn_rate_trackers["codex_session"].record(now, rate_limits.five_hour_pct)
    if rate_limits.seven_day_pct is not None:
        burn_rate_trackers["codex_weekly"].record(now, rate_limits.seven_day_pct)
    session_absent = (
        rate_limits.five_hour_pct is None and rate_limits.five_hour_window_minutes is None
    )
    session_title = (
        ""
        if session_absent
        else _codex_window_title(
            rate_limits.five_hour_window_minutes, "session_label", language
        )
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
    agy_rows: tuple[QuotaRowState, QuotaRowState],
    agy_group_name: str,
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
    hide_agy: bool,
    codex_stale: CodexStaleState | None,
    agy_stale: AgyStaleState | None,
    card_order: tuple[str, ...] = ("claude", "codex", "agy"),
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
        agy_session=agy_rows[0],
        agy_weekly=agy_rows[1],
        agy_group_name=agy_group_name,
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
        hide_agy=hide_agy,
        codex_stale=codex_stale,
        agy_stale=agy_stale,
        card_order=card_order,
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

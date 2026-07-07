# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import contextlib
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import tempfile
import time
from typing import Any, NotRequired, TypedDict, cast

import codex_loader
from analyzer import ai_updates_loader
from analyzer import persona_loader
from analyzer import subscription
from adapters import claude, codex
from adapters.types import AgentInfo, UsageEntry
from pricing import calculate_cost, is_model_priced

from .aggregator import aggregate_sessions
from . import diagnoser

logger = logging.getLogger(__name__)

AGENT_LOADERS = {"claude-code": claude, "codex": codex}
AGENT_NAMES = {"claude-code": "Claude Code", "codex": "Codex"}
_YEAR_WEEKS = 53
YEAR_CACHE_PATH = Path(os.path.expanduser("~/.usage/year_cache.json"))
YEAR_LEDGER_PATH = YEAR_CACHE_PATH.with_name("year_ledger.json")
YEAR_CACHE_TTL_SECONDS = 6 * 3600
_YEAR_CACHE_SCHEMA = 1
_YEAR_LEDGER_SCHEMA = 1
_YEAR_LEDGER_TRIM_BUFFER_DAYS = 60


class _YearDay(TypedDict):
    total_tokens: int
    cost: float
    model_tokens: dict[str, int]
    project_tokens: dict[str, int]
    agent_tokens: dict[str, int]
    sessions: int


class _YearLedger(TypedDict):
    schema_version: int
    days: dict[str, _YearDay]


class SummaryReportData(TypedDict):
    total_tokens: int
    cost_usd: float
    sessions: int
    messages: int
    active_days: int
    total_days: int


class AgentReportRow(TypedDict):
    id: str
    name: str
    tokens: int
    cost: float
    sessions: int
    messages: int
    pct: float


class ProjectReportRow(TypedDict):
    project: str
    tokens: int
    cost: float
    sessions: int
    pct: float


class ModelReportRow(TypedDict):
    model: str
    tokens: int
    cost: float
    cost_known: bool
    pct: float
    top_project: str | None


class DailyTrendPoint(TypedDict):
    date: str
    tokens: int
    cost: float


class TopSessionReportRow(TypedDict):
    start_time: str
    project: str
    model: str
    duration_min: float
    tokens: int
    cost: float


class ComparisonReportData(TypedDict):
    period: str
    has_prev: bool
    prev_tokens: int
    prev_cost: float
    prev_projects: list[str]
    prev_model_share: dict[str, float]


class PersonaReportData(TypedDict):
    hour_histogram: list[int]
    recent_titles: list[str]
    top_projects: NotRequired[list[tuple[str, int]]]


class ContributionDay(TypedDict):
    date: str
    tokens: int
    level: int


class BusiestDay(TypedDict):
    date: str
    tokens: int


class ContributionReportData(TypedDict):
    weeks: list[list[ContributionDay]]
    start: str
    end: str
    max_tokens: int
    total_tokens: int
    active_days: int
    current_streak: int
    longest_streak: int
    busiest_day: BusiestDay | None


class WrappedReportData(TypedDict):
    year_label: str
    total_tokens: int
    total_cost: float
    active_days: int
    total_sessions: int
    top_model: str | None
    top_project: str | None
    busiest_day: BusiestDay | None
    longest_streak: int
    claude_tokens: int
    codex_tokens: int
    beast: str | None


class YearReportData(TypedDict):
    contribution: ContributionReportData
    wrapped: WrappedReportData


class ReportData(TypedDict):
    period: str
    period_label: str
    date_from: str
    date_to: str
    summary: SummaryReportData
    by_agent: list[AgentReportRow]
    by_project: list[ProjectReportRow]
    by_model: list[ModelReportRow]
    daily_trend: list[DailyTrendPoint]
    top_sessions: list[TopSessionReportRow]
    comparison: ComparisonReportData
    subscriptions: list[dict[str, str | None]]
    persona: PersonaReportData | None
    ai_updates: list[dict[str, Any]] | None
    contribution: ContributionReportData
    wrapped: WrappedReportData


@dataclass(frozen=True)
class _PeriodSpec:
    persona_days: int
    has_comparison: bool


# 每個時間範圍的所有屬性集中在這一張表 —— 加新範圍只改這裡，
# 不再散落到多個函式各維護一份名單（那正是 last30 漏掉前期比較的根因）。
PERIOD_SPECS: dict[str, _PeriodSpec] = {
    "today": _PeriodSpec(persona_days=1, has_comparison=False),
    "week": _PeriodSpec(persona_days=7, has_comparison=True),
    "last7": _PeriodSpec(persona_days=7, has_comparison=True),
    "month": _PeriodSpec(persona_days=30, has_comparison=True),
    # last30 刻意不做前期比較：它是預設/最常開的報告，做比較要多載一倍歷史
    # （v0.11.6「faster Codex reports」的效能取捨，由 test_report_last30_uses_expected_codex_hours_back 守護）。
    "last30": _PeriodSpec(persona_days=30, has_comparison=False),
    "all": _PeriodSpec(persona_days=3650, has_comparison=False),
}
# 未知 period 的保底：與收斂前各名單對未列出 period 的行為一致。
_DEFAULT_PERIOD_SPEC = _PeriodSpec(persona_days=30, has_comparison=False)


def _period_spec(period: str) -> _PeriodSpec:
    return PERIOD_SPECS.get(period, _DEFAULT_PERIOD_SPEC)


def _entry_date(entry: UsageEntry) -> date:
    ts = entry.timestamp
    if ts.tzinfo:
        ts = ts.astimezone()
    return ts.date()


def _period_bounds(period: str, today: date) -> tuple[date | None, date]:
    if period == "today":
        return today, today
    if period == "week":
        return today - timedelta(days=today.weekday()), today
    if period == "last7":
        return today - timedelta(days=6), today
    if period == "month":
        return today.replace(day=1), today
    if period == "all":
        return None, today
    if period == "last30":
        return today - timedelta(days=29), today
    return today.replace(day=1), today


def _load_agent_entries(
    agent: AgentInfo,
    hours_back: int = 0,
) -> list[UsageEntry]:
    if hours_back > 0 and agent.id == "claude-code":
        return _load_recent_claude_entries(hours_back)
    if agent.id == "codex":
        return _load_codex_entries(hours_back)
    loader = AGENT_LOADERS.get(agent.id)
    if loader is None:
        return []
    entries: list[UsageEntry] = loader.load_entries(hours_back=hours_back)
    for entry in entries:
        entry.agent_id = agent.id
    return entries


def _load_recent_claude_entries(hours_back: int) -> list[UsageEntry]:
    entries: list[UsageEntry] = []
    seen: set[str] = set()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    cutoff_ts = cutoff.timestamp()
    jobs: list[tuple[Path, Path]] = []
    for base_dir in claude.get_claude_dirs():
        base = Path(base_dir)
        if not base.is_dir():
            continue
        for jsonl_path in base.rglob("*.jsonl"):
            try:
                if jsonl_path.stat().st_mtime < cutoff_ts:
                    continue
            except OSError:
                continue
            jobs.append((jsonl_path, base))
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = executor.map(lambda job: _parse_claude_file(job[0], job[1], cutoff), jobs)
        for parsed in results:
            for entry in parsed:
                if entry.dedup_key in seen:
                    continue
                seen.add(entry.dedup_key)
                entries.append(entry)
    entries.sort(key=lambda entry: entry.timestamp)
    return entries


def _parse_claude_file(path: Path, base: Path, cutoff: datetime) -> list[UsageEntry]:
    parsed: list[UsageEntry] = []
    local_seen: set[str] = set()
    fallback_project = claude.extract_project_from_dir(path, base)
    claude.parse_jsonl(path, fallback_project, parsed, local_seen, cutoff)
    return parsed


def _load_codex_entries(hours_back: int) -> list[UsageEntry]:
    return [
        UsageEntry(
            timestamp=entry.timestamp,
            session_id=entry.session_id,
            message_id=entry.message_id,
            request_id=entry.request_id,
            model=entry.model,
            input_tokens=entry.input_tokens,
            output_tokens=entry.output_tokens,
            cache_creation_tokens=entry.cache_creation_tokens,
            cache_read_tokens=entry.cache_read_tokens,
            cost_usd=entry.cost_usd,
            project=entry.project,
            agent_id="codex",
            message_count=getattr(entry, "message_count", 1),
        )
        for entry in codex_loader.load_entries(hours_back=hours_back)
    ]


def _pct(value: int, total: int) -> float:
    return round((value / total * 100), 1) if total else 0.0


def _round_cost(value: float) -> float:
    return round(value, 4)


def _load_persona_for_period(period: str) -> PersonaReportData | None:
    days_back = _period_spec(period).persona_days
    try:
        profile = persona_loader.load_profile(days_back)
    except Exception:
        return None
    return {
        "hour_histogram": list(profile.hour_histogram),
        "recent_titles": list(profile.recent_titles),
    }


def _empty_comparison(period: str) -> ComparisonReportData:
    return {
        "period": period,
        "has_prev": False,
        "prev_tokens": 0,
        "prev_cost": 0.0,
        "prev_projects": [],
        "prev_model_share": {},
    }


def _build_comparison(
    raw_entries: list[UsageEntry],
    period: str,
    date_from: date,
    date_to: date,
) -> ComparisonReportData:
    if not _period_spec(period).has_comparison:
        return _empty_comparison(period)

    total_days = (date_to - date_from).days + 1
    prev_date_to = date_from - timedelta(days=1)
    prev_date_from = prev_date_to - timedelta(days=total_days - 1)
    prev_entries = [
        entry
        for entry in raw_entries
        if prev_date_from <= _entry_date(entry) <= prev_date_to
    ]

    prev_tokens = sum(entry.total_tokens for entry in prev_entries)
    prev_cost = sum(calculate_cost(entry) for entry in prev_entries)
    prev_projects = sorted(
        {entry.project or "unknown" for entry in prev_entries}
    )
    model_tokens: dict[str, int] = defaultdict(int)
    for entry in prev_entries:
        model_tokens[entry.model or "unknown"] += entry.total_tokens
    prev_model_share = {
        model: _pct(tokens, prev_tokens)
        for model, tokens in sorted(model_tokens.items())
    }

    return {
        "period": period,
        "has_prev": bool(prev_entries),
        "prev_tokens": prev_tokens,
        "prev_cost": _round_cost(prev_cost),
        "prev_projects": prev_projects,
        "prev_model_share": prev_model_share,
    }


def _top_project(project_tokens: dict[str, int]) -> str | None:
    if not project_tokens:
        return None
    return max(project_tokens.items(), key=lambda item: item[1])[0]


def _top_name(bucket: dict[str, int]) -> str | None:
    if not bucket:
        return None
    return sorted(bucket.items(), key=lambda item: (-item[1], item[0]))[0][0]


def _streaks(
    daily_tokens: dict[date, int],
    start: date,
    end: date,
) -> tuple[int, int]:
    current_streak = 0
    cursor = end
    while cursor >= start and daily_tokens.get(cursor, 0) > 0:
        current_streak += 1
        cursor -= timedelta(days=1)

    longest_streak = 0
    streak = 0
    cursor = start
    while cursor <= end:
        if daily_tokens.get(cursor, 0) > 0:
            streak += 1
            longest_streak = max(longest_streak, streak)
        else:
            streak = 0
        cursor += timedelta(days=1)
    return current_streak, longest_streak


def _contribution_thresholds(active_tokens: list[int]) -> list[int]:
    sorted_tokens = sorted(tokens for tokens in active_tokens if tokens > 0)
    if not sorted_tokens:
        return []

    last_index = len(sorted_tokens) - 1
    return [
        sorted_tokens[min(last_index, (len(sorted_tokens) * quartile - 1) // 4)]
        for quartile in range(1, 5)
    ]


def _contribution_level(tokens: int, thresholds: list[int]) -> int:
    if tokens <= 0 or not thresholds:
        return 0
    for level, threshold in enumerate(thresholds, start=1):
        if tokens <= threshold:
            return level
    return 4


def _empty_year_ledger() -> _YearLedger:
    return {
        "schema_version": _YEAR_LEDGER_SCHEMA,
        "days": {},
    }


def _token_map(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    tokens: dict[str, int] = {}
    for key, raw_tokens in value.items():
        if (
            isinstance(key, str)
            and isinstance(raw_tokens, int)
            and not isinstance(raw_tokens, bool)
        ):
            tokens[key] = raw_tokens
    return tokens


def _year_day_from_json(value: object) -> _YearDay | None:
    if not isinstance(value, dict):
        return None
    total_tokens = value.get("total_tokens")
    cost = value.get("cost")
    sessions = value.get("sessions")
    if (
        not isinstance(total_tokens, int)
        or isinstance(total_tokens, bool)
        or not isinstance(cost, int | float)
        or isinstance(cost, bool)
        or not isinstance(sessions, int)
        or isinstance(sessions, bool)
    ):
        return None
    return {
        "total_tokens": total_tokens,
        "cost": float(cost),
        "model_tokens": _token_map(value.get("model_tokens")),
        "project_tokens": _token_map(value.get("project_tokens")),
        "agent_tokens": _token_map(value.get("agent_tokens")),
        "sessions": sessions,
    }


def _read_year_ledger() -> _YearLedger:
    try:
        with YEAR_LEDGER_PATH.open(encoding="utf-8") as file:
            ledger = json.load(file)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        if os.environ.get("USAGE_DEBUG") == "1":
            logger.warning(
                "failed to read year ledger %s",
                YEAR_LEDGER_PATH,
                exc_info=True,
            )
        return _empty_year_ledger()

    if not isinstance(ledger, dict):
        return _empty_year_ledger()
    if ledger.get("schema_version") != _YEAR_LEDGER_SCHEMA:
        return _empty_year_ledger()
    raw_days = ledger.get("days")
    if not isinstance(raw_days, dict):
        return _empty_year_ledger()

    days: dict[str, _YearDay] = {}
    for day_key, raw_day in raw_days.items():
        if not isinstance(day_key, str):
            continue
        try:
            date.fromisoformat(day_key)
        except ValueError:
            continue
        day = _year_day_from_json(raw_day)
        if day is not None:
            days[day_key] = day
    return {
        "schema_version": _YEAR_LEDGER_SCHEMA,
        "days": days,
    }


def _write_year_ledger(ledger: _YearLedger) -> None:
    tmp_path: str | None = None
    try:
        YEAR_LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=YEAR_LEDGER_PATH.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(ledger, file, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp_path, YEAR_LEDGER_PATH)
        tmp_path = None
    except Exception as exc:
        if os.environ.get("USAGE_DEBUG") == "1":
            logger.warning("failed to write year ledger %s: %s", YEAR_LEDGER_PATH, exc)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)


def _new_year_day() -> _YearDay:
    return {
        "total_tokens": 0,
        "cost": 0.0,
        "model_tokens": {},
        "project_tokens": {},
        "agent_tokens": {},
        "sessions": 0,
    }


def _aggregate_year_days(entries: list[UsageEntry]) -> dict[str, _YearDay]:
    days: dict[str, _YearDay] = {}
    session_ids: dict[str, set[str]] = defaultdict(set)
    for entry in entries:
        day_key = _entry_date(entry).isoformat()
        day = days.setdefault(day_key, _new_year_day())
        entry_tokens = entry.total_tokens
        day["total_tokens"] += entry_tokens
        day["cost"] += calculate_cost(entry)
        day["model_tokens"][entry.model or "unknown"] = (
            day["model_tokens"].get(entry.model or "unknown", 0) + entry_tokens
        )
        day["project_tokens"][entry.project or "unknown"] = (
            day["project_tokens"].get(entry.project or "unknown", 0) + entry_tokens
        )
        day["agent_tokens"][entry.agent_id or "unknown"] = (
            day["agent_tokens"].get(entry.agent_id or "unknown", 0) + entry_tokens
        )
        session_ids[day_key].add(entry.session_id)

    for day_key, ids in session_ids.items():
        days[day_key]["sessions"] = len(ids)
    return days


def _merge_year_ledger(
    current_days: dict[str, _YearDay],
    *,
    trim_before: date,
) -> _YearLedger:
    ledger = _read_year_ledger()
    days = ledger["days"]
    for day_key, current_day in current_days.items():
        ledger_day = days.get(day_key)
        if ledger_day is None or current_day["total_tokens"] >= ledger_day["total_tokens"]:
            days[day_key] = current_day

    ledger["days"] = {
        day_key: day
        for day_key, day in days.items()
        if date.fromisoformat(day_key) >= trim_before
    }
    _write_year_ledger(ledger)
    return ledger


def _build_year_output_from_ledger(
    ledger: _YearLedger,
    *,
    grid_start: date,
    grid_end: date,
    today: date,
) -> YearReportData:
    daily_tokens: dict[date, int] = {}
    model_tokens: dict[str, int] = defaultdict(int)
    project_tokens: dict[str, int] = defaultdict(int)
    agent_tokens: dict[str, int] = defaultdict(int)
    total_tokens = 0
    total_cost = 0.0
    total_sessions = 0

    for day_key, day in ledger["days"].items():
        day_date = date.fromisoformat(day_key)
        if not grid_start <= day_date <= today:
            continue
        daily_tokens[day_date] = day["total_tokens"]
        total_tokens += day["total_tokens"]
        total_cost += day["cost"]
        total_sessions += day["sessions"]
        for model, tokens in day["model_tokens"].items():
            model_tokens[model] += tokens
        for project, tokens in day["project_tokens"].items():
            project_tokens[project] += tokens
        for agent_id, tokens in day["agent_tokens"].items():
            agent_tokens[agent_id] += tokens

    active_days = sum(1 for tokens in daily_tokens.values() if tokens > 0)
    contribution_thresholds = _contribution_thresholds(list(daily_tokens.values()))
    max_tokens = max(daily_tokens.values(), default=0)
    busiest_day: BusiestDay | None = None
    if max_tokens > 0:
        busiest_date = min(
            day for day, tokens in daily_tokens.items() if tokens == max_tokens
        )
        busiest_day = {
            "date": busiest_date.isoformat(),
            "tokens": max_tokens,
        }

    current_streak, longest_streak = _streaks(daily_tokens, grid_start, today)

    weeks: list[list[ContributionDay]] = []
    cursor = grid_start
    while cursor <= grid_end:
        week: list[ContributionDay] = []
        for _ in range(7):
            tokens = daily_tokens.get(cursor, 0) if cursor <= today else 0
            week.append(
                {
                    "date": cursor.isoformat(),
                    "tokens": tokens,
                    "level": _contribution_level(tokens, contribution_thresholds),
                }
            )
            cursor += timedelta(days=1)
        weeks.append(week)

    claude_tokens = agent_tokens.get("claude-code", 0)
    codex_tokens = agent_tokens.get("codex", 0)
    beast = None
    if total_tokens > 0:
        beast = "phoenix" if claude_tokens >= codex_tokens else "dragon"

    contribution: ContributionReportData = {
        "weeks": weeks,
        "start": grid_start.isoformat(),
        "end": today.isoformat(),
        "max_tokens": max_tokens,
        "total_tokens": total_tokens,
        "active_days": active_days,
        "current_streak": current_streak,
        "longest_streak": longest_streak,
        "busiest_day": busiest_day,
    }
    wrapped: WrappedReportData = {
        "year_label": str(today.year),
        "total_tokens": total_tokens,
        "total_cost": _round_cost(total_cost),
        "active_days": active_days,
        "total_sessions": total_sessions,
        "top_model": _top_name(model_tokens),
        "top_project": _top_name(project_tokens),
        "busiest_day": busiest_day,
        "longest_streak": longest_streak,
        "claude_tokens": claude_tokens,
        "codex_tokens": codex_tokens,
        "beast": beast,
    }
    return {
        "contribution": contribution,
        "wrapped": wrapped,
    }


def build_year_data(agents: list[AgentInfo]) -> YearReportData:
    today = datetime.now().astimezone().date()
    grid_end = today + timedelta(days=(5 - today.weekday()) % 7)
    grid_start = grid_end - timedelta(days=_YEAR_WEEKS * 7 - 1)
    hours_back = ((today - grid_start).days + 2) * 24

    raw_entries: list[UsageEntry] = []
    for agent in agents:
        raw_entries.extend(_load_agent_entries(agent, hours_back))

    entries = [
        entry
        for entry in raw_entries
        if grid_start <= _entry_date(entry) <= today
    ]

    current_days = _aggregate_year_days(entries)
    ledger = _merge_year_ledger(
        current_days,
        trim_before=grid_start - timedelta(days=_YEAR_LEDGER_TRIM_BUFFER_DAYS),
    )
    return _build_year_output_from_ledger(
        ledger,
        grid_start=grid_start,
        grid_end=grid_end,
        today=today,
    )


def _load_year_data_cached(agents: list[AgentInfo]) -> YearReportData:
    cached = _read_year_cache()
    if cached is not None:
        return cast(YearReportData, cached)

    data = build_year_data(agents)
    _write_year_cache(data)
    return data


def _read_year_cache() -> dict[str, Any] | None:
    try:
        with YEAR_CACHE_PATH.open(encoding="utf-8") as file:
            cache = json.load(file)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        if os.environ.get("USAGE_DEBUG") == "1":
            logger.warning("failed to read year cache %s", YEAR_CACHE_PATH, exc_info=True)
        return None

    if not isinstance(cache, dict):
        return None
    if cache.get("schema_version") != _YEAR_CACHE_SCHEMA:
        return None

    cached_at = cache.get("cached_at")
    if not isinstance(cached_at, int | float):
        return None
    if (time.time() - float(cached_at)) > YEAR_CACHE_TTL_SECONDS:
        return None

    data = cache.get("data")
    return data if isinstance(data, dict) else None


def _write_year_cache(data: YearReportData) -> None:
    tmp_path: str | None = None
    try:
        YEAR_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=YEAR_CACHE_PATH.parent, suffix=".tmp")
        payload = {
            "schema_version": _YEAR_CACHE_SCHEMA,
            "cached_at": time.time(),
            "data": data,
        }
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp_path, YEAR_CACHE_PATH)
        tmp_path = None
    except Exception as exc:
        if os.environ.get("USAGE_DEBUG") == "1":
            logger.warning("failed to write year cache %s: %s", YEAR_CACHE_PATH, exc)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)


def serialize_diagnosis(
    result: diagnoser.DiagnosisResult,
    *,
    total_corpus_tokens: int,
) -> dict[str, Any]:
    waste_pct = (
        result.total_waste_tokens / total_corpus_tokens * 100
        if total_corpus_tokens
        else 0.0
    )
    fixable_pct = (
        result.fixable_waste_tokens / total_corpus_tokens * 100
        if total_corpus_tokens
        else 0.0
    )
    return {
        "has_data": result.has_data,
        "total_waste_usd": _round_cost(result.total_waste_usd),
        "monthly_savings_estimate_usd": _round_cost(
            result.monthly_savings_estimate_usd
        ),
        "total_waste_tokens": int(result.total_waste_tokens),
        "fixable_waste_tokens": int(result.fixable_waste_tokens),
        "total_corpus_tokens": int(total_corpus_tokens),
        "waste_pct": round(waste_pct, 1),
        "fixable_pct": round(fixable_pct, 1),
        "findings": [
            {
                "severity": finding.severity,
                "kind": finding.kind,
                "headline_plain": finding.headline_plain,
                "headline_detail": finding.headline_detail,
                "estimated_waste_usd": _round_cost(finding.estimated_waste_usd),
                "estimated_waste_tokens": int(finding.estimated_waste_tokens),
                "items": finding.items,
            }
            for finding in result.findings
        ],
        "suggested_claudeignore": result.suggested_claudeignore,
    }


def build_report_data(agents: list[AgentInfo], period: str = "month") -> ReportData:
    """
    period: "today" | "week" | "last7" | "month" | "all"
    回傳 dict，包含：
      period_label: str
      date_from: str
      date_to: str
      summary: dict
      by_agent: list[dict]
      by_project: list[dict]
      by_model: list[dict]
      daily_trend: list[dict]
      top_sessions: list[dict]
    """
    today = datetime.now().astimezone().date()
    date_from, date_to = _period_bounds(period, today)
    hours_back = 0 if date_from is None else ((date_to - date_from).days + 2) * 24
    if date_from is not None and _period_spec(period).has_comparison:
        total_days_for_comparison = (date_to - date_from).days + 1
        prev_date_from = date_from - timedelta(days=total_days_for_comparison)
        hours_back = ((date_to - prev_date_from).days + 2) * 24

    raw_entries: list[UsageEntry] = []
    for agent in agents:
        raw_entries.extend(_load_agent_entries(agent, hours_back))

    if date_from is None and raw_entries:
        date_from = min(_entry_date(entry) for entry in raw_entries)
    if date_from is None:
        date_from = date_to

    entries = [
        entry
        for entry in raw_entries
        if date_from <= _entry_date(entry) <= date_to
    ]

    total_tokens = sum(entry.total_tokens for entry in entries)
    total_cost = 0.0
    session_ids = {entry.session_id for entry in entries}
    active_dates = {_entry_date(entry) for entry in entries}
    total_days = (date_to - date_from).days + 1
    comparison = _build_comparison(raw_entries, period, date_from, date_to)

    by_agent_totals: dict[str, dict[str, Any]] = defaultdict(lambda: {"tokens": 0, "cost": 0.0, "sessions": set(), "messages": 0})
    by_project_totals: dict[str, dict[str, Any]] = defaultdict(lambda: {"tokens": 0, "cost": 0.0, "sessions": set()})
    by_model_totals: dict[str, dict[str, Any]] = defaultdict(lambda: {"tokens": 0, "cost": 0.0})
    by_model_project: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    daily_totals: dict[date, dict[str, Any]] = defaultdict(lambda: {"tokens": 0, "cost": 0.0})

    for entry in entries:
        cost = calculate_cost(entry)
        total_cost += cost
        agent_totals = by_agent_totals[entry.agent_id or "unknown"]
        agent_totals["tokens"] += entry.total_tokens
        agent_totals["cost"] += cost
        agent_totals["sessions"].add(entry.session_id)
        agent_totals["messages"] += entry.message_count

        project = by_project_totals[entry.project or "unknown"]
        project["tokens"] += entry.total_tokens
        project["cost"] += cost
        project["sessions"].add(entry.session_id)

        model = by_model_totals[entry.model or "unknown"]
        model["tokens"] += entry.total_tokens
        model["cost"] += cost
        by_model_project[entry.model or "unknown"][entry.project or "unknown"] += (
            entry.total_tokens
        )

        day = daily_totals[_entry_date(entry)]
        day["tokens"] += entry.total_tokens
        day["cost"] += cost

    by_agent: list[AgentReportRow] = [
        {
            "id": agent_id,
            "name": AGENT_NAMES.get(agent_id, agent_id),
            "tokens": data["tokens"],
            "cost": _round_cost(data["cost"]),
            "sessions": len(data["sessions"]),
            "messages": data["messages"],
            "pct": _pct(data["tokens"], total_tokens),
        }
        for agent_id, data in by_agent_totals.items()
    ]
    by_agent.sort(key=lambda item: item["tokens"], reverse=True)

    by_project: list[ProjectReportRow] = [
        {
            "project": project,
            "tokens": data["tokens"],
            "cost": _round_cost(data["cost"]),
            "sessions": len(data["sessions"]),
            "pct": _pct(data["tokens"], total_tokens),
        }
        for project, data in by_project_totals.items()
    ]
    by_project.sort(key=lambda item: item["tokens"], reverse=True)

    by_model: list[ModelReportRow] = [
        {
            "model": model,
            "tokens": data["tokens"],
            "cost": _round_cost(data["cost"]),
            "cost_known": is_model_priced(model),
            "pct": _pct(data["tokens"], total_tokens),
            "top_project": _top_project(by_model_project.get(model, {})),
        }
        for model, data in by_model_totals.items()
    ]
    by_model.sort(key=lambda item: item["tokens"], reverse=True)

    daily_trend: list[DailyTrendPoint] = []
    cursor = date_from
    while cursor <= date_to:
        day = daily_totals[cursor]
        daily_trend.append({
            "date": cursor.isoformat(),
            "tokens": day["tokens"],
            "cost": _round_cost(day["cost"]),
        })
        cursor += timedelta(days=1)

    top_sessions: list[TopSessionReportRow] = []
    sessions_by_cost = sorted(aggregate_sessions(entries), key=lambda session: session.cost_usd, reverse=True)
    for session in sessions_by_cost[:5]:
        top_sessions.append({
            "start_time": session.start_time.astimezone().strftime("%Y-%m-%d %H:%M") if session.start_time.tzinfo else session.start_time.strftime("%Y-%m-%d %H:%M"),
            "project": session.project or "unknown",
            "model": session.model or "unknown",
            "duration_min": session.duration_minutes,
            "tokens": session.total_tokens,
            "cost": _round_cost(session.cost_usd),
        })

    year_data = _load_year_data_cached(agents)

    return {
        "period": period,
        "period_label": f"{date_from.isoformat()} -> {date_to.isoformat()}",
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "summary": {
            "total_tokens": total_tokens,
            "cost_usd": _round_cost(total_cost),
            "sessions": len(session_ids),
            "messages": sum(entry.message_count for entry in entries),
            "active_days": len(active_dates),
            "total_days": total_days,
        },
        "by_agent": by_agent,
        "by_project": by_project[:10],
        "by_model": by_model,
        "daily_trend": daily_trend,
        "top_sessions": top_sessions,
        "comparison": comparison,
        "subscriptions": subscription.load_subscriptions(),
        "persona": _load_persona_for_period(period),
        "ai_updates": ai_updates_loader.load_ai_updates(),
        "contribution": year_data["contribution"],
        "wrapped": year_data["wrapped"],
    }

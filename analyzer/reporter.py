# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import logging
from pathlib import Path
from typing import Any

import codex_loader
import persona_loader
import subscription
from adapters import claude, codex
from adapters.types import AgentInfo, UsageEntry
from pricing import calculate_cost

from .aggregator import aggregate_sessions
from . import diagnoser

AGENT_LOADERS = {"claude-code": claude, "codex": codex}
AGENT_NAMES = {"claude-code": "Claude Code", "codex": "Codex"}
logger = logging.getLogger(__name__)
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


def _load_claude_report_inputs(
    *,
    hours_back: int,
    diagnosis_date_from: date,
    diagnosis_date_to: date,
) -> tuple[list[UsageEntry], list[diagnoser.ToolCall]]:
    entries: list[UsageEntry] = []
    tool_calls: list[diagnoser.ToolCall] = []
    seen: set[str] = set()
    cutoff = None
    cutoff_ts = 0.0
    if hours_back > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
        cutoff_ts = cutoff.timestamp()

    jobs: list[tuple[Path, Path]] = []
    for base_dir in claude.get_claude_dirs():
        base = Path(base_dir)
        if not base.is_dir():
            continue
        for jsonl_path in base.rglob("*.jsonl"):
            if cutoff is not None:
                try:
                    if jsonl_path.stat().st_mtime < cutoff_ts:
                        continue
                except OSError:
                    continue
            jobs.append((jsonl_path, base))

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = executor.map(
            lambda job: _scan_claude_report_file(
                job[0],
                job[1],
                cutoff,
                diagnosis_date_from,
                diagnosis_date_to,
            ),
            jobs,
        )
        for parsed_entries, parsed_tool_calls in results:
            for entry in parsed_entries:
                if entry.dedup_key in seen:
                    continue
                seen.add(entry.dedup_key)
                entries.append(entry)
            tool_calls.extend(parsed_tool_calls)

    entries.sort(key=lambda entry: entry.timestamp)
    tool_calls.sort(key=lambda call: call.timestamp)
    return entries, tool_calls


def _parse_claude_file(path: Path, base: Path, cutoff: datetime) -> list[UsageEntry]:
    parsed: list[UsageEntry] = []
    local_seen: set[str] = set()
    fallback_project = claude.extract_project_from_dir(path, base)
    claude.parse_jsonl(path, fallback_project, parsed, local_seen, cutoff)
    return parsed


def _scan_claude_report_file(
    path: Path,
    base: Path,
    cutoff: datetime | None,
    diagnosis_date_from: date,
    diagnosis_date_to: date,
) -> tuple[list[UsageEntry], list[diagnoser.ToolCall]]:
    parsed_entries: list[UsageEntry] = []
    local_seen: set[str] = set()
    fallback_project = claude.extract_project_from_dir(path, base)
    claude.parse_jsonl(path, fallback_project, parsed_entries, local_seen, cutoff)
    tool_calls = diagnoser.parse_tool_calls(
        path,
        fallback_project,
        diagnosis_date_from,
        diagnosis_date_to,
    )
    return parsed_entries, tool_calls

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


def _load_persona_for_period(period: str) -> dict[str, Any] | None:
    days_back = _period_spec(period).persona_days
    try:
        profile = persona_loader.load_profile(days_back)
    except Exception:
        return None
    return {
        "hour_histogram": list(profile.hour_histogram),
        "recent_titles": list(profile.recent_titles),
    }


def _empty_comparison(period: str) -> dict[str, Any]:
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
) -> dict[str, Any]:
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


def build_report_data(agents: list[AgentInfo], period: str = "month") -> dict[str, Any]:
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
    claude_entries: list[UsageEntry] = []
    claude_tool_calls: list[diagnoser.ToolCall] = []
    diagnosis_date_from = date.min if date_from is None else date_from
    for agent in agents:
        if agent.id == "claude-code":
            loaded_entries, loaded_tool_calls = _load_claude_report_inputs(
                hours_back=hours_back,
                diagnosis_date_from=diagnosis_date_from,
                diagnosis_date_to=date_to,
            )
            raw_entries.extend(loaded_entries)
            claude_entries.extend(loaded_entries)
            claude_tool_calls.extend(loaded_tool_calls)
            continue
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

    by_agent = [
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

    by_project = [
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

    by_model = [
        {
            "model": model,
            "tokens": data["tokens"],
            "cost": _round_cost(data["cost"]),
            "pct": _pct(data["tokens"], total_tokens),
            "top_project": _top_project(by_model_project.get(model, {})),
        }
        for model, data in by_model_totals.items()
    ]
    by_model.sort(key=lambda item: item["tokens"], reverse=True)

    daily_trend = []
    cursor = date_from
    while cursor <= date_to:
        day = daily_totals[cursor]
        daily_trend.append({
            "date": cursor.isoformat(),
            "tokens": day["tokens"],
            "cost": _round_cost(day["cost"]),
        })
        cursor += timedelta(days=1)

    top_sessions = []
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

    try:
        diagnosis_result = diagnoser.analyze_loaded_records(
            date_from=date_from,
            date_to=date_to,
            total_cost_usd=total_cost,
            tool_calls=claude_tool_calls,
            entries=claude_entries,
        )
        diagnosis = serialize_diagnosis(
            diagnosis_result,
            total_corpus_tokens=total_tokens,
        )
    except Exception:
        logger.warning("failed to build diagnosis section", exc_info=True)
        diagnosis = {"has_data": False}

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
        "diagnosis": diagnosis,
    }

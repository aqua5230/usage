from __future__ import annotations

import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import codex_loader
from adapters import claude, codex
from adapters.types import AgentInfo, UsageEntry
from pricing import calculate_cost

from .aggregator import aggregate_sessions

AGENT_LOADERS = {"claude-code": claude, "codex": codex}
AGENT_NAMES = {"claude-code": "Claude Code", "codex": "Codex"}


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
    if period == "month":
        return today.replace(day=1), today
    if period == "all":
        return None, today
    if period == "last30":
        return today - timedelta(days=29), today
    return today.replace(day=1), today


def _load_agent_entries(agent: AgentInfo, hours_back: int = 0) -> list[UsageEntry]:
    if hours_back > 0 and agent.id == "claude-code":
        return _load_recent_claude_entries(hours_back)
    if agent.id == "codex":
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
                agent_id=agent.id,
            )
            for entry in codex_loader.load_entries(hours_back=hours_back)
        ]
    loader = AGENT_LOADERS.get(agent.id)
    if loader is None:
        return []
    entries = loader.load_entries(hours_back=hours_back)
    for entry in entries:
        entry.agent_id = agent.id
    return entries


def _load_recent_claude_entries(hours_back: int) -> list[UsageEntry]:
    entries: list[UsageEntry] = []
    seen: set[str] = set()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    cutoff_ts = cutoff.timestamp()
    jobs: list[tuple[Path, Path]] = []
    for base_dir in claude._get_claude_dirs():  # type: ignore[attr-defined]
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
    fallback_project = claude._extract_project_from_dir(path, base)  # type: ignore[attr-defined]
    claude._parse_jsonl(path, fallback_project, parsed, local_seen, cutoff)  # type: ignore[attr-defined]
    return parsed


def _load_recent_codex_entries(hours_back: int) -> list[UsageEntry]:
    entries: list[UsageEntry] = []
    seen: set[str] = set()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    cutoff_ts = cutoff.timestamp()
    models = codex._load_thread_models()  # type: ignore[attr-defined]
    sessions_path = Path(codex.SESSIONS_DIR)
    if not sessions_path.is_dir():
        return entries
    jobs: list[Path] = []
    for jsonl_path in sessions_path.rglob("*.jsonl"):
        try:
            if jsonl_path.stat().st_mtime < cutoff_ts:
                continue
        except OSError:
            continue
        jobs.append(jsonl_path)
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = executor.map(lambda path: _parse_codex_file(path, models, cutoff), jobs)
        for parsed in results:
            for entry in parsed:
                if entry.dedup_key in seen:
                    continue
                seen.add(entry.dedup_key)
                entries.append(entry)
    entries.sort(key=lambda entry: entry.timestamp)
    return entries


def _parse_codex_file(path: Path, models: dict[str, str], cutoff: datetime) -> list[UsageEntry]:
    try:
        with path.open("rb") as f:
            head = f.read(64 * 1024)
    except (OSError, PermissionError):
        return []

    session_id = ""
    session_ts = ""
    project = "unknown"
    for raw_line in head.splitlines()[:12]:
        if b"session_meta" not in raw_line:
            continue
        try:
            data = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        payload = data.get("payload", {})
        session_id = payload.get("id", "")
        session_ts = payload.get("timestamp", "")
        cwd = payload.get("cwd", "")
        if cwd:
            project = codex._project_from_cwd(cwd)  # type: ignore[attr-defined]
        break

    if not session_id:
        return []

    try:
        ts = datetime.fromisoformat(session_ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return []
    if ts < cutoff:
        return []

    raw_usage_line = _read_last_matching_line(path, b"token_count", b"total_token_usage")
    if raw_usage_line is None:
        return []
    try:
        data = json.loads(raw_usage_line)
    except json.JSONDecodeError:
        return []
    payload = data.get("payload", {})
    info = payload.get("info")
    last_usage = info.get("total_token_usage") if info else None
    if not last_usage:
        return []

    cached = last_usage.get("cached_input_tokens", 0)
    input_tokens = last_usage.get("input_tokens", 0) - cached
    output_tokens = last_usage.get("output_tokens", 0) + last_usage.get("reasoning_output_tokens", 0)
    if input_tokens == 0 and output_tokens == 0:
        return []

    return [UsageEntry(
        timestamp=ts,
        session_id=session_id,
        message_id=session_id,
        request_id="",
        model=models.get(session_id, "unknown"),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_tokens=0,
        cache_read_tokens=cached,
        cost_usd=None,
        project=project,
        agent_id="codex",
        message_count=_count_token_events(path),
    )]


def _count_token_events(path: Path) -> int:
    count = 0
    try:
        with path.open("rb") as f:
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                count += chunk.count(b'"token_count"')
    except (OSError, PermissionError):
        return 1
    return max(1, count)


def _read_last_matching_line(path: Path, needle_a: bytes, needle_b: bytes) -> bytes | None:
    chunk_size = 64 * 1024
    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            pos = f.tell()
            tail = b""
            while pos > 0:
                read_size = min(chunk_size, pos)
                pos -= read_size
                f.seek(pos)
                data = f.read(read_size) + tail
                lines = data.splitlines()
                tail = lines[0] if pos > 0 and lines else b""
                search_lines = lines[1:] if pos > 0 else lines
                for raw_line in reversed(search_lines):
                    if needle_a in raw_line and needle_b in raw_line:
                        return raw_line
    except (OSError, PermissionError):
        return None
    return None


def _pct(value: int, total: int) -> float:
    return round((value / total * 100), 1) if total else 0.0


def _round_cost(value: float) -> float:
    return round(value, 4)


def build_report_data(agents, period: str = "month") -> dict:
    """
    period: "today" | "week" | "month" | "all"
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
    total_cost = sum(calculate_cost(entry) for entry in entries)
    session_ids = {entry.session_id for entry in entries}
    active_dates = {_entry_date(entry) for entry in entries}
    total_days = (date_to - date_from).days + 1

    by_agent_totals: dict[str, dict] = defaultdict(lambda: {"tokens": 0, "cost": 0.0, "sessions": set(), "messages": 0})
    by_project_totals: dict[str, dict] = defaultdict(lambda: {"tokens": 0, "cost": 0.0, "sessions": set()})
    by_model_totals: dict[str, dict] = defaultdict(lambda: {"tokens": 0, "cost": 0.0})
    daily_totals: dict[date, dict] = defaultdict(lambda: {"tokens": 0, "cost": 0.0})

    for entry in entries:
        cost = calculate_cost(entry)
        agent = by_agent_totals[entry.agent_id or "unknown"]
        agent["tokens"] += entry.total_tokens
        agent["cost"] += cost
        agent["sessions"].add(entry.session_id)
        agent["messages"] += entry.message_count

        project = by_project_totals[entry.project or "unknown"]
        project["tokens"] += entry.total_tokens
        project["cost"] += cost
        project["sessions"].add(entry.session_id)

        model = by_model_totals[entry.model or "unknown"]
        model["tokens"] += entry.total_tokens
        model["cost"] += cost

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

    return {
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
    }

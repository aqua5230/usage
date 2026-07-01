# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from statistics import median
from typing import Any

from adapters import claude
from adapters.types import UsageEntry
from jsonl_utils import iter_jsonl_dicts

TOOLS = {"Read", "Edit", "Bash", "Grep", "Glob", "LS"}
# Below this estimated waste a finding stays "info": cents must not outrank
# dollar-sized findings when the session-start reminder picks what to mention.
CRITICAL_WASTE_USD = 1.0
# Long sessions are dominated by cache reads, which the API bills at a tenth
# of the input rate — pricing them at $3/MTok would inflate anomaly findings
# several-fold and cost the diagnosis its credibility.
CACHE_READ_USD_PER_MTOK = 0.3
POLLUTER_DIRS = (
    "node_modules",
    "dist",
    "build",
    ".next",
    ".nuxt",
    ".turbo",
    "__pycache__",
    ".cache",
    ".venv",
    "venv",
    "target",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "coverage",
    ".gradle",
    ".idea",
    ".vscode",
    ".git",
    ".hg",
    ".svn",
    "bower_components",
    "vendor",
)


@dataclass(slots=True)
class ToolCall:
    timestamp: datetime
    session_id: str
    project: str
    tool_name: str
    target_path: str
    result_size_chars: int


@dataclass(slots=True)
class DiagnosisFinding:
    severity: str
    kind: str
    headline_plain: str
    headline_detail: str
    estimated_waste_usd: float
    items: list[dict[str, object]]
    estimated_waste_tokens: int = 0


@dataclass(slots=True)
class DiagnosisResult:
    total_waste_usd: float
    monthly_savings_estimate_usd: float
    total_waste_tokens: int
    fixable_waste_tokens: int
    findings: list[DiagnosisFinding]
    suggested_claudeignore: str
    has_data: bool


@dataclass(slots=True)
class _SessionUsage:
    session_id: str
    project: str
    total_tokens: int
    start_time: datetime
    cache_read_tokens: int = 0


def analyze(
    date_from: date,
    date_to: date,
    total_cost_usd: float,
) -> DiagnosisResult:
    tool_calls, sessions = _load_records(date_from, date_to)
    return analyze_loaded_records(
        date_from=date_from,
        date_to=date_to,
        total_cost_usd=total_cost_usd,
        tool_calls=tool_calls,
        entries=None,
        sessions=sessions,
    )


def analyze_loaded_records(
    *,
    date_from: date,
    date_to: date,
    total_cost_usd: float,
    tool_calls: list[ToolCall],
    entries: list[UsageEntry] | None = None,
    sessions: list[_SessionUsage] | None = None,
) -> DiagnosisResult:
    if sessions is None:
        sessions = _aggregate_sessions(entries or [], date_from, date_to)
    if not tool_calls and not sessions:
        return DiagnosisResult(0.0, 0.0, 0, 0, [], "", False)

    repeated = _find_repeated_reads(tool_calls)
    polluters, ignored_dirs = _find_polluter_dirs(tool_calls)
    anomalies = _find_anomaly_sessions(sessions)
    noisy = _find_noisy_bash(tool_calls)
    repeated_bash = _find_repeated_bash(tool_calls)
    findings = [
        finding
        for finding in (repeated, polluters, anomalies, noisy, repeated_bash)
        if finding is not None
    ]

    total_waste = sum(finding.estimated_waste_usd for finding in findings)
    total_waste_tokens = sum(finding.estimated_waste_tokens for finding in findings)
    fixable_waste_tokens = sum(
        finding.estimated_waste_tokens
        for finding in findings
        if finding.kind == "polluter_dirs"
    )
    if total_cost_usd > 0:
        total_waste = min(total_waste, total_cost_usd)

    days = max(1, (date_to - date_from).days + 1)
    monthly_savings = min(total_waste / days * 30, total_waste)
    return DiagnosisResult(
        total_waste_usd=total_waste,
        monthly_savings_estimate_usd=monthly_savings,
        total_waste_tokens=total_waste_tokens,
        fixable_waste_tokens=fixable_waste_tokens,
        findings=findings,
        suggested_claudeignore="\n".join(f"{name}/" for name in sorted(ignored_dirs)),
        has_data=True,
    )


def _load_records(
    date_from: date,
    date_to: date,
) -> tuple[list[ToolCall], list[_SessionUsage]]:
    tool_calls: list[ToolCall] = []
    entries: list[UsageEntry] = []
    seen_entries: set[str] = set()

    for base_dir in claude.get_claude_dirs():
        base = Path(base_dir)
        if not base.is_dir():
            continue
        for jsonl_path in base.rglob("*.jsonl"):
            fallback_project = claude.extract_project_from_dir(jsonl_path, base)
            tool_calls.extend(
                parse_tool_calls(jsonl_path, fallback_project, date_from, date_to)
            )
            claude.parse_jsonl(
                jsonl_path,
                fallback_project,
                entries,
                seen_entries,
                cutoff=None,
            )

    sessions = _aggregate_sessions(entries, date_from, date_to)
    return tool_calls, sessions


def parse_tool_calls(
    path: Path,
    fallback_project: str,
    date_from: date,
    date_to: date,
) -> list[ToolCall]:
    tool_calls: list[ToolCall] = []
    pending: dict[str, ToolCall] = {}

    try:
        for data in iter_jsonl_dicts(path):
                record_type = data.get("type")
                if record_type == "assistant":
                    _parse_assistant_tool_uses(
                        data,
                        fallback_project,
                        date_from,
                        date_to,
                        pending,
                    )
                elif record_type == "user":
                    _parse_user_results(data, pending, tool_calls)
    except (OSError, UnicodeDecodeError):
        return tool_calls

    tool_calls.extend(pending.values())
    return tool_calls


def _parse_assistant_tool_uses(
    data: dict[str, Any],
    fallback_project: str,
    date_from: date,
    date_to: date,
    pending: dict[str, ToolCall],
) -> None:
    timestamp = _parse_timestamp(data.get("timestamp"))
    if timestamp is None or not _in_range(timestamp, date_from, date_to):
        return

    message = data.get("message")
    if not isinstance(message, dict):
        return
    content = message.get("content")
    if not isinstance(content, list):
        return

    session_id = str(data.get("sessionId") or "")
    for part in content:
        if not isinstance(part, dict) or part.get("type") != "tool_use":
            continue
        tool_name = str(part.get("name") or "")
        if tool_name not in TOOLS:
            continue
        tool_id = str(part.get("id") or "")
        target = _tool_target(tool_name, part.get("input"))
        if not tool_id or not target:
            continue
        pending[tool_id] = ToolCall(
            timestamp=timestamp,
            session_id=session_id,
            project=fallback_project,
            tool_name=tool_name,
            target_path=target,
            result_size_chars=0,
        )


def _parse_user_results(
    data: dict[str, Any],
    pending: dict[str, ToolCall],
    tool_calls: list[ToolCall],
) -> None:
    message = data.get("message")
    if not isinstance(message, dict):
        return
    content = message.get("content")
    if not isinstance(content, list):
        return

    for part in content:
        if not isinstance(part, dict) or part.get("type") != "tool_result":
            continue
        tool_id = str(part.get("tool_use_id") or "")
        call = pending.pop(tool_id, None)
        if call is None:
            continue
        call.result_size_chars = _content_size(part.get("content"))
        tool_calls.append(call)


def _aggregate_sessions(
    entries: list[UsageEntry],
    date_from: date,
    date_to: date,
) -> list[_SessionUsage]:
    sessions: dict[tuple[str, str], _SessionUsage] = {}

    for entry in entries:
        if not _in_range(entry.timestamp, date_from, date_to):
            continue
        key = (entry.project, entry.session_id)
        current = sessions.get(key)
        if current is None:
            sessions[key] = _SessionUsage(
                session_id=entry.session_id,
                project=entry.project,
                total_tokens=entry.total_tokens,
                start_time=entry.timestamp,
                cache_read_tokens=entry.cache_read_tokens,
            )
            continue
        current.total_tokens += entry.total_tokens
        current.cache_read_tokens += entry.cache_read_tokens
        if entry.timestamp < current.start_time:
            current.start_time = entry.timestamp

    return list(sessions.values())


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _in_range(timestamp: datetime, date_from: date, date_to: date) -> bool:
    if timestamp.tzinfo is not None:
        timestamp = timestamp.astimezone()
    return date_from <= timestamp.date() <= date_to


def _tool_target(tool_name: str, raw_input: object) -> str:
    if not isinstance(raw_input, dict):
        return ""
    if tool_name in {"Read", "Edit"}:
        return str(raw_input.get("file_path") or "")
    if tool_name in {"Grep", "Glob", "LS"}:
        path = str(raw_input.get("path") or "")
        pattern = str(raw_input.get("pattern") or raw_input.get("query") or "")
        return f"{path} [{pattern}]" if pattern else path
    return str(raw_input.get("command") or "")[:200]


def _content_size(content: object) -> int:
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        total = 0
        for item in content:
            if isinstance(item, str):
                total += len(item)
                continue
            if not isinstance(item, dict):
                continue
            text = item.get("text") or item.get("content")
            if isinstance(text, str):
                total += len(text)
        return total
    return 0


def _find_repeated_reads(tool_calls: list[ToolCall]) -> DiagnosisFinding | None:
    grouped: dict[str, list[ToolCall]] = defaultdict(list)
    for call in tool_calls:
        if call.tool_name == "Read":
            grouped[call.target_path].append(call)

    candidates: list[dict[str, object]] = []
    total_cost = 0.0
    total_tokens = 0
    for path, calls in sorted(grouped.items(), key=lambda item: len(item[1]), reverse=True):
        if len(calls) < 10:
            continue
        average_size = sum(call.result_size_chars for call in calls) / len(calls)
        estimated_tokens = int(len(calls) * average_size / 4)
        cost = _tokens_to_usd(estimated_tokens)
        total_cost += cost
        total_tokens += estimated_tokens
        candidates.append(
            {
                "label": path,
                "stat": "diag_item_read_times",
                "n": len(calls),
                "size_bytes": int(sum(call.result_size_chars for call in calls)),
                "cost": round(cost, 4),
                "estimated_waste_tokens": estimated_tokens,
            }
        )

    if not candidates:
        return None
    return DiagnosisFinding(
        severity="critical" if total_cost >= CRITICAL_WASTE_USD else "info",
        kind="repeated_reads",
        headline_plain="diag_kind_repeated_reads",
        headline_detail="diag_kind_repeated_reads_d",
        estimated_waste_usd=total_cost,
        estimated_waste_tokens=total_tokens,
        items=candidates[:5],
    )


def _find_polluter_dirs(tool_calls: list[ToolCall]) -> tuple[DiagnosisFinding | None, set[str]]:
    stats: dict[str, dict[str, int]] = defaultdict(lambda: {"count": 0, "chars": 0})
    for call in tool_calls:
        if call.tool_name not in {"Read", "Edit"}:
            continue
        polluter = _polluter_dir(call.target_path)
        if polluter is None:
            continue
        stats[polluter]["count"] += 1
        stats[polluter]["chars"] += call.result_size_chars

    items = [
        {
            "label": name,
            "stat": "diag_item_read_times",
            "n": values["count"],
            "size_bytes": values["chars"],
            "cost": round(_tokens_to_usd(values["chars"] // 4), 4),
            "estimated_waste_tokens": values["chars"] // 4,
        }
        for name, values in sorted(
            stats.items(),
            key=lambda item: item[1]["count"],
            reverse=True,
        )[:8]
    ]
    if not items:
        return None, set()

    total_cost = sum(_tokens_to_usd(values["chars"] // 4) for values in stats.values())
    total_tokens = sum(values["chars"] // 4 for values in stats.values())
    return (
        DiagnosisFinding(
            severity="critical" if total_cost >= CRITICAL_WASTE_USD else "info",
            kind="polluter_dirs",
            headline_plain="diag_kind_polluter_dirs",
            headline_detail="diag_kind_polluter_dirs_d",
            estimated_waste_usd=total_cost,
            estimated_waste_tokens=total_tokens,
            items=items,
        ),
        set(stats),
    )


def _polluter_dir(path: str) -> str | None:
    normalized = path.replace("\\", "/")
    for part in normalized.split("/"):
        if part in POLLUTER_DIRS:
            return part
    return None


def _find_anomaly_sessions(sessions: list[_SessionUsage]) -> DiagnosisFinding | None:
    by_project: dict[str, list[_SessionUsage]] = defaultdict(list)
    for session in sessions:
        by_project[session.project].append(session)

    candidates: list[tuple[float, _SessionUsage, float]] = []
    for project_sessions in by_project.values():
        baseline = median(session.total_tokens for session in project_sessions)
        if baseline <= 0:
            continue
        for session in project_sessions:
            ratio = session.total_tokens / baseline
            if session.total_tokens > 30_000 and ratio > 5:
                candidates.append((ratio, session, baseline))

    candidates.sort(key=lambda item: item[0], reverse=True)
    items: list[dict[str, object]] = []
    estimated_waste_usd = 0.0
    estimated_waste_tokens = 0
    for ratio, session, baseline in candidates[:3]:
        # Only the excess over the project baseline is waste: the baseline-sized
        # part of an anomalous session is the work the user came to do.
        excess_tokens = int(session.total_tokens - baseline)
        excess_share = excess_tokens / session.total_tokens
        cost = round(_session_cost_usd(session) * excess_share, 4)
        items.append(
            {
                "label": session.session_id[:8] or "unknown",
                "cost": cost,
                "tokens": session.total_tokens,
                "estimated_waste_tokens": excess_tokens,
                "baseline_tokens": int(baseline),
                "ratio": round(ratio, 1),
                "session_start_iso": (
                    session.start_time.astimezone().isoformat()
                    if session.start_time.tzinfo
                    else session.start_time.isoformat()
                ),
                "project": session.project or "unknown",
            }
        )
        estimated_waste_usd += cost
        estimated_waste_tokens += excess_tokens
    if not items:
        return None

    return DiagnosisFinding(
        severity="warning",
        kind="anomaly_session",
        headline_plain="diag_kind_anomaly_session",
        headline_detail="diag_kind_anomaly_session_d",
        estimated_waste_usd=estimated_waste_usd,
        estimated_waste_tokens=estimated_waste_tokens,
        items=items,
    )


def _find_noisy_bash(tool_calls: list[ToolCall]) -> DiagnosisFinding | None:
    calls = [
        call
        for call in tool_calls
        if call.tool_name == "Bash" and call.result_size_chars > 20_000
    ]
    calls.sort(key=lambda call: call.result_size_chars, reverse=True)
    items: list[dict[str, object]] = []
    estimated_waste_usd = 0.0
    estimated_waste_tokens = 0
    for call in calls[:5]:
        cost = round(_tokens_to_usd(call.result_size_chars // 4), 4)
        tokens = call.result_size_chars // 4
        items.append(
            {
                "label": call.target_path[:80],
                "n": call.result_size_chars,
                "size_bytes": call.result_size_chars,
                "cost": cost,
                "estimated_waste_tokens": tokens,
            }
        )
        estimated_waste_usd += cost
        estimated_waste_tokens += tokens
    if not items:
        return None
    return DiagnosisFinding(
        severity="info",
        kind="noisy_bash",
        headline_plain="diag_kind_noisy_bash",
        headline_detail="diag_kind_noisy_bash_d",
        estimated_waste_usd=estimated_waste_usd,
        estimated_waste_tokens=estimated_waste_tokens,
        items=items,
    )


def _find_repeated_bash(tool_calls: list[ToolCall]) -> DiagnosisFinding | None:
    grouped: dict[str, list[ToolCall]] = defaultdict(list)
    for call in tool_calls:
        if call.tool_name == "Bash":
            grouped[call.target_path].append(call)

    candidates: list[dict[str, object]] = []
    total_cost = 0.0
    total_tokens = 0
    for command, calls in sorted(grouped.items(), key=lambda item: len(item[1]), reverse=True):
        if len(calls) < 15:
            continue
        estimated_waste_tokens = len(calls) * 500
        cost = _tokens_to_usd(estimated_waste_tokens)
        total_cost += cost
        total_tokens += estimated_waste_tokens
        candidates.append(
            {
                "label": command[:100],
                "stat": "diag_item_read_times",
                "n": len(calls),
                "cost": round(cost, 4),
                "estimated_waste_tokens": estimated_waste_tokens,
            }
        )

    if not candidates:
        return None
    return DiagnosisFinding(
        severity="info",
        kind="repeated_bash",
        headline_plain="diag_kind_repeated_bash",
        headline_detail="diag_kind_repeated_bash_d",
        estimated_waste_usd=total_cost,
        estimated_waste_tokens=total_tokens,
        items=candidates[:5],
    )


def _tokens_to_usd(tokens: int) -> float:
    return tokens / 1_000_000 * 3


def _session_cost_usd(session: _SessionUsage) -> float:
    other_tokens = session.total_tokens - session.cache_read_tokens
    return _tokens_to_usd(other_tokens) + (
        session.cache_read_tokens / 1_000_000 * CACHE_READ_USD_PER_MTOK
    )

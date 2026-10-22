# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>

"""Local dispatch matching and subscription quota estimates for HTML reports."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, TypedDict

from adapters import rate_limits
from adapters.types import UsageEntry
from loaders import agy_loader, agy_quota_probe, codex_loader, muse_quota_probe
from loaders.claude_paths import claude_config_dirs
from usage_common.project_resolver import resolve_project_name

_DISPATCH = {
    "codex": re.compile(r"(^|[;&|(\s])codex exec"),
    "antigravity": re.compile(r"(^|[;&|(\s])agy -p"),
}
_UUID = re.compile(r"\b[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\b")
_CWD = re.compile(rb'"Cwd":"((?:[^"\\]|\\.)*)"')
_file_cache: dict[tuple[Path, int, float], list[Dispatch]] = {}
_codex_cache: dict[Path, tuple[tuple[int, float], Candidate | None]] = {}


@dataclass(frozen=True)
class Dispatch:
    timestamp: datetime
    session_id: str
    cwd: str
    command: str
    agent_id: str


@dataclass(frozen=True)
class Candidate:
    agent_id: str
    session_id: str
    timestamp: datetime
    cwd: str
    first_message: str = ""


@dataclass(frozen=True)
class QuotaWindow:
    used_pct: float
    resets_at: datetime
    length: timedelta


class LedgerRow(TypedDict):
    date: str
    project: str
    title: str
    dispatch_count: int
    claude_pct: float | None
    codex_pct: float | None
    agy_groups: dict[str, float]
    claude_reset: bool
    codex_reset: bool
    agy_reset: bool
    total_pct: float


class LedgerData(TypedDict):
    rows: list[LedgerRow]
    unowned_codex: int
    unowned_agy: int
    used_pct: dict[str, float]


class LedgerBlock(TypedDict):
    quota: str
    used_pct: float | None
    conversations: list[tuple[LedgerRow, float]]
    more_count: int
    more_pct: float
    other_pct: float | None
    all_reset: bool


def ledger_blocks(rows: list[LedgerRow], used_pct: dict[str, float]) -> list[LedgerBlock]:
    """Select each quota's top five from every owned conversation."""
    shares: dict[str, list[tuple[LedgerRow, float]]] = defaultdict(list)
    for row in rows:
        if row["codex_pct"] is not None and row["codex_pct"] > 0:
            shares["codex"].append((row, row["codex_pct"]))
        for group, value in row["agy_groups"].items():
            if value > 0:
                shares[f"antigravity:{group}"].append((row, value))
    if any(row["codex_reset"] for row in rows):
        shares.setdefault("codex", [])
    blocks: list[LedgerBlock] = []
    for quota, conversations in shares.items():
        conversations.sort(key=lambda item: item[1], reverse=True)
        total = sum(value for _, value in conversations)
        used = used_pct.get(quota)
        other = max(0.0, used - total) if used is not None else None
        blocks.append(
            {
                "quota": quota,
                "used_pct": used,
                "conversations": conversations[:5],
                "more_count": len(conversations[5:]),
                "more_pct": sum(value for _, value in conversations[5:]),
                "other_pct": other if other is not None and other >= 0.5 else None,
                "all_reset": quota == "codex" and not conversations,
            }
        )
    blocks.sort(
        key=lambda block: sum(value for _, value in block["conversations"]) + block["more_pct"],
        reverse=True,
    )
    return blocks


def _timestamp(value: object) -> datetime | None:
    try:
        if isinstance(value, (float, int)) and not isinstance(value, bool):
            return datetime.fromtimestamp(value, UTC)
        if isinstance(value, str):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    except (ValueError, OverflowError):
        pass
    return None


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _claude_paths(cutoff: datetime) -> list[Path]:
    paths: list[Path] = []
    for root in claude_config_dirs():
        for path in (root / "projects").glob("*/*.jsonl"):
            try:
                if path.stat().st_mtime >= cutoff.timestamp():
                    paths.append(path)
            except OSError:
                continue
    return paths


def _read_dispatches(path: Path) -> list[Dispatch]:
    try:
        stat = path.stat()
        key = (path, stat.st_size, stat.st_mtime)
        cached = _file_cache.get(key)
        if cached is not None:
            return cached
        found: list[Dispatch] = []
        with path.open(encoding="utf-8", errors="replace") as stream:
            for line in stream:
                if "codex exec" not in line and "agy -p" not in line:
                    continue
                try:
                    record = _dict(json.loads(line))
                except json.JSONDecodeError:
                    continue
                timestamp = _timestamp(record.get("timestamp"))
                if timestamp is None:
                    continue
                message = _dict(record.get("message"))
                blocks = message.get("content")
                if not isinstance(blocks, list):
                    blocks = [record]
                for block in blocks:
                    item = _dict(block)
                    if item.get("type") != "tool_use" or item.get("name") != "Bash":
                        continue
                    command = _dict(item.get("input")).get("command")
                    if not isinstance(command, str):
                        continue
                    for agent_id, pattern in _DISPATCH.items():
                        for _ in pattern.finditer(command):
                            found.append(
                                Dispatch(
                                    timestamp,
                                    path.stem,
                                    str(record.get("cwd") or ""),
                                    command,
                                    agent_id,
                                )
                            )
        for old_key in tuple(_file_cache):
            if old_key[0] == path and old_key != key:
                del _file_cache[old_key]
        _file_cache[key] = found
        return found
    except OSError:
        return []


def _read_codex_candidate(path: Path) -> Candidate | None:
    try:
        stat = path.stat()
        signature = (stat.st_size, stat.st_mtime)
        cached = _codex_cache.get(path)
        if cached is not None and cached[0] == signature:
            return cached[1]
        candidate = None
        with path.open(encoding="utf-8", errors="replace") as stream:
            first = _dict(json.loads(next(stream)))
            meta = _dict(first.get("payload"))
            started = _timestamp(first.get("timestamp"))
            if (
                first.get("type") == "session_meta"
                and meta.get("originator") == "codex_exec"
                and started is not None
            ):
                message = ""
                for line in stream:
                    if '"user_message"' not in line:
                        continue
                    try:
                        payload = _dict(_dict(json.loads(line)).get("payload"))
                    except json.JSONDecodeError:
                        continue
                    if payload.get("type") == "user_message":
                        message = str(payload.get("message") or "")
                        break
                candidate = Candidate(
                    "codex",
                    str(meta.get("id") or path.stem),
                    started,
                    str(meta.get("cwd") or ""),
                    message,
                )
        _codex_cache[path] = (signature, candidate)
        return candidate
    except (OSError, StopIteration, json.JSONDecodeError):
        return None


def _codex_candidates(cutoff: datetime, now: datetime) -> list[Candidate]:
    day = (cutoff - timedelta(days=1)).date()
    day_dirs = []
    while day <= (now + timedelta(days=1)).date():
        day_dirs.append(codex_loader.SESSIONS_DIR / f"{day:%Y}" / f"{day:%m}" / f"{day:%d}")
        day += timedelta(days=1)
    result: list[Candidate] = []
    for path in (path for day_dir in day_dirs for path in day_dir.glob("*.jsonl")):
        candidate = _read_codex_candidate(path)
        if candidate is not None and cutoff <= candidate.timestamp <= now:
            result.append(candidate)
    return result


def _agy_candidates(cutoff: datetime, now: datetime) -> list[Candidate]:
    result: list[Candidate] = []
    for path in agy_loader.AGY_SESSIONS_DIR.glob("*.db"):
        try:
            if path.stat().st_mtime < cutoff.timestamp():
                continue
            with sqlite3.connect(agy_loader._readonly_sqlite_uri(path), uri=True) as connection:
                started = agy_loader._session_timestamp(connection, path)
                if not cutoff <= started <= now:
                    continue
                row = connection.execute(
                    'SELECT step_payload FROM steps WHERE step_payload LIKE \'%"Cwd":"%\' ORDER BY idx LIMIT 1'
                ).fetchone()
                match = _CWD.search(row[0]) if row and isinstance(row[0], bytes) else None
                cwd = (
                    json.loads('"' + match.group(1).decode("utf-8", "replace") + '"')
                    if match
                    else ""
                )
                result.append(
                    Candidate(
                        "antigravity", path.stem, started, cwd if isinstance(cwd, str) else ""
                    )
                )
        except (OSError, sqlite3.Error, json.JSONDecodeError):
            continue
    return result


def match_candidate(
    candidate: Candidate, dispatches: list[Dispatch], known_sessions: set[str]
) -> str | None:
    if candidate.agent_id == "codex":
        direct: set[str] = {
            value.lower() for value in _UUID.findall(candidate.cwd + " " + candidate.first_message)
        } & known_sessions
        if len(direct) == 1:
            return next(iter(direct))
        if len(direct) > 1:
            return None
    eligible = [
        dispatch
        for dispatch in dispatches
        if dispatch.agent_id == candidate.agent_id
        and -5 <= (candidate.timestamp - dispatch.timestamp).total_seconds() <= 120
    ]
    owners = {dispatch.session_id for dispatch in eligible}
    if len(owners) > 1:
        eligible = [
            dispatch
            for dispatch in eligible
            if candidate.cwd
            and (candidate.cwd == dispatch.cwd or candidate.cwd in dispatch.command)
        ]
        owners = {dispatch.session_id for dispatch in eligible}
    return next(iter(owners)) if len(owners) == 1 else None


def _window(pct: float | None, reset: object, minutes: float) -> QuotaWindow | None:
    resets_at = _timestamp(reset)
    if pct is None or resets_at is None or minutes <= 0:
        return None
    return QuotaWindow(pct, resets_at, timedelta(minutes=minutes))


def load_windows() -> dict[str, QuotaWindow]:
    windows: dict[str, QuotaWindow] = {}
    claude = rate_limits.load_rate_limits()
    if claude:
        window = _window(claude.seven_day_pct, claude.seven_day_resets_at, 7 * 24 * 60)
        if window:
            windows["claude-code"] = window
    codex = codex_loader.load_rate_limits()
    if codex:
        window = _window(
            codex.seven_day_pct,
            codex.seven_day_resets_at,
            codex.seven_day_window_minutes or 7 * 24 * 60,
        )
        if window:
            windows["codex"] = window
    agy = agy_quota_probe._read_cache()
    if agy:
        fetched = _timestamp(agy.fetched_at)
        if fetched:
            for group in agy.groups:
                weekly = group.weekly
                if weekly is None or weekly.resets_in_minutes is None:
                    continue
                minutes = weekly.resets_in_minutes
                window = QuotaWindow(
                    100 - weekly.remaining_percent,
                    fetched + timedelta(minutes=minutes),
                    timedelta(days=7),
                )
                group_key = f"antigravity:{group.name}"
                windows[group_key] = window
                for model in group.models:
                    windows[f"antigravity-model:{model.lower()}"] = window
    muse = muse_quota_probe.read_cache()
    if muse:
        window = _window(muse["weekly"]["used_percent"], muse["weekly"]["resets_at"], 7 * 24 * 60)
        if window:
            windows["muse"] = window
    return windows


def estimate_pct(
    session_tokens: int, total_tokens: int, window: QuotaWindow | None, now: datetime
) -> float | None:
    if window is None or window.resets_at <= now or total_tokens <= 0:
        return None
    return session_tokens / total_tokens * window.used_pct


SessionGroup = tuple[str, str, str]


def estimate_sessions(
    entries: list[UsageEntry], windows: dict[str, QuotaWindow], now: datetime
) -> tuple[dict[SessionGroup, float], set[SessionGroup]]:
    totals: dict[str, int] = defaultdict(int)
    sessions: dict[tuple[str, str, str], int] = defaultdict(int)
    before_window: set[SessionGroup] = set()
    for entry in entries:
        group = entry.agent_id
        if entry.agent_id == "antigravity":
            model = entry.model.lower().replace("-", " ")
            matched = next(
                (
                    label.removeprefix("antigravity-model:")
                    for label in windows
                    if label.startswith("antigravity-model:")
                    and all(
                        word in model for word in label.removeprefix("antigravity-model:").split()
                    )
                ),
                None,
            )
            if matched is None:
                continue
            group = next(
                (
                    key
                    for key, window in windows.items()
                    if key.startswith("antigravity:")
                    and window is windows[f"antigravity-model:{matched}"]
                ),
                "",
            )
        window = windows.get(group)
        tokens = entry.input_tokens + entry.output_tokens + entry.cache_creation_tokens
        if window is None or entry.timestamp > now or tokens <= 0:
            continue
        key = (entry.agent_id, entry.session_id, group)
        if entry.timestamp < window.resets_at - window.length:
            before_window.add(key)
            continue
        totals[group] += tokens
        sessions[key] += tokens
    estimates: dict[SessionGroup, float] = {}
    for (agent_id, session_id, group), tokens in sessions.items():
        value = estimate_pct(tokens, totals[group], windows.get(group), now)
        if value is not None:
            estimates[(agent_id, session_id, group)] = value
    return estimates, before_window - sessions.keys()


def _session_title(path: Path) -> str:
    """Return Claude Code's own ai-title, falling back to the first user text."""
    title = first_text = ""
    try:
        with path.open(encoding="utf-8", errors="replace") as stream:
            for line in stream:
                if '"ai-title"' not in line and (first_text or '"user"' not in line):
                    continue
                try:
                    item = _dict(json.loads(line))
                except json.JSONDecodeError:
                    continue
                if item.get("type") == "ai-title" and isinstance(item.get("aiTitle"), str):
                    title = item["aiTitle"].strip()
                elif item.get("type") == "user" and not first_text:
                    content = _dict(item.get("message")).get("content")
                    blocks = [{"text": content}] if isinstance(content, str) else content
                    for block in blocks if isinstance(blocks, list) else []:
                        text = _dict(block).get("text")
                        if isinstance(text, str) and text.strip():
                            first_text = text.strip()[:40]
                            break
    except OSError:
        return ""
    return title or first_text


def build_ledger(
    estimates: dict[SessionGroup, float],
    now: datetime,
    reset_sessions: set[SessionGroup] | None = None,
    used_pct: dict[str, float] | None = None,
) -> LedgerData:
    cutoff = now - timedelta(days=7)
    paths = _claude_paths(cutoff)
    dispatches = [
        item for path in paths for item in _read_dispatches(path) if cutoff <= item.timestamp <= now
    ]
    empty: LedgerData = {
        "rows": [],
        "unowned_codex": 0,
        "unowned_agy": 0,
        "used_pct": used_pct or {},
    }
    if not dispatches:
        return empty
    known_sessions = {path.stem for path in paths}
    candidates = _codex_candidates(cutoff - timedelta(seconds=5), now) + _agy_candidates(
        cutoff - timedelta(seconds=5), now
    )
    owned: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for candidate in candidates:
        owner = match_candidate(candidate, dispatches, known_sessions)
        if owner is None:
            if candidate.agent_id == "codex":
                empty["unowned_codex"] += 1
            else:
                empty["unowned_agy"] += 1
        else:
            owned[owner][candidate.agent_id].add(candidate.session_id)
    if not owned:
        return empty
    path_by_session = {path.stem: path for path in paths}
    by_owner: dict[str, list[Dispatch]] = defaultdict(list)
    for dispatch in dispatches:
        by_owner[dispatch.session_id].append(dispatch)
    rows: list[tuple[str, LedgerRow]] = []
    for owner, children in owned.items():
        origin = by_owner.get(owner)
        if not origin:
            continue
        claude_pct = estimates.get(("claude-code", owner, "claude-code"))
        codex_values = [
            estimates[("codex", child, "codex")]
            for child in children["codex"]
            if ("codex", child, "codex") in estimates
        ]
        codex_pct = sum(codex_values) if codex_values else None
        agy_groups: dict[str, float] = {}
        for (agent, child, group), value in estimates.items():
            if agent == "antigravity" and child in children[agent]:
                name = group.removeprefix("antigravity:")
                agy_groups[name] = agy_groups.get(name, 0.0) + value
        reset_agents = {
            agent
            for agent, session, _ in reset_sessions or set()
            if (agent == "claude-code" and session == owner)
            or session in children.get(agent, set())
        }
        first = min(origin, key=lambda item: item.timestamp)
        rows.append(
            (
                owner,
                {
                    "date": first.timestamp.astimezone().strftime("%Y-%m-%d"),
                    "project": resolve_project_name(first.cwd),
                    "title": "",
                    "dispatch_count": len(origin),
                    "claude_pct": claude_pct,
                    "codex_pct": codex_pct,
                    "agy_groups": agy_groups,
                    "claude_reset": claude_pct is None and "claude-code" in reset_agents,
                    "codex_reset": codex_pct is None and "codex" in reset_agents,
                    "agy_reset": not agy_groups and "antigravity" in reset_agents,
                    "total_pct": (claude_pct or 0) + (codex_pct or 0) + sum(agy_groups.values()),
                },
            )
        )
    rows.sort(key=lambda item: item[1]["total_pct"], reverse=True)
    empty["rows"] = [row for _, row in rows]
    displayed = {
        id(row)
        for block in ledger_blocks(empty["rows"], empty["used_pct"])
        for row, _ in block["conversations"]
    }
    for owner, row in rows:
        if id(row) in displayed:
            row["title"] = _session_title(path_by_session[owner])
    return empty

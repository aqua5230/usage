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
from loaders import agy_loader, agy_quota_probe, codex_loader
from loaders.claude_paths import claude_config_dirs

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
    agy_pct: float | None
    total_pct: float


class LedgerData(TypedDict):
    rows: list[LedgerRow]
    unowned_codex: int
    unowned_agy: int


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
                minutes = group.weekly.resets_in_minutes
                if minutes is None:
                    continue
                window = QuotaWindow(
                    100 - group.weekly.remaining_percent,
                    fetched + timedelta(minutes=minutes),
                    timedelta(days=7),
                )
                group_key = f"antigravity:{group.name}"
                windows[group_key] = window
                for model in group.models:
                    windows[f"antigravity-model:{model.lower()}"] = window
    return windows


def estimate_pct(
    session_tokens: int, total_tokens: int, window: QuotaWindow | None, now: datetime
) -> float | None:
    if window is None or window.resets_at <= now or total_tokens <= 0:
        return None
    return session_tokens / total_tokens * window.used_pct


def estimate_sessions(
    entries: list[UsageEntry], windows: dict[str, QuotaWindow], now: datetime
) -> dict[tuple[str, str], float | None]:
    totals: dict[str, int] = defaultdict(int)
    sessions: dict[tuple[str, str, str], int] = defaultdict(int)
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
        if window is None or not window.resets_at - window.length <= entry.timestamp <= now:
            continue
        tokens = entry.input_tokens + entry.output_tokens + entry.cache_creation_tokens
        totals[group] += tokens
        sessions[(entry.agent_id, entry.session_id, group)] += tokens
    estimates: dict[tuple[str, str], float | None] = {}
    for (agent_id, session_id, group), tokens in sessions.items():
        value = estimate_pct(tokens, totals[group], windows.get(group), now)
        if value is not None:
            key = (agent_id, session_id)
            estimates[key] = (estimates.get(key) or 0.0) + value
    return estimates


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


def build_ledger(estimates: dict[tuple[str, str], float | None], now: datetime) -> LedgerData:
    cutoff = now - timedelta(days=7)
    paths = _claude_paths(cutoff)
    dispatches = [
        item for path in paths for item in _read_dispatches(path) if cutoff <= item.timestamp <= now
    ]
    empty: LedgerData = {"rows": [], "unowned_codex": 0, "unowned_agy": 0}
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
        shares = {"claude-code": estimates.get(("claude-code", owner))}
        for agent_id in ("codex", "antigravity"):
            values = [estimates.get((agent_id, session_id)) for session_id in children[agent_id]]
            shares[agent_id] = (
                sum(value for value in values if value is not None)
                if any(value is not None for value in values)
                else None
            )
        first = min(origin, key=lambda item: item.timestamp)
        rows.append(
            (
                owner,
                {
                    "date": first.timestamp.astimezone().strftime("%Y-%m-%d"),
                    "project": Path(first.cwd).name or "unknown",
                    "title": "",
                    "dispatch_count": len(origin),
                    "claude_pct": shares["claude-code"],
                    "codex_pct": shares["codex"],
                    "agy_pct": shares["antigravity"],
                    "total_pct": sum(value for value in shares.values() if value is not None),
                },
            )
        )
    rows.sort(key=lambda item: item[1]["total_pct"], reverse=True)
    for owner, row in rows[:15]:
        row["title"] = _session_title(path_by_session[owner])
        empty["rows"].append(row)
    return empty

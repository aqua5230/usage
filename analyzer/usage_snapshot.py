# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Permanent session-grain archive of report totals.

Raw jsonl can be deleted once this file holds the computed subtotals.
Writes after each report build; reads back as synthetic entries when a day's
live transcripts fall short of the stored totals.
"""

from __future__ import annotations

import contextlib
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo
import json
import logging
import os
from pathlib import Path
import tempfile
import threading
from typing import NotRequired, TypeGuard, TypedDict

from adapters import agy
from adapters.types import UsageEntry
from loaders import cache_quarantine
from usage_common.pricing import calculate_cost

logger = logging.getLogger(__name__)

SNAPSHOT_PATH = Path(os.path.expanduser("~/.usage/usage_snapshot.json"))
SNAPSHOT_SCHEMA = 1
AGENT_VERSIONS: dict[str, int] = {"antigravity": 2}
_snapshot_lock = threading.Lock()

_RowKey = tuple[str, str, str, str, str]


class SnapshotRow(TypedDict):
    session_id: str
    date: str
    agent_id: str
    model: str
    project: str
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    cost: float
    message_count: int
    first_ts: NotRequired[str]
    last_ts: NotRequired[str]


class SessionHeader(TypedDict):
    start_time: str
    duration_min: float
    project: NotRequired[str]


class UsageSnapshot(TypedDict):
    schema_version: int
    rows: list[SnapshotRow]
    sessions: dict[str, SessionHeader]
    day_versions: NotRequired[dict[str, dict[str, int]]]


@dataclass(frozen=True)
class PeriodTotals:
    total_tokens: int
    cost: float
    sessions: int


def record_entries(
    entries: Sequence[UsageEntry],
    *,
    entry_dates: Mapping[int, date] | None = None,
) -> UsageSnapshot:
    """Merge this load into the on-disk snapshot and return the result."""
    new_rows, new_headers, new_day_versions = _aggregate_entries(entries, entry_dates)
    with _snapshot_lock:
        merged = _merge_snapshot(_read_snapshot(), new_rows, new_headers, new_day_versions)
        _write_snapshot(merged)
        return merged


def read_snapshot() -> UsageSnapshot:
    return _read_snapshot()


def period_totals(
    snapshot: UsageSnapshot,
    date_from: date,
    date_to: date,
) -> PeriodTotals:
    tokens = 0
    cost = 0.0
    session_ids: set[str] = set()
    for row in snapshot["rows"]:
        try:
            day = date.fromisoformat(row["date"])
        except ValueError:
            continue
        if date_from <= day <= date_to:
            tokens += _row_tokens(row)
            cost += row["cost"]
            session_ids.add(row["session_id"])
    return PeriodTotals(total_tokens=tokens, cost=cost, sessions=len(session_ids))


def totals_match(
    snapshot_totals: PeriodTotals,
    *,
    total_tokens: int,
    cost: float,
    sessions: int,
) -> bool:
    return (
        snapshot_totals.total_tokens == total_tokens
        and snapshot_totals.sessions == sessions
        and round(snapshot_totals.cost, 4) == round(cost, 4)
    )


def earliest_date(snapshot: UsageSnapshot | None = None) -> date | None:
    payload = snapshot if snapshot is not None else _read_snapshot()
    earliest: date | None = None
    for row in payload["rows"]:
        try:
            day = date.fromisoformat(row["date"])
        except ValueError:
            continue
        if earliest is None or day < earliest:
            earliest = day
    return earliest


def replay_entries(date_from: date, date_to: date) -> list[UsageEntry]:
    """Rehydrate snapshot rows in [date_from, date_to] as synthetic UsageEntry values."""
    snapshot = _read_snapshot()
    entries: list[UsageEntry] = []
    for row in snapshot["rows"]:
        try:
            day = date.fromisoformat(row["date"])
        except ValueError:
            continue
        if date_from <= day <= date_to:
            entries.extend(_replay_row(row, snapshot["sessions"].get(row["session_id"])))
    return _lead_with_header_project(entries, snapshot["sessions"])


def should_replace_day(
    *,
    stored_tokens: int,
    stored_sessions: int,
    stored_agents: Mapping[str, int],
    stored_versions: Mapping[str, int],
    current_tokens: int,
    current_sessions: int,
    current_agents: Mapping[str, int],
    target_versions: Mapping[str, int] = AGENT_VERSIONS,
) -> bool:
    """Return True if live/current data should replace stored day totals."""
    if current_tokens >= stored_tokens:
        return True
    upgraded_agents = [
        agent
        for agent, version in target_versions.items()
        if stored_versions.get(agent, 0) < version
    ]
    if not upgraded_agents:
        return False
    if current_sessions < stored_sessions:
        return False
    return any(
        current_agents.get(agent, 0) > 0
        and all(
            current_agents.get(other, 0) >= tokens
            for other, tokens in stored_agents.items()
            if other != agent
        )
        for agent in upgraded_agents
    )


def _day_agent_versions(entries: Sequence[UsageEntry]) -> dict[str, int]:
    # Days written now are counted by the current parsers; snapshots written before
    # day_versions existed carry no versions and read as version 0.
    del entries
    return dict(AGENT_VERSIONS)


def _rows_day_stats(rows: Sequence[SnapshotRow]) -> tuple[int, int, dict[str, int]]:
    tokens = 0
    sessions: set[str] = set()
    agents: dict[str, int] = defaultdict(int)
    for row in rows:
        row_tokens = _row_tokens(row)
        tokens += row_tokens
        sessions.add(row["session_id"])
        agents[row["agent_id"]] += row_tokens
    return tokens, len(sessions), agents


def _entries_day_stats(entries: Sequence[UsageEntry]) -> tuple[int, int, dict[str, int]]:
    tokens = 0
    sessions: set[str] = set()
    agents: dict[str, int] = defaultdict(int)
    for entry in entries:
        tokens += entry.total_tokens
        sessions.add(entry.session_id)
        agents[entry.agent_id or "unknown"] += entry.total_tokens
    return tokens, len(sessions), agents


def merge_live_with_snapshot(
    live_entries: Sequence[UsageEntry],
    live_dates: Mapping[int, date],
    date_from: date,
    date_to: date,
) -> tuple[list[UsageEntry], dict[int, date]]:
    """Replace any day whose live tokens fall short of the snapshot with a replay.

    Days the snapshot does not mention are left as the live entries (possibly
    empty). Dates assigned to replayed entries are the snapshot row dates, so
    the caller does not need to re-run ``_entry_date``.
    """
    live_by_day: dict[date, list[UsageEntry]] = defaultdict(list)
    for entry in live_entries:
        day = live_dates[id(entry)]
        if date_from <= day <= date_to:
            live_by_day[day].append(entry)

    snapshot = _read_snapshot()
    snap_rows_by_day: dict[date, list[SnapshotRow]] = defaultdict(list)
    replay_by_day: dict[date, list[UsageEntry]] = defaultdict(list)
    for row in snapshot["rows"]:
        try:
            day = date.fromisoformat(row["date"])
        except ValueError:
            continue
        if date_from <= day <= date_to:
            snap_rows_by_day[day].append(row)
            replay_by_day[day].extend(_replay_row(row, snapshot["sessions"].get(row["session_id"])))
    for day, day_entries in replay_by_day.items():
        replay_by_day[day] = _lead_with_header_project(day_entries, snapshot["sessions"])
    snap_day_versions = snapshot.get("day_versions", {})

    merged: list[UsageEntry] = []
    merged_dates: dict[int, date] = {}
    cursor = date_from
    while cursor <= date_to:
        live_day = live_by_day.get(cursor, [])
        snap_rows = snap_rows_by_day.get(cursor)
        if snap_rows is None:
            chosen = live_day
        else:
            snap_tokens, snap_sessions, snap_agents = _rows_day_stats(snap_rows)
            live_tokens, live_sessions, live_agents = _entries_day_stats(live_day)
            if should_replace_day(
                stored_tokens=snap_tokens,
                stored_sessions=snap_sessions,
                stored_agents=snap_agents,
                stored_versions=snap_day_versions.get(cursor.isoformat(), {}),
                current_tokens=live_tokens,
                current_sessions=live_sessions,
                current_agents=live_agents,
                target_versions=_day_agent_versions(live_day),
            ):
                chosen = live_day
            else:
                chosen = replay_by_day.get(cursor, [])
        for entry in chosen:
            merged.append(entry)
            merged_dates[id(entry)] = cursor
        cursor += timedelta(days=1)
    return merged, merged_dates


def _empty_snapshot() -> UsageSnapshot:
    return {
        "schema_version": SNAPSHOT_SCHEMA,
        "rows": [],
        "sessions": {},
        "day_versions": {},
    }


def _entry_date(entry: UsageEntry) -> date:
    ts = entry.timestamp
    if ts.tzinfo:
        ts = ts.astimezone()
    return ts.date()


def _is_int(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: object) -> TypeGuard[int | float]:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _row_tokens(row: SnapshotRow) -> int:
    return (
        row["input_tokens"]
        + row["output_tokens"]
        + row["cache_creation_tokens"]
        + row["cache_read_tokens"]
    )


def _day_tokens(rows: Sequence[SnapshotRow]) -> int:
    return sum(_row_tokens(row) for row in rows)


def _row_key(row: SnapshotRow) -> _RowKey:
    return (
        row["session_id"],
        row["date"],
        row["agent_id"],
        row["model"],
        row["project"],
    )


def _parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _earlier_start(old: str, new: str) -> str:
    old_dt = _parse_iso(old)
    new_dt = _parse_iso(new)
    if old_dt is None:
        return new
    if new_dt is None:
        return old
    try:
        return old if old_dt <= new_dt else new
    except TypeError:
        return old


def _later_end(old: str, new: str) -> str:
    old_dt = _parse_iso(old)
    new_dt = _parse_iso(new)
    if old_dt is None:
        return new
    if new_dt is None:
        return old
    try:
        return old if old_dt >= new_dt else new
    except TypeError:
        return old


def _datetime_local_date(ts: datetime) -> date:
    if ts.tzinfo:
        ts = ts.astimezone()
    return ts.date()


def _local_tz() -> tzinfo | None:
    return datetime.now().astimezone().tzinfo


def _midnight(day: date, tz: tzinfo | None) -> datetime:
    if tz is None:
        return datetime(day.year, day.month, day.day)
    return datetime(day.year, day.month, day.day, tzinfo=_local_tz())


def _token_timestamp(day: date, start: datetime | None, duration_min: float) -> datetime:
    if start is None:
        return _midnight(day, None)
    if _datetime_local_date(start) == day:
        return start
    if duration_min > 0:
        end = start + timedelta(minutes=duration_min)
        if _datetime_local_date(end) == day:
            return end
    return _midnight(day, start.tzinfo)


def _synthetic_ids(row: SnapshotRow, suffix: str) -> tuple[str, str]:
    key = (
        f"{row['session_id']}|{row['date']}|{row['agent_id']}|"
        f"{row['model']}|{row['project']}{suffix}"
    )
    token = f"usage-snapshot:{key}"
    return token, token


def _replay_model(row: SnapshotRow) -> str:
    # Rows recorded before agy names were normalized keep raw IDs (gemini-3.8-flash-n).
    if row["agent_id"] == "antigravity":
        return agy._normalize_model(row["model"])
    return row["model"]


def _zero_entry(row: SnapshotRow, timestamp: datetime, suffix: str) -> UsageEntry:
    message_id, request_id = _synthetic_ids(row, suffix)
    return UsageEntry(
        timestamp=timestamp,
        session_id=row["session_id"],
        message_id=message_id,
        request_id=request_id,
        model=_replay_model(row),
        input_tokens=0,
        output_tokens=0,
        cache_creation_tokens=0,
        cache_read_tokens=0,
        cost_usd=0.0,
        project=row["project"],
        agent_id=row["agent_id"],
        message_count=0,
    )


def _replay_row(row: SnapshotRow, header: SessionHeader | None) -> list[UsageEntry]:
    day = date.fromisoformat(row["date"])
    parsed_first = _parse_iso(row["first_ts"]) if row.get("first_ts") else None
    parsed_last = _parse_iso(row["last_ts"]) if row.get("last_ts") else None
    if parsed_first is not None:
        first_ts = parsed_first
        last_ts = parsed_last if parsed_last is not None else parsed_first
    else:
        start = _parse_iso(header["start_time"]) if header is not None else None
        duration_min = float(header["duration_min"]) if header is not None else 0.0
        first_ts = _token_timestamp(day, start, duration_min)
        last_ts = first_ts
        if duration_min > 0:
            end_ts = (
                start + timedelta(minutes=duration_min)
                if start is not None
                else first_ts + timedelta(minutes=duration_min)
            )
            if _datetime_local_date(end_ts) == day and end_ts != first_ts:
                last_ts = end_ts
    message_id, request_id = _synthetic_ids(row, "")
    entries = [
        UsageEntry(
            timestamp=first_ts,
            session_id=row["session_id"],
            message_id=message_id,
            request_id=request_id,
            model=_replay_model(row),
            input_tokens=row["input_tokens"],
            output_tokens=row["output_tokens"],
            cache_creation_tokens=row["cache_creation_tokens"],
            cache_read_tokens=row["cache_read_tokens"],
            # Live agy entries carry no cost and are priced on read; replay them the same
            # way so rows stored while their model was unpriced are not frozen at 0.
            cost_usd=None if row["agent_id"] == "antigravity" else row["cost"],
            project=row["project"],
            agent_id=row["agent_id"],
            message_count=row["message_count"],
        )
    ]
    if last_ts != first_ts:
        entries.append(_zero_entry(row, last_ts, ":end"))
    return entries


def _new_row(
    *,
    session_id: str,
    day: str,
    agent_id: str,
    model: str,
    project: str,
) -> SnapshotRow:
    return {
        "session_id": session_id,
        "date": day,
        "agent_id": agent_id,
        "model": model,
        "project": project,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_tokens": 0,
        "cache_read_tokens": 0,
        "cost": 0.0,
        "message_count": 0,
    }


def _row_from_json(value: object) -> SnapshotRow | None:
    if not isinstance(value, dict):
        return None
    session_id = value.get("session_id")
    day = value.get("date")
    agent_id = value.get("agent_id")
    model = value.get("model")
    project = value.get("project")
    input_tokens = value.get("input_tokens")
    output_tokens = value.get("output_tokens")
    cache_creation_tokens = value.get("cache_creation_tokens")
    cache_read_tokens = value.get("cache_read_tokens")
    cost = value.get("cost")
    message_count = value.get("message_count")
    if (
        not isinstance(session_id, str)
        or not isinstance(day, str)
        or not isinstance(agent_id, str)
        or not isinstance(model, str)
        or not isinstance(project, str)
        or not _is_int(input_tokens)
        or not _is_int(output_tokens)
        or not _is_int(cache_creation_tokens)
        or not _is_int(cache_read_tokens)
        or not _is_number(cost)
        or not _is_int(message_count)
    ):
        return None
    try:
        date.fromisoformat(day)
    except ValueError:
        return None
    row: SnapshotRow = {
        "session_id": session_id,
        "date": day,
        "agent_id": agent_id,
        "model": model,
        "project": project,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_creation_tokens": cache_creation_tokens,
        "cache_read_tokens": cache_read_tokens,
        "cost": float(cost),
        "message_count": message_count,
    }
    first_ts = value.get("first_ts")
    last_ts = value.get("last_ts")
    if isinstance(first_ts, str) and first_ts:
        row["first_ts"] = first_ts
    if isinstance(last_ts, str) and last_ts:
        row["last_ts"] = last_ts
    return row


def _header_from_json(value: object) -> SessionHeader | None:
    if not isinstance(value, dict):
        return None
    start_time = value.get("start_time")
    duration_min = value.get("duration_min")
    if not isinstance(start_time, str) or not start_time or not _is_number(duration_min):
        return None
    header: SessionHeader = {
        "start_time": start_time,
        "duration_min": float(duration_min),
    }
    project = value.get("project")
    if isinstance(project, str) and project:
        header["project"] = project
    return header


def _lead_with_header_project(
    entries: list[UsageEntry],
    sessions: Mapping[str, SessionHeader],
) -> list[UsageEntry]:
    """Within each session, put the header-project row first; keep the rest."""
    if not entries or not any(header.get("project") for header in sessions.values()):
        return entries
    grouped: dict[str, list[UsageEntry]] = {}
    order: list[str] = []
    for entry in entries:
        bucket = grouped.get(entry.session_id)
        if bucket is None:
            grouped[entry.session_id] = [entry]
            order.append(entry.session_id)
        else:
            bucket.append(entry)
    result: list[UsageEntry] = []
    for session_id in order:
        group = grouped[session_id]
        header = sessions.get(session_id)
        project = header.get("project") if header is not None else None
        if not project:
            result.extend(group)
            continue
        result.extend(entry for entry in group if entry.project == project)
        result.extend(entry for entry in group if entry.project != project)
    return result


def _read_snapshot() -> UsageSnapshot:
    try:
        with SNAPSHOT_PATH.open(encoding="utf-8") as file:
            payload = json.load(file)
    except FileNotFoundError:
        return _empty_snapshot()
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        if os.environ.get("USAGE_DEBUG") == "1":
            logger.warning(
                "failed to read usage snapshot %s",
                SNAPSHOT_PATH,
                exc_info=True,
            )
        cache_quarantine.quarantine(SNAPSHOT_PATH, "usage snapshot unreadable")
        return _empty_snapshot()

    if not isinstance(payload, dict):
        cache_quarantine.quarantine(SNAPSHOT_PATH, "usage snapshot schema unreadable")
        return _empty_snapshot()
    if payload.get("schema_version") != SNAPSHOT_SCHEMA:
        logger.warning(
            "usage snapshot schema mismatch in %s: expected %s, got %s; rebuilding",
            SNAPSHOT_PATH,
            SNAPSHOT_SCHEMA,
            payload.get("schema_version"),
        )
        return _empty_snapshot()

    raw_rows = payload.get("rows")
    raw_sessions = payload.get("sessions")
    rows: list[SnapshotRow] = []
    if isinstance(raw_rows, list):
        seen: dict[_RowKey, SnapshotRow] = {}
        for raw_row in raw_rows:
            row = _row_from_json(raw_row)
            if row is not None:
                seen[_row_key(row)] = row
        rows = list(seen.values())
    sessions: dict[str, SessionHeader] = {}
    if isinstance(raw_sessions, dict):
        for session_id, raw_header in raw_sessions.items():
            if not isinstance(session_id, str):
                continue
            header = _header_from_json(raw_header)
            if header is not None:
                sessions[session_id] = header
    raw_day_versions = payload.get("day_versions")
    day_versions: dict[str, dict[str, int]] = {}
    if isinstance(raw_day_versions, dict):
        for day_key, raw_versions in raw_day_versions.items():
            if not isinstance(day_key, str) or not isinstance(raw_versions, dict):
                continue
            try:
                date.fromisoformat(day_key)
            except ValueError:
                continue
            parsed_versions = {
                agent: version
                for agent, version in raw_versions.items()
                if isinstance(agent, str) and _is_int(version)
            }
            if parsed_versions:
                day_versions[day_key] = parsed_versions
    return {
        "schema_version": SNAPSHOT_SCHEMA,
        "rows": rows,
        "sessions": sessions,
        "day_versions": day_versions,
    }


def _write_snapshot(snapshot: UsageSnapshot) -> None:
    tmp_path: str | None = None
    try:
        SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=SNAPSHOT_PATH.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(snapshot, file, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp_path, SNAPSHOT_PATH)
        tmp_path = None
    except Exception as exc:
        if os.environ.get("USAGE_DEBUG") == "1":
            logger.warning("failed to write usage snapshot %s: %s", SNAPSHOT_PATH, exc)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)


def _aggregate_entries(
    entries: Sequence[UsageEntry],
    entry_dates: Mapping[int, date] | None,
) -> tuple[dict[_RowKey, SnapshotRow], dict[str, SessionHeader], dict[str, dict[str, int]]]:
    rows: dict[_RowKey, SnapshotRow] = {}
    by_session: dict[str, list[UsageEntry]] = defaultdict(list)
    by_day_entries: dict[str, list[UsageEntry]] = defaultdict(list)
    for entry in entries:
        day = (
            entry_dates.get(id(entry), _entry_date(entry))
            if entry_dates is not None
            else _entry_date(entry)
        )
        day_key = day.isoformat()
        agent_id = entry.agent_id or "unknown"
        model = entry.model or "unknown"
        project = entry.project or "unknown"
        key: _RowKey = (entry.session_id, day_key, agent_id, model, project)
        row = rows.get(key)
        if row is None:
            row = _new_row(
                session_id=entry.session_id,
                day=day_key,
                agent_id=agent_id,
                model=model,
                project=project,
            )
            rows[key] = row
        row["input_tokens"] += entry.input_tokens
        row["output_tokens"] += entry.output_tokens
        row["cache_creation_tokens"] += entry.cache_creation_tokens
        row["cache_read_tokens"] += entry.cache_read_tokens
        row["cost"] += calculate_cost(entry)
        row["message_count"] += entry.message_count
        ts_iso = entry.timestamp.isoformat()
        current_first = row.get("first_ts")
        current_last = row.get("last_ts")
        row["first_ts"] = ts_iso if current_first is None else _earlier_start(current_first, ts_iso)
        row["last_ts"] = ts_iso if current_last is None else _later_end(current_last, ts_iso)
        by_session[entry.session_id].append(entry)
        by_day_entries[day_key].append(entry)

    headers: dict[str, SessionHeader] = {}
    for session_id, group in by_session.items():
        group.sort(key=lambda item: item.timestamp)
        first = group[0]
        last = group[-1]
        try:
            duration = (last.timestamp - first.timestamp).total_seconds() / 60
        except TypeError:
            duration = 0.0
        headers[session_id] = {
            "start_time": first.timestamp.isoformat(),
            "duration_min": round(duration, 1),
            "project": first.project or "unknown",
        }
    day_versions = {
        day_key: versions
        for day_key, day_entries in by_day_entries.items()
        if (versions := _day_agent_versions(day_entries))
    }
    return rows, headers, day_versions


def _merge_snapshot(
    current: UsageSnapshot,
    new_rows: dict[_RowKey, SnapshotRow],
    new_headers: dict[str, SessionHeader],
    new_day_versions: Mapping[str, Mapping[str, int]],
) -> UsageSnapshot:
    old_by_day: dict[str, list[SnapshotRow]] = defaultdict(list)
    for row in current["rows"]:
        old_by_day[row["date"]].append(row)

    new_by_day: dict[str, list[SnapshotRow]] = defaultdict(list)
    for row in new_rows.values():
        new_by_day[row["date"]].append(row)

    old_day_versions = current.get("day_versions", {})
    merged_day_versions: dict[str, dict[str, int]] = {}
    merged_rows: list[SnapshotRow] = []
    for day, rows in old_by_day.items():
        if day not in new_by_day:
            merged_rows.extend(rows)
            if day in old_day_versions:
                merged_day_versions[day] = dict(old_day_versions[day])

    for day, rows in new_by_day.items():
        old_rows = old_by_day.get(day)
        target_versions = new_day_versions.get(day, {})
        if old_rows is None:
            merged_rows.extend(rows)
            if target_versions:
                merged_day_versions[day] = dict(target_versions)
            continue
        old_tokens, old_sessions, old_agents = _rows_day_stats(old_rows)
        new_tokens, new_sessions, new_agents = _rows_day_stats(rows)
        if should_replace_day(
            stored_tokens=old_tokens,
            stored_sessions=old_sessions,
            stored_agents=old_agents,
            stored_versions=old_day_versions.get(day, {}),
            current_tokens=new_tokens,
            current_sessions=new_sessions,
            current_agents=new_agents,
            target_versions=target_versions,
        ):
            merged_rows.extend(rows)
            # Unchanged totals (e.g. a day replayed from this snapshot) prove nothing about
            # the parser that counted them, so they keep the stored versions.
            unchanged = new_tokens == old_tokens and new_sessions == old_sessions
            versions = old_day_versions.get(day, {}) if unchanged else target_versions
            if versions:
                merged_day_versions[day] = dict(versions)
        else:
            merged_rows.extend(old_rows)
            if day in old_day_versions:
                merged_day_versions[day] = dict(old_day_versions[day])

    merged_rows.sort(
        key=lambda row: (
            row["date"],
            row["session_id"],
            row["agent_id"],
            row["model"],
            row["project"],
        )
    )

    merged_headers = dict(current["sessions"])
    for session_id, header in new_headers.items():
        existing = merged_headers.get(session_id)
        if existing is None:
            merged_headers[session_id] = header
            continue
        start_time = _earlier_start(existing["start_time"], header["start_time"])
        merged_header: SessionHeader = {
            "start_time": start_time,
            "duration_min": max(existing["duration_min"], header["duration_min"]),
        }
        if start_time == existing["start_time"]:
            project = existing.get("project") or header.get("project")
        else:
            project = header.get("project")
        if project:
            merged_header["project"] = project
        merged_headers[session_id] = merged_header
    return {
        "schema_version": SNAPSHOT_SCHEMA,
        "rows": merged_rows,
        "sessions": merged_headers,
        "day_versions": merged_day_versions,
    }

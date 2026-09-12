# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Permanent session-grain archive of report totals.

Raw jsonl can be deleted once this file holds the computed subtotals.
This module only writes; the report still reads live entries.
"""

from __future__ import annotations

import contextlib
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
import json
import logging
import os
from pathlib import Path
import tempfile
from typing import TypeGuard, TypedDict

from adapters.types import UsageEntry
from loaders import cache_quarantine
from pricing import calculate_cost

logger = logging.getLogger(__name__)

SNAPSHOT_PATH = Path(os.path.expanduser("~/.usage/usage_snapshot.json"))
SNAPSHOT_SCHEMA = 1

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


class SessionHeader(TypedDict):
    start_time: str
    duration_min: float


class UsageSnapshot(TypedDict):
    schema_version: int
    rows: list[SnapshotRow]
    sessions: dict[str, SessionHeader]


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
    new_rows, new_headers = _aggregate_entries(entries, entry_dates)
    merged = _merge_snapshot(_read_snapshot(), new_rows, new_headers)
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


def _empty_snapshot() -> UsageSnapshot:
    return {
        "schema_version": SNAPSHOT_SCHEMA,
        "rows": [],
        "sessions": {},
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
    return {
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


def _header_from_json(value: object) -> SessionHeader | None:
    if not isinstance(value, dict):
        return None
    start_time = value.get("start_time")
    duration_min = value.get("duration_min")
    if not isinstance(start_time, str) or not start_time or not _is_number(duration_min):
        return None
    return {
        "start_time": start_time,
        "duration_min": float(duration_min),
    }


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
    return {
        "schema_version": SNAPSHOT_SCHEMA,
        "rows": rows,
        "sessions": sessions,
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
) -> tuple[dict[_RowKey, SnapshotRow], dict[str, SessionHeader]]:
    rows: dict[_RowKey, SnapshotRow] = {}
    by_session: dict[str, list[UsageEntry]] = defaultdict(list)
    for entry in entries:
        day = entry_dates.get(id(entry), _entry_date(entry)) if entry_dates is not None else _entry_date(entry)
        agent_id = entry.agent_id or "unknown"
        model = entry.model or "unknown"
        project = entry.project or "unknown"
        key: _RowKey = (entry.session_id, day.isoformat(), agent_id, model, project)
        row = rows.get(key)
        if row is None:
            row = _new_row(
                session_id=entry.session_id,
                day=day.isoformat(),
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
        by_session[entry.session_id].append(entry)

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
        }
    return rows, headers


def _merge_snapshot(
    current: UsageSnapshot,
    new_rows: dict[_RowKey, SnapshotRow],
    new_headers: dict[str, SessionHeader],
) -> UsageSnapshot:
    old_by_day: dict[str, list[SnapshotRow]] = defaultdict(list)
    for row in current["rows"]:
        old_by_day[row["date"]].append(row)

    new_by_day: dict[str, list[SnapshotRow]] = defaultdict(list)
    for row in new_rows.values():
        new_by_day[row["date"]].append(row)

    merged_rows: list[SnapshotRow] = []
    for day, rows in old_by_day.items():
        if day not in new_by_day:
            merged_rows.extend(rows)

    for day, rows in new_by_day.items():
        old_rows = old_by_day.get(day)
        if old_rows is None or _day_tokens(rows) >= _day_tokens(old_rows):
            merged_rows.extend(rows)
        else:
            merged_rows.extend(old_rows)

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
        merged_headers[session_id] = {
            "start_time": _earlier_start(existing["start_time"], header["start_time"]),
            "duration_min": max(existing["duration_min"], header["duration_min"]),
        }
    return {
        "schema_version": SNAPSHOT_SCHEMA,
        "rows": merged_rows,
        "sessions": merged_headers,
    }

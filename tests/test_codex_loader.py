# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

import codex_loader
from tests.helpers import write_codex_session as _write_session
from tests.helpers import (
    write_codex_session_with_turn_context_model as _write_session_with_turn_context_model,
)


@pytest.fixture(autouse=True)
def _clear_jsonl_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    codex_loader._jsonl_cache.clear()
    codex_loader._fork_replay_cache.clear()
    codex_loader._file_info_cache.clear()
    monkeypatch.setattr(codex_loader, "ARCHIVED_SESSIONS_DIR", tmp_path / "missing-archived")
    monkeypatch.setattr(codex_loader, "LOGS_DB", tmp_path / "missing-logs.sqlite")
    monkeypatch.setattr(codex_loader, "STATE_DB", tmp_path / "missing-state.sqlite")


def _write_rate_limit_session(path: Path, timestamp: str, rate_limits: dict[str, Any] | None, mtime: float) -> None:  # noqa: E501
    _write_session(path, session_id=path.stem, timestamp=timestamp, rate_limits=rate_limits, mtime=mtime)  # noqa: E501

def _rate_limits() -> dict[str, Any]:
    return {"primary": {"used_percent": 30, "resets_at": 9_999_999_999}, "secondary": {"used_percent": 60, "resets_at": 9_999_999_999}}  # noqa: E501


def _write_session_with_usage_events(
    path: Path,
    *,
    session_id: str,
    events: list[tuple[str, dict[str, Any]]],
    cwd: str = "/tmp/demo",
) -> None:
    lines = [
        {
            "type": "session_meta",
            "payload": {"id": session_id, "timestamp": events[0][0], "cwd": cwd},
        },
    ]
    lines.extend(
        {
            "type": "event_msg",
            "timestamp": timestamp,
            "payload": {"type": "token_count", "info": {"total_token_usage": usage}},
        }
        for timestamp, usage in events
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")


def _write_fork_session(
    path: Path,
    *,
    session_id: str,
    parent_session_id: str,
    timestamp: str,
    replay_events: list[dict[str, Any]],
    own_events: list[tuple[str, dict[str, Any]]],
) -> None:
    lines = [
        {
            "type": "session_meta",
            "timestamp": timestamp,
            "payload": {
                "id": session_id,
                "forked_from_id": parent_session_id,
                "timestamp": timestamp,
                "cwd": "/tmp/fork",
            },
        },
        {
            "type": "session_meta",
            "timestamp": timestamp,
            "payload": {
                "id": parent_session_id,
                "timestamp": "2026-01-01T00:00:00+00:00",
                "cwd": "/tmp/parent",
            },
        },
    ]
    lines.extend(
        {
            "type": "event_msg",
            "timestamp": timestamp,
            "payload": {"type": "token_count", "info": {"total_token_usage": usage}},
        }
        for usage in replay_events
    )
    lines.append(
        {
            "type": "event_msg",
            "timestamp": timestamp,
            "payload": {"type": "thread_rolled_back", "num_turns": 1},
        }
    )
    lines.extend(
        {
            "type": "event_msg",
            "timestamp": event_timestamp,
            "payload": {"type": "token_count", "info": {"total_token_usage": usage}},
        }
        for event_timestamp, usage in own_events
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")


def test_load_entries_returns_empty_list_when_sessions_dir_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", tmp_path / "missing")
    monkeypatch.setattr(codex_loader, "LOGS_DB", tmp_path / "missing.sqlite")

    assert codex_loader.load_entries() == []


def test_load_entries_parses_valid_jsonl_and_filters_by_hours_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sessions_dir = tmp_path / "sessions"
    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(
        codex_loader,
        "_load_thread_metadata",
        lambda: {
            "session-old": codex_loader._ThreadMetadata(model="gpt-test"),
            "session-new": codex_loader._ThreadMetadata(model="gpt-test"),
        },
    )
    old_ts = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    new_ts = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    _write_session(
        sessions_dir / "old.jsonl",
        session_id="session-old",
        timestamp=old_ts,
        usage={"input_tokens": 10, "cached_input_tokens": 2, "output_tokens": 3},
    )
    _write_session(
        sessions_dir / "new.jsonl",
        session_id="session-new",
        timestamp=new_ts,
        usage={"input_tokens": 20, "cached_input_tokens": 5, "output_tokens": 7},
    )

    all_entries = codex_loader.load_entries()
    recent_entries = codex_loader.load_entries(hours_back=1)

    assert [entry.input_tokens for entry in all_entries] == [8, 15]
    assert [entry.output_tokens for entry in all_entries] == [3, 7]
    assert all(entry.model == "gpt-test" for entry in all_entries)
    assert len(recent_entries) == 1
    assert recent_entries[0].input_tokens == 15
    assert recent_entries[0].output_tokens == 7


def test_load_entries_includes_archived_sessions_when_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sessions_dir = tmp_path / "sessions"
    archived_sessions_dir = tmp_path / "archived_sessions"
    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(codex_loader, "ARCHIVED_SESSIONS_DIR", archived_sessions_dir)
    monkeypatch.setattr(codex_loader, "_load_thread_models", lambda: {})

    timestamp = datetime.now(UTC).isoformat()
    _write_session(
        sessions_dir / "active.jsonl",
        session_id="active-session",
        timestamp=timestamp,
        usage={"input_tokens": 10, "output_tokens": 1},
    )

    active_only_entries = codex_loader.load_entries()

    _write_session(
        archived_sessions_dir / "2026" / "06" / "archived.jsonl",
        session_id="archived-session",
        timestamp=timestamp,
        usage={"input_tokens": 20, "output_tokens": 2},
    )

    all_entries = codex_loader.load_entries()

    assert [entry.session_id for entry in active_only_entries] == ["active-session"]
    assert sum(entry.total_tokens for entry in active_only_entries) == 11
    assert {entry.session_id for entry in all_entries} == {
        "active-session",
        "archived-session",
    }
    assert sum(entry.total_tokens for entry in all_entries) == 33


def test_load_entries_keeps_latest_duplicate_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sessions_dir = tmp_path / "sessions"
    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(codex_loader, "_load_thread_models", lambda: {})
    older_ts = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    newer_ts = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    _write_session(
        sessions_dir / "newer-dir" / "newer.jsonl",
        session_id="same-session",
        timestamp=newer_ts,
        usage={"input_tokens": 100, "cached_input_tokens": 20, "output_tokens": 30},
    )
    _write_session(
        sessions_dir / "older-dir" / "older.jsonl",
        session_id="same-session",
        timestamp=older_ts,
        usage={"input_tokens": 10, "cached_input_tokens": 2, "output_tokens": 3},
    )

    entries = codex_loader.load_entries()

    assert len(entries) == 1
    assert entries[0].timestamp == datetime.fromisoformat(newer_ts)
    assert entries[0].total_tokens == 130


def test_load_entries_keeps_larger_duplicate_when_timestamps_match(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sessions_dir = tmp_path / "sessions"
    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(codex_loader, "_load_thread_models", lambda: {})
    timestamp = datetime.now(UTC).isoformat()
    _write_session(
        sessions_dir / "small.jsonl",
        session_id="same-session",
        timestamp=timestamp,
        usage={"input_tokens": 10, "cached_input_tokens": 2, "output_tokens": 3},
    )
    _write_session(
        sessions_dir / "large.jsonl",
        session_id="same-session",
        timestamp=timestamp,
        usage={"input_tokens": 100, "cached_input_tokens": 20, "output_tokens": 30},
    )

    entries = codex_loader.load_entries()

    assert len(entries) == 1
    assert entries[0].total_tokens == 130


def test_load_entries_deduplicates_session_across_files_without_summing_logs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Regression guard: duplicate session jsonl files must not double-count tokens."""
    sessions_dir = tmp_path / "sessions"
    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", sessions_dir)
    timestamp_1 = datetime(2026, 1, 1, 0, 0, tzinfo=UTC).isoformat()
    timestamp_2 = datetime(2026, 1, 1, 0, 1, tzinfo=UTC).isoformat()
    timestamp_3 = datetime(2026, 1, 1, 0, 2, tzinfo=UTC).isoformat()
    _write_session_with_usage_events(
        sessions_dir / "partial.jsonl",
        session_id="duplicated-session",
        events=[
            (
                timestamp_1,
                {"input_tokens": 100, "cached_input_tokens": 20, "output_tokens": 30},
            ),
            (
                timestamp_3,
                {"input_tokens": 120, "cached_input_tokens": 25, "output_tokens": 35},
            ),
        ],
    )
    _write_session_with_usage_events(
        sessions_dir / "complete.jsonl",
        session_id="duplicated-session",
        events=[
            (
                timestamp_1,
                {"input_tokens": 100, "cached_input_tokens": 20, "output_tokens": 30},
            ),
            (
                timestamp_2,
                {"input_tokens": 130, "cached_input_tokens": 25, "output_tokens": 40},
            ),
            (
                timestamp_3,
                {"input_tokens": 180, "cached_input_tokens": 30, "output_tokens": 60},
            ),
        ],
    )

    entries = codex_loader.load_entries()

    assert [entry.message_id for entry in entries] == [
        "duplicated-session:1",
        "duplicated-session:2",
        "duplicated-session:3",
    ]
    assert [entry.total_tokens for entry in entries] == [130, 40, 70]
    assert sum(entry.total_tokens for entry in entries) == 240


def test_load_entries_splits_cumulative_usage_into_time_range_deltas(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sessions_dir = tmp_path / "sessions"
    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(codex_loader, "_load_thread_models", lambda: {})
    old_ts = (datetime.now(UTC) - timedelta(days=20)).isoformat()
    recent_ts = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    _write_session_with_usage_events(
        sessions_dir / "long-running.jsonl",
        session_id="long-running",
        events=[
            (
                old_ts,
                {
                    "input_tokens": 110,
                    "cached_input_tokens": 10,
                    "output_tokens": 50,
                },
            ),
            (
                recent_ts,
                {
                    "input_tokens": 160,
                    "cached_input_tokens": 20,
                    "output_tokens": 70,
                    "reasoning_output_tokens": 10,
                },
            ),
        ],
    )

    all_entries = codex_loader.load_entries()
    week_entries = codex_loader.load_entries(hours_back=168)

    assert [entry.total_tokens for entry in all_entries] == [160, 70]
    assert [entry.total_tokens for entry in week_entries] == [70]
    assert week_entries[0].input_tokens == 40
    assert week_entries[0].output_tokens == 20
    assert week_entries[0].cache_read_tokens == 10


def test_load_entries_skips_jsonl_when_file_mtime_is_older_than_cutoff(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Regression guard: old session file mtimes must stay outside cutoff scans."""
    sessions_dir = tmp_path / "sessions"
    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", sessions_dir)
    recent_ts = datetime.now(UTC).replace(microsecond=0)
    stale_mtime = (recent_ts - timedelta(hours=2)).timestamp()
    _write_session(
        sessions_dir / "stale-file.jsonl",
        session_id="stale-file",
        timestamp=recent_ts.isoformat(),
        usage={"input_tokens": 100, "cached_input_tokens": 20, "output_tokens": 30},
        mtime=stale_mtime,
    )
    _write_session(
        sessions_dir / "fresh-file.jsonl",
        session_id="fresh-file",
        timestamp=recent_ts.isoformat(),
        usage={"input_tokens": 10, "cached_input_tokens": 2, "output_tokens": 3},
        mtime=recent_ts.timestamp(),
    )

    entries = codex_loader.load_entries(hours_back=1)

    assert [entry.session_id for entry in entries] == ["fresh-file"]
    assert entries[0].total_tokens == 13


def test_load_entries_excludes_replayed_parent_usage_from_fork(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sessions_dir = tmp_path / "sessions"
    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(codex_loader, "_load_thread_models", lambda: {})
    old_ts = "2026-01-01T00:00:00+00:00"
    fork_ts = datetime.now(UTC).replace(microsecond=0)
    replay_ts = fork_ts.isoformat()
    own_ts_1 = (fork_ts + timedelta(minutes=1)).isoformat()
    own_ts_2 = (fork_ts + timedelta(minutes=2)).isoformat()
    parent_usage = [
        {
            "input_tokens": 100,
            "cached_input_tokens": 20,
            "output_tokens": 30,
            "reasoning_output_tokens": 10,
        },
        {
            "input_tokens": 150,
            "cached_input_tokens": 30,
            "output_tokens": 40,
            "reasoning_output_tokens": 15,
        },
    ]
    _write_session_with_usage_events(
        sessions_dir / "parent.jsonl",
        session_id="parent",
        events=[(old_ts, parent_usage[0]), (old_ts, parent_usage[1])],
    )
    _write_fork_session(
        sessions_dir / "fork.jsonl",
        session_id="fork",
        parent_session_id="parent",
        timestamp=replay_ts,
        replay_events=parent_usage,
        own_events=[
            (
                own_ts_1,
                {
                    "input_tokens": 60,
                    "cached_input_tokens": 10,
                    "output_tokens": 8,
                    "reasoning_output_tokens": 3,
                },
            ),
            (
                own_ts_2,
                {
                    "input_tokens": 90,
                    "cached_input_tokens": 20,
                    "output_tokens": 12,
                    "reasoning_output_tokens": 5,
                },
            ),
        ],
    )

    entries = codex_loader.load_entries()
    recent_entries = codex_loader.load_entries(hours_back=24)

    assert [entry.session_id for entry in entries] == ["parent", "parent", "fork", "fork"]
    assert [entry.total_tokens for entry in entries] == [130, 60, 68, 34]
    assert [entry.session_id for entry in recent_entries] == ["fork", "fork"]
    assert [entry.timestamp for entry in recent_entries] == [
        datetime.fromisoformat(own_ts_1),
        datetime.fromisoformat(own_ts_2),
    ]


def test_load_entries_excludes_recent_replay_events_from_fork_cutoff_window(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Regression guard for #40: fork replay timestamps must not become new usage."""
    sessions_dir = tmp_path / "sessions"
    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", sessions_dir)
    parent_ts = "2026-01-01T00:00:00+00:00"
    fork_ts = datetime.now(UTC).replace(microsecond=0)
    own_ts = (fork_ts + timedelta(minutes=1)).isoformat()
    parent_usage = [
        {"input_tokens": 100, "cached_input_tokens": 20, "output_tokens": 30},
        {"input_tokens": 150, "cached_input_tokens": 30, "output_tokens": 40},
    ]
    _write_session_with_usage_events(
        sessions_dir / "parent.jsonl",
        session_id="parent",
        events=[(parent_ts, parent_usage[0]), (parent_ts, parent_usage[1])],
    )
    _write_fork_session(
        sessions_dir / "fork.jsonl",
        session_id="fork",
        parent_session_id="parent",
        timestamp=fork_ts.isoformat(),
        replay_events=parent_usage,
        own_events=[
            (
                own_ts,
                {"input_tokens": 80, "cached_input_tokens": 10, "output_tokens": 12},
            )
        ],
    )

    entries = codex_loader.load_entries(hours_back=24)

    assert [entry.session_id for entry in entries] == ["fork"]
    assert [entry.timestamp for entry in entries] == [datetime.fromisoformat(own_ts)]
    assert [entry.total_tokens for entry in entries] == [92]


def test_load_entries_handles_duplicate_snapshots_across_multiple_forks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sessions_dir = tmp_path / "sessions"
    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(codex_loader, "_load_thread_models", lambda: {})
    timestamp = datetime.now(UTC).replace(microsecond=0)
    first_usage = {"input_tokens": 100, "cached_input_tokens": 20, "output_tokens": 30}
    second_usage = {"input_tokens": 150, "cached_input_tokens": 30, "output_tokens": 40}
    replay = [first_usage, first_usage, second_usage]
    _write_session_with_usage_events(
        sessions_dir / "parent.jsonl",
        session_id="parent",
        events=[
            ("2026-01-01T00:00:00+00:00", first_usage),
            ("2026-01-01T00:01:00+00:00", first_usage),
            ("2026-01-01T00:02:00+00:00", second_usage),
        ],
    )
    for index in range(2):
        _write_fork_session(
            sessions_dir / f"fork-{index}.jsonl",
            session_id=f"fork-{index}",
            parent_session_id="parent",
            timestamp=timestamp.isoformat(),
            replay_events=replay,
            own_events=[
                (
                    (timestamp + timedelta(minutes=index + 1)).isoformat(),
                    {
                        "input_tokens": 60 + index,
                        "cached_input_tokens": 10,
                        "output_tokens": 8,
                    },
                )
            ],
        )

    entries = codex_loader.load_entries()

    assert [entry.session_id for entry in entries] == [
        "parent",
        "parent",
        "fork-0",
        "fork-1",
    ]
    assert [entry.total_tokens for entry in entries] == [130, 60, 68, 69]


def test_load_entries_skips_fork_jsonl_when_parent_replay_source_is_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sessions_dir = tmp_path / "sessions"
    state_db = tmp_path / "state.sqlite"
    logs_db = tmp_path / "logs.sqlite"
    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(codex_loader, "STATE_DB", state_db)
    monkeypatch.setattr(codex_loader, "LOGS_DB", logs_db)
    timestamp = datetime.now(UTC).replace(microsecond=0)
    usage = {"input_tokens": 100, "cached_input_tokens": 20, "output_tokens": 30}
    _write_fork_session(
        sessions_dir / "fork.jsonl",
        session_id="fork",
        parent_session_id="missing-parent",
        timestamp=timestamp.isoformat(),
        replay_events=[usage],
        own_events=[((timestamp + timedelta(minutes=1)).isoformat(), usage)],
    )
    sqlite_timestamp = timestamp + timedelta(minutes=2)
    _create_state_db(state_db, [("fork", "gpt-test", "/tmp/fork")])
    _create_logs_db(
        logs_db,
        [
            (
                1,
                int(sqlite_timestamp.timestamp()),
                _sqlite_token_body(
                    session_id="fork",
                    timestamp=sqlite_timestamp.isoformat().replace("+00:00", "Z"),
                    input_tokens=50,
                    output_tokens=3,
                    cached_tokens=10,
                ),
            )
        ],
    )

    entries = codex_loader.load_entries()

    assert len(entries) == 1
    assert entries[0].message_id.startswith("fork:sqlite:")
    assert entries[0].total_tokens == 53


def _create_state_db(path: Path, rows: list[tuple[str, str, str]]) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE threads (id TEXT, model TEXT, cwd TEXT)")
        conn.executemany("INSERT INTO threads (id, model, cwd) VALUES (?, ?, ?)", rows)


def _create_logs_db(
    path: Path,
    rows: list[tuple[int, int, str]],
    *,
    target: str = "codex_otel.trace_safe",
) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE logs ("
            "id INTEGER PRIMARY KEY, "
            "ts INTEGER NOT NULL, "
            "ts_nanos INTEGER NOT NULL, "
            "level TEXT NOT NULL DEFAULT 'INFO', "
            "target TEXT NOT NULL, "
            "feedback_log_body TEXT, "
            "module_path TEXT, "
            "file TEXT, "
            "line INTEGER, "
            "thread_id TEXT, "
            "process_uuid TEXT, "
            "estimated_bytes INTEGER NOT NULL DEFAULT 0)"
        )
        for row_id, ts, body in rows:
            conn.execute(
                "INSERT INTO logs (id, ts, ts_nanos, target, feedback_log_body) "
                "VALUES (?, ?, ?, ?, ?)",
                (row_id, ts, row_id * 10, target, body),
            )


def _sqlite_token_body(
    *,
    session_id: str,
    timestamp: str,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int,
    reasoning_tokens: int = 0,
    model: str = "gpt-test",
) -> str:
    return (
        'event.name="codex.sse_event" event.kind=response.completed '
        f"input_token_count={input_tokens} output_token_count={output_tokens} "
        f"cached_token_count={cached_tokens} reasoning_token_count={reasoning_tokens} "
        f"tool_token_count={input_tokens + output_tokens} event.timestamp={timestamp} "
        f"conversation.id={session_id} model={model}"
    )


def test_load_entries_includes_sqlite_logs_when_sessions_dir_is_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sessions_dir = tmp_path / "missing-sessions"
    state_db = tmp_path / "state.sqlite"
    logs_db = tmp_path / "logs.sqlite"
    timestamp = datetime.now(UTC).replace(microsecond=0)
    _create_state_db(state_db, [("session-sqlite", "gpt-state", "/tmp/demo")])
    _create_logs_db(
        logs_db,
        [
            (
                1,
                int(timestamp.timestamp()),
                _sqlite_token_body(
                    session_id="session-sqlite",
                    timestamp=timestamp.isoformat().replace("+00:00", "Z"),
                    input_tokens=100,
                    output_tokens=7,
                    cached_tokens=20,
                    reasoning_tokens=3,
                ),
            )
        ],
    )
    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(codex_loader, "STATE_DB", state_db)
    monkeypatch.setattr(codex_loader, "LOGS_DB", logs_db)

    entries = codex_loader.load_entries()

    assert len(entries) == 1
    assert entries[0].timestamp == timestamp
    assert entries[0].session_id == "session-sqlite"
    assert entries[0].input_tokens == 80
    assert entries[0].output_tokens == 7
    assert entries[0].cache_read_tokens == 20
    assert entries[0].total_tokens == 107
    assert entries[0].project == "demo"


def test_sqlite_reads_close_connections(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class _Cursor:
        def __init__(self, rows: list[tuple[Any, ...]]) -> None:
            self._rows = rows

        def fetchall(self) -> list[tuple[Any, ...]]:
            return self._rows

    class _Connection:
        def __init__(self) -> None:
            self.closed = False

        def execute(self, *_args: Any) -> _Cursor:
            return _Cursor([])

        def close(self) -> None:
            self.closed = True

    connections: list[_Connection] = []

    def _connect(*_args: Any, **_kwargs: Any) -> _Connection:
        conn = _Connection()
        connections.append(conn)
        return conn

    state_db = tmp_path / "state.sqlite"
    logs_db = tmp_path / "logs.sqlite"
    state_db.touch()
    logs_db.touch()
    monkeypatch.setattr(codex_loader, "STATE_DB", state_db)
    monkeypatch.setattr(codex_loader, "LOGS_DB", logs_db)
    monkeypatch.setattr(sqlite3, "connect", _connect)

    assert codex_loader._load_thread_metadata() == {}
    assert codex_loader._load_sqlite_rate_limits() is None
    assert codex_loader._load_sqlite_log_entries({}, None, {}) == []

    assert len(connections) == 3
    assert all(conn.closed for conn in connections)


def test_load_entries_skips_sqlite_logs_already_covered_by_jsonl(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sessions_dir = tmp_path / "sessions"
    state_db = tmp_path / "state.sqlite"
    logs_db = tmp_path / "logs.sqlite"
    old_ts = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    jsonl_ts = datetime(2026, 1, 1, 0, 5, tzinfo=UTC)
    new_ts = datetime(2026, 1, 1, 0, 10, tzinfo=UTC)
    _write_session(
        sessions_dir / "session.jsonl",
        session_id="same-session",
        timestamp=jsonl_ts.isoformat(),
        usage={"input_tokens": 20, "cached_input_tokens": 5, "output_tokens": 4},
    )
    _create_state_db(state_db, [("same-session", "gpt-state", "/tmp/demo")])
    _create_logs_db(
        logs_db,
        [
            (
                1,
                int(old_ts.timestamp()),
                _sqlite_token_body(
                    session_id="same-session",
                    timestamp=old_ts.isoformat().replace("+00:00", "Z"),
                    input_tokens=100,
                    output_tokens=7,
                    cached_tokens=20,
                ),
            ),
            (
                2,
                int(new_ts.timestamp()),
                _sqlite_token_body(
                    session_id="same-session",
                    timestamp=new_ts.isoformat().replace("+00:00", "Z"),
                    input_tokens=50,
                    output_tokens=3,
                    cached_tokens=10,
                ),
            ),
        ],
    )
    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(codex_loader, "STATE_DB", state_db)
    monkeypatch.setattr(codex_loader, "LOGS_DB", logs_db)

    entries = codex_loader.load_entries()

    assert [entry.timestamp for entry in entries] == [jsonl_ts, new_ts]
    assert [entry.total_tokens for entry in entries] == [24, 53]


def test_parse_jsonl_skips_bad_lines_and_missing_fields(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text(
        "\n".join(
            [
                "{bad json",
                json.dumps({"type": "event_msg", "payload": {"type": "token_count"}}),
                json.dumps({"type": "session_meta", "payload": {"id": "s1"}}),
            ]
        ),
        encoding="utf-8",
    )

    assert codex_loader._parse_jsonl(path, {}, None) == []


def test_codex_session_with_bad_encoding_is_skipped(tmp_path: Path) -> None:
    # A non-UTF-8 session log must be skipped, not crash quota/history reads.
    path = tmp_path / "binary.jsonl"
    path.write_bytes(b"\xff\xfe not utf-8\n")

    assert codex_loader._parse_jsonl(path, {}, None) == []
    assert codex_loader._extract_rate_limits(path, {}) is None


def test_jsonl_cache_evicts_oldest_entry_when_maxsize_exceeded(tmp_path: Path) -> None:
    timestamp = datetime.now(UTC).isoformat()
    paths = [
        tmp_path / f"session-{index}.jsonl"
        for index in range(codex_loader._JSONL_CACHE_MAXSIZE + 1)
    ]

    for index, path in enumerate(paths):
        _write_session(
            path,
            session_id=f"session-{index}",
            timestamp=timestamp,
            usage={"input_tokens": 10, "cached_input_tokens": 2, "output_tokens": 3},
        )
        codex_loader._parse_jsonl(path, {}, None)

    assert len(codex_loader._jsonl_cache) == codex_loader._JSONL_CACHE_MAXSIZE
    assert paths[0] not in codex_loader._jsonl_cache
    assert paths[-1] in codex_loader._jsonl_cache


def test_file_info_cache_reuses_result_on_unmodified_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Second call on unchanged file returns cached result without reopening."""
    sessions_dir = tmp_path / "sessions"
    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", sessions_dir)
    path = sessions_dir / "test.jsonl"
    _write_session(
        path,
        session_id="cached-session",
        timestamp="2026-01-01T00:00:00+00:00",
        usage={"input_tokens": 10},
    )

    uncached_calls = 0
    original_uncached = codex_loader._read_session_file_info_uncached

    def _counting_uncached(p: Path) -> codex_loader._SessionFileInfo:
        nonlocal uncached_calls
        uncached_calls += 1
        return original_uncached(p)

    monkeypatch.setattr(
        codex_loader, "_read_session_file_info_uncached", _counting_uncached
    )

    first = codex_loader._read_session_file_info(path)
    assert first.session_id == "cached-session"
    assert uncached_calls == 1

    second = codex_loader._read_session_file_info(path)
    assert second.session_id == "cached-session"
    assert uncached_calls == 1, "Cached hit should not call uncached function"


def test_file_info_cache_invalidates_on_mtime_or_size_change(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Cache invalidates when file mtime or size changes."""
    sessions_dir = tmp_path / "sessions"
    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", sessions_dir)
    path = sessions_dir / "changing.jsonl"
    original_ts = "2026-01-01T00:00:00+00:00"

    _write_session(
        path,
        session_id="original-session",
        timestamp=original_ts,
        usage={"input_tokens": 10},
    )

    first = codex_loader._read_session_file_info(path)
    assert first.session_id == "original-session"

    path.touch()  # Change mtime without changing content
    second = codex_loader._read_session_file_info(path)
    assert second.session_id == "original-session"
    assert len(codex_loader._file_info_cache) == 1

    new_ts = "2026-01-02T00:00:00+00:00"
    _write_session(
        path,
        session_id="updated-session",
        timestamp=new_ts,
        usage={"input_tokens": 20},
    )

    third = codex_loader._read_session_file_info(path)
    assert third.session_id == "updated-session"


def test_file_info_cache_evicts_oldest_entry_when_maxsize_exceeded(
    tmp_path: Path,
) -> None:
    """Cache evicts oldest entry when maxsize is exceeded."""
    timestamp = datetime.now(UTC).isoformat()
    paths = [
        tmp_path / f"session-{index}.jsonl"
        for index in range(codex_loader._JSONL_CACHE_MAXSIZE + 1)
    ]

    for index, path in enumerate(paths):
        _write_session(
            path,
            session_id=f"session-{index}",
            timestamp=timestamp,
            usage={"input_tokens": 10},
        )
        codex_loader._read_session_file_info(path)

    assert len(codex_loader._file_info_cache) == codex_loader._JSONL_CACHE_MAXSIZE
    assert paths[0] not in codex_loader._file_info_cache
    assert paths[-1] in codex_loader._file_info_cache


def test_parse_timestamp_accepts_expected_iso8601_variants() -> None:
    expected = datetime(2026, 1, 1, tzinfo=UTC)

    assert codex_loader._parse_timestamp("2026-01-01T00:00:00Z") == expected
    assert codex_loader._parse_timestamp("2026-01-01T00:00:00+00:00") == expected
    assert codex_loader._parse_timestamp("2026-01-01T00:00:00") == expected


def test_load_rate_limits_returns_none_when_sessions_dir_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", tmp_path / "missing")

    assert codex_loader.load_rate_limits() is None


def test_load_rate_limits_reads_primary_and_secondary_windows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sessions_dir = tmp_path / "sessions"
    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(codex_loader, "_load_thread_models", lambda: {"session-1": "gpt-test"})
    now = datetime.now(UTC)
    meta = {
        "type": "session_meta",
        "payload": {"id": "session-1", "timestamp": now.isoformat(), "cwd": "/tmp/demo"},
    }
    payload = {
        "type": "event_msg",
        "timestamp": now.isoformat(),
        "payload": {
            "type": "token_count",
            "rate_limits": {
                "primary": {"used_percent": 25.0, "resets_at": now.timestamp() + 60},
                "secondary": {"used_percent": 70.0, "resets_at": now.timestamp() + 120},
            },
        },
    }
    path = sessions_dir / "rate.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{json.dumps(meta)}\n{json.dumps(payload)}", encoding="utf-8")

    result = codex_loader.load_rate_limits()

    assert result == codex_loader.CodexRateLimits(
        five_hour_pct=25.0,
        five_hour_resets_at=now.timestamp() + 60,
        seven_day_pct=70.0,
        seven_day_resets_at=now.timestamp() + 120,
        model="gpt-test",
        updated_at=now.isoformat(),
    )


def test_load_rate_limits_resets_expired_primary_window_to_zero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sessions_dir = tmp_path / "sessions"
    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(codex_loader, "_load_thread_models", lambda: {"session-1": "gpt-test"})
    now = datetime.now(UTC)
    _write_rate_limit_session(
        sessions_dir / "rate.jsonl",
        now.isoformat(),
        {
            "primary": {"used_percent": 42.0, "resets_at": now.timestamp() - 60},
            "secondary": {"used_percent": 70.0, "resets_at": now.timestamp() + 120},
        },
        now.timestamp(),
    )

    result = codex_loader.load_rate_limits()

    assert result is not None
    assert result.five_hour_pct == 0.0
    assert result.five_hour_resets_at is None
    assert result.seven_day_pct == 70.0


def test_load_rate_limits_prefers_sqlite_websocket_rate_limits(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sessions_dir = tmp_path / "sessions"
    logs_db = tmp_path / "logs.sqlite"
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    stale_limits = _rate_limits()
    stale_limits["primary"]["used_percent"] = 9
    _write_rate_limit_session(
        sessions_dir / "rate.jsonl",
        now.isoformat(),
        stale_limits,
        now.timestamp(),
    )
    body = (
        "session_loop{thread_id=session-sqlite}:turn{model=gpt-5.5}: "
        'websocket event: {"type":"codex.rate_limits","plan_type":"plus",'
        '"rate_limits":{"allowed":true,"limit_reached":false,'
        '"primary":{"used_percent":40,"window_minutes":300,"reset_at":9999999999},'
        '"secondary":{"used_percent":6,"window_minutes":10080,"reset_at":9999999998}},'
        '"code_review_rate_limits":null}'
    )
    _create_logs_db(
        logs_db,
        [(1, int(now.timestamp()), body)],
        target="codex_api::endpoint::responses_websocket",
    )
    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(codex_loader, "LOGS_DB", logs_db)

    result = codex_loader.load_rate_limits()

    assert result == codex_loader.CodexRateLimits(
        five_hour_pct=40.0,
        five_hour_resets_at=9999999999.0,
        seven_day_pct=6.0,
        seven_day_resets_at=9999999998.0,
        five_hour_window_minutes=300.0,
        seven_day_window_minutes=10080.0,
        model="gpt-5.5",
        updated_at=now.isoformat(),
    )


def test_load_rate_limits_uses_newer_jsonl_when_sqlite_is_stale(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sessions_dir = tmp_path / "sessions"
    logs_db = tmp_path / "logs.sqlite"
    old = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    new = datetime(2026, 1, 1, 12, 5, tzinfo=UTC)
    new_limits = _rate_limits()
    new_limits["primary"]["used_percent"] = 25
    new_limits["secondary"]["used_percent"] = 70
    _write_rate_limit_session(
        sessions_dir / "rate.jsonl",
        new.isoformat(),
        new_limits,
        new.timestamp(),
    )
    body = (
        "session_loop{thread_id=session-sqlite}:turn{model=gpt-5.5}: "
        'websocket event: {"type":"codex.rate_limits","plan_type":"plus",'
        '"rate_limits":{"allowed":true,"limit_reached":false,'
        '"primary":{"used_percent":40,"window_minutes":300,"reset_at":9999999999},'
        '"secondary":{"used_percent":6,"window_minutes":10080,"reset_at":9999999998}},'
        '"code_review_rate_limits":null}'
    )
    _create_logs_db(
        logs_db,
        [(1, int(old.timestamp()), body)],
        target="codex_api::endpoint::responses_websocket",
    )
    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(codex_loader, "LOGS_DB", logs_db)

    result = codex_loader.load_rate_limits()

    assert result == codex_loader.CodexRateLimits(
        five_hour_pct=25.0,
        five_hour_resets_at=9_999_999_999.0,
        seven_day_pct=70.0,
        seven_day_resets_at=9_999_999_999.0,
        model="unknown",
        updated_at=new.isoformat(),
    )


def test_load_rate_limits_keeps_active_sqlite_limit_over_newer_jsonl_snapshot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sessions_dir = tmp_path / "sessions"
    logs_db = tmp_path / "logs.sqlite"
    old = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    new = datetime(2026, 1, 1, 12, 5, tzinfo=UTC)
    reset_at = 9_999_999_999
    stale_limits = _rate_limits()
    stale_limits["primary"]["used_percent"] = 80
    stale_limits["primary"]["resets_at"] = reset_at
    _write_rate_limit_session(
        sessions_dir / "rate.jsonl",
        new.isoformat(),
        stale_limits,
        new.timestamp(),
    )
    body = (
        "session_loop{thread_id=session-error}:turn{model=gpt-5.5}: "
        'websocket event: {"type":"error","error":{"type":"usage_limit_reached"},'
        '"headers":{"X-Codex-Primary-Used-Percent":"100",'
        '"X-Codex-Secondary-Used-Percent":"16",'
        f'"X-Codex-Primary-Reset-At":"{reset_at}",'
        '"X-Codex-Secondary-Reset-At":"9999999998"}}'
    )
    _create_logs_db(
        logs_db,
        [(1, int(old.timestamp()), body)],
        target="codex_api::endpoint::responses_websocket",
    )
    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(codex_loader, "LOGS_DB", logs_db)

    result = codex_loader.load_rate_limits()

    assert result is not None
    assert result.five_hour_pct == 100.0
    assert result.five_hour_resets_at == float(reset_at)
    assert result.seven_day_pct == 60.0
    assert result.seven_day_resets_at == 9_999_999_999.0
    assert result.updated_at == new.isoformat()


def test_load_rate_limits_uses_newer_jsonl_after_sqlite_limit_reset_window(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sessions_dir = tmp_path / "sessions"
    logs_db = tmp_path / "logs.sqlite"
    old = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    new = datetime(2026, 1, 1, 12, 5, tzinfo=UTC)
    old_reset_at = 9_999_999_000
    new_reset_at = 9_999_999_999
    new_limits = _rate_limits()
    new_limits["primary"]["used_percent"] = 1
    new_limits["primary"]["resets_at"] = new_reset_at
    _write_rate_limit_session(
        sessions_dir / "rate.jsonl",
        new.isoformat(),
        new_limits,
        new.timestamp(),
    )
    body = (
        "session_loop{thread_id=session-error}:turn{model=gpt-5.5}: "
        'websocket event: {"type":"error","error":{"type":"usage_limit_reached"},'
        '"headers":{"X-Codex-Primary-Used-Percent":"100",'
        '"X-Codex-Secondary-Used-Percent":"16",'
        f'"X-Codex-Primary-Reset-At":"{old_reset_at}",'
        '"X-Codex-Secondary-Reset-At":"9999999998"}}'
    )
    _create_logs_db(
        logs_db,
        [(1, int(old.timestamp()), body)],
        target="codex_api::endpoint::responses_websocket",
    )
    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(codex_loader, "LOGS_DB", logs_db)

    result = codex_loader.load_rate_limits()

    assert result is not None
    assert result.five_hour_pct == 1.0
    assert result.five_hour_resets_at == float(new_reset_at)
    assert result.updated_at == new.isoformat()


def test_load_rate_limits_ignores_websocket_command_echoes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    logs_db = tmp_path / "logs.sqlite"
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    noisy_rows = [
        (
            index,
            int(now.timestamp()) + index,
            'websocket event: {"type":"response.function_call_arguments.done",'
            '"arguments":"sqlite query for \\"type\\":\\"codex.rate_limits\\""}',
        )
        for index in range(2, 82)
    ]
    body = (
        "session_loop{thread_id=session-sqlite}:turn{model=gpt-5.5}: "
        'websocket event: {"type":"codex.rate_limits","plan_type":"plus",'
        '"rate_limits":{"allowed":true,"limit_reached":false,'
        '"primary":{"used_percent":40,"window_minutes":300,"reset_at":9999999999},'
        '"secondary":{"used_percent":6,"window_minutes":10080,"reset_at":9999999998}},'
        '"code_review_rate_limits":null}'
    )
    _create_logs_db(
        logs_db,
        [(1, int(now.timestamp()), body), *noisy_rows],
        target="codex_api::endpoint::responses_websocket",
    )
    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", tmp_path / "missing-sessions")
    monkeypatch.setattr(codex_loader, "LOGS_DB", logs_db)

    result = codex_loader.load_rate_limits()

    assert result is not None
    assert result.five_hour_pct == 40.0
    assert result.seven_day_pct == 6.0


def test_load_rate_limits_skips_unescaped_quota_echoes_filling_query_window(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Regression for #23. Unescaped `"type":"codex.rate_limits"` echoes that are
    # NOT at the event head (e.g. inside a delta payload) matched the old loose
    # query. Being newer than the real row, 80 of them filled the entire
    # `ORDER BY ts DESC LIMIT 50` window and pushed the genuine rate-limits row
    # out of range, so Codex usage silently showed nothing. The tightened query
    # only matches `websocket event: {"type":"codex.rate_limits"` at the head and
    # ignores these echoes. Unlike the escaped variant above, this body actually
    # satisfies the old query, so it fails on the pre-fix loader and passes after.
    logs_db = tmp_path / "logs.sqlite"
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    noisy_rows = [
        (
            index,
            int(now.timestamp()) + index,
            'websocket event: {"type":"response.output_text.delta",'
            '"delta":"type":"codex.rate_limits"}',
        )
        for index in range(2, 82)
    ]
    body = (
        "session_loop{thread_id=session-sqlite}:turn{model=gpt-5.5}: "
        'websocket event: {"type":"codex.rate_limits","plan_type":"plus",'
        '"rate_limits":{"allowed":true,"limit_reached":false,'
        '"primary":{"used_percent":40,"window_minutes":300,"reset_at":9999999999},'
        '"secondary":{"used_percent":6,"window_minutes":10080,"reset_at":9999999998}},'
        '"code_review_rate_limits":null}'
    )
    _create_logs_db(
        logs_db,
        [(1, int(now.timestamp()), body), *noisy_rows],
        target="codex_api::endpoint::responses_websocket",
    )
    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", tmp_path / "missing-sessions")
    monkeypatch.setattr(codex_loader, "LOGS_DB", logs_db)

    result = codex_loader.load_rate_limits()

    assert result is not None
    assert result.five_hour_pct == 40.0
    assert result.seven_day_pct == 6.0


def test_load_rate_limits_reads_sqlite_usage_limit_error_headers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    logs_db = tmp_path / "logs.sqlite"
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    body = (
        "session_loop{thread_id=session-error}:turn{model=gpt-5.4}: "
        'websocket event: {"type":"error","error":{"type":"usage_limit_reached"},'
        '"headers":{"X-Codex-Primary-Used-Percent":"100",'
        '"X-Codex-Secondary-Used-Percent":"47",'
        '"X-Codex-Primary-Reset-At":"9999999999",'
        '"X-Codex-Secondary-Reset-At":"9999999998"}}'
    )
    _create_logs_db(
        logs_db,
        [(1, int(now.timestamp()), body)],
        target="codex_api::endpoint::responses_websocket",
    )
    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", tmp_path / "missing-sessions")
    monkeypatch.setattr(codex_loader, "LOGS_DB", logs_db)

    result = codex_loader.load_rate_limits()

    assert result == codex_loader.CodexRateLimits(
        five_hour_pct=100.0,
        five_hour_resets_at=9999999999.0,
        seven_day_pct=47.0,
        seven_day_resets_at=9999999998.0,
        model="gpt-5.4",
        updated_at=now.isoformat(),
    )


def test_load_rate_limits_clears_expired_primary_window(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sessions_dir = tmp_path / "sessions"
    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(codex_loader, "_load_thread_models", lambda: {})
    now = datetime.now(UTC)
    rate_limits = {
        "primary": {"used_percent": 25.0, "resets_at": 1},
        "secondary": {"used_percent": 70.0, "resets_at": now.timestamp() + 120},
    }
    _write_rate_limit_session(
        sessions_dir / "rate.jsonl", now.isoformat(), rate_limits, now.timestamp()
    )

    result = codex_loader.load_rate_limits()

    assert result is not None
    assert result.five_hour_pct == 0.0
    assert result.five_hour_resets_at is None
    assert result.seven_day_pct == 70.0
    assert result.seven_day_resets_at == now.timestamp() + 120


def test_load_rate_limits_skips_null_recent_sessions(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:  # noqa: E501
    sessions_dir = tmp_path / "sessions"
    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(codex_loader, "_load_thread_models", lambda: {})
    valid_limits = _rate_limits()
    valid_limits["primary"].update({"limit_id": "primary-window", "plan_type": "pro"})
    valid_limits["secondary"].update({"limit_name": "weekly", "rate_limit_reached_type": None})
    for index in range(6):
        _write_rate_limit_session(sessions_dir / f"session-{index}.jsonl", "2026-05-27T16:39:00+00:00", valid_limits if index == 0 else None, 100 + index)  # noqa: E501

    result = codex_loader.load_rate_limits()

    assert result is not None
    assert result.five_hour_pct == 30.0


def test_load_rate_limits_returns_none_when_all_30_are_null(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:  # noqa: E501
    sessions_dir = tmp_path / "sessions"
    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(codex_loader, "_load_thread_models", lambda: {})
    for index in range(codex_loader._RECENT_JSONL_SCAN_LIMIT):
        _write_rate_limit_session(sessions_dir / f"session-{index}.jsonl", "2026-05-27T16:45:00+00:00", None, 100 + index)  # noqa: E501

    assert codex_loader.load_rate_limits() is None


def test_load_rate_limits_picks_most_recent_valid(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:  # noqa: E501
    sessions_dir = tmp_path / "sessions"
    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(codex_loader, "_load_thread_models", lambda: {})
    old_ts = "2026-05-27T16:39:00+00:00"
    new_ts = "2026-05-27T16:45:00+00:00"
    limits = _rate_limits()
    _write_rate_limit_session(sessions_dir / "old.jsonl", old_ts, limits, 100)
    _write_rate_limit_session(sessions_dir / "new.jsonl", new_ts, limits, 200)

    result = codex_loader.load_rate_limits()

    assert result is not None
    assert result.updated_at == new_ts


def test_recent_jsonl_files_sorts_visible_sessions_by_mtime(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sessions_dir = tmp_path / "sessions"
    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", sessions_dir)
    specs: list[tuple[str, int, float]] = [
        ("2026/02/01", 10, 3000),
        ("2026/01/31", 25, 2000),
        ("2025/12/31", 10, 1000),
    ]
    for date_dir, count, base_mtime in specs:
        for index in range(count):
            _write_rate_limit_session(
                sessions_dir / date_dir / f"session-{index:02}.jsonl",
                "2026-05-27T16:45:00+00:00",
                None,
                base_mtime + index,
            )

    expected = [
        path
        for _, path in sorted(
            ((path.stat().st_mtime, path) for path in sessions_dir.rglob("*.jsonl")),
            key=lambda item: item[0],
            reverse=True,
        )[: codex_loader._RECENT_JSONL_SCAN_LIMIT]
    ]

    assert codex_loader._recent_jsonl_files() == expected


def test_recent_jsonl_files_keeps_newest_file_even_if_older_date_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sessions_dir = tmp_path / "sessions"
    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", sessions_dir)
    for index in range(codex_loader._RECENT_JSONL_SCAN_LIMIT + 5):
        _write_rate_limit_session(
            sessions_dir / "2026" / "06" / "12" / f"session-{index:02}.jsonl",
            "2026-06-12T15:38:27+00:00",
            None,
            1_000 + index,
        )
    important = sessions_dir / "2026" / "05" / "25" / "important.jsonl"
    _write_rate_limit_session(
        important,
        "2026-06-13T03:39:36+00:00",
        _rate_limits(),
        9_999,
    )

    assert important in codex_loader._recent_jsonl_files()


def test_recent_jsonl_files_ignores_dotfiles(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sessions_dir = tmp_path / "sessions"
    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", sessions_dir)
    for index in range(35):
        _write_rate_limit_session(
            sessions_dir / "2026" / "02" / "01" / f"session-{index:02}.jsonl",
            "2026-05-27T16:45:00+00:00",
            None,
            1000 + index,
        )
    (sessions_dir / ".DS_Store").write_text("", encoding="utf-8")
    (sessions_dir / "2026" / ".localized").write_text("", encoding="utf-8")
    (sessions_dir / "2026" / "02" / ".DS_Store").write_text("", encoding="utf-8")
    (sessions_dir / "2026" / "02" / "01" / ".DS_Store").write_text("", encoding="utf-8")
    fallback_only = sessions_dir / ".fallback-only.jsonl"
    _write_rate_limit_session(
        fallback_only,
        "2026-05-27T16:46:00+00:00",
        None,
        9999,
    )

    expected = [
        path
        for _, path in sorted(
            (
                (path.stat().st_mtime, path)
                for path in (sessions_dir / "2026" / "02" / "01").glob("*.jsonl")
            ),
            key=lambda item: item[0],
            reverse=True,
        )[: codex_loader._RECENT_JSONL_SCAN_LIMIT]
    ]

    assert codex_loader._recent_jsonl_files() == expected


def test_recent_jsonl_files_includes_non_date_directories(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sessions_dir = tmp_path / "sessions"
    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", sessions_dir)
    _write_rate_limit_session(
        sessions_dir / "2026" / "02" / "01" / "standard.jsonl",
        "2026-05-27T16:45:00+00:00",
        None,
        100,
    )
    unexpected = sessions_dir / "latest" / "unexpected.jsonl"
    _write_rate_limit_session(
        unexpected,
        "2026-05-27T16:46:00+00:00",
        None,
        200,
    )

    assert codex_loader._recent_jsonl_files()[0] == unexpected


def test_recent_jsonl_files_returns_empty_for_empty_sessions_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", sessions_dir)

    assert codex_loader._recent_jsonl_files() == []


def test_load_entries_accepts_numeric_string_usage_fields(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sessions_dir = tmp_path / "sessions"
    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(codex_loader, "_load_thread_models", lambda: {})
    timestamp = datetime.now(UTC).isoformat()
    _write_session(
        sessions_dir / "string-usage.jsonl",
        session_id="string-usage",
        timestamp=timestamp,
        usage={
            "input_tokens": "10",
            "cached_input_tokens": "2",
            "output_tokens": "3",
            "reasoning_output_tokens": "4",
        },
    )

    entries = codex_loader.load_entries()

    assert len(entries) == 1
    assert entries[0].input_tokens == 8
    assert entries[0].output_tokens == 3
    assert entries[0].cache_read_tokens == 2


def test_load_entries_uses_turn_context_model_when_state_db_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sessions_dir = tmp_path / "sessions"
    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(codex_loader, "_load_thread_models", lambda: {})
    timestamp = datetime.now(UTC).isoformat()
    _write_session_with_turn_context_model(
        sessions_dir / "turn-context.jsonl",
        session_id="turn-context",
        timestamp=timestamp,
        model="gpt-5.4-mini",
        usage={"input_tokens": 10, "cached_input_tokens": 2, "output_tokens": 3},
    )

    entries = codex_loader.load_entries()

    assert len(entries) == 1
    assert entries[0].model == "gpt-5.4-mini"


def test_load_entries_cache_keeps_turn_context_model_when_state_db_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sessions_dir = tmp_path / "sessions"
    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(codex_loader, "_load_thread_models", lambda: {})
    timestamp = datetime.now(UTC).isoformat()
    _write_session_with_turn_context_model(
        sessions_dir / "turn-context.jsonl",
        session_id="turn-context",
        timestamp=timestamp,
        model="gpt-5.4-mini",
        usage={"input_tokens": 10, "cached_input_tokens": 2, "output_tokens": 3},
    )

    assert codex_loader.load_entries()[0].model == "gpt-5.4-mini"
    assert codex_loader.load_entries()[0].model == "gpt-5.4-mini"


def test_load_rate_limits_accepts_numeric_string_fields(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sessions_dir = tmp_path / "sessions"
    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(codex_loader, "_load_thread_models", lambda: {})
    now = datetime.now(UTC)
    _write_rate_limit_session(
        sessions_dir / "string-rate.jsonl",
        now.isoformat(),
        {
            "primary": {"used_percent": "25", "resets_at": str(now.timestamp() + 60)},
            "secondary": {"used_percent": "70.0", "resets_at": str(now.timestamp() + 120)},
        },
        now.timestamp(),
    )

    result = codex_loader.load_rate_limits()

    assert result is not None
    assert result.five_hour_pct == 25.0
    assert result.seven_day_pct == 70.0


def test_load_rate_limits_uses_turn_context_model_when_state_db_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sessions_dir = tmp_path / "sessions"
    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(codex_loader, "_load_thread_models", lambda: {})
    now = datetime.now(UTC)
    _write_session_with_turn_context_model(
        sessions_dir / "turn-context-rate.jsonl",
        session_id="turn-context-rate",
        timestamp=now.isoformat(),
        model="gpt-5.4-mini",
        usage={"input_tokens": 1},
        rate_limits={
            "primary": {"used_percent": 25, "resets_at": now.timestamp() + 60},
            "secondary": {"used_percent": 70, "resets_at": now.timestamp() + 120},
        },
        mtime=now.timestamp(),
    )

    result = codex_loader.load_rate_limits()

    assert result == codex_loader.CodexRateLimits(
        five_hour_pct=25.0,
        five_hour_resets_at=now.timestamp() + 60,
        seven_day_pct=70.0,
        seven_day_resets_at=now.timestamp() + 120,
        model="gpt-5.4-mini",
        updated_at=now.isoformat(),
    )


# ===== Disk cache tests =====


def test_usage_entry_round_trip() -> None:
    """Test that UsageEntry serialization/deserialization is lossless."""
    from history_loader import UsageEntry

    original = UsageEntry(
        timestamp=datetime(2026, 6, 24, 12, 0, 0, tzinfo=UTC),
        session_id="test-session",
        message_id="test-session:1",
        request_id="req-123",
        model="gpt-5.4-mini",
        input_tokens=100,
        output_tokens=50,
        cache_creation_tokens=10,
        cache_read_tokens=5,
        cost_usd=None,  # Codex entries always have None
        project="/tmp/demo",
    )

    serialized = codex_loader._serialize_usage_entry(original)
    deserialized = codex_loader._deserialize_usage_entry(serialized)

    # All fields must be equal
    assert deserialized == original
    assert deserialized.timestamp == original.timestamp
    assert deserialized.timestamp.tzinfo == UTC  # Timezone preserved
    assert deserialized.cost_usd is None  # None preserved


def test_disk_cache_seed_loads_on_cold_start(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Test that disk cache seeds memory cache on cold start."""

    cache_file = tmp_path / "codex_jsonl_cache.json"
    sessions_dir = tmp_path / "sessions"
    monkeypatch.setattr(codex_loader, "JSONL_CACHE_PATH", cache_file)
    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", sessions_dir)

    now = datetime.now(UTC)
    session_path = sessions_dir / "2026-06-24" / "test-session.jsonl"
    session_path.parent.mkdir(parents=True, exist_ok=True)

    # Prepare pre-seeded cache with one file
    cache_data = {
        "schema_version": codex_loader._CODEX_JSONL_CACHE_SCHEMA,
        "cached_at": now.timestamp(),
        "files": {
            str(session_path): {
                "mtime": 123456.0,
                "size": 1000,
                "session_id": "test-session",
                "forked_from_id": "",
                "entries": [
                    {
                        "timestamp": "2026-06-24T12:00:00+00:00",
                        "session_id": "test-session",
                        "message_id": "test-session:1",
                        "request_id": "",
                        "model": "gpt-5.4-mini",
                        "input_tokens": 100,
                        "output_tokens": 50,
                        "cache_creation_tokens": 0,
                        "cache_read_tokens": 0,
                        "cost_usd": None,
                        "project": "/tmp/demo",
                    }
                ],
            }
        },
    }
    cache_file.write_text(json.dumps(cache_data), encoding="utf-8")

    # Clear module flag to force seed reload
    monkeypatch.setattr(codex_loader, "_disk_cache_seeded", False)

    # Trigger seed loading by calling load_entries
    codex_loader.load_entries()

    # Cache should be seeded from disk
    assert len(codex_loader._jsonl_cache) == 1
    assert len(codex_loader._file_info_cache) == 1

    # The seeded entry should be in cache
    assert session_path in codex_loader._jsonl_cache
    mtime, size, replay_key, cached_entries = codex_loader._jsonl_cache[session_path]
    assert mtime == 123456.0
    assert size == 1000
    assert replay_key is None  # Non-fork file
    assert len(cached_entries) == 1
    assert cached_entries[0].input_tokens == 100


def test_disk_cache_invalid_schema_fails_safely(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Test that invalid schema version is silently ignored."""
    cache_file = tmp_path / "codex_jsonl_cache.json"
    sessions_dir = tmp_path / "sessions"
    monkeypatch.setattr(codex_loader, "JSONL_CACHE_PATH", cache_file)
    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", sessions_dir)

    # Write cache with wrong schema version
    cache_file.write_text(
        json.dumps(
            {
                "schema_version": 999,  # Wrong version
                "cached_at": datetime.now(UTC).timestamp(),
                "files": {},
            }
        ),
        encoding="utf-8",
    )

    # Clear module flag
    monkeypatch.setattr(codex_loader, "_disk_cache_seeded", False)

    # Should not raise error; seed is simply ignored
    codex_loader._seed_caches_from_disk()

    # Caches should remain empty
    assert len(codex_loader._jsonl_cache) == 0
    assert len(codex_loader._file_info_cache) == 0


def test_disk_cache_corrupted_json_fails_safely(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Test that corrupted JSON is silently ignored."""
    cache_file = tmp_path / "codex_jsonl_cache.json"
    monkeypatch.setattr(codex_loader, "JSONL_CACHE_PATH", cache_file)

    # Write garbage
    cache_file.write_text("not valid json {", encoding="utf-8")

    # Clear module flag
    monkeypatch.setattr(codex_loader, "_disk_cache_seeded", False)

    # Should not raise error
    codex_loader._seed_caches_from_disk()

    # Caches should remain empty
    assert len(codex_loader._jsonl_cache) == 0


def test_disk_cache_fork_file_entries_not_written(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Test that fork files have entries=null in disk cache."""
    cache_file = tmp_path / "codex_jsonl_cache.json"
    monkeypatch.setattr(codex_loader, "JSONL_CACHE_PATH", cache_file)

    # Manually construct a fork cache entry (replay_cache_key is not None)
    fork_path = Path("/fake/fork.jsonl")
    codex_loader._jsonl_cache[fork_path] = (
        123.0,
        500,
        ("parent-session", 123.0, 100, 5),  # Non-None replay_cache_key indicates fork
        [],  # entries exist for fork, but should not be written
    )
    codex_loader._file_info_cache[fork_path] = (
        123.0,
        500,
        codex_loader._SessionFileInfo(session_id="fork-session", forked_from_id="parent-session"),
    )

    # Flush to disk
    codex_loader._flush_caches_to_disk()

    # Read back and verify fork file has null entries
    with cache_file.open(encoding="utf-8") as f:
        data = json.load(f)

    fork_data = data["files"].get(str(fork_path))
    assert fork_data is not None
    assert fork_data["session_id"] == "fork-session"
    assert fork_data["forked_from_id"] == "parent-session"
    assert fork_data["entries"] is None  # Fork files must have null entries


def test_disk_cache_file_mtime_invalidates_seed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Test that file with mismatched mtime/size is not treated as cache hit."""

    cache_file = tmp_path / "codex_jsonl_cache.json"
    sessions_dir = tmp_path / "sessions"
    monkeypatch.setattr(codex_loader, "JSONL_CACHE_PATH", cache_file)
    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", sessions_dir)

    now = datetime.now(UTC)
    session_path = sessions_dir / "2026-06-24" / "test-session.jsonl"
    session_path.parent.mkdir(parents=True, exist_ok=True)

    # Seed cache with old mtime/size
    cache_data = {
        "schema_version": codex_loader._CODEX_JSONL_CACHE_SCHEMA,
        "cached_at": now.timestamp(),
        "files": {
            str(session_path): {
                "mtime": 100.0,  # Wrong mtime
                "size": 200,  # Wrong size
                "session_id": "test-session",
                "forked_from_id": "",
                "entries": [
                    {
                        "timestamp": "2026-06-24T12:00:00+00:00",
                        "session_id": "test-session",
                        "message_id": "test-session:1",
                        "request_id": "",
                        "model": "gpt-5.4-mini",
                        "input_tokens": 100,
                        "output_tokens": 50,
                        "cache_creation_tokens": 0,
                        "cache_read_tokens": 0,
                        "cost_usd": None,
                        "project": "/tmp/demo",
                    }
                ],
            }
        },
    }
    cache_file.write_text(json.dumps(cache_data), encoding="utf-8")

    # Write actual session file with different mtime/size
    _write_session(
        session_path,
        session_id="test-session",
        timestamp=now.isoformat(),
        usage={"input_tokens": 200, "output_tokens": 100},  # Different content
    )

    # Clear module flag
    monkeypatch.setattr(codex_loader, "_disk_cache_seeded", False)

    # Load entries - should parse actual file, not use stale seed
    entries = codex_loader.load_entries()
    assert len(entries) == 1
    # Should have the actual file's values, not the seed's
    assert entries[0].input_tokens == 200
    assert entries[0].output_tokens == 100

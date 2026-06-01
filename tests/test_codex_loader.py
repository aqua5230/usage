from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

import codex_loader


@pytest.fixture(autouse=True)
def _clear_jsonl_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    codex_loader._jsonl_cache.clear()
    monkeypatch.setattr(codex_loader, "LOGS_DB", tmp_path / "missing-logs.sqlite")
    monkeypatch.setattr(codex_loader, "STATE_DB", tmp_path / "missing-state.sqlite")


def _write_session(
    path: Path,
    *,
    session_id: str,
    timestamp: str,
    usage: dict[str, Any] | None = None,
    rate_limits: dict[str, Any] | None = None,
    mtime: float | None = None,
    cwd: str = "/tmp/demo",
) -> None:
    lines = [
        {
            "type": "session_meta",
            "payload": {"id": session_id, "timestamp": timestamp, "cwd": cwd},
        },
        {
            "type": "event_msg",
            "timestamp": timestamp,
            "payload": {"type": "token_count", "info": {"total_token_usage": usage or {"input_tokens": 1}}, "rate_limits": rate_limits},  # noqa: E501
        },
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))


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

    assert [entry.total_tokens for entry in all_entries] == [160, 80]
    assert [entry.total_tokens for entry in week_entries] == [80]
    assert week_entries[0].input_tokens == 40
    assert week_entries[0].output_tokens == 30
    assert week_entries[0].cache_read_tokens == 10


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
    assert entries[0].output_tokens == 10
    assert entries[0].cache_read_tokens == 20
    assert entries[0].total_tokens == 110
    assert entries[0].project == "demo"


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
        model="gpt-5.5",
        updated_at=now.isoformat(),
    )


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
    assert result.five_hour_pct is None
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
    assert entries[0].output_tokens == 7
    assert entries[0].cache_read_tokens == 2


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

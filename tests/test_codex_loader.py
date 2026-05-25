from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import codex_loader


@pytest.fixture(autouse=True)
def _clear_jsonl_cache() -> None:
    codex_loader._jsonl_cache.clear()


def _write_session(
    path: Path,
    *,
    session_id: str,
    timestamp: str,
    usage: dict[str, int],
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
            "payload": {"type": "token_count", "info": {"total_token_usage": usage}},
        },
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")


def test_load_entries_returns_empty_list_when_sessions_dir_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", tmp_path / "missing")

    assert codex_loader.load_entries() == []


def test_load_entries_parses_valid_jsonl_and_filters_by_hours_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sessions_dir = tmp_path / "sessions"
    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(
        codex_loader,
        "_load_thread_models",
        lambda: {"session-old": "gpt-test", "session-new": "gpt-test"},
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
    older_ts = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
    newer_ts = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    _write_session(
        sessions_dir / "older.jsonl",
        session_id="session-1",
        timestamp=older_ts,
        usage={"input_tokens": 10, "cached_input_tokens": 0, "output_tokens": 5},
    )
    _write_session(
        sessions_dir / "newer.jsonl",
        session_id="session-1",
        timestamp=newer_ts,
        usage={"input_tokens": 100, "cached_input_tokens": 20, "output_tokens": 50},
    )

    entries = codex_loader.load_entries()

    assert len(entries) == 1
    assert entries[0].timestamp == datetime.fromisoformat(newer_ts)
    assert entries[0].total_tokens == 150


def test_load_entries_uses_larger_duplicate_when_timestamps_match(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sessions_dir = tmp_path / "sessions"
    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(codex_loader, "_load_thread_models", lambda: {})
    timestamp = datetime.now(UTC).isoformat()
    _write_session(
        sessions_dir / "small.jsonl",
        session_id="session-1",
        timestamp=timestamp,
        usage={"input_tokens": 10, "cached_input_tokens": 0, "output_tokens": 5},
    )
    _write_session(
        sessions_dir / "large.jsonl",
        session_id="session-1",
        timestamp=timestamp,
        usage={"input_tokens": 100, "cached_input_tokens": 20, "output_tokens": 50},
    )

    entries = codex_loader.load_entries()

    assert len(entries) == 1
    assert entries[0].total_tokens == 150


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

    assert codex_loader._parse_jsonl(path, {}, None) is None


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
    now = datetime.now(UTC)
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
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = codex_loader.load_rate_limits()

    assert result == codex_loader.CodexRateLimits(
        five_hour_pct=25.0,
        five_hour_resets_at=now.timestamp() + 60,
        seven_day_pct=70.0,
        seven_day_resets_at=now.timestamp() + 120,
        updated_at=now.isoformat(),
    )

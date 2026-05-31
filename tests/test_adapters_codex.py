from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from adapters import codex


@pytest.fixture(autouse=True)
def _clear_file_cache() -> None:
    codex._file_cache.clear()


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
            "payload": {
                "type": "token_count",
                "info": {"total_token_usage": usage or {"input_tokens": 1}},
                "rate_limits": rate_limits,
            },
        },
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))


def test_loaders_skip_bad_utf8_jsonl_without_crashing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sessions_dir = tmp_path / "sessions"
    path = sessions_dir / "bad.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xff\xfe not utf-8\n")
    monkeypatch.setattr(codex, "SESSIONS_DIR", str(sessions_dir))
    monkeypatch.setattr(codex, "_load_thread_models", lambda: {})

    assert codex.load_entries() == []
    assert codex.load_rate_limits() is None


def test_load_rate_limits_accepts_numeric_string_fields(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sessions_dir = tmp_path / "sessions"
    now = datetime.now(UTC)
    _write_session(
        sessions_dir / "string-rate.jsonl",
        session_id="string-rate",
        timestamp=now.isoformat(),
        rate_limits={
            "primary": {"used_percent": "25", "resets_at": "9999999999"},
            "secondary": {"used_percent": "70.0", "resets_at": "9999999998"},
        },
        mtime=now.timestamp(),
    )
    monkeypatch.setattr(codex, "SESSIONS_DIR", str(sessions_dir))
    monkeypatch.setattr(codex, "_load_thread_models", lambda: {"string-rate": "gpt-test"})

    result = codex.load_rate_limits()

    assert result is not None
    assert result.five_hour_pct == 25.0
    assert result.five_hour_resets_at == 9999999999
    assert result.seven_day_pct == 70.0
    assert result.seven_day_resets_at == 9999999998
    assert result.model == "gpt-test"


def test_load_entries_accepts_numeric_string_usage_fields(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sessions_dir = tmp_path / "sessions"
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
    monkeypatch.setattr(codex, "SESSIONS_DIR", str(sessions_dir))
    monkeypatch.setattr(codex, "_load_thread_models", lambda: {})

    entries = codex.load_entries()

    assert len(entries) == 1
    assert entries[0].input_tokens == 8
    assert entries[0].output_tokens == 7
    assert entries[0].cache_read_tokens == 2

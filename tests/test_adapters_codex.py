# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from adapters import codex
from tests.helpers import write_codex_session as _write_session
from tests.helpers import (
    write_codex_session_with_turn_context_model as _write_session_with_turn_context_model,
)


@pytest.fixture(autouse=True)
def _clear_file_cache() -> None:
    codex._file_cache.clear()


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
    assert codex._extract_rate_limits(path, {}) is None


def test_extract_rate_limits_resets_expired_primary_window_to_zero(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    path = tmp_path / "sessions" / "expired-primary.jsonl"
    _write_session(
        path,
        session_id="expired-primary",
        timestamp=now.isoformat(),
        rate_limits={
            "primary": {"used_percent": 12, "resets_at": now.timestamp() - 60},
            "secondary": {"used_percent": 34, "resets_at": 9999999998},
        },
        mtime=now.timestamp(),
    )

    result = codex._extract_rate_limits(path, {})

    assert result is not None
    assert result.five_hour_pct == 0.0
    assert result.five_hour_resets_at is None
    assert result.seven_day_pct == 34


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
    assert entries[0].output_tokens == 3
    assert entries[0].cache_read_tokens == 2


def test_load_entries_uses_turn_context_model_when_state_db_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sessions_dir = tmp_path / "sessions"
    timestamp = datetime.now(UTC).isoformat()
    _write_session_with_turn_context_model(
        sessions_dir / "turn-context.jsonl",
        session_id="turn-context",
        timestamp=timestamp,
        model="gpt-5.4-mini",
        usage={"input_tokens": 10, "cached_input_tokens": 2, "output_tokens": 3},
    )
    monkeypatch.setattr(codex, "SESSIONS_DIR", str(sessions_dir))
    monkeypatch.setattr(codex, "_load_thread_models", lambda: {})

    entries = codex.load_entries()

    assert len(entries) == 1
    assert entries[0].model == "gpt-5.4-mini"


def test_load_entries_prefers_state_db_model_over_turn_context(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sessions_dir = tmp_path / "sessions"
    timestamp = datetime.now(UTC).isoformat()
    _write_session_with_turn_context_model(
        sessions_dir / "turn-context.jsonl",
        session_id="turn-context",
        timestamp=timestamp,
        model="gpt-5.4-mini",
        usage={"input_tokens": 10, "cached_input_tokens": 2, "output_tokens": 3},
    )
    monkeypatch.setattr(codex, "SESSIONS_DIR", str(sessions_dir))
    monkeypatch.setattr(codex, "_load_thread_models", lambda: {"turn-context": "gpt-state"})

    entries = codex.load_entries()

    assert len(entries) == 1
    assert entries[0].model == "gpt-state"


def test_extract_rate_limits_uses_turn_context_model_when_state_db_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sessions_dir = tmp_path / "sessions"
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
    monkeypatch.setattr(codex, "SESSIONS_DIR", str(sessions_dir))
    monkeypatch.setattr(codex, "_load_thread_models", lambda: {})

    result = codex._extract_rate_limits(sessions_dir / "turn-context-rate.jsonl", {})

    assert result is not None
    assert result.model == "gpt-5.4-mini"

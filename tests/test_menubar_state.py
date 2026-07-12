# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import codex_loader
import menubar_state
from history_loader import UsageEntry


def test_history_sources_fingerprint_uses_claude_projects_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    projects_dir = home / ".claude" / "projects"
    projects_dir.mkdir(parents=True)
    (projects_dir / "project.jsonl").write_text("{}", encoding="utf-8")
    archived_dir = home / ".codex" / "archived_sessions"
    archived_dir.mkdir(parents=True)
    (archived_dir / "archived.jsonl").write_text("{}", encoding="utf-8")
    noise_dir = home / ".claude" / "sessions"
    noise_dir.mkdir(parents=True)
    (noise_dir / "noise.jsonl").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(menubar_state, "CLAUDE_PROJECTS_DIR", projects_dir)
    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", home / ".codex" / "sessions")
    monkeypatch.setattr(codex_loader, "ARCHIVED_SESSIONS_DIR", archived_dir)
    monkeypatch.setattr(codex_loader, "LOGS_DB", home / ".codex" / "logs_2.sqlite")
    monkeypatch.setattr(codex_loader, "STATE_DB", home / ".codex" / "state_5.sqlite")

    fingerprint = menubar_state.history_sources_fingerprint()

    assert fingerprint[0][0] == str(projects_dir)
    assert fingerprint[0][1] == 1
    assert fingerprint[2][0] == str(archived_dir)
    assert fingerprint[2][1] == 1


def test_codex_stale_state_hides_fresh_data() -> None:
    now = datetime(2026, 1, 1, 1, 0, tzinfo=UTC)
    updated_at = (now - timedelta(seconds=900)).isoformat()

    assert menubar_state.codex_stale_state(updated_at, now.timestamp(), "en") is None


def test_codex_stale_state_uses_minutes_for_recent_stale_data() -> None:
    now = datetime(2026, 1, 1, 1, 0, tzinfo=UTC)
    updated_at = (now - timedelta(minutes=30)).isoformat()

    state = menubar_state.codex_stale_state(updated_at, now.timestamp(), "en")

    assert state is not None
    assert state["ageText"]


def test_codex_stale_state_uses_hours_for_old_stale_data() -> None:
    now = datetime(2026, 1, 1, 3, 0, tzinfo=UTC)
    updated_at = (now - timedelta(hours=2, minutes=30)).isoformat()

    state = menubar_state.codex_stale_state(updated_at, now.timestamp(), "en")

    assert state is not None
    assert state["ageText"]


def test_codex_stale_state_hides_missing_timestamp() -> None:
    now = datetime(2026, 1, 1, 1, 0, tzinfo=UTC).timestamp()

    assert menubar_state.codex_stale_state("", now, "en") is None


def test_history_load_error_state_none_when_no_reason() -> None:
    assert menubar_state.history_load_error_state(None, "en") is None


def test_history_load_error_state_localizes_reason() -> None:
    state = menubar_state.history_load_error_state("history_load_error_file", "en")

    assert state is not None
    assert state["reasonText"]


def test_file_event_refresh_decision_passes_through_outside_interval() -> None:
    decision = menubar_state.file_event_refresh_decision(130.0, 100.0, False)

    assert decision.refresh_now is True
    assert decision.trailing_delay is None


def test_file_event_refresh_decision_schedules_trailing_inside_interval() -> None:
    decision = menubar_state.file_event_refresh_decision(110.0, 100.0, False)

    assert decision.refresh_now is False
    assert decision.trailing_delay == 20.0


def test_file_event_refresh_decision_merges_into_existing_trailing() -> None:
    decision = menubar_state.file_event_refresh_decision(129.0, 100.0, True)

    assert decision.refresh_now is False
    assert decision.trailing_delay is None


def test_project_rows_for_windows_matches_window_boundaries() -> None:
    now = datetime.now(UTC).replace(microsecond=0)

    def entry(project: str, timestamp: datetime, tokens: int) -> UsageEntry:
        return UsageEntry(
            timestamp=timestamp,
            session_id=project,
            message_id=project,
            request_id=project,
            model="test",
            input_tokens=tokens,
            output_tokens=0,
            cache_creation_tokens=0,
            cache_read_tokens=0,
            cost_usd=float(tokens),
            project=project,
        )

    rows_24h, rows_7d, rows_30d, rows_all = menubar_state.project_rows_for_windows(
        [
            entry("today", now, 4),
            entry("week", now - timedelta(days=2), 3),
            entry("month", now - timedelta(days=10), 2),
            entry("old", now - timedelta(days=40), 1),
        ],
        now=now,
    )

    assert rows_24h == [("today", 4, 4.0)]
    assert rows_7d == [("today", 4, 4.0), ("week", 3, 3.0)]
    assert rows_30d == [
        ("today", 4, 4.0),
        ("week", 3, 3.0),
        ("month", 2, 2.0),
    ]
    assert rows_all == [
        ("today", 4, 4.0),
        ("week", 3, 3.0),
        ("month", 2, 2.0),
    ]

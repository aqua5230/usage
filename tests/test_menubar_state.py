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

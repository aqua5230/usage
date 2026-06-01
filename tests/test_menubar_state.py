from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import menubar_state


def test_history_sources_fingerprint_uses_claude_projects_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    projects_dir = home / ".claude" / "projects"
    projects_dir.mkdir(parents=True)
    (projects_dir / "project.jsonl").write_text("{}", encoding="utf-8")
    noise_dir = home / ".claude" / "sessions"
    noise_dir.mkdir(parents=True)
    (noise_dir / "noise.jsonl").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(menubar_state, "CLAUDE_PROJECTS_DIR", projects_dir)

    fingerprint = menubar_state.history_sources_fingerprint()

    assert fingerprint[0][0] == str(projects_dir)
    assert fingerprint[0][1] == 1


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

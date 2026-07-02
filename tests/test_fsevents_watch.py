# SPDX-License-Identifier: AGPL-3.0-only

from pathlib import Path

import pytest

import fsevents_watch


def test_usage_watch_paths_only_includes_existing_history_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claude_projects = tmp_path / ".claude" / "projects"
    codex_sessions = tmp_path / ".codex" / "sessions"
    archived_sessions = tmp_path / ".codex" / "archived_sessions"
    claude_projects.mkdir(parents=True)
    codex_sessions.mkdir(parents=True)
    archived_sessions.mkdir(parents=True)
    (tmp_path / ".codex" / "logs_2.sqlite-wal").touch()
    (tmp_path / ".codex" / "cache").mkdir()

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    assert fsevents_watch.usage_watch_paths() == [
        claude_projects,
        codex_sessions,
        archived_sessions,
    ]


def test_usage_watch_paths_omits_missing_history_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    codex_sessions = tmp_path / ".codex" / "sessions"
    codex_sessions.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    assert fsevents_watch.usage_watch_paths() == [codex_sessions]

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


def test_classify_file_events_returns_reliable_file_paths() -> None:
    changes = fsevents_watch.classify_file_events(
        ["/tmp/one.jsonl", "/tmp/two.jsonl"],
        [0x00010000 | 0x00001000, 0x00010000 | 0x00000200],
    )

    assert changes.paths == frozenset(
        {Path("/tmp/one.jsonl"), Path("/tmp/two.jsonl")}
    )
    assert changes.needs_full_scan is False


@pytest.mark.parametrize("flag", [0x00000001, 0x00000008, 0x00020000])
def test_classify_file_events_requests_full_scan_for_uncertain_scope(flag: int) -> None:
    changes = fsevents_watch.classify_file_events(["/tmp/history"], [flag])

    assert changes.paths == frozenset()
    assert changes.needs_full_scan is True


def test_classify_file_events_requests_full_scan_for_mismatched_arrays() -> None:
    changes = fsevents_watch.classify_file_events(["/tmp/one.jsonl"], [])

    assert changes.needs_full_scan is True

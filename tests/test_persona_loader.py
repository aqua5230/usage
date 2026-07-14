# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

import project_resolver
from analyzer import persona_loader


@pytest.fixture(autouse=True)
def _reset_persona_cache() -> None:
    persona_loader._reset_cache()
    project_resolver.resolve_project_name.cache_clear()
    project_resolver._resolve_project_name.cache_clear()


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )


def _row(
    *,
    timestamp: datetime,
    session_id: str = "session-1",
    cwd: str = "/tmp/work/project-a",
    type_: str = "assistant",
) -> dict[str, Any]:
    return {
        "type": type_,
        "timestamp": timestamp.isoformat(),
        "sessionId": session_id,
        "cwd": cwd,
        "message": {"content": "must not be read"},
    }


def _title_row(session_id: str, ai_title: str) -> dict[str, Any]:
    return {
        "type": "ai-title",
        "sessionId": session_id,
        "aiTitle": ai_title,
    }


def test_profile_cache_keeps_each_period_within_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = persona_loader.PersonaProfile([0] * 24, [], [], 0, 0)
    load = Mock(return_value=profile)
    monkeypatch.setattr(persona_loader, "_load_profile_uncached", load)

    assert persona_loader.load_profile(1) is profile
    assert persona_loader.load_profile(7) is profile
    assert persona_loader.load_profile(1) is profile
    assert persona_loader.load_profile(7) is profile

    assert load.call_args_list == [((1,), {}), ((7,), {})]


def test_empty_directory_returns_empty_profile(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setattr(persona_loader, "CLAUDE_PROJECTS_DIR", projects_dir)

    profile = persona_loader.load_profile()

    assert profile.hour_histogram == [0] * 24
    assert profile.top_projects == []
    assert profile.recent_titles == []
    assert profile.total_sessions == 0
    assert profile.total_messages == 0


def test_hour_histogram_buckets_by_local_hour(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    projects_dir = tmp_path / "projects"
    monkeypatch.setattr(persona_loader, "CLAUDE_PROJECTS_DIR", projects_dir)
    now_local = datetime.now().astimezone()
    hour_three = now_local.replace(hour=3, minute=10, second=0, microsecond=0)
    hour_twenty = now_local.replace(hour=20, minute=45, second=0, microsecond=0)
    _write_jsonl(
        projects_dir / "project-a" / "a.jsonl",
        [
            _row(timestamp=hour_three),
            _row(timestamp=hour_three, session_id="session-2"),
            _row(timestamp=hour_twenty, session_id="session-3"),
            {"bad": "line"},
        ],
    )

    profile = persona_loader.load_profile()

    assert profile.hour_histogram[3] == 2
    assert profile.hour_histogram[20] == 1
    assert sum(profile.hour_histogram) == 3
    assert profile.total_messages == 3


def test_non_message_rows_do_not_count_toward_histogram_or_total_messages(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    projects_dir = tmp_path / "projects"
    monkeypatch.setattr(persona_loader, "CLAUDE_PROJECTS_DIR", projects_dir)
    now_local = datetime.now().astimezone().replace(hour=9, minute=0, second=0, microsecond=0)
    _write_jsonl(
        projects_dir / "project-a" / "a.jsonl",
        [
            _row(timestamp=now_local, session_id="message", type_="user"),
            _row(timestamp=now_local, session_id="attachment", type_="attachment"),
            _row(timestamp=now_local, session_id="system", type_="system"),
            _row(timestamp=now_local, session_id="queue", type_="queue-operation"),
            _title_row("message", "Real work"),
        ],
    )

    profile = persona_loader.load_profile()

    assert profile.hour_histogram[9] == 1
    assert sum(profile.hour_histogram) == 1
    assert profile.total_messages == 1


def test_top_projects_count_distinct_sessions_and_sort(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    projects_dir = tmp_path / "projects"
    monkeypatch.setattr(persona_loader, "CLAUDE_PROJECTS_DIR", projects_dir)
    now = datetime.now(UTC)
    old = now - timedelta(days=31)
    recent_file = projects_dir / "encoded-project" / "recent.jsonl"
    old_file = projects_dir / "old-project" / "old.jsonl"
    _write_jsonl(
        recent_file,
        [
            _row(timestamp=now, session_id="a-1", cwd="/tmp/work/alpha"),
            _row(timestamp=now, session_id="a-1", cwd="/tmp/work/alpha"),
            _row(timestamp=now, session_id="a-2", cwd="/tmp/work/alpha"),
            _row(timestamp=now, session_id="b-1", cwd="/tmp/work/beta"),
            _row(timestamp=now, session_id="b-2", cwd="/tmp/work/beta"),
            _row(timestamp=now, session_id="b-3", cwd="/tmp/work/beta"),
            _row(timestamp=now, session_id="c-1", cwd="/tmp/work/gamma"),
            _row(timestamp=old, session_id="old-1", cwd="/tmp/work/old"),
        ],
    )
    _write_jsonl(old_file, [_row(timestamp=old, session_id="old-2", cwd="/tmp/work/old")])
    old_mtime = old.timestamp() - 1
    os.utime(old_file, (old_mtime, old_mtime))

    profile = persona_loader.load_profile()

    assert profile.top_projects == [("beta", 3), ("alpha", 2), ("gamma", 1)]
    assert profile.total_sessions == 6
    assert profile.total_messages == 7


def test_project_falls_back_to_encoded_file_path_without_cwd(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    projects_dir = tmp_path / "projects"
    real_project = tmp_path / "Users" / "me" / "fallback-project"
    real_project.mkdir(parents=True)
    encoded_project = str(real_project).replace(os.sep, "-")
    monkeypatch.setattr(persona_loader, "CLAUDE_PROJECTS_DIR", projects_dir)
    _write_jsonl(
        projects_dir / encoded_project / "a.jsonl",
        [
            {
                "type": "assistant",
                "timestamp": datetime.now(UTC).isoformat(),
                "sessionId": "fallback-session",
            }
        ],
    )

    profile = persona_loader.load_profile()

    assert profile.top_projects == [("fallback-project", 1)]


def test_recent_titles_use_session_message_time_when_ai_title_has_no_timestamp(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    projects_dir = tmp_path / "projects"
    monkeypatch.setattr(persona_loader, "CLAUDE_PROJECTS_DIR", projects_dir)
    now = datetime.now(UTC)
    rows = [
        _title_row("older", "Build panel"),
        _row(timestamp=now - timedelta(minutes=3), session_id="older", type_="user"),
        _title_row("newer", "Fix tests"),
        _row(timestamp=now - timedelta(minutes=1), session_id="newer", type_="assistant"),
        _title_row("middle", "Build panel"),
        _row(timestamp=now - timedelta(minutes=2), session_id="middle", type_="user"),
        _title_row("no-message-time", "Ignored title"),
    ]
    _write_jsonl(projects_dir / "project-a" / "a.jsonl", rows)

    profile = persona_loader.load_profile()

    assert profile.recent_titles == ["Fix tests", "Build panel"]


def test_same_session_uses_last_ai_title(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    projects_dir = tmp_path / "projects"
    monkeypatch.setattr(persona_loader, "CLAUDE_PROJECTS_DIR", projects_dir)
    now = datetime.now(UTC)
    _write_jsonl(
        projects_dir / "project-a" / "a.jsonl",
        [
            _title_row("session", "Old title"),
            _row(timestamp=now, session_id="session", type_="assistant"),
            _title_row("session", "  New title  "),
        ],
    )

    profile = persona_loader.load_profile()

    assert profile.recent_titles == ["New title"]


def test_noise_only_attachment_returns_empty_profile(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    projects_dir = tmp_path / "projects"
    monkeypatch.setattr(persona_loader, "CLAUDE_PROJECTS_DIR", projects_dir)
    _write_jsonl(
        projects_dir / "project-a" / "a.jsonl",
        [
            _row(
                timestamp=datetime.now(UTC),
                session_id="attachment-only",
                type_="attachment",
            )
        ],
    )

    profile = persona_loader.load_profile()

    assert profile.hour_histogram == [0] * 24
    assert profile.top_projects == []
    assert profile.recent_titles == []
    assert profile.total_sessions == 0
    assert profile.total_messages == 0

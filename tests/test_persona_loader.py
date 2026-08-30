# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import json
import os
from collections.abc import Sequence
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


def _assistant_row(
    *,
    timestamp: datetime,
    model: str | None,
    index: int,
) -> dict[str, Any]:
    return {
        "type": "assistant",
        "timestamp": timestamp.isoformat(),
        "sessionId": f"session-{index % 3}",
        "uuid": f"uuid-{index}",
        "message": {"id": f"message-{index}", "model": model, "content": []},
    }


def _user_row(*, timestamp: datetime, index: int) -> dict[str, Any]:
    return {
        "type": "user",
        "timestamp": timestamp.isoformat(),
        "sessionId": f"session-{index % 3}",
        "uuid": f"user-{index}",
        "message": {"content": f"prompt {index}"},
    }


def _conversation_rows(
    timestamp: datetime,
    models: Sequence[str | None],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, model in enumerate(models):
        rows.extend(
            [
                _user_row(timestamp=timestamp, index=index),
                _assistant_row(timestamp=timestamp, model=model, index=index),
            ]
        )
    return rows


def _signal_row(
    *,
    timestamp: datetime,
    interrupted_message_id: str | None = None,
    denied_parent_uuid: str | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "type": "user",
        "timestamp": timestamp.isoformat(),
        "sessionId": "signal-session",
        "message": {"content": []},
    }
    if interrupted_message_id is not None:
        row["interruptedMessageId"] = interrupted_message_id
    if denied_parent_uuid is not None:
        row["parentUuid"] = denied_parent_uuid
        row["message"] = {
            "content": [
                {
                    "type": "tool_result",
                    "content": "Permission to use Bash has been denied by the user",
                }
            ]
        }
    return row


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
    encoded_project = str(real_project).replace(os.sep, "-").replace(":", "-")
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


def test_profile_carries_titles_by_session(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    projects_dir = tmp_path / "projects"
    monkeypatch.setattr(persona_loader, "CLAUDE_PROJECTS_DIR", projects_dir)
    _write_jsonl(
        projects_dir / "project-a" / "a.jsonl",
        [
            _title_row("session-1", "First topic"),
            _row(timestamp=datetime.now(UTC), session_id="session-1"),
            _title_row("session-2", "Second topic"),
        ],
    )

    profile = persona_loader.load_profile()

    assert profile.titles_by_session == {
        "session-1": "First topic",
        "session-2": "Second topic",
    }


def test_empty_profile_has_empty_titles_by_session() -> None:
    assert persona_loader._empty_profile().titles_by_session == {}


def test_persona_profile_positional_construction_keeps_title_map_default() -> None:
    profile = persona_loader.PersonaProfile([0] * 24, [], [], 0, 0)

    assert profile.titles_by_session == {}


def test_one_pass_multiple_interruptions_only_fail_one_user_turn(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    projects_dir = tmp_path / "projects"
    monkeypatch.setattr(persona_loader, "CLAUDE_PROJECTS_DIR", projects_dir)
    now = datetime.now(UTC)
    rows: list[dict[str, Any]] = []
    for index, model in enumerate(["claude-sonnet-4"] * 18 + ["gpt-5-codex"] * 12):
        rows.extend(
            [
                _user_row(timestamp=now, index=index),
                _assistant_row(timestamp=now, model=model, index=index),
            ]
        )
        if index == 0:
            rows.extend(
                [
                    _signal_row(timestamp=now, interrupted_message_id="message-0"),
                    _signal_row(timestamp=now, interrupted_message_id="message-0"),
                ]
            )
    _write_jsonl(projects_dir / "project-a" / "a.jsonl", rows)

    stats = persona_loader.load_profile().one_pass

    assert stats is not None
    assert stats.total_turns == 30
    assert stats.interruptions == 2
    assert stats.denied_tools == 0
    assert stats.pass_rate == 96.7
    assert [
        (item.model, item.turns, item.interruptions, item.denied_tools, item.pass_rate)
        for item in stats.by_model
    ] == [
        ("claude-sonnet-4", 18, 2, 0, 94.4),
        ("gpt-5-codex", 12, 0, 0, 100.0),
    ]


def test_tool_results_do_not_start_new_user_turns(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    projects_dir = tmp_path / "projects"
    monkeypatch.setattr(persona_loader, "CLAUDE_PROJECTS_DIR", projects_dir)
    now = datetime.now(UTC)
    rows: list[dict[str, Any]] = []
    for index, model in enumerate(["claude-sonnet-4"] * 15 + ["gpt-5-codex"] * 15):
        rows.extend(
            [
                _user_row(timestamp=now, index=index),
                _assistant_row(timestamp=now, model=model, index=index),
            ]
        )
        if index == 0:
            rows.extend(
                _signal_row(timestamp=now, denied_parent_uuid="uuid-0")
                for _ in range(3)
            )
    _write_jsonl(projects_dir / "project-a" / "a.jsonl", rows)

    stats = persona_loader.load_profile().one_pass

    assert stats is not None
    assert stats.total_turns == 30
    assert stats.denied_tools == 3
    assert stats.pass_rate == 96.7
    assert stats.by_model[0].pass_rate == 93.3


def test_synthetic_empty_and_none_models_are_excluded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    projects_dir = tmp_path / "projects"
    monkeypatch.setattr(persona_loader, "CLAUDE_PROJECTS_DIR", projects_dir)
    now = datetime.now(UTC)
    models: list[str | None] = ["claude-sonnet-4"] * 15
    models.extend(["gpt-5-codex"] * 15)
    models.extend(["<synthetic>", "<internal marker>", "", None])
    _write_jsonl(
        projects_dir / "project-a" / "a.jsonl",
        _conversation_rows(now, models),
    )

    stats = persona_loader.load_profile().one_pass

    assert stats is not None
    assert stats.total_turns == 30
    assert [item.model for item in stats.by_model] == [
        "claude-sonnet-4",
        "gpt-5-codex",
    ]


def test_unmatched_signals_stay_unattributed_but_fail_current_turn(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    projects_dir = tmp_path / "projects"
    monkeypatch.setattr(persona_loader, "CLAUDE_PROJECTS_DIR", projects_dir)
    now = datetime.now(UTC)
    rows: list[dict[str, Any]] = []
    for index, model in enumerate(["claude-sonnet-4"] * 15 + ["gpt-5-codex"] * 15):
        rows.extend(
            [
                _user_row(timestamp=now, index=index),
                _assistant_row(timestamp=now, model=model, index=index),
            ]
        )
        if index == 15:
            rows.extend(
                [
                    _signal_row(timestamp=now, interrupted_message_id="missing-message"),
                    _signal_row(timestamp=now, denied_parent_uuid="missing-uuid"),
                ]
            )
    _write_jsonl(projects_dir / "project-a" / "a.jsonl", rows)

    stats = persona_loader.load_profile().one_pass

    assert stats is not None
    assert stats.unattributed_interruptions == 1
    assert stats.unattributed_denied_tools == 1
    assert all(item.interruptions == 0 for item in stats.by_model)
    assert all(item.denied_tools == 0 for item in stats.by_model)
    assert stats.pass_rate == 96.7
    assert stats.by_model[1].pass_rate == 93.3


def test_signal_can_resolve_to_assistant_in_later_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    projects_dir = tmp_path / "projects"
    monkeypatch.setattr(persona_loader, "CLAUDE_PROJECTS_DIR", projects_dir)
    now = datetime.now(UTC)
    rows = _conversation_rows(
        now,
        ["claude-sonnet-4"] * 15 + ["gpt-5-codex"] * 15,
    )
    rows.append(_signal_row(timestamp=now, interrupted_message_id="message-999"))
    _write_jsonl(projects_dir / "project-a" / "a-signal.jsonl", rows)
    _write_jsonl(
        projects_dir / "project-a" / "z-target.jsonl",
        [_assistant_row(timestamp=now, model="gpt-5-codex", index=999)],
    )

    stats = persona_loader.load_profile().one_pass

    assert stats is not None
    assert stats.unattributed_interruptions == 0
    assert stats.by_model[1].interruptions == 1


@pytest.mark.parametrize(
    "models",
    [
        ["claude-sonnet-4"] * 30,
        ["claude-sonnet-4"] * 15 + ["gpt-5-codex"] * 14,
    ],
)
def test_one_pass_stats_are_empty_below_comparison_thresholds(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    models: list[str],
) -> None:
    projects_dir = tmp_path / "projects"
    monkeypatch.setattr(persona_loader, "CLAUDE_PROJECTS_DIR", projects_dir)
    now = datetime.now(UTC)
    _write_jsonl(
        projects_dir / "project-a" / "a.jsonl",
        _conversation_rows(now, models),
    )

    assert persona_loader.load_profile().one_pass is None

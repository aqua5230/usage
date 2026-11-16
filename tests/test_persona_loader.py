# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any, Self
from unittest.mock import Mock

import pytest

from analyzer import persona_loader, reporter
from loaders.jsonl_utils import iter_jsonl_dicts
from usage_common import project_resolver


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


@pytest.mark.parametrize("days_back", [-1, 0, 1, 7, 30])
def test_report_profile_matches_full_profile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, days_back: int
) -> None:
    now = datetime(2026, 11, 16, 12, tzinfo=UTC)

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> Self:
            return cls.fromtimestamp(now.timestamp(), tz)

    monkeypatch.setattr(persona_loader, "datetime", FixedDateTime)
    roots = [tmp_path / "claude-a" / "projects", tmp_path / "claude-b" / "projects"]
    monkeypatch.setattr(persona_loader, "_claude_projects_dirs", lambda: roots)
    rows: list[dict[str, Any]] = []
    for index in range(12):
        session = f"session-{index}"
        rows.extend(
            [
                _title_row(session, " Duplicate " if index < 2 else f"Title {index}"),
                _row(
                    timestamp=(now - timedelta(minutes=index + 1)).astimezone(
                        timezone(timedelta(hours=8 if index % 2 else -5))
                    ),
                    session_id=session,
                    cwd=str(tmp_path / "project-a"),
                    type_="user" if index % 2 else "assistant",
                ),
            ]
        )
    for days in (1, 7, 30):
        for offset in (-1, 0, 1):
            session = f"boundary-{days}-{offset}"
            rows.extend(
                [
                    _title_row(session, session),
                    _row(
                        timestamp=now - timedelta(days=days) + timedelta(microseconds=offset),
                        session_id=session,
                    ),
                ]
            )
    rows.extend(
        [
            _title_row("session-0", " Replaced title "),
            _title_row("session-0", "   "),
            _title_row("title-only", "Ignore no message"),
            _title_row("bad-time", "Ignore invalid timestamp"),
            {"type": "user", "sessionId": "bad-time", "timestamp": "bad"},
            {"type": "assistant", "sessionId": "bad-time"},
            _row(timestamp=now, session_id="noise", type_="system"),
            _title_row("noise", "Ignore system message"),
            _row(timestamp=now, session_id=""),
            _row(timestamp=now, session_id="zero", type_="user"),
            _title_row("zero", "At cutoff"),
            _row(timestamp=now + timedelta(seconds=1), session_id="future"),
            _title_row("future", "Future message"),
        ]
    )
    path_a = roots[0] / "project-a" / "a.jsonl"
    _write_jsonl(path_a, rows)
    with path_a.open("a", encoding="utf-8") as file:
        file.write('not json\n{"broken":\n[]\nnull\n\n')
    path_b = roots[1] / "project-b" / "b.jsonl"
    _write_jsonl(
        path_b,
        [
            {"type": "ai-title", "session_id": "alias", "aiTitle": "Alias session"},
            {"type": "user", "session_id": "alias", "timestamp": now.isoformat()},
            _row(timestamp=now - timedelta(days=40), session_id="session-0"),
            _row(timestamp=now - timedelta(minutes=20), session_id="session-2"),
        ],
    )
    stale = roots[0] / "project-old" / "old.jsonl"
    _write_jsonl(stale, [_row(timestamp=now), _title_row("session-1", "Ignore stale file")])
    stale_ts = (now - timedelta(days=40)).timestamp()
    os.utime(stale, (stale_ts, stale_ts))
    for path in (path_a, path_b):
        os.utime(path, (now.timestamp(), now.timestamp()))

    full = persona_loader.load_profile(days_back)
    report = persona_loader.load_report_profile(days_back)

    assert report.hour_histogram == full.hour_histogram
    assert report.recent_titles == full.recent_titles
    if days_back <= 0:
        assert sum(report.hour_histogram) == 4
        assert report.recent_titles == ["Future message", "At cutoff", "Alias session"]
    else:
        assert len(report.recent_titles) == 8
        assert report.recent_titles[:5] == [
            "Future message",
            "At cutoff",
            "Alias session",
            "Replaced title",
            "Duplicate",
        ]
        assert (
            sum(report.hour_histogram)
            == 16
            + sum(3 if days < days_back else 2 if days == days_back else 0 for days in (1, 7, 30))
            + 1
        )  # The older message in b.jsonl still counts separately.


def test_report_profile_reads_each_jsonl_once_and_caches_until_reset_or_ttl(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    projects = tmp_path / "projects"
    monkeypatch.setattr(persona_loader, "_claude_projects_dirs", lambda: [projects])
    paths = [projects / "a" / "a.jsonl", projects / "b" / "b.jsonl"]
    for path in paths:
        _write_jsonl(path, [_row(timestamp=datetime.now(UTC))])
    read = Mock(wraps=iter_jsonl_dicts)
    monkeypatch.setattr(persona_loader, "iter_jsonl_dicts", read)
    indexes = Mock(side_effect=AssertionError("report must not build assistant indexes"))
    monkeypatch.setattr(persona_loader, "_build_assistant_indexes", indexes)
    clock = Mock(return_value=1000.0)
    monkeypatch.setattr("analyzer.persona_loader.time.time", clock)

    first = persona_loader.load_report_profile(7)
    assert sorted(call.args[0] for call in read.call_args_list) == sorted(paths)
    assert all(call.kwargs == {"errors": "replace"} for call in read.call_args_list)
    clock.return_value = 1000.0 + persona_loader._CACHE_TTL_SECONDS - 1
    assert persona_loader.load_report_profile(7) is first
    assert read.call_count == 2
    persona_loader._reset_cache()
    assert persona_loader.load_report_profile(7) == first
    assert read.call_count == 4
    clock.return_value += persona_loader._CACHE_TTL_SECONDS
    assert persona_loader.load_report_profile(7) == first
    assert read.call_count == 6
    indexes.assert_not_called()


def test_report_profile_cache_is_independent_and_keeps_each_period(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = persona_loader.ReportProfile([0] * 24, [])
    full = persona_loader.PersonaProfile([0] * 24, [], [], 0, 0)
    report_load = Mock(return_value=report)
    full_load = Mock(return_value=full)
    monkeypatch.setattr(persona_loader, "_load_report_profile_uncached", report_load)
    monkeypatch.setattr(persona_loader, "_load_profile_uncached", full_load)

    for days in (1, 7, 1, 7):
        assert persona_loader.load_report_profile(days) is report
        assert persona_loader.load_profile(days) is full
    assert report_load.call_args_list == [((1,), {}), ((7,), {})]
    assert full_load.call_args_list == [((1,), {}), ((7,), {})]
    persona_loader._reset_cache()
    assert persona_loader.load_report_profile(1) is report
    assert persona_loader.load_profile(1) is full
    assert report_load.call_count == full_load.call_count == 3


@pytest.mark.parametrize("missing", [False, True])
def test_report_profile_is_empty_without_logs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, missing: bool
) -> None:
    projects = tmp_path / "projects"
    if not missing:
        projects.mkdir()
    monkeypatch.setattr(persona_loader, "_claude_projects_dirs", lambda: [projects])

    assert persona_loader.load_report_profile() == persona_loader.ReportProfile([0] * 24, [])


@pytest.mark.parametrize("period,days", [("today", 1), ("last7", 7), ("all", 3650)])
def test_reporter_uses_report_profile_and_copies_fields(
    monkeypatch: pytest.MonkeyPatch, period: str, days: int
) -> None:
    profile = persona_loader.ReportProfile(list(range(24)), ["Title"])
    load = Mock(return_value=profile)
    monkeypatch.setattr(persona_loader, "load_report_profile", load)
    full_load = Mock(side_effect=AssertionError("report must not load full profile"))
    monkeypatch.setattr(persona_loader, "load_profile", full_load)

    result = reporter._load_persona_for_period(period)

    assert result == {"hour_histogram": profile.hour_histogram, "recent_titles": ["Title"]}
    assert result["hour_histogram"] is not profile.hour_histogram
    assert result["recent_titles"] is not profile.recent_titles
    load.assert_called_once_with(days)
    full_load.assert_not_called()


def test_reporter_returns_none_when_report_profile_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(persona_loader, "load_report_profile", Mock(side_effect=OSError("log")))

    assert reporter._load_persona_for_period("last7") is None


def test_empty_directory_returns_empty_profile(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setattr(persona_loader, "_claude_projects_dirs", lambda: [projects_dir])

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
    monkeypatch.setattr(persona_loader, "_claude_projects_dirs", lambda: [projects_dir])
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
    monkeypatch.setattr(persona_loader, "_claude_projects_dirs", lambda: [projects_dir])
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
    monkeypatch.setattr(persona_loader, "_claude_projects_dirs", lambda: [projects_dir])
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
    monkeypatch.setattr(persona_loader, "_claude_projects_dirs", lambda: [projects_dir])
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
    monkeypatch.setattr(persona_loader, "_claude_projects_dirs", lambda: [projects_dir])
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
    monkeypatch.setattr(persona_loader, "_claude_projects_dirs", lambda: [projects_dir])
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
    monkeypatch.setattr(persona_loader, "_claude_projects_dirs", lambda: [projects_dir])
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
    monkeypatch.setattr(persona_loader, "_claude_projects_dirs", lambda: [projects_dir])
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
    monkeypatch.setattr(persona_loader, "_claude_projects_dirs", lambda: [projects_dir])
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
    monkeypatch.setattr(persona_loader, "_claude_projects_dirs", lambda: [projects_dir])
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
            rows.extend(_signal_row(timestamp=now, denied_parent_uuid="uuid-0") for _ in range(3))
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
    monkeypatch.setattr(persona_loader, "_claude_projects_dirs", lambda: [projects_dir])
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
    monkeypatch.setattr(persona_loader, "_claude_projects_dirs", lambda: [projects_dir])
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


def test_interruption_of_assistant_without_model_stays_unattributed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    projects_dir = tmp_path / "projects"
    monkeypatch.setattr(persona_loader, "_claude_projects_dirs", lambda: [projects_dir])
    now = datetime.now(UTC)
    rows = _conversation_rows(
        now,
        ["claude-sonnet-4"] * 15 + ["gpt-5-codex"] * 15,
    )
    missing_model = _assistant_row(timestamp=now, model=None, index=999)
    del missing_model["message"]["model"]
    rows.extend(
        [
            missing_model,
            _signal_row(timestamp=now, interrupted_message_id="message-999"),
        ]
    )
    _write_jsonl(projects_dir / "project-a" / "a.jsonl", rows)

    stats = persona_loader.load_profile().one_pass

    assert stats is not None
    assert stats.unattributed_interruptions == 1


def test_signal_can_resolve_to_assistant_in_later_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    projects_dir = tmp_path / "projects"
    monkeypatch.setattr(persona_loader, "_claude_projects_dirs", lambda: [projects_dir])
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
    monkeypatch.setattr(persona_loader, "_claude_projects_dirs", lambda: [projects_dir])
    now = datetime.now(UTC)
    _write_jsonl(
        projects_dir / "project-a" / "a.jsonl",
        _conversation_rows(now, models),
    )

    assert persona_loader.load_profile().one_pass is None

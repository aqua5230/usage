# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

import history_loader
import project_resolver


@pytest.fixture(autouse=True)
def _clear_file_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    history_loader._file_cache.clear()
    monkeypatch.setattr(history_loader, "_disk_cache_seeded", False)
    monkeypatch.setattr(history_loader, "HISTORY_CACHE_PATH", tmp_path / "history_jsonl_cache.json")
    monkeypatch.setattr(history_loader, "_disk_cache_dirty", False)
    monkeypatch.setattr(history_loader, "_last_disk_cache_flush_at", None)
    project_resolver.resolve_project_name.cache_clear()
    project_resolver._resolve_project_name.cache_clear()


def test_disk_cache_flush_is_throttled_and_dirty_is_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flush = Mock()
    now = 100.0
    monkeypatch.setattr(history_loader, "flush_caches", flush)
    monkeypatch.setattr(history_loader, "_monotonic", lambda: now)
    monkeypatch.setattr(history_loader, "_disk_cache_dirty", True)

    history_loader._flush_caches_to_disk()
    now = 200.0
    monkeypatch.setattr(history_loader, "_disk_cache_dirty", True)
    history_loader._flush_caches_to_disk()

    assert flush.call_count == 1
    assert history_loader._disk_cache_dirty is True

    now = 400.0
    history_loader._flush_caches_to_disk()
    assert flush.call_count == 2
    assert history_loader._disk_cache_dirty is False


def test_history_cache_terminate_flush_is_best_effort(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(history_loader, "_disk_cache_dirty", True)
    monkeypatch.setattr(history_loader, "flush_caches", Mock(side_effect=OSError("full")))

    history_loader.flush_caches_on_terminate()

    assert history_loader._disk_cache_dirty is True


def _line(
    *,
    timestamp: str | None = "2026-01-01T00:00:00Z",
    message_id: str = "message",
    request_id: str = "request",
    input_tokens: int = 1,
    output_tokens: int = 2,
    cache_creation_tokens: int = 3,
    cache_read_tokens: int = 4,
    cwd: str | None = None,
    cost_usd: Any = 0.01,
) -> str:
    data: dict[str, Any] = {
        "type": "assistant",
        "sessionId": "session",
        "requestId": request_id,
        "message": {
            "id": message_id,
            "model": "claude-sonnet",
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_creation_input_tokens": cache_creation_tokens,
                "cache_read_input_tokens": cache_read_tokens,
            },
        },
        "costUSD": cost_usd,
    }
    if timestamp is not None:
        data["timestamp"] = timestamp
    if cwd is not None:
        data["cwd"] = cwd
    return json.dumps(data)


def test_parse_line_rejects_non_assistant_type() -> None:
    assert history_loader._parse_line(json.dumps({"type": "user"}), "project") is None


def test_parse_line_rejects_non_dict_message() -> None:
    assert (
        history_loader._parse_line(
            json.dumps(
                {
                    "type": "assistant",
                    "message": "bad",
                    "timestamp": "2026-01-01T00:00:00Z",
                }
            ),
            "project",
        )
        is None
    )


def test_parse_line_rejects_non_dict_usage() -> None:
    assert (
        history_loader._parse_line(
            json.dumps(
                {
                    "type": "assistant",
                    "timestamp": "2026-01-01T00:00:00Z",
                    "message": {"usage": "bad"},
                }
            ),
            "project",
        )
        is None
    )


def test_parse_line_rejects_missing_timestamp() -> None:
    assert history_loader._parse_line(_line(timestamp=None), "project") is None


def test_parse_line_rejects_zero_tokens() -> None:
    assert (
        history_loader._parse_line(
            _line(
                input_tokens=0,
                output_tokens=0,
                cache_creation_tokens=0,
                cache_read_tokens=0,
            ),
            "project",
        )
        is None
    )


def test_parse_line_accepts_digit_string_tokens() -> None:
    entry = history_loader._parse_line(
        _line(
            input_tokens="1",  # type: ignore[arg-type]
            output_tokens="2",  # type: ignore[arg-type]
            cache_creation_tokens="3",  # type: ignore[arg-type]
            cache_read_tokens="4",  # type: ignore[arg-type]
        ),
        "project",
    )

    assert entry is not None
    assert entry.total_tokens == 10


def test_parse_line_treats_non_ascii_digit_tokens_as_zero() -> None:
    # "²" is str.isdigit() True but int("²") raises; must not crash, must be 0.
    entry = history_loader._parse_line(
        _line(
            input_tokens="²",  # type: ignore[arg-type]
            output_tokens=7,
            cache_creation_tokens=0,
            cache_read_tokens=0,
        ),
        "project",
    )

    assert entry is not None
    assert entry.input_tokens == 0
    assert entry.output_tokens == 7


def test_parse_line_parses_valid_entry_and_cwd_project() -> None:
    entry = history_loader._parse_line(_line(cwd="/tmp/work/my-project"), "fallback")

    assert entry is not None
    assert entry.timestamp == datetime(2026, 1, 1, tzinfo=UTC)
    assert entry.session_id == "session"
    assert entry.message_id == "message"
    assert entry.request_id == "request"
    assert entry.model == "claude-sonnet"
    assert entry.total_tokens == 10
    assert entry.cost_usd == 0.01
    assert entry.project == "my-project"


def test_as_optional_float_accepts_finite_numeric_strings() -> None:
    assert history_loader._as_optional_float("0.05") == 0.05
    assert history_loader._as_optional_float("nan") is None
    assert history_loader._as_optional_float("inf") is None


def test_parse_line_accepts_numeric_string_cost_usd() -> None:
    entry = history_loader._parse_line(_line(cost_usd="0.05"), "project")

    assert entry is not None
    assert entry.cost_usd == 0.05


def test_parse_line_uses_main_worktree_project_for_cwd(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = Mock(
        return_value=subprocess.CompletedProcess(
            args=["git", "-C", "/tmp/work/my-project-feature", "worktree", "list", "--porcelain"],
            returncode=0,
            stdout="worktree /tmp/work/my-project\nworktree /tmp/work/my-project-feature\n",
            stderr="",
        )
    )
    monkeypatch.setattr("project_resolver.subprocess.run", run)

    entry = history_loader._parse_line(_line(cwd="/tmp/work/my-project-feature"), "fallback")

    assert entry is not None
    assert entry.project == "my-project"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-01-01T00:00:00Z", datetime(2026, 1, 1, tzinfo=UTC)),
        ("2026-01-01T00:00:00+00:00", datetime(2026, 1, 1, tzinfo=UTC)),
        ("2026-01-01T00:00:00", datetime(2026, 1, 1, tzinfo=UTC)),
        ("not-a-date", None),
        (123, None),
    ],
)
def test_parse_timestamp(value: object, expected: datetime | None) -> None:
    assert history_loader._parse_timestamp(value) == expected


def test_project_from_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    projects_dir = tmp_path / "projects"
    real_project = tmp_path / "Users" / "me" / "alpha"
    real_project.mkdir(parents=True)
    encoded_project = str(real_project).replace(os.sep, "-")
    monkeypatch.setattr(history_loader, "CLAUDE_PROJECTS_DIR", projects_dir)

    assert history_loader._project_from_path(projects_dir / encoded_project / "a.jsonl") == "alpha"
    assert (
        history_loader._project_from_path(projects_dir / "plain-project" / "a.jsonl")
        == "plain-project"
    )
    assert history_loader._project_from_path(tmp_path / "outside.jsonl") == "unknown"


def test_project_from_path_resolves_existing_dash_project_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    projects_dir = tmp_path / "projects"
    real_project = tmp_path / "Users" / "me" / "Desktop" / "claude-tutorial-video"
    real_project.mkdir(parents=True)
    encoded_project = str(real_project).replace(os.sep, "-")
    monkeypatch.setattr(history_loader, "CLAUDE_PROJECTS_DIR", projects_dir)

    project = history_loader._project_from_path(projects_dir / encoded_project / "a.jsonl")

    assert project == "claude-tutorial-video"


def test_project_from_path_fallback_preserves_dash(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    projects_dir = tmp_path / "projects"
    monkeypatch.setattr(history_loader, "CLAUDE_PROJECTS_DIR", projects_dir)

    project = history_loader._project_from_path(projects_dir / "-missing-plain-project" / "a.jsonl")

    assert project == "missing-plain-project"


@pytest.mark.parametrize(
    ("cwd", "expected"),
    [
        ("/Users/me/work/app", "app"),
        ("~/work/app", "app"),
        ("/", "unknown"),
        ("", "unknown"),
    ],
)
def test_project_from_cwd(cwd: str, expected: str) -> None:
    assert history_loader._project_from_cwd(cwd) == expected


def test_load_entries_deduplicates_sorts_and_filters_hours_back(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    projects_dir = tmp_path / "projects"
    real_project = tmp_path / "Users" / "me" / "alpha"
    real_project.mkdir(parents=True)
    encoded_project = str(real_project).replace(os.sep, "-")
    project_dir = projects_dir / encoded_project
    project_dir.mkdir(parents=True)
    now = datetime.now(UTC)
    old = now - timedelta(hours=2)
    newer = now - timedelta(minutes=5)
    older = now - timedelta(minutes=30)
    log_path = project_dir / "session.jsonl"
    log_path.write_text(
        "\n".join(
            [
                _line(timestamp=old.isoformat(), message_id="old", request_id="old"),
                _line(timestamp=newer.isoformat(), message_id="newer", request_id="same"),
                _line(timestamp=older.isoformat(), message_id="older", request_id="unique"),
                _line(timestamp=newer.isoformat(), message_id="newer", request_id="same"),
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(history_loader, "CLAUDE_PROJECTS_DIR", projects_dir)

    entries = history_loader.load_entries(hours_back=1)

    assert [(entry.message_id, entry.request_id) for entry in entries] == [
        ("older", "unique"),
        ("newer", "same"),
    ]
    assert [entry.project for entry in entries] == ["alpha", "alpha"]


def test_load_entries_skips_bad_utf8_bytes_without_crashing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    projects_dir = tmp_path / "projects"
    project_dir = projects_dir / "plain-project"
    project_dir.mkdir(parents=True)
    log_path = project_dir / "session.jsonl"
    valid_line = _line(message_id="valid", request_id="valid")
    log_path.write_bytes(valid_line.encode("utf-8") + b"\n\xff\n")
    monkeypatch.setattr(history_loader, "CLAUDE_PROJECTS_DIR", projects_dir)

    entries = history_loader.load_entries()

    assert [(entry.message_id, entry.request_id) for entry in entries] == [("valid", "valid")]


def test_file_cache_evicts_oldest_entry_when_maxsize_exceeded(tmp_path: Path) -> None:
    paths = [
        tmp_path / f"session-{index}.jsonl"
        for index in range(history_loader._FILE_CACHE_MAXSIZE + 1)
    ]

    for index, path in enumerate(paths):
        path.write_text(_line(message_id=f"message-{index}"), encoding="utf-8")
        history_loader._load_file(path, "project", None, set(), [])

    assert len(history_loader._file_cache) == history_loader._FILE_CACHE_MAXSIZE
    assert paths[0] not in history_loader._file_cache
    assert paths[-1] in history_loader._file_cache


def test_load_entries_incremental_append_matches_full_reparse(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    projects_dir = tmp_path / "projects"
    project_dir = projects_dir / "plain-project"
    project_dir.mkdir(parents=True)
    monkeypatch.setattr(history_loader, "CLAUDE_PROJECTS_DIR", projects_dir)

    lines = [_line(message_id=f"m{index}", request_id=f"r{index}") for index in range(6)]

    full_path = project_dir / "full.jsonl"
    full_path.write_text("\n".join(lines), encoding="utf-8")
    expected = history_loader.load_entries(jsonl_paths=[full_path])

    history_loader._file_cache.clear()

    incremental_path = project_dir / "incremental.jsonl"
    partial = lines[2][: len(lines[2]) // 2]
    incremental_path.write_text("\n".join([lines[0], lines[1]]) + "\n" + partial, encoding="utf-8")

    first = history_loader.load_entries(jsonl_paths=[incremental_path])
    assert [entry.message_id for entry in first] == ["m0", "m1"]

    with incremental_path.open("a", encoding="utf-8") as file:
        file.write(lines[2][len(partial) :] + "\n" + lines[3])

    second = history_loader.load_entries(jsonl_paths=[incremental_path])
    assert [entry.message_id for entry in second] == ["m0", "m1", "m2", "m3"]

    with incremental_path.open("a", encoding="utf-8") as file:
        file.write("\n" + "\n".join(lines[4:]))

    final = history_loader.load_entries(jsonl_paths=[incremental_path])

    assert final == expected


def test_load_entries_falls_back_to_full_reparse_when_prefix_changes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    projects_dir = tmp_path / "projects"
    project_dir = projects_dir / "plain-project"
    project_dir.mkdir(parents=True)
    monkeypatch.setattr(history_loader, "CLAUDE_PROJECTS_DIR", projects_dir)

    path = project_dir / "session.jsonl"
    original_lines = [
        _line(message_id="m1", request_id="r1", input_tokens=1),
        _line(message_id="m2", request_id="r2", input_tokens=2),
    ]
    path.write_text("\n".join(original_lines), encoding="utf-8")

    first = history_loader.load_entries(jsonl_paths=[path])
    assert [entry.input_tokens for entry in first] == [1, 2]

    rewritten_lines = [
        _line(message_id="m1", request_id="r1", input_tokens=10),
        _line(message_id="m2", request_id="r2", input_tokens=2),
        _line(message_id="m3", request_id="r3", input_tokens=3),
    ]
    path.write_text("\n".join(rewritten_lines), encoding="utf-8")

    second = history_loader.load_entries(jsonl_paths=[path])

    assert [entry.input_tokens for entry in second] == [10, 2, 3]


def test_disk_cache_seed_loads_on_cold_start(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cache_file = tmp_path / "history_jsonl_cache.json"
    projects_dir = tmp_path / "projects"
    session_path = projects_dir / "plain-project" / "session.jsonl"
    session_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(history_loader, "HISTORY_CACHE_PATH", cache_file)
    monkeypatch.setattr(history_loader, "CLAUDE_PROJECTS_DIR", projects_dir)

    cache_file.write_text(
        json.dumps(
            {
                "schema_version": history_loader._HISTORY_JSONL_CACHE_SCHEMA,
                "cached_at": datetime.now(UTC).timestamp(),
                "files": {
                    str(session_path): {
                        "mtime": 123456.0,
                        "size": 1000,
                        "entries": [
                            {
                                "timestamp": "2026-06-24T12:00:00+00:00",
                                "session_id": "test-session",
                                "message_id": "test-message",
                                "request_id": "test-request",
                                "model": "claude-sonnet",
                                "input_tokens": 100,
                                "output_tokens": 50,
                                "cache_creation_tokens": 10,
                                "cache_read_tokens": 5,
                                "cost_usd": 0.25,
                                "project": "plain-project",
                            }
                        ],
                        "confirmed_offset": 1000,
                        "confirmed_prefix_digest": "abcd",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    history_loader.load_entries()

    assert len(history_loader._file_cache) == 1
    assert session_path in history_loader._file_cache
    cache_entry = history_loader._file_cache[session_path]
    assert cache_entry.mtime == 123456.0
    assert cache_entry.size == 1000
    assert len(cache_entry.entries) == 1
    assert cache_entry.entries[0].input_tokens == 100
    assert cache_entry.entries[0].cache_creation_tokens == 10
    assert cache_entry.confirmed_offset == 1000
    assert cache_entry.confirmed_prefix_digest == bytes.fromhex("abcd")


def test_disk_cache_invalid_schema_fails_safely(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cache_file = tmp_path / "history_jsonl_cache.json"
    monkeypatch.setattr(history_loader, "HISTORY_CACHE_PATH", cache_file)
    cache_file.write_text(
        json.dumps(
            {
                "schema_version": 999,
                "cached_at": datetime.now(UTC).timestamp(),
                "files": {},
            }
        ),
        encoding="utf-8",
    )

    history_loader._seed_caches_from_disk()

    assert len(history_loader._file_cache) == 0


def test_disk_cache_missing_file_fails_safely(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cache_file = tmp_path / "history_jsonl_cache.json"
    monkeypatch.setattr(history_loader, "HISTORY_CACHE_PATH", cache_file)

    history_loader._seed_caches_from_disk()

    assert len(history_loader._file_cache) == 0


def test_disk_cache_corrupted_json_fails_safely(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cache_file = tmp_path / "history_jsonl_cache.json"
    monkeypatch.setattr(history_loader, "HISTORY_CACHE_PATH", cache_file)
    cache_file.write_text("not valid json {", encoding="utf-8")

    history_loader._seed_caches_from_disk()

    assert len(history_loader._file_cache) == 0


def test_disk_cache_file_mtime_invalidates_seed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cache_file = tmp_path / "history_jsonl_cache.json"
    projects_dir = tmp_path / "projects"
    project_dir = projects_dir / "plain-project"
    project_dir.mkdir(parents=True)
    session_path = project_dir / "session.jsonl"
    monkeypatch.setattr(history_loader, "HISTORY_CACHE_PATH", cache_file)
    monkeypatch.setattr(history_loader, "CLAUDE_PROJECTS_DIR", projects_dir)

    cache_file.write_text(
        json.dumps(
            {
                "schema_version": history_loader._HISTORY_JSONL_CACHE_SCHEMA,
                "cached_at": datetime.now(UTC).timestamp(),
                "files": {
                    str(session_path): {
                        "mtime": 100.0,
                        "size": 200,
                        "entries": [
                            {
                                "timestamp": "2026-06-24T12:00:00+00:00",
                                "session_id": "test-session",
                                "message_id": "stale-message",
                                "request_id": "stale-request",
                                "model": "claude-sonnet",
                                "input_tokens": 1,
                                "output_tokens": 2,
                                "cache_creation_tokens": 3,
                                "cache_read_tokens": 4,
                                "cost_usd": 0.01,
                                "project": "plain-project",
                            }
                        ],
                        "confirmed_offset": 200,
                        "confirmed_prefix_digest": "abcd",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    session_path.write_text(
        _line(
            message_id="fresh-message",
            request_id="fresh-request",
            input_tokens=20,
            output_tokens=30,
            cache_creation_tokens=40,
            cache_read_tokens=50,
        ),
        encoding="utf-8",
    )

    entries = history_loader.load_entries()

    assert len(entries) == 1
    assert entries[0].message_id == "fresh-message"
    assert entries[0].input_tokens == 20
    assert entries[0].output_tokens == 30

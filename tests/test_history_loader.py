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
def _clear_file_cache() -> None:
    history_loader._file_cache.clear()
    project_resolver._resolve_project_name.cache_clear()


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

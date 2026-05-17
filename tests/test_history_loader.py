from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

import history_loader


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
        "costUSD": 0.01,
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
    monkeypatch.setattr(history_loader, "CLAUDE_PROJECTS_DIR", projects_dir)

    assert history_loader._project_from_path(projects_dir / "Users-me-alpha" / "a.jsonl") == "alpha"
    assert (
        history_loader._project_from_path(projects_dir / "plain-project" / "a.jsonl") == "project"
    )
    assert history_loader._project_from_path(tmp_path / "outside.jsonl") == "unknown"


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
    project_dir = projects_dir / "Users-me-alpha"
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

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from analyzer import claude_activity
from loaders import claude_paths


@pytest.fixture
def activity_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(claude_paths, "claude_config_dirs", lambda: [tmp_path])
    return tmp_path / "stats-cache.json"


def test_activity_dates_uses_only_positive_message_counts(activity_path: Path) -> None:
    payload = {
        "dailyActivity": [
            {"date": "2026-04-27", "messageCount": 290},
            {"date": "2026-05-09", "messageCount": 463},
            {"date": "2026-05-09", "messageCount": 1},
            {"date": "2026-05-10", "messageCount": 0},
        ],
        "modelUsage": {"unused": "invalid"},
        "dailyModelTokens": "invalid",
    }
    original = json.dumps(payload).encode()
    activity_path.write_bytes(original)
    assert claude_activity.activity_dates() == frozenset({date(2026, 4, 27), date(2026, 5, 9)})
    assert activity_path.read_bytes() == original


def test_activity_dates_missing_file(activity_path: Path) -> None:
    assert claude_activity.activity_dates() == frozenset()
    assert not activity_path.exists()


@pytest.mark.parametrize("content", [b"{", b"\xff", b"[" * 2000])
def test_activity_dates_bad_json(activity_path: Path, content: bytes) -> None:
    activity_path.write_bytes(content)
    assert claude_activity.activity_dates() == frozenset()
    assert activity_path.read_bytes() == content


def test_activity_dates_oversize(activity_path: Path) -> None:
    activity_path.write_bytes(b" " * (5 * 1024 * 1024 + 1))
    assert claude_activity.activity_dates() == frozenset()
    assert activity_path.stat().st_size == 5 * 1024 * 1024 + 1


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"dailyActivity": None},
        {"dailyActivity": {}},
        {"dailyActivity": [None]},
        {"dailyActivity": [{}]},
        *[
            {"dailyActivity": [{"date": day, "messageCount": count}]}
            for day, count in [
                (None, 1),
                (20260427, 1),
                ("2026-02-30", 1),
                ("20260427", 1),
                ("2026-04-27", None),
                ("2026-04-27", "1"),
                ("2026-04-27", True),
                ("2026-04-27", 1.5),
            ]
        ],
        {
            "dailyActivity": [
                {"date": "2026-04-27", "messageCount": 1},
                {"date": "2026-04-28", "messageCount": "bad"},
            ]
        },
    ],
)
def test_activity_dates_invalid_types(activity_path: Path, payload: object) -> None:
    activity_path.write_text(json.dumps(payload), encoding="utf-8")
    assert claude_activity.activity_dates() == frozenset()


def test_activity_dates_unions_valid_directories(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    directories = [tmp_path / str(index) for index in range(4)]
    for directory in directories:
        directory.mkdir()
    for directory, day in zip(directories[:2], ["2026-04-27", "2026-05-09"], strict=True):
        (directory / "stats-cache.json").write_text(
            json.dumps(
                {
                    "dailyActivity": [
                        {"date": day, "messageCount": 1},
                    ]
                }
            ),
            encoding="utf-8",
        )
    (directories[2] / "stats-cache.json").write_text("bad", encoding="utf-8")
    monkeypatch.setattr(claude_paths, "claude_config_dirs", lambda: directories)
    assert claude_activity.activity_dates() == frozenset({date(2026, 4, 27), date(2026, 5, 9)})

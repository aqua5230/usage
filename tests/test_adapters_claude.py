from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

import pricing
from adapters import claude


@pytest.fixture(autouse=True)
def _clear_file_cache() -> None:
    claude._file_cache.clear()


def _write_assistant_log(
    path: Path,
    *,
    timestamp: str,
    usage: dict[str, Any],
    cost_usd: Any = None,
    cwd: str = "/tmp/demo",
) -> None:
    line = {
        "type": "assistant",
        "timestamp": timestamp,
        "sessionId": "session-1",
        "requestId": "request-1",
        "cwd": cwd,
        "costUSD": cost_usd,
        "message": {
            "id": "message-1",
            "model": "claude-3-5-sonnet-20241022",
            "usage": usage,
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(line), encoding="utf-8")


def test_load_entries_skips_bad_utf8_jsonl_without_crashing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    projects_dir = tmp_path / "projects"
    bad_path = projects_dir / "demo" / "bad.jsonl"
    bad_path.parent.mkdir(parents=True, exist_ok=True)
    bad_path.write_bytes(b"\xff\xfe not utf-8\n")
    monkeypatch.setattr(claude, "CLAUDE_DIRS", [str(projects_dir)])

    assert claude.load_entries() == []


def test_load_entries_converts_numeric_string_tokens_for_pricing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    projects_dir = tmp_path / "projects"
    _write_assistant_log(
        projects_dir / "demo" / "entry.jsonl",
        timestamp=datetime.now(UTC).isoformat(),
        usage={
            "input_tokens": "10",
            "output_tokens": "3",
            "cache_creation_input_tokens": "2",
            "cache_read_input_tokens": "1",
        },
    )
    monkeypatch.setattr(claude, "CLAUDE_DIRS", [str(projects_dir)])
    monkeypatch.setattr(
        pricing,
        "get_pricing",
        lambda: {
            "claude-3-5-sonnet-20241022": {
                "input_cost_per_token": 1.0,
                "output_cost_per_token": 2.0,
                "cache_creation_input_token_cost": 3.0,
                "cache_read_input_token_cost": 4.0,
            }
        },
    )

    entries = claude.load_entries()

    assert len(entries) == 1
    entry = entries[0]
    assert isinstance(entry.input_tokens, int)
    assert isinstance(entry.output_tokens, int)
    assert isinstance(entry.cache_creation_tokens, int)
    assert isinstance(entry.cache_read_tokens, int)
    assert entry.input_tokens == 10
    assert entry.output_tokens == 3
    assert entry.cache_creation_tokens == 2
    assert entry.cache_read_tokens == 1
    assert pricing.calculate_cost(entry) == 26.0


def test_load_entries_converts_numeric_string_cost_usd_to_float(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    projects_dir = tmp_path / "projects"
    _write_assistant_log(
        projects_dir / "demo" / "entry.jsonl",
        timestamp=datetime.now(UTC).isoformat(),
        usage={"input_tokens": 1},
        cost_usd="0.05",
    )
    monkeypatch.setattr(claude, "CLAUDE_DIRS", [str(projects_dir)])

    entries = claude.load_entries()

    assert len(entries) == 1
    assert entries[0].cost_usd == 0.05
    assert isinstance(entries[0].cost_usd, float)

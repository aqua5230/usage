# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

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


def test_load_entries_tracks_1h_cache_and_only_bills_advisor_iterations(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    projects_dir = tmp_path / "projects"
    _write_assistant_log(
        projects_dir / "demo" / "entry.jsonl",
        timestamp=datetime.now(UTC).isoformat(),
        usage={
            "input_tokens": 4,
            "output_tokens": 625,
            "cache_creation_input_tokens": 3_526,
            "cache_read_input_tokens": 205_601,
            "cache_creation": {"ephemeral_1h_input_tokens": 3_526},
            "iterations": [
                {"type": "message", "input_tokens": 2, "output_tokens": 157},
                {
                    "type": "advisor_message",
                    "model": "claude-opus-5",
                    "input_tokens": 104_982,
                    "output_tokens": 7_883,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                },
                {"type": "message", "input_tokens": 2, "output_tokens": 468},
            ],
        },
        cost_usd=0.01,
    )
    monkeypatch.setattr(claude, "CLAUDE_DIRS", [str(projects_dir)])

    entries = claude.load_entries()

    assert [(entry.request_id, entry.input_tokens, entry.output_tokens) for entry in entries] == [
        ("request-1", 4, 625),
        ("request-1#advisor1", 104_982, 7_883),
    ]
    assert entries[0].cache_creation_1h_tokens == 3_526
    assert entries[1].model == "claude-opus-5"
    assert entries[1].cost_usd is None


def test_load_entries_without_iterations_keeps_single_entry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    projects_dir = tmp_path / "projects"
    _write_assistant_log(
        projects_dir / "demo" / "entry.jsonl",
        timestamp=datetime.now(UTC).isoformat(),
        usage={"input_tokens": 1},
    )
    monkeypatch.setattr(claude, "CLAUDE_DIRS", [str(projects_dir)])

    assert len(claude.load_entries()) == 1

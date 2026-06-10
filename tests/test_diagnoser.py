# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from adapters import claude
from analyzer import diagnoser


def _write_jsonl(path: Path, records: list[dict[str, Any] | str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = [
        record if isinstance(record, str) else json.dumps(record, ensure_ascii=False)
        for record in records
    ]
    path.write_text("\n".join(serialized) + "\n", encoding="utf-8")


def _assistant(
    *,
    session_id: str,
    tool_id: str,
    name: str,
    tool_input: dict[str, str],
    tokens: int = 1000,
    timestamp: str = "2026-05-10T12:00:00Z",
    cwd: str = "/Users/tester/project",
) -> dict[str, Any]:
    return {
        "type": "assistant",
        "timestamp": timestamp,
        "sessionId": session_id,
        "requestId": f"request-{tool_id}",
        "cwd": cwd,
        "message": {
            "id": f"message-{tool_id}",
            "model": "claude-3-5-sonnet-20241022",
            "usage": {"input_tokens": tokens, "output_tokens": 0},
            "content": [
                {
                    "type": "tool_use",
                    "id": tool_id,
                    "name": name,
                    "input": tool_input,
                }
            ],
        },
    }


def _user_result(tool_id: str, size: int = 1000) -> dict[str, Any]:
    return {
        "type": "user",
        "timestamp": "2026-05-10T12:00:01Z",
        "sessionId": "s1",
        "message": {
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": "x" * size,
                }
            ]
        },
    }


def _patch_claude_dirs(monkeypatch: pytest.MonkeyPatch, base: Path) -> None:
    monkeypatch.setattr(claude, "CLAUDE_DIRS", [str(base)])


def test_analyze_without_jsonl_dir_returns_no_data(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_claude_dirs(monkeypatch, tmp_path / "missing")

    result = diagnoser.analyze(
        date_from=date(2026, 5, 1),
        date_to=date(2026, 5, 31),
        total_cost_usd=0.0,
    )

    assert result.has_data is False
    assert result.findings == []


def test_jsonl_parsing_ignores_invalid_lines_and_pairs_tool_results(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    base = tmp_path / "projects"
    records: list[dict[str, Any] | str] = [
        "not-json",
        _assistant(
            session_id="s1",
            tool_id="read-1",
            name="Read",
            tool_input={"file_path": "/repo/app.py"},
        ),
        _user_result("read-1", 1200),
        {"type": "assistant", "timestamp": "bad-timestamp"},
    ]
    _write_jsonl(base / "repo" / "session.jsonl", records)
    _patch_claude_dirs(monkeypatch, base)

    result = diagnoser.analyze(date(2026, 5, 1), date(2026, 5, 31), 100.0)

    repeated = [finding for finding in result.findings if finding.kind == "repeated_reads"]
    assert result.has_data is True
    assert repeated == []
    assert result.total_waste_tokens == 0


def test_repeated_reads_flags_same_file_read_11_times(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    base = tmp_path / "projects"
    records: list[dict[str, Any] | str] = []
    for index in range(11):
        tool_id = f"read-{index}"
        records.append(
            _assistant(
                session_id="s1",
                tool_id=tool_id,
                name="Read",
                tool_input={"file_path": "/repo/app.py"},
            )
        )
        records.append(_user_result(tool_id, 1200))
    _write_jsonl(base / "repo" / "session.jsonl", records)
    _patch_claude_dirs(monkeypatch, base)

    result = diagnoser.analyze(date(2026, 5, 1), date(2026, 5, 31), 100.0)

    repeated = [finding for finding in result.findings if finding.kind == "repeated_reads"]
    assert repeated
    assert repeated[0].items[0]["label"] == "/repo/app.py"
    assert repeated[0].items[0]["n"] == 11


def test_polluter_dirs_detects_node_modules(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    base = tmp_path / "projects"
    records: list[dict[str, Any] | str] = [
        _assistant(
            session_id="s1",
            tool_id="polluter",
            name="Read",
            tool_input={"file_path": "/repo/node_modules/foo.js"},
        ),
        _user_result("polluter", 4096),
    ]
    _write_jsonl(base / "repo" / "session.jsonl", records)
    _patch_claude_dirs(monkeypatch, base)

    result = diagnoser.analyze(date(2026, 5, 1), date(2026, 5, 31), 100.0)

    polluters = [finding for finding in result.findings if finding.kind == "polluter_dirs"]
    assert polluters
    assert polluters[0].items[0]["label"] == "node_modules"
    assert result.suggested_claudeignore == "node_modules/"


def test_anomaly_session_detects_session_over_five_times_project_median(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    base = tmp_path / "projects"
    records: list[dict[str, Any] | str] = []
    for index, tokens in enumerate([1000, 1000, 1000, 1000, 60_000]):
        records.append(
            _assistant(
                session_id=f"s{index}",
                tool_id=f"bash-{index}",
                name="Bash",
                tool_input={"command": "true"},
                tokens=tokens,
            )
        )
        records.append(_user_result(f"bash-{index}", 10))
    _write_jsonl(base / "repo" / "session.jsonl", records)
    _patch_claude_dirs(monkeypatch, base)

    result = diagnoser.analyze(date(2026, 5, 1), date(2026, 5, 31), 100.0)

    anomalies = [finding for finding in result.findings if finding.kind == "anomaly_session"]
    assert anomalies
    assert anomalies[0].items[0]["tokens"] == 60_000


def test_anomaly_session_has_project_and_start_time(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    base = tmp_path / "projects"
    records: list[dict[str, Any] | str] = []
    for index, tokens in enumerate([1000, 1000, 1000, 1000]):
        records.append(
            _assistant(
                session_id=f"s{index}",
                tool_id=f"bash-{index}",
                name="Bash",
                tool_input={"command": "true"},
                tokens=tokens,
                cwd="/Users/tester/my-app",
            )
        )
        records.append(_user_result(f"bash-{index}", 10))
    records.append(
        _assistant(
            session_id="burst",
            tool_id="burst-1",
            name="Bash",
            tool_input={"command": "true"},
            tokens=60_000,
            timestamp="2026-05-09T10:23:00Z",
            cwd="/Users/tester/my-app",
        )
    )
    records.append(_user_result("burst-1", 10))
    _write_jsonl(base / "repo" / "session.jsonl", records)
    _patch_claude_dirs(monkeypatch, base)

    result = diagnoser.analyze(date(2026, 5, 1), date(2026, 5, 31), 100.0)

    anomalies = [finding for finding in result.findings if finding.kind == "anomaly_session"]
    assert anomalies
    item = anomalies[0].items[0]
    assert item["project"] == "my-app"
    started = datetime.fromisoformat(str(item["session_start_iso"]))
    assert started == datetime(2026, 5, 9, 10, 23, tzinfo=UTC)
    assert started.utcoffset() is not None


def test_noisy_bash_flags_large_single_bash_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    base = tmp_path / "projects"
    records: list[dict[str, Any] | str] = [
        _assistant(
            session_id="s1",
            tool_id="bash-large",
            name="Bash",
            tool_input={"command": "find . -type f"},
        ),
        _user_result("bash-large", 20_001),
    ]
    _write_jsonl(base / "repo" / "session.jsonl", records)
    _patch_claude_dirs(monkeypatch, base)

    result = diagnoser.analyze(date(2026, 5, 1), date(2026, 5, 31), 100.0)

    findings = [finding for finding in result.findings if finding.kind == "noisy_bash"]
    assert findings
    assert findings[0].severity == "info"
    assert findings[0].items[0]["label"] == "find . -type f"
    assert findings[0].items[0]["size_bytes"] == 20_001


def test_noisy_bash_ignores_output_at_or_below_threshold(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    base = tmp_path / "projects"
    records: list[dict[str, Any] | str] = [
        _assistant(
            session_id="s1",
            tool_id="bash-threshold",
            name="Bash",
            tool_input={"command": "find . -type f"},
        ),
        _user_result("bash-threshold", 20_000),
    ]
    _write_jsonl(base / "repo" / "session.jsonl", records)
    _patch_claude_dirs(monkeypatch, base)

    result = diagnoser.analyze(date(2026, 5, 1), date(2026, 5, 31), 100.0)

    findings = [finding for finding in result.findings if finding.kind == "noisy_bash"]
    assert findings == []


def test_repeated_bash_flags_same_command_run_15_times(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    base = tmp_path / "projects"
    records: list[dict[str, Any] | str] = []
    for index in range(15):
        tool_id = f"bash-repeat-{index}"
        records.append(
            _assistant(
                session_id=f"s{index}",
                tool_id=tool_id,
                name="Bash",
                tool_input={"command": "pytest -q"},
            )
        )
        records.append(_user_result(tool_id, 100))
    _write_jsonl(base / "repo" / "session.jsonl", records)
    _patch_claude_dirs(monkeypatch, base)

    result = diagnoser.analyze(date(2026, 5, 1), date(2026, 5, 31), 100.0)

    findings = [finding for finding in result.findings if finding.kind == "repeated_bash"]
    assert findings
    assert findings[0].severity == "info"
    assert findings[0].items[0]["label"] == "pytest -q"
    assert findings[0].items[0]["n"] == 15
    assert findings[0].items[0]["estimated_waste_tokens"] == 7_500


def test_repeated_bash_ignores_command_below_threshold(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    base = tmp_path / "projects"
    records: list[dict[str, Any] | str] = []
    for index in range(14):
        tool_id = f"bash-repeat-{index}"
        records.append(
            _assistant(
                session_id=f"s{index}",
                tool_id=tool_id,
                name="Bash",
                tool_input={"command": "pytest -q"},
            )
        )
        records.append(_user_result(tool_id, 100))
    _write_jsonl(base / "repo" / "session.jsonl", records)
    _patch_claude_dirs(monkeypatch, base)

    result = diagnoser.analyze(date(2026, 5, 1), date(2026, 5, 31), 100.0)

    findings = [finding for finding in result.findings if finding.kind == "repeated_bash"]
    assert findings == []


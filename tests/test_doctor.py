# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

import codex_loader
import doctor
import setup_hook


@pytest.fixture(autouse=True)
def _patch_doctor_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    claude_dir = tmp_path / ".claude"
    codex_dir = tmp_path / ".codex"
    monkeypatch.setattr(setup_hook, "CLAUDE_SETTINGS", claude_dir / "settings.json")
    monkeypatch.setattr(setup_hook, "HOOK_TARGET", claude_dir / "usage-statusline.py")
    monkeypatch.setattr(
        setup_hook,
        "FORWARDER_TARGET",
        claude_dir / "usage-statusline-forwarder.py",
    )
    monkeypatch.setattr(setup_hook, "STATUS_FILE", claude_dir / "usage-status.json")
    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", codex_dir / "sessions")
    monkeypatch.setattr(codex_loader, "LOGS_DB", codex_dir / "logs_2.sqlite")
    monkeypatch.setattr(codex_loader, "STATE_DB", codex_dir / "state_5.sqlite")
    monkeypatch.setattr(codex_loader, "load_rate_limits", lambda: None)


def test_doctor_handles_missing_settings_and_status_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(setup_hook, "CLAUDE_SETTINGS", tmp_path / ".claude" / "settings.json")
    monkeypatch.setattr(setup_hook, "HOOK_TARGET", tmp_path / ".claude" / "usage-statusline.py")
    monkeypatch.setattr(
        setup_hook,
        "FORWARDER_TARGET",
        tmp_path / ".claude" / "usage-statusline-forwarder.py",
    )
    monkeypatch.setattr(setup_hook, "STATUS_FILE", tmp_path / ".claude" / "usage-status.json")
    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", tmp_path / ".codex" / "sessions")
    monkeypatch.setattr(codex_loader, "LOGS_DB", tmp_path / ".codex" / "logs_2.sqlite")
    monkeypatch.setattr(codex_loader, "STATE_DB", tmp_path / ".codex" / "state_5.sqlite")
    monkeypatch.setattr(codex_loader, "load_rate_limits", lambda: None)

    output = doctor.render()
    lines = output.splitlines()

    assert "usage v" in output
    assert lines[2] == "[core]"
    assert [line.split(":", 1)[0] for line in lines[3:6]] == [
        "status file",
        "codex jsonl",
        "codex state",
    ]
    assert lines[6] == doctor.SEPARATOR
    assert lines[7] == "[hook]"
    assert lines[12] == doctor.SEPARATOR
    assert lines[13] == "[optional]"
    assert "hook state:        none" in output
    forwarder_line = next(line for line in lines if line.startswith("forwarder script:"))
    assert forwarder_line.endswith("[not needed in none mode]")
    assert "status file:" in output
    assert "self-heal log (last 5):\n  none" in output


def test_doctor_flags_missing_forwarder_in_forwarder_mode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    settings = claude_dir / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "statusLine": {
                    "type": "command",
                    "command": "python usage-statusline-forwarder.py",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(setup_hook, "CLAUDE_SETTINGS", settings)

    output = doctor.render()
    forwarder_line = next(
        line for line in output.splitlines() if line.startswith("forwarder script:")
    )

    assert "hook state:        us-forwarder" in output
    assert forwarder_line.endswith("[missing]")


def test_doctor_reports_external_hook_keyword(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    settings = claude_dir / "settings.json"
    settings.write_text(
        json.dumps({"statusLine": {"type": "command", "command": "node /opt/ccusage/bin/cli"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(setup_hook, "CLAUDE_SETTINGS", settings)
    monkeypatch.setattr(setup_hook, "STATUS_FILE", claude_dir / "usage-status.json")
    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", tmp_path / ".codex" / "sessions")
    monkeypatch.setattr(codex_loader, "LOGS_DB", tmp_path / ".codex" / "logs_2.sqlite")
    monkeypatch.setattr(codex_loader, "STATE_DB", tmp_path / ".codex" / "state_5.sqlite")
    monkeypatch.setattr(codex_loader, "load_rate_limits", lambda: None)

    output = doctor.render()

    assert "hook state:        external" in output
    assert "external hooks:    ccusage" in output


def test_doctor_flags_windows_backslash_statusline_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    settings = claude_dir / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "statusLine": {
                    "type": "command",
                    "command": (
                        r"C:\Python\python.exe "
                        r"C:\Users\test\.claude\usage-statusline.py"
                    ),
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(setup_hook, "CLAUDE_SETTINGS", settings)

    output = doctor.render()

    assert "status command:    Windows Git Bash-incompatible paths" in output


def test_doctor_reports_codex_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    claude_dir = tmp_path / ".claude"
    codex_dir = tmp_path / ".codex"
    sessions_dir = codex_dir / "sessions"
    logs_db = codex_dir / "logs_2.sqlite"
    state_db = codex_dir / "state_5.sqlite"
    session_path = sessions_dir / "2026" / "01" / "01" / "session.jsonl"
    session_path.parent.mkdir(parents=True)
    session_path.write_text("{}", encoding="utf-8")
    now = datetime.now(UTC)
    os.utime(session_path, (now.timestamp(), now.timestamp()))
    codex_dir.mkdir(exist_ok=True)
    with sqlite3.connect(logs_db) as conn:
        conn.execute("CREATE TABLE logs (feedback_log_body TEXT)")
        conn.executemany(
            "INSERT INTO logs (feedback_log_body) VALUES (?)",
            [
                ("websocket event: {\"type\":\"codex.rate_limits\"}",),
                ("websocket event: {\"type\":\"error\",\"error\":\"usage_limit_reached\"}",),
                ("other",),
            ],
        )
    state_db.write_text("", encoding="utf-8")
    monkeypatch.setattr(setup_hook, "CLAUDE_SETTINGS", claude_dir / "settings.json")
    monkeypatch.setattr(setup_hook, "STATUS_FILE", claude_dir / "usage-status.json")
    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(codex_loader, "LOGS_DB", logs_db)
    monkeypatch.setattr(codex_loader, "STATE_DB", state_db)
    monkeypatch.setattr(
        codex_loader,
        "load_rate_limits",
        lambda: codex_loader.CodexRateLimits(
            five_hour_pct=None,
            five_hour_resets_at=None,
            seven_day_pct=12.0,
            seven_day_resets_at=now.timestamp() + 3600,
            model="gpt-test",
            updated_at=now.isoformat(),
        ),
    )

    output = doctor.render()

    assert "codex jsonl:       1 files, latest wrote" in output
    assert "codex logs:" in output
    assert "[ok], rate_limit rows: 2" in output
    assert "codex state:" in output
    assert "[ok]" in output
    assert "codex rate limits: 5h: no, weekly: yes, updated:" in output


def test_render_json_has_structured_checks() -> None:
    payload = json.loads(doctor.render_json())

    assert isinstance(payload["version"], str)
    assert set(payload) == {"version", "checks", "self_heal_log", "summary"}
    assert payload["summary"] == {"ok": 3, "warn": 9, "error": 0}
    expected_codes = {
        "status_file",
        "codex_sessions",
        "codex_state",
        "hook_state",
        "hook_version",
        "hook_script",
        "status_command",
        "forwarder_script",
        "forwarder_prompt",
        "external_hooks",
        "codex_logs",
        "codex_rate_limits",
    }
    checks = payload["checks"]
    assert {check["code"] for check in checks} == expected_codes
    assert all(
        set(check) == {"section", "code", "status", "detail"}
        and check["status"] in {"ok", "warn", "error"}
        for check in checks
    )


def test_render_json_isolates_check_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail() -> doctor.CheckResult:
        raise RuntimeError("broken status file")

    monkeypatch.setattr(doctor, "_status_file", fail)

    payload = json.loads(doctor.render_json())
    checks = {check["code"]: check for check in payload["checks"]}

    assert checks["status_file"]["status"] == "error"
    assert checks["status_file"]["detail"] == "error: broken status file"
    assert all(
        check["status"] != "error" for code, check in checks.items() if code != "status_file"
    )


def test_exit_code_is_zero_without_errors_and_one_with_errors() -> None:
    healthy = doctor.DoctorReport(
        version="1.0.0",
        checks=[("core", doctor.CheckResult("status_file", "ok", "ok"))],
        self_heal_log=[],
    )
    unhealthy = doctor.DoctorReport(
        version="1.0.0",
        checks=[("core", doctor.CheckResult("status_file", "error", "error: broken"))],
        self_heal_log=[],
    )

    assert doctor.exit_code(healthy) == 0
    assert doctor.exit_code(unhealthy) == 1

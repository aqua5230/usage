from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

import codex_loader
import doctor
import setup_hook


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

    assert "usage v" in output
    assert "hook state:        none" in output
    assert "status file:" in output
    assert "self-heal log (last 5):\n  none" in output


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

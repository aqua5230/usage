# SPDX-License-Identifier: AGPL-3.0-only
"""Upstream checks use synthetic files exclusively, including all installed hooks."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from scripts import check_upstream as check


def write_json(path: Path, value: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return path


def write_rows(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    return path


def now() -> str:
    return datetime.now(UTC).isoformat()


@pytest.fixture(autouse=True)
def isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(check, "CLAUDE_STATUS_PATH", tmp_path / "claude/usage-status.json")
    monkeypatch.setattr(check, "CLAUDE_PROJECTS_DIR", tmp_path / "claude/projects")
    monkeypatch.setattr(check.codex_loader, "SESSIONS_DIR", tmp_path / "codex/sessions")
    for constant, filename in (
        ("STATE_DB", "state_5.sqlite"),
        ("LOGS_DB", "logs_2.sqlite"),
        ("THREAD_HISTORY_DB", "thread_history_1.sqlite"),
    ):
        monkeypatch.setattr(check.codex_loader, constant, tmp_path / "codex" / filename)
    monkeypatch.setattr(check.agy_loader, "AGY_SESSIONS_DIR", tmp_path / "agy/conversations")
    monkeypatch.setattr(
        check.agy_quota_probe, "CACHE_PATH", tmp_path / "usage/agy_quota_cache.json"
    )
    for module in (check.grok_loader, check.grok_quota_probe):
        monkeypatch.setattr(module, "GROK_HOME", tmp_path / "grok")
        monkeypatch.setattr(module, "GROK_LOG_PATH", tmp_path / "grok/logs/unified.jsonl")
    for module, names in (
        (
            check.setup_hook,
            ("HOOK_TARGET", "FORWARDER_TARGET", "AGY_HOOK_TARGET", "GROK_HOOK_TARGET"),
        ),
        (
            check.session_hooks,
            (
                "RESUME_HOOK_TARGET",
                "TERSE_HOOK_TARGET",
                "CODEX_TERSE_HOOK_TARGET",
                "TERSE_REMINDER_HOOK_TARGET",
            ),
        ),
    ):
        for name in names:
            monkeypatch.setattr(module, name, tmp_path / "hooks" / name)

    def no_network(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("unexpected network request")

    monkeypatch.setattr(check.service_status.urllib.request, "urlopen", no_network)
    monkeypatch.setattr(check.agy_quota_probe, "probe_quota", no_network)


@pytest.fixture
def status() -> dict[str, Any]:
    return {
        "_received_at_ts": time.time(),
        "workspace": {"project_dir": "/tmp/project"},
        "model": {"display_name": "Claude"},
        "cost": {"total_duration_ms": 10},
        "context_window": {"used_percentage": 20, "context_window_size": 1000000},
        "prompt_cache": {
            "caching_observed": True,
            "hit_ratio": 0.9,
            "miss_causes": {},
            "last_miss_cause": None,
        },
        "rate_limits": {
            slot: {"used_percentage": 20, "resets_at": time.time() + 3600}
            for slot in ("five_hour", "seven_day")
        },
    }


def test_claude_statusline_ok(status: dict[str, Any]) -> None:
    write_json(check.CLAUDE_STATUS_PATH, status)
    assert check.check_claude_statusline()[0] == "OK"


@pytest.mark.parametrize("location", ["miss_causes", "last_miss_cause"])
def test_unknown_miss_cause(status: dict[str, Any], location: str) -> None:
    status["prompt_cache"][location] = (
        {"upstream_changed": 1} if location == "miss_causes" else {"causes": ["upstream_changed"]}
    )
    write_json(check.CLAUDE_STATUS_PATH, status)
    state, detail = check.check_claude_statusline()
    assert state == "NEW" and "upstream_changed" in detail


@pytest.mark.parametrize("field", ["rate_limits", "context_window", "prompt_cache"])
def test_statusline_missing_structure(status: dict[str, Any], field: str) -> None:
    del status[field]
    write_json(check.CLAUDE_STATUS_PATH, status)
    state, detail = check.check_claude_statusline()
    assert state == "BROKEN" and field in detail and str(check.CLAUDE_STATUS_PATH) in detail


def test_statusline_new_fields(status: dict[str, Any]) -> None:
    status["new_top"] = True
    status["rate_limits"]["new_slot"] = {}
    status["prompt_cache"]["new_metric"] = 1
    write_json(check.CLAUDE_STATUS_PATH, status)
    state, detail = check.check_claude_statusline()
    assert state == "NEW"
    assert all(key in detail for key in ("new_top", "new_slot", "new_metric"))


def test_statusline_changed_type(status: dict[str, Any]) -> None:
    status["rate_limits"]["five_hour"]["used_percentage"] = "20"
    write_json(check.CLAUDE_STATUS_PATH, status)
    assert check.check_claude_statusline()[0] == "BROKEN"


def test_received_at_stale(status: dict[str, Any]) -> None:
    status["_received_at_ts"] -= check.MAX_AGE + 10
    write_json(check.CLAUDE_STATUS_PATH, status)
    assert check.check_claude_statusline()[0] == "NO_DATA"


@pytest.fixture
def assistant() -> dict[str, Any]:
    return {
        "type": "assistant",
        "timestamp": now(),
        "message": {"model": "claude-sonnet", "usage": {key: 10 for key in check.CLAUDE_TOKENS}},
    }


def test_claude_transcript_ok(assistant: dict[str, Any]) -> None:
    write_rows(check.CLAUDE_PROJECTS_DIR / "project/session.jsonl", [assistant])
    assert check.check_claude_transcript()[0] == "OK"


@pytest.mark.parametrize("change,expected", [("missing", "BROKEN"), ("new", "NEW")])
def test_claude_transcript_changed(assistant: dict[str, Any], change: str, expected: str) -> None:
    if change == "missing":
        del assistant["message"]["usage"]["input_tokens"]
    else:
        assistant["message"]["usage"]["new_tokens"] = 1
    path = write_rows(check.CLAUDE_PROJECTS_DIR / "project/session.jsonl", [assistant])
    state, detail = check.check_claude_transcript()
    assert state == expected and str(path) in detail


def test_claude_partial_rows_allowed(assistant: dict[str, Any]) -> None:
    write_rows(
        check.CLAUDE_PROJECTS_DIR / "project/session.jsonl",
        [assistant, {"type": "assistant", "message": {}}],
    )
    assert check.check_claude_transcript()[0] == "OK"


@pytest.fixture
def codex_event() -> dict[str, Any]:
    return {
        "type": "event_msg",
        "timestamp": now(),
        "payload": {
            "type": "token_count",
            "info": {"total_token_usage": {key: 10 for key in check.CODEX_TOKENS}},
            "rate_limits": {
                "limit_id": "codex",
                "primary": {
                    "used_percent": 10,
                    "window_minutes": 300,
                    "resets_at": time.time() + 1000,
                },
                "secondary": None,
                "credits": None,
            },
        },
    }


def test_codex_sessions_ok(codex_event: dict[str, Any]) -> None:
    write_rows(check.codex_loader.SESSIONS_DIR / "2026/session.jsonl", [codex_event])
    assert check.check_codex_sessions()[0] == "OK"


@pytest.mark.parametrize("field", ["rate_limits", "info"])
def test_codex_missing(codex_event: dict[str, Any], field: str) -> None:
    del codex_event["payload"][field]
    write_rows(check.codex_loader.SESSIONS_DIR / "session.jsonl", [codex_event])
    state, detail = check.check_codex_sessions()
    assert state == "BROKEN"
    assert ("rate_limits" if field == "rate_limits" else "total_token_usage") in detail


@pytest.mark.parametrize("location", ["limits", "window", "usage"])
def test_codex_new(codex_event: dict[str, Any], location: str) -> None:
    payload = codex_event["payload"]
    target = {
        "limits": payload["rate_limits"],
        "window": payload["rate_limits"]["primary"],
        "usage": payload["info"]["total_token_usage"],
    }[location]
    target["upstream_new"] = 1
    write_rows(check.codex_loader.SESSIONS_DIR / "session.jsonl", [codex_event])
    state, detail = check.check_codex_sessions()
    assert state == "NEW" and "upstream_new" in detail


def test_codex_window_type(codex_event: dict[str, Any]) -> None:
    codex_event["payload"]["rate_limits"]["primary"]["window_minutes"] = []
    write_rows(check.codex_loader.SESSIONS_DIR / "session.jsonl", [codex_event])
    assert check.check_codex_sessions()[0] == "BROKEN"


def make_db(path: Path, schema: dict[str, set[str]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        for table, columns in schema.items():
            conn.execute(f'CREATE TABLE "{table}" ({", ".join(sorted(columns))})')
    return path


@pytest.fixture
def codex_dbs() -> None:
    for constant, schema in check.CODEX_SCHEMAS.items():
        make_db(getattr(check.codex_loader, constant), schema)


def test_codex_sqlite_ok(codex_dbs: None) -> None:
    assert check.check_codex_sqlite()[0] == "OK"


def test_codex_sqlite_new_version(codex_dbs: None) -> None:
    check.codex_loader.STATE_DB.with_name("state_6.sqlite").touch()
    state, detail = check.check_codex_sqlite()
    assert state == "NEW" and "state_6.sqlite" in detail


def test_codex_sqlite_missing_file(codex_dbs: None) -> None:
    check.codex_loader.LOGS_DB.unlink()
    state, detail = check.check_codex_sqlite()
    assert state == "BROKEN" and "logs_2.sqlite" in detail


def test_codex_sqlite_missing_column(codex_dbs: None) -> None:
    with sqlite3.connect(check.codex_loader.STATE_DB) as conn:
        conn.execute("ALTER TABLE threads DROP COLUMN model")
    state, detail = check.check_codex_sqlite()
    assert state == "BROKEN" and "threads.model" in detail


def test_agy_conversations_ok() -> None:
    make_db(check.agy_loader.AGY_SESSIONS_DIR / "session.db", check.AGY_SCHEMA)
    assert check.check_agy_conversations()[0] == "OK"


def test_agy_conversations_missing_table() -> None:
    path = make_db(
        check.agy_loader.AGY_SESSIONS_DIR / "session.db", {"gen_metadata": {"idx", "data"}}
    )
    state, detail = check.check_agy_conversations()
    assert state == "BROKEN" and "steps.metadata" in detail and str(path) in detail


def test_sqlite_opens_readonly(monkeypatch: pytest.MonkeyPatch) -> None:
    path = make_db(check.agy_loader.AGY_SESSIONS_DIR / "session.db", check.AGY_SCHEMA)
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
    before = path.read_bytes()
    original = sqlite3.connect
    uris = []

    def connect(database: str, **kwargs: Any) -> sqlite3.Connection:
        uris.append(database)
        assert "mode=ro" in database and kwargs["uri"] is True
        return original(database, **kwargs)

    monkeypatch.setattr(check.sqlite3, "connect", connect)
    assert check.check_agy_conversations()[0] == "OK"
    assert uris and before == path.read_bytes()


@pytest.fixture
def quota() -> dict[str, Any]:
    return {
        "fetched_at": now(),
        "groups": [{"weekly": {"remaining_percent": 40}, "five_hour": {"remaining_percent": 80}}],
    }


def test_agy_quota_ok(quota: dict[str, Any]) -> None:
    write_json(check.agy_quota_probe.CACHE_PATH, quota)
    assert check.check_agy_quota_cache()[0] == "OK"


@pytest.mark.parametrize("missing", ["groups", "weekly", "five_hour"])
def test_agy_quota_missing(quota: dict[str, Any], missing: str) -> None:
    if missing == "groups":
        quota["groups"] = []
    else:
        del quota["groups"][0][missing]
    write_json(check.agy_quota_probe.CACHE_PATH, quota)
    state, detail = check.check_agy_quota_cache()
    assert state == "BROKEN" and missing in detail


def test_quota_stale_even_with_recent_mtime(quota: dict[str, Any]) -> None:
    quota["fetched_at"] = (datetime.now(UTC) - timedelta(days=8)).isoformat()
    quota["groups"] = []
    write_json(check.agy_quota_probe.CACHE_PATH, quota)
    assert check.check_agy_quota_cache()[0] == "NO_DATA"


@pytest.fixture
def grok_rows() -> list[dict[str, Any]]:
    return [
        {
            "msg": "shell.turn.inference_done",
            "ts": now(),
            "sid": "session",
            "ctx": {
                "loop_index": 1,
                "prompt_tokens": 10,
                "cached_prompt_tokens": 2,
                "completion_tokens": 3,
            },
        },
        {
            "msg": "billing: fetched credits config",
            "ts": now(),
            "ctx": {"config": {"currentPeriod": {"end": now()}}},
        },
    ]


def test_grok_ok(grok_rows: list[dict[str, Any]]) -> None:
    write_rows(check.grok_loader.GROK_LOG_PATH, grok_rows)
    assert check.check_grok()[0] == "OK"


@pytest.mark.parametrize("missing", ["event", "field"])
def test_grok_broken(grok_rows: list[dict[str, Any]], missing: str) -> None:
    if missing == "event":
        grok_rows.pop()
    else:
        del grok_rows[0]["ctx"]["prompt_tokens"]
    write_rows(check.grok_loader.GROK_LOG_PATH, grok_rows)
    assert check.check_grok()[0] == "BROKEN"


def test_grok_stale_events(grok_rows: list[dict[str, Any]]) -> None:
    for row in grok_rows:
        row["ts"] = (datetime.now(UTC) - timedelta(days=8)).isoformat()
    write_rows(check.grok_loader.GROK_LOG_PATH, grok_rows)
    assert check.check_grok()[0] == "NO_DATA"


@pytest.mark.parametrize(
    "change,expected",
    [("same", "OK"), ("version", "BROKEN"), ("content", "BROKEN"), ("absent", "NO_DATA")],
)
def test_hook_copies(tmp_path: Path, change: str, expected: str) -> None:
    source, target = tmp_path / "source.py", tmp_path / "installed.py"
    source.write_text('__version__ = "1.0"\nprint("new")\n')
    if change != "absent":
        text = source.read_text()
        if change == "version":
            text = text.replace("1.0", "0.9")
        if change == "content":
            text = text.replace("new", "old")
        target.write_text(text)
    state, detail = check.check_hook_copies(source, target)
    assert state == expected
    if change == "content":
        assert "never update" in detail and "installer version constant" in detail
    if change == "version":
        assert "rebuild and reinstall" in detail


def test_service_status_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        check.service_status,
        "_fetch_status",
        lambda config: {"components": [{"name": name} for name in config.component_names]},
    )
    assert check.check_service_status()[0] == "OK"


def test_service_status_missing_component(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(check.service_status, "_fetch_status", lambda config: {"components": []})
    state, detail = check.check_service_status()
    assert state == "BROKEN" and "Claude Code" in detail and "Codex API" in detail


def test_service_offline() -> None:
    assert check.check_service_status(True)[0] == "NO_DATA"


@pytest.mark.parametrize(
    "name",
    [
        "claude_statusline",
        "claude_transcript",
        "codex_sessions",
        "agy_conversations",
        "agy_quota_cache",
        "grok",
    ],
)
def test_no_local_data(name: str) -> None:
    assert getattr(check, f"check_{name}")()[0] == "NO_DATA"


def test_stale_transcript(assistant: dict[str, Any]) -> None:
    path = write_rows(check.CLAUDE_PROJECTS_DIR / "project/session.jsonl", [assistant])
    old = time.time() - check.MAX_AGE - 10
    os.utime(path, (old, old))
    assert check.check_claude_transcript()[0] == "NO_DATA"


def test_invalid_json_is_reported() -> None:
    path = check.CLAUDE_STATUS_PATH
    path.parent.mkdir(parents=True)
    path.write_text("{invalid")
    state, detail = check._run(check.check_claude_statusline)
    assert state == "BROKEN" and str(path) in detail


@pytest.mark.parametrize("status,exit_code", [("OK", 0), ("NEW", 0), ("BROKEN", 1)])
def test_main_exit_and_report(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], status: str, exit_code: int
) -> None:
    monkeypatch.setattr(check, "check_codex_sqlite", lambda: (status, "sample"))
    monkeypatch.setattr(check.sys, "argv", ["check_upstream.py", "--offline"])
    assert check.main() == exit_code
    output = capsys.readouterr().out.splitlines()
    assert len(output) == 17
    assert f"{status} codex_sqlite — sample" in output
    assert output[-1].startswith("TOTAL OK=")


def test_main_readonly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: dict[str, Any],
    quota: dict[str, Any],
    assistant: dict[str, Any],
    codex_event: dict[str, Any],
    codex_dbs: None,
    grok_rows: list[dict[str, Any]],
) -> None:
    write_json(check.CLAUDE_STATUS_PATH, status)
    write_json(check.agy_quota_probe.CACHE_PATH, quota)
    write_rows(check.CLAUDE_PROJECTS_DIR / "project/session.jsonl", [assistant])
    write_rows(check.codex_loader.SESSIONS_DIR / "session.jsonl", [codex_event])
    write_rows(check.grok_loader.GROK_LOG_PATH, grok_rows)
    make_db(check.agy_loader.AGY_SESSIONS_DIR / "session.db", check.AGY_SCHEMA)
    before = {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    monkeypatch.setattr(check.sys, "argv", ["check_upstream.py", "--offline"])
    assert check.main() == 0
    assert before == {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}


@pytest.mark.parametrize("changed", [False, True])
def test_unversioned_hooks(tmp_path: Path, changed: bool) -> None:
    source, target = tmp_path / "usage_statusline_agy.py", tmp_path / "installed.py"
    source.write_text('print("new")\n')
    target.write_text('print("old")\n' if changed else source.read_text())
    assert check.check_hook_copies(source, target)[0] == ("BROKEN" if changed else "OK")


def test_known_miss_causes_from_translations(status: dict[str, Any]) -> None:
    reasons = [
        key.removeprefix("miss_")
        for key in check.usage_statusline.STATUSLINE_TRANSLATIONS["en"]
        if key.startswith("miss_")
    ] + ["unknown"]
    status["prompt_cache"]["miss_causes"] = dict.fromkeys(reasons, 1)
    status["prompt_cache"]["last_miss_cause"] = {"causes": reasons}
    write_json(check.CLAUDE_STATUS_PATH, status)
    assert check.check_claude_statusline()[0] == "OK"


def test_grok_changed_token_type(grok_rows: list[dict[str, Any]]) -> None:
    grok_rows[0]["ctx"]["prompt_tokens"] = "bad"
    write_rows(check.grok_loader.GROK_LOG_PATH, grok_rows)
    state, detail = check.check_grok()
    assert state == "BROKEN" and "prompt_tokens" in detail


def test_sqlite_sees_active_wal() -> None:
    path = check.agy_loader.AGY_SESSIONS_DIR / "session.db"
    path.parent.mkdir(parents=True)
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA wal_autocheckpoint=0")
        for table, columns in check.AGY_SCHEMA.items():
            conn.execute(f'CREATE TABLE "{table}" ({", ".join(sorted(columns))})')
        conn.commit()
        assert Path(str(path) + "-wal").stat().st_size > 0
        assert check.check_agy_conversations()[0] == "OK"


def test_all_sqlite_stale(codex_dbs: None) -> None:
    old = time.time() - check.MAX_AGE - 10
    for constant in check.CODEX_SCHEMAS:
        os.utime(getattr(check.codex_loader, constant), (old, old))
    assert check.check_codex_sqlite()[0] == "NO_DATA"


def test_service_failed_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(check.service_status, "_fetch_status", lambda config: None)
    assert check.check_service_status()[0] == "BROKEN"


def test_sqlite_changed_column_in_wal() -> None:
    path = make_db(check.agy_loader.AGY_SESSIONS_DIR / "session.db", check.AGY_SCHEMA)
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("ALTER TABLE gen_metadata DROP COLUMN data")
        conn.commit()
        state, detail = check.check_agy_conversations()
        assert state == "BROKEN" and "gen_metadata.data" in detail


def test_sqlite_uncommitted_schema_ignored() -> None:
    path = make_db(check.agy_loader.AGY_SESSIONS_DIR / "session.db", check.AGY_SCHEMA)
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("BEGIN")
        conn.execute("ALTER TABLE gen_metadata DROP COLUMN data")
        assert check.check_agy_conversations()[0] == "OK"
        conn.rollback()


def test_sqlite_recent_wal_overrides_old_database(codex_dbs: None) -> None:
    path = check.codex_loader.STATE_DB
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("INSERT INTO threads(id, model, cwd) VALUES ('s', 'gpt', '/tmp')")
        conn.commit()
        old = time.time() - check.MAX_AGE - 10
        os.utime(path, (old, old))
        state, detail = check.check_codex_sqlite()
        assert state == "OK" and str(path) in detail and "stale:" not in detail

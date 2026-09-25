from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from adapters import rate_limits
from adapters.types import UsageEntry
from analyzer import dispatch_ledger as ledger
from loaders import agy_loader, agy_quota_probe, cache_quarantine, codex_loader
from ui import html_report
from ui.report_ledger import render_ledger

NOW = datetime(2026, 9, 26, 12, tzinfo=UTC)
A = "11111111-1111-1111-1111-111111111111"
B = "22222222-2222-2222-2222-222222222222"
TITLES = {A: "Task A", B: "Task B"}


@pytest.fixture
def paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path]:
    claude = tmp_path / ".claude"
    codex = tmp_path / ".codex" / "sessions"
    agy = tmp_path / ".gemini" / "conversations"
    monkeypatch.setattr(ledger, "claude_config_dirs", lambda: [claude])
    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", codex)
    monkeypatch.setattr(agy_loader, "AGY_SESSIONS_DIR", agy)
    monkeypatch.setattr(agy_quota_probe, "CACHE_PATH", tmp_path / ".usage" / "agy-quota.json")
    monkeypatch.setattr(cache_quarantine, "QUARANTINE_DIR", tmp_path / ".usage" / "quarantine")
    ledger._file_cache.clear()
    ledger._codex_cache.clear()
    return claude, codex, agy


def _claude(
    root: Path, session: str, command: str, cwd: str = "/work/a", when: datetime = NOW
) -> None:
    path = root / "projects" / "project" / f"{session}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    block = {"type": "tool_use", "name": "Bash", "input": {"command": command}}
    lines = [
        {"type": "ai-title", "aiTitle": TITLES.get(session, ""), "sessionId": session},
        {
            "type": "assistant",
            "timestamp": when.isoformat(),
            "cwd": cwd,
            "message": {"content": [block]},
        },
    ]
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n")
    os.utime(path, (NOW.timestamp(), NOW.timestamp()))


def _codex(
    root: Path, session: str, cwd: str = "/work/a", when: datetime = NOW, message: str = "task"
) -> None:
    path = root / f"{when:%Y}" / f"{when:%m}" / f"{when:%d}" / f"rollout-{session}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        {
            "type": "session_meta",
            "timestamp": when.isoformat(),
            "payload": {"originator": "codex_exec", "cwd": cwd, "id": session},
        },
        {"type": "event_msg", "payload": {"type": "user_message", "message": message}},
    ]
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n")


def _agy(root: Path, session: str, cwd: str = "/work/a") -> None:
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{session}.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE steps (idx INTEGER, step_payload BLOB)")
        connection.execute("INSERT INTO steps VALUES (0, ?)", (json.dumps({"Cwd": cwd}).encode(),))
    os.utime(path, (NOW.timestamp(), NOW.timestamp()))


def test_foreground_dispatch_matches_real_fake_files(paths: tuple[Path, Path, Path]) -> None:
    claude, codex, _ = paths
    _claude(claude, A, "codex exec 'do work'")
    _codex(codex, "child")
    result = ledger.build_ledger({}, NOW)
    assert len(result["rows"]) == 1
    assert result["rows"][0]["title"] == "Task A"
    assert result["rows"][0]["dispatch_count"] == 1


def test_claude_file_cache_reuses_unchanged_file(paths: tuple[Path, Path, Path]) -> None:
    claude, _, _ = paths
    _claude(claude, A, "codex exec task")
    path = claude / "projects" / "project" / f"{A}.jsonl"
    first = ledger._read_dispatches(path)
    assert ledger._read_dispatches(path) is first
    _claude(claude, A, "codex exec task & codex exec second")
    assert len(ledger._read_dispatches(path)) == 2
    assert len(ledger._file_cache) == 1


def test_background_command_with_hidden_brief_matches_by_time(
    paths: tuple[Path, Path, Path],
) -> None:
    claude, codex, _ = paths
    _claude(claude, A, 'codex exec "$(cat brief.md)" &')
    _codex(codex, "child", message="the brief contents are absent from command")
    assert ledger.build_ledger({}, NOW)["rows"][0]["title"] == "Task A"


def test_simultaneous_different_cwd_matches_each_owner() -> None:
    dispatches = [
        ledger.Dispatch(NOW, A, "/work/a", "codex exec a", "codex"),
        ledger.Dispatch(NOW, B, "/work/b", "codex exec b", "codex"),
    ]
    assert (
        ledger.match_candidate(ledger.Candidate("codex", "one", NOW, "/work/a"), dispatches, {A, B})
        == A
    )
    assert (
        ledger.match_candidate(ledger.Candidate("codex", "two", NOW, "/work/b"), dispatches, {A, B})
        == B
    )


def test_simultaneous_same_cwd_remains_unowned() -> None:
    dispatches = [ledger.Dispatch(NOW, owner, "/work/a", "codex exec", "codex") for owner in (A, B)]
    assert (
        ledger.match_candidate(ledger.Candidate("codex", "one", NOW, "/work/a"), dispatches, {A, B})
        is None
    )


def test_one_session_three_parallel_dispatches(paths: tuple[Path, Path, Path]) -> None:
    claude, codex, _ = paths
    _claude(claude, A, "codex exec one & codex exec two & codex exec three")
    for n in range(3):
        _codex(codex, f"child-{n}")
    assert ledger.build_ledger({}, NOW)["rows"][0]["dispatch_count"] == 3


def test_undispatched_codex_counts_unowned(paths: tuple[Path, Path, Path]) -> None:
    claude, codex, _ = paths
    _claude(claude, A, "codex exec task")
    _codex(codex, "owned")
    _codex(codex, "outside", when=NOW - timedelta(hours=1))
    assert ledger.build_ledger({}, NOW)["unowned_codex"] == 1


def test_uuid_direct_evidence_overrides_time_window() -> None:
    dispatches = [ledger.Dispatch(NOW, B, "/work/b", "codex exec", "codex")]
    candidate = ledger.Candidate("codex", "child", NOW, "/work/b", f"For Claude session {A}")
    assert ledger.match_candidate(candidate, dispatches, {A, B}) == A


def test_agy_readonly_candidate_and_match(paths: tuple[Path, Path, Path]) -> None:
    claude, _, agy = paths
    _claude(claude, A, "agy -p task")
    _agy(agy, "agy-child")
    result = ledger.build_ledger({}, NOW)
    assert len(result["rows"]) == 1
    assert result["unowned_agy"] == 0


def _entry(when: datetime, session: str, tokens: int, cache_read: int = 0) -> UsageEntry:
    return UsageEntry(
        when, session, session, session, "model", tokens, 0, 0, cache_read, None, "project", "codex"
    )


def test_missing_quota_is_none() -> None:
    assert ledger.estimate_sessions([_entry(NOW, "s", 10)], {}, NOW) == {}
    assert ledger.estimate_pct(10, 100, None, NOW) is None


def test_cross_period_counts_only_current_tokens() -> None:
    window = ledger.QuotaWindow(50, NOW + timedelta(days=1), timedelta(days=7))
    entries = [
        _entry(NOW - timedelta(days=7), "s", 900),
        _entry(NOW, "s", 100, 200),
        _entry(NOW, "other", 100),
    ]
    assert ledger.estimate_sessions(entries, {"codex": window}, NOW)[("codex", "s")] == 25


def test_agy_models_share_group_denominator() -> None:
    window = ledger.QuotaWindow(60, NOW + timedelta(days=1), timedelta(days=7))
    windows = {
        "antigravity:GEMINI MODELS": window,
        "antigravity-model:gemini flash": window,
        "antigravity-model:gemini pro": window,
    }
    entries = [
        _entry(NOW, "flash", 100),
        _entry(NOW, "pro", 200),
    ]
    entries[0].agent_id = entries[1].agent_id = "antigravity"
    entries[0].model = "gemini-3-flash-preview"
    entries[1].model = "gemini-3.1-pro"
    estimates = ledger.estimate_sessions(entries, windows, NOW)
    assert estimates[("antigravity", "flash")] == pytest.approx(20)
    assert estimates[("antigravity", "pro")] == pytest.approx(40)


def test_agy_quota_uses_cache_only(
    paths: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rate_limits, "load_rate_limits", lambda: None)
    monkeypatch.setattr(codex_loader, "load_rate_limits", lambda: None)
    monkeypatch.setattr(agy_quota_probe, "probe_quota", lambda: pytest.fail("probe called"))
    monkeypatch.setattr(
        agy_quota_probe, "load_quota", lambda: pytest.fail("load called"), raising=False
    )
    window = agy_quota_probe.AgyQuotaWindow(40, None, 120)
    group = agy_quota_probe.AgyQuotaGroup("GEMINI MODELS", ["Gemini Flash"], window, window)
    cached = agy_quota_probe.AgyQuotaResult([group], NOW.isoformat())
    monkeypatch.setattr(agy_quota_probe, "_read_cache", lambda: cached)
    result = ledger.load_windows()
    assert result["antigravity:GEMINI MODELS"].used_pct == 60
    assert result["antigravity:GEMINI MODELS"].resets_at == NOW + timedelta(hours=2)


def test_render_ledger_formats_values_and_escapes_title() -> None:
    row: ledger.LedgerRow = {
        "date": "2026-09-26",
        "project": "work",
        "title": "<script>",
        "dispatch_count": 2,
        "claude_pct": 0.4,
        "codex_pct": 3,
        "agy_pct": None,
        "total_pct": 3.4,
    }
    rendered = render_ledger(
        {"dispatch_ledger": {"rows": [row], "unowned_codex": 1, "unowned_agy": 0}}, "zh-TW"
    )
    assert "約 0.4%" in rendered and "約 3%" in rendered
    assert "&lt;script&gt;" in rendered and "<script>" not in rendered
    assert "1 個 Codex" in rendered


def test_top_session_renders_weekly_quota_after_tokens() -> None:
    row = {
        "start_time": "2026-09-26 12:00",
        "project": "work",
        "model": "gpt-test",
        "duration_min": 1,
        "tokens": 100,
        "weekly_quota_pct": 0.4,
        "cost": 0.01,
    }
    rendered = html_report._render_session_section({"top_sessions": [row]}, "zh-TW")
    assert rendered.index("約佔週額度") < rendered.index("花費")
    assert rendered.index("100") < rendered.index("約 0.4%") < rendered.index("$0.0100")


def test_no_dispatch_omits_entire_html_section(paths: tuple[Path, Path, Path]) -> None:
    data = {"dispatch_ledger": ledger.build_ledger({}, NOW)}
    assert render_ledger(data, "zh-TW") == ""
    from tests.test_html_report_snapshot import _full_report_data

    report = _full_report_data()
    report.update(data)
    assert "dispatch-ledger-section" not in html_report.generate_html(report, language="zh-TW")


@pytest.mark.parametrize(
    ("session", "total", "used", "reset_delta", "expected"),
    [
        (10, 0, 50, 1, None),
        (10, 100, 0, 1, 0),
        (10, 100, 100, 1, 10),
        (0, 100, 50, 1, 0),
        (10, 100, 50, -1, None),
    ],
)
def test_estimate_boundary_values(
    session: int, total: int, used: float, reset_delta: int, expected: float | None
) -> None:
    window = ledger.QuotaWindow(used, NOW + timedelta(days=reset_delta), timedelta(days=7))
    assert ledger.estimate_pct(session, total, window, NOW) == expected


def test_session_title_falls_back_to_first_user_text(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    path.write_text(
        json.dumps({"type": "user", "message": {"content": "  幫我整理派工帳本  "}}) + "\n"
    )
    assert ledger._session_title(path) == "幫我整理派工帳本"
    assert ledger._session_title(tmp_path / "missing.jsonl") == ""


def test_ledger_escapes_user_text_and_uses_language_separator() -> None:
    row = {
        "date": "2026-09-26",
        "project": "client<portal>",
        "title": "<img src=x onerror=1>",
        "dispatch_count": 1,
        "claude_pct": None,
        "codex_pct": 2.0,
        "agy_pct": None,
        "total_pct": 2.0,
    }
    html = render_ledger(
        {"dispatch_ledger": {"rows": [row], "unowned_codex": 3, "unowned_agy": 4}}, "en"
    )
    assert "<img" not in html
    assert "&lt;img src=x onerror=1&gt;" in html
    assert "client&lt;portal&gt;" in html
    assert "3 Codex, 4 Antigravity" in html

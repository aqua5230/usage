from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import replace
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
    monkeypatch.setattr(ledger, "resolve_project_name", lambda cwd: "test-project")
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
    result = ledger.build_ledger({("codex", "child", "codex"): 1}, NOW)
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
    assert (
        ledger.build_ledger({("codex", "child", "codex"): 1}, NOW)["rows"][0]["title"] == "Task A"
    )


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
    assert ledger.estimate_sessions([_entry(NOW, "s", 10)], {}, NOW) == ({}, set())
    assert ledger.estimate_pct(10, 100, None, NOW) is None


def test_cross_period_counts_only_current_tokens() -> None:
    window = ledger.QuotaWindow(50, NOW + timedelta(days=1), timedelta(days=7))
    entries = [
        _entry(NOW - timedelta(days=7), "s", 900),
        _entry(NOW, "s", 100, 200),
        _entry(NOW, "other", 100),
    ]
    assert ledger.estimate_sessions(entries, {"codex": window}, NOW) == (
        {("codex", "s", "codex"): 25, ("codex", "other", "codex"): 25},
        set(),
    )


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
    estimates, resets = ledger.estimate_sessions(entries, windows, NOW)
    assert estimates[("antigravity", "flash", "antigravity:GEMINI MODELS")] == pytest.approx(20)
    assert estimates[("antigravity", "pro", "antigravity:GEMINI MODELS")] == pytest.approx(40)


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


def test_agy_quota_skips_group_without_reported_weekly(
    paths: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rate_limits, "load_rate_limits", lambda: None)
    monkeypatch.setattr(codex_loader, "load_rate_limits", lambda: None)
    five_hour = agy_quota_probe.AgyQuotaWindow(99.5, None, 100)
    group = agy_quota_probe.AgyQuotaGroup("GEMINI MODELS", ["Gemini Flash"], None, five_hour)
    cached = agy_quota_probe.AgyQuotaResult([group], NOW.isoformat())
    monkeypatch.setattr(agy_quota_probe, "_read_cache", lambda: cached)
    assert "antigravity:GEMINI MODELS" not in ledger.load_windows()


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
    assert rendered.index("約佔週額度") < rendered.index("API 等值")
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


def test_muse_weekly_session_estimate_reads_only_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    from loaders import muse_quota_probe

    monkeypatch.setattr(rate_limits, "load_rate_limits", lambda: None)
    monkeypatch.setattr(codex_loader, "load_rate_limits", lambda: None)
    monkeypatch.setattr(agy_quota_probe, "_read_cache", lambda: None)
    reset = (NOW + timedelta(days=1)).timestamp()
    muse_quota_probe.CACHE_PATH.write_text(
        json.dumps(
            {
                "checked_at": NOW.timestamp(),
                "window": {"used_percent": 80, "resets_at": NOW.timestamp() + 3600},
                "weekly": {"used_percent": 60, "resets_at": reset},
            }
        )
    )
    monkeypatch.setattr(
        muse_quota_probe, "load_quota_snapshot", lambda: pytest.fail("report must not probe Muse")
    )
    windows = ledger.load_windows()
    assert windows["muse"].used_pct == 60
    entries = [
        replace(_entry(NOW, "one", 10), agent_id="muse"),
        replace(_entry(NOW, "two", 20), agent_id="muse"),
    ]
    estimates, resets = ledger.estimate_sessions(entries, windows, NOW)
    assert estimates[("muse", "one", "muse")] == 20
    assert estimates[("muse", "two", "muse")] == 40
    assert ledger.estimate_sessions(entries, windows, NOW + timedelta(days=2)) == ({}, set())


def test_agy_groups_remain_separate_across_children(paths: tuple[Path, Path, Path]) -> None:
    claude, _, agy = paths
    _claude(claude, A, "agy -p one & agy -p two")
    for child in ("one", "two"):
        _agy(agy, child)
    gemini = ledger.QuotaWindow(60, NOW + timedelta(days=1), timedelta(days=7))
    other = ledger.QuotaWindow(40, NOW + timedelta(days=2), timedelta(days=7))
    windows = {
        "antigravity:GEMINI MODELS": gemini,
        "antigravity-model:gemini": gemini,
        "antigravity:CLAUDE AND GPT MODELS": other,
        "antigravity-model:claude": other,
    }
    entries = [
        replace(_entry(NOW, child, tokens), agent_id="antigravity", model=model)
        for child, model, tokens in (
            ("one", "gemini", 10),
            ("one", "claude", 10),
            ("two", "gemini", 20),
        )
    ]
    estimates, resets = ledger.estimate_sessions(entries, windows, NOW)
    assert estimates[("antigravity", "one", "antigravity:GEMINI MODELS")] == 20
    assert estimates[("antigravity", "one", "antigravity:CLAUDE AND GPT MODELS")] == 40
    data = ledger.build_ledger(estimates, NOW, resets)
    assert data["rows"][0]["agy_groups"] == {"GEMINI MODELS": 60, "CLAUDE AND GPT MODELS": 40}
    assert data["rows"][0]["total_pct"] == 100
    rendered = render_ledger({"dispatch_ledger": data}, "zh-TW")
    assert rendered.index("Gemini") < rendered.index("Claude/GPT")
    assert "約 40%" in rendered and "約 60%" in rendered


@pytest.mark.parametrize(
    ("lang", "label"),
    [
        ("zh-TW", "最近 7 天的派工都在額度重置前，算在上週。"),
        (
            "en",
            "All dispatched work in the last 7 days came before the quota reset, "
            "so it counts toward last week.",
        ),
    ],
)
@pytest.mark.parametrize("agent", ["codex", "claude-code", "antigravity"])
def test_pre_window_usage_renders_reset(
    paths: tuple[Path, Path, Path], agent: str, lang: str, label: str
) -> None:
    claude, codex, agy = paths
    is_agy = agent == "antigravity"
    _claude(claude, A, "agy -p task" if is_agy else "codex exec task")
    if is_agy:
        _agy(agy, "child")
    else:
        _codex(codex, "child")
    window = ledger.QuotaWindow(10, NOW + timedelta(days=6), timedelta(days=7))
    group = "antigravity:GEMINI MODELS" if is_agy else agent
    windows = {group: window}
    if is_agy:
        windows["antigravity-model:gemini"] = window
    session = A if agent == "claude-code" else "child"
    entry = replace(_entry(NOW - timedelta(days=2), session, 10), agent_id=agent, model="gemini")
    estimates, resets = ledger.estimate_sessions([entry], windows, NOW)
    assert not estimates
    assert resets == {(agent, session, group)}
    data = ledger.build_ledger(estimates, NOW, resets)
    row = data["rows"][0]
    tool = {"claude-code": "claude", "codex": "codex", "antigravity": "agy"}[agent]
    assert row.get(f"{tool}_reset") is True
    rendered = render_ledger({"dispatch_ledger": data}, lang)
    if agent == "codex":
        assert label in rendered
        assert "Codex</h3>" in rendered
        assert "Task A" not in rendered
    else:
        assert rendered == ""


def test_child_without_usage_or_window_stays_dash(paths: tuple[Path, Path, Path]) -> None:
    claude, codex, _ = paths
    _claude(claude, A, "codex exec task")
    _codex(codex, "child")
    estimates, resets = ledger.estimate_sessions([], {}, NOW)
    data = ledger.build_ledger(estimates, NOW, resets)
    assert data["rows"][0]["codex_pct"] is None
    assert data["rows"][0]["codex_reset"] is False
    assert render_ledger({"dispatch_ledger": data}, "zh-TW") == ""


def test_project_uses_resolver(
    paths: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    claude, codex, _ = paths
    cwd = "/work/election-desk/戰情室"
    _claude(claude, A, "codex exec task", cwd=cwd)
    _codex(codex, "child", cwd=cwd)
    seen: list[str] = []

    def resolve(value: str) -> str:
        seen.append(value)
        return "election-desk"

    monkeypatch.setattr(ledger, "resolve_project_name", resolve)
    data = ledger.build_ledger({}, NOW)
    assert seen == [cwd]
    assert data["rows"][0]["project"] == "election-desk"


def _row(index: int, codex: float | None = None, **groups: float) -> ledger.LedgerRow:
    return {
        "date": "2026-10-23",
        "project": "client<portal>",
        "title": f"<task {index}>",
        "dispatch_count": index,
        "claude_pct": 90,
        "codex_pct": codex,
        "agy_groups": groups,
        "claude_reset": False,
        "codex_reset": False,
        "agy_reset": False,
        "total_pct": 90 + (codex or 0) + sum(groups.values()),
    }


def test_blocks_sort_and_roll_up_each_quota_independently() -> None:
    rows = [_row(i, float(i), **{"GEMINI 4 ARGON": float(2 * (9 - i))}) for i in range(1, 9)]
    blocks = ledger.ledger_blocks(rows, {"codex": 40, "antigravity:GEMINI 4 ARGON": 50})
    assert [b["quota"] for b in blocks] == ["antigravity:GEMINI 4 ARGON", "codex"]
    assert [r["dispatch_count"] for r, _ in blocks[0]["conversations"]] == [1, 2, 3, 4, 5]
    assert [r["dispatch_count"] for r, _ in blocks[1]["conversations"]] == [8, 7, 6, 5, 4]
    assert blocks[0]["more_count"] == blocks[1]["more_count"] == 3
    assert blocks[0]["more_pct"] == 12
    assert blocks[1]["more_pct"] == 6
    assert blocks[1]["other_pct"] == 4
    rendered = render_ledger({"dispatch_ledger": {"rows": rows, "used_pct": {"codex": 40}}}, "en")
    assert rendered.count("3 more dispatching conversations") == 2
    assert '3 more dispatching conversations</span><span class="pct">about 6%</span>' in rendered
    assert '3 more dispatching conversations</span><span class="pct">about 12%</span>' in rendered
    assert rendered.index("Argon") < rendered.index("Codex ·")
    assert rendered.count('class="rank-line"') == 13


@pytest.mark.parametrize(
    ("used", "expected"), [(None, None), (10.49, None), (10.5, 0.5), (9, None), (15, 5)]
)
def test_other_is_current_used_minus_all_dispatches(
    used: float | None, expected: float | None
) -> None:
    usage = {} if used is None else {"codex": used}
    rows = [_row(1, 10)]
    assert ledger.ledger_blocks(rows, usage)[0]["other_pct"] == expected
    rendered = render_ledger({"dispatch_ledger": {"rows": rows, "used_pct": usage}}, "en")
    assert ("Other (your own use, or no dispatch record found)" in rendered) == (
        expected is not None
    )


def test_reset_block_last_and_never_has_other() -> None:
    row = _row(1, **{"GEMINI MODELS": 20})
    row["codex_reset"] = True
    blocks = ledger.ledger_blocks([row], {"codex": 1})
    assert [block["quota"] for block in blocks] == ["antigravity:GEMINI MODELS", "codex"]
    rendered = render_ledger(
        {"dispatch_ledger": {"rows": [row], "used_pct": {"codex": 1}}}, "zh-TW"
    )
    assert "Codex · 本週已用 1%" in rendered
    assert "其他（" not in rendered


@pytest.mark.parametrize(
    ("group", "short"),
    [
        ("GEMINI MODELS", "Gemini"),
        ("CLAUDE AND GPT MODELS", "Claude/GPT"),
        ("GEMINI 4 ARGON", "Argon"),
        ("<model & group>", "&lt;model &amp; group&gt;"),
    ],
)
def test_names_and_masked_text_are_escaped(group: str, short: str) -> None:
    row = _row(2, **{group: 0.01})
    rendered = render_ledger(
        {"dispatch_ledger": {"rows": [row], "used_pct": {f"antigravity:{group}": 96.7}}}, "zh-TW"
    )
    assert f'<h3 class="ledger-quota">{short} · 本週已用 97%</h3>' in rendered
    assert "<span data-mask>&lt;task 2&gt;</span>" in rendered
    assert "<span data-mask>client&lt;portal&gt;</span> · 派工 2 次" in rendered
    assert "&lt;0.1%" in rendered
    assert "<task" not in rendered


def test_only_displayed_titles_are_read_from_all_owned_conversations(
    paths: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    claude, codex, agy = paths
    estimates: dict[ledger.SessionGroup, float] = {}
    for i in range(20):
        owner = f"owner-{i}"
        when = NOW - timedelta(minutes=i * 3)
        _claude(claude, owner, "codex exec task & agy -p task", when=when)
        _codex(codex, f"child-{i}", when=when)
        estimates[("codex", f"child-{i}", "codex")] = float(20 - i)
        estimates[("claude-code", owner, "claude-code")] = float(100 - i)
    # The last owner lies outside the old top 15 and leads a different quota.
    _agy(agy, "agy-child")
    monkeypatch.setattr(
        ledger,
        "_agy_candidates",
        lambda *_: [
            ledger.Candidate("antigravity", "agy-child", NOW - timedelta(minutes=57), "/work/a")
        ],
    )
    estimates[("claude-code", "owner-19", "claude-code")] = 0
    estimates[("antigravity", "agy-child", "antigravity:GEMINI MODELS")] = 50
    calls: list[str] = []

    def title(path: Path) -> str:
        calls.append(path.stem)
        return path.stem

    monkeypatch.setattr(ledger, "_session_title", title)
    data = ledger.build_ledger(estimates, NOW)
    assert len(data["rows"]) == 20
    assert set(calls) == {"owner-0", "owner-1", "owner-2", "owner-3", "owner-4", "owner-19"}
    assert len(calls) == 6
    assert "owner-19" in render_ledger({"dispatch_ledger": data}, "en")

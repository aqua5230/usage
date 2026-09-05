# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import i18n
from adapters.types import AgentInfo, RateLimits, SessionStats, UsageEntry
from analyzer import reporter
from ui import html_report, tables

usage_cli: Any = import_module("usage_cli")


@pytest.fixture(autouse=True)
def _stub_persona_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    profile = usage_cli.persona_loader.PersonaProfile([0] * 24, [], [], 0, 0)
    monkeypatch.setattr(
        usage_cli.persona_loader,
        "load_profile",
        lambda days_back=30: profile,
    )


def _entry() -> UsageEntry:
    return UsageEntry(
        timestamp=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        session_id="session-1",
        message_id="message-1",
        request_id="request-1",
        model="gpt-test",
        input_tokens=10,
        output_tokens=5,
        cache_creation_tokens=2,
        cache_read_tokens=3,
        cost_usd=0.01,
        project="project",
        agent_id="codex",
    )


def _session(session_id: str) -> SessionStats:
    start = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    return SessionStats(
        session_id=session_id,
        project="usage",
        model="claude-test",
        start_time=start,
        end_time=start,
        duration_minutes=0,
    )


def test_load_session_titles_uses_30_day_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []
    profile = usage_cli.persona_loader.PersonaProfile(
        [0] * 24,
        [],
        [],
        0,
        0,
        {"session-1": "Fix dashboard"},
    )
    def fake_load_profile(days_back: int) -> usage_cli.persona_loader.PersonaProfile:
        calls.append(days_back)
        return profile

    monkeypatch.setattr(usage_cli.persona_loader, "load_profile", fake_load_profile)

    assert usage_cli._load_session_titles() == {"session-1": "Fix dashboard"}
    assert calls == [30]


def test_load_session_titles_returns_none_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(_days_back: int) -> None:
        raise OSError("unavailable")

    monkeypatch.setattr(usage_cli.persona_loader, "load_profile", fail)

    assert usage_cli._load_session_titles() is None


def test_recent_titles_section_tolerates_missing_key() -> None:
    assert html_report._render_recent_titles_section(
        {"persona": {"hour_histogram": []}},
        "en",
    ) == ""


def test_dashboard_and_reporter_agree_on_agent_loaders() -> None:
    """鎖住 dashboard 與 report 的 loader map 必須同步；兩份 map 曾只同步一半，
    導致 dashboard 的 Antigravity 分頁顯示 No data，但 report 指令仍有資料。"""
    assert set(usage_cli.AGENT_LOADERS) == set(reporter.AGENT_LOADERS)


def test_recent_titles_section_masks_and_escapes_each_title() -> None:
    rendered = html_report._render_recent_titles_section(
        {"persona": {"recent_titles": ["Fix <table>", "Review & ship"]}},
        "en",
    )

    assert "What you worked on" in rendered
    assert rendered.count('class="recent-title" data-mask') == 2
    assert "Fix &lt;table&gt;" in rendered
    assert "Review &amp; ship" in rendered
    assert "Fix <table>" not in rendered


def test_recent_sessions_shows_topic_and_blank_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    printed: list[Any] = []
    monkeypatch.setattr(tables, "_width_mode", lambda: "medium")
    monkeypatch.setattr(tables, "t", lambda key, **kwargs: key)
    monkeypatch.setattr(tables.console, "print", printed.append)

    tables._render_recent_sessions(
        [_session("known"), _session("missing")],
        session_titles={"known": "Known topic"},
    )

    table = printed[0]
    headers = [str(column.header) for column in table.columns]
    topic_index = headers.index("col_session_title")
    assert headers[topic_index - 1] == "col_project"
    assert table.columns[topic_index].max_width == 20
    assert list(table.columns[topic_index].cells) == ["Known topic", ""]


def test_recent_sessions_hides_topic_in_compact_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    printed: list[Any] = []
    monkeypatch.setattr(tables, "_width_mode", lambda: "compact")
    monkeypatch.setattr(tables, "t", lambda key, **kwargs: key)
    monkeypatch.setattr(tables.console, "print", printed.append)

    tables._render_recent_sessions(
        [_session("known")],
        session_titles={"known": "Hidden topic"},
    )

    table = printed[0]
    assert "col_session_title" not in [str(column.header) for column in table.columns]
    assert "Hidden topic" not in [
        str(cell)
        for column in table.columns
        for cell in column.cells
    ]


@pytest.mark.parametrize(
    ("lang", "heading", "column"),
    [
        ("zh-TW", "最近在做什麼", "在做什麼"),
        ("zh-CN", "最近在做什么", "在做什么"),
        ("en", "What you worked on", "Topic"),
        ("ja", "最近の作業", "作業内容"),
        ("ko", "최근 작업", "작업 내용"),
    ],
)
def test_session_title_translations(
    lang: str,
    heading: str,
    column: str,
) -> None:
    assert i18n._t(lang, "report_recent_titles_heading") == heading
    assert i18n._t(lang, "col_session_title") == column


def test_parse_sort_args_extracts_major_flags() -> None:
    remaining, sort_key, descending = usage_cli._parse_sort_args(
        ["30", "--sort", "cost", "--asc"]
    )

    assert remaining == ["30"]
    assert sort_key == "cost"
    assert descending is False


def test_apply_sort_time_key_sorts_by_default_attr_honoring_user_direction() -> None:
    # SORT_KEYS["time"] is None, so _apply_sort falls back to default_attr but
    # follows the caller's descending flag rather than the command default.
    a = SimpleNamespace(timestamp=1)
    b = SimpleNamespace(timestamp=2)
    c = SimpleNamespace(timestamp=3)

    stats = [b, a, c]
    usage_cli._apply_sort(
        stats, "time", descending=False, default_attr="timestamp", default_reverse=True
    )
    assert [s.timestamp for s in stats] == [1, 2, 3]

    stats = [b, a, c]
    usage_cli._apply_sort(
        stats, "time", descending=True, default_attr="timestamp", default_reverse=False
    )
    assert [s.timestamp for s in stats] == [3, 2, 1]


def test_main_dashboard_uses_mocked_loaders_without_touching_agent_dirs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = AgentInfo("codex", "Codex", "~/.codex", True)
    rendered: dict[str, Any] = {}

    monkeypatch.setattr(sys, "argv", ["usage", "dashboard"])
    monkeypatch.setattr(usage_cli, "detect_agents", lambda: [agent])
    monkeypatch.setattr(usage_cli, "is_setup", lambda: True)
    monkeypatch.setattr(usage_cli, "_load_entries", lambda agent_id: [_entry()])
    monkeypatch.setattr(
        usage_cli,
        "RATE_LIMIT_LOADERS",
        {"codex": lambda: RateLimits(five_hour_pct=12, seven_day_pct=34)},
    )
    monkeypatch.setattr(usage_cli, "render_dashboard", lambda **kwargs: rendered.update(kwargs))

    usage_cli.main()

    assert rendered["agents"] == ["Codex"]
    assert len(rendered["daily_stats"]) == 1
    assert rendered["rate_limits"] == RateLimits(five_hour_pct=12, seven_day_pct=34)


def test_cli_codex_rate_limits_use_shared_loader_conversion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        usage_cli.codex_loader,
        "load_rate_limits",
        lambda: usage_cli.codex_loader.CodexRateLimits(
            five_hour_pct=0.0,
            five_hour_resets_at=1234.9,
            seven_day_pct=56.0,
            seven_day_resets_at=9876.1,
            model="gpt-test",
            updated_at="2026-01-01T00:00:00+00:00",
        ),
    )

    result = usage_cli.RATE_LIMIT_LOADERS["codex"]()

    assert result == RateLimits(
        five_hour_pct=0.0,
        five_hour_resets_at=1234,
        seven_day_pct=56.0,
        seven_day_resets_at=9876,
        model="gpt-test",
        updated_at="2026-01-01T00:00:00+00:00",
    )


def test_main_status_json_outputs_both_local_agents(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["usage", "status", "--json"])
    monkeypatch.setattr(
        usage_cli,
        "RATE_LIMIT_LOADERS",
        {
            "claude-code": lambda: RateLimits(
                five_hour_pct=41.0,
                five_hour_resets_at=1_786_676_400,
                seven_day_pct=65.0,
                seven_day_resets_at=1_786_788_000,
                model="claude-opus-5",
                updated_at="2026-08-14T06:52:00Z",
            ),
            "codex": lambda: RateLimits(
                seven_day_pct=21.0,
                seven_day_resets_at=1_787_196_910,
                updated_at="2026-08-14T06:52:23Z",
            ),
        },
    )
    monkeypatch.setattr(
        usage_cli,
        "detect_agents",
        lambda: pytest.fail("status should not detect agents"),
    )

    usage_cli.main()

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert captured.err == ""
    assert payload["schema_version"] == 1
    assert datetime.fromisoformat(payload["generated_at"].replace("Z", "+00:00")).tzinfo == UTC
    assert payload["agents"] == {
        "claude-code": {
            "available": True,
            "five_hour": {"used_percent": 41.0, "resets_at": 1_786_676_400},
            "seven_day": {"used_percent": 65.0, "resets_at": 1_786_788_000},
            "model": "claude-opus-5",
            "updated_at": "2026-08-14T06:52:00Z",
        },
        "codex": {
            "available": True,
            "five_hour": {"used_percent": None, "resets_at": None},
            "seven_day": {"used_percent": 21.0, "resets_at": 1_787_196_910},
            "model": "",
            "updated_at": "2026-08-14T06:52:23Z",
        },
    }


def test_main_status_json_marks_none_loader_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["usage", "status", "--json"])
    monkeypatch.setattr(
        usage_cli,
        "RATE_LIMIT_LOADERS",
        {
            "claude-code": lambda: None,
            "codex": lambda: RateLimits(seven_day_pct=12.0),
        },
    )

    usage_cli.main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["agents"]["claude-code"] == {
        "available": False,
        "five_hour": {"used_percent": None, "resets_at": None},
        "seven_day": {"used_percent": None, "resets_at": None},
        "model": None,
        "updated_at": None,
    }
    assert payload["agents"]["codex"]["available"] is True


def test_main_status_json_isolates_loader_exception(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail() -> RateLimits:
        raise OSError("unavailable")

    monkeypatch.setattr(sys, "argv", ["usage", "status", "--json"])
    monkeypatch.setattr(
        usage_cli,
        "RATE_LIMIT_LOADERS",
        {
            "claude-code": lambda: RateLimits(five_hour_pct=3.0),
            "codex": fail,
        },
    )

    usage_cli.main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["agents"]["claude-code"]["available"] is True
    assert payload["agents"]["codex"]["available"] is False


def test_main_status_json_succeeds_when_both_loaders_return_none(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["usage", "status", "--json"])
    monkeypatch.setattr(
        usage_cli,
        "RATE_LIMIT_LOADERS",
        {"claude-code": lambda: None, "codex": lambda: None},
    )

    usage_cli.main()

    payload = json.loads(capsys.readouterr().out)
    assert all(not status["available"] for status in payload["agents"].values())


def test_main_status_without_json_prints_one_line(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["usage", "status"])
    monkeypatch.setattr(
        usage_cli,
        "RATE_LIMIT_LOADERS",
        {
            "claude-code": lambda: RateLimits(five_hour_pct=41.0, seven_day_pct=65.0),
            "codex": lambda: None,
        },
    )

    usage_cli.main()

    assert capsys.readouterr().out == (
        "claude-code 5h=41.0% 7d=65.0% | codex available=false\n"
    )


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_main_status_help_does_not_load_agents(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    flag: str,
) -> None:
    monkeypatch.setattr(sys, "argv", ["usage", "status", flag])
    monkeypatch.setattr(
        usage_cli,
        "RATE_LIMIT_LOADERS",
        {
            "claude-code": lambda: pytest.fail("status help should not load quotas"),
            "codex": lambda: pytest.fail("status help should not load quotas"),
        },
    )

    usage_cli.main()

    assert "Usage: usage status [--json]" in capsys.readouterr().out


def test_main_daily_sort_flag_controls_render_order(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = AgentInfo("codex", "Codex", "~/.codex", True)
    high = _entry()
    low = _entry()
    high.input_tokens = 100
    high.timestamp = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    low.input_tokens = 1
    low.timestamp = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)
    rendered: dict[str, Any] = {}

    monkeypatch.setattr(sys, "argv", ["usage", "daily", "--sort", "tokens", "--asc"])
    monkeypatch.setattr(usage_cli, "detect_agents", lambda: [agent])
    monkeypatch.setattr(usage_cli, "is_setup", lambda: True)
    monkeypatch.setattr(usage_cli, "_load_entries", lambda agent_id: [high, low])
    monkeypatch.setattr(
        usage_cli,
        "render_daily",
        lambda stats, agents: rendered.update(stats=stats),
    )

    usage_cli.main()

    assert [stat.total_tokens for stat in rendered["stats"]] == [11, 110]


def test_main_codex_warning_checks_only_codex_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = AgentInfo("codex", "Codex", "~/.codex", True)
    printed: list[str] = []

    monkeypatch.setattr(sys, "argv", ["usage", "codex"])
    monkeypatch.setattr(usage_cli, "detect_agents", lambda: [agent])
    monkeypatch.setattr(usage_cli, "is_claude_setup", lambda: False)
    monkeypatch.setattr(usage_cli, "is_codex_setup", lambda: True)
    monkeypatch.setattr(usage_cli, "is_setup", lambda: False)
    monkeypatch.setattr(usage_cli, "_load_entries", lambda agent_id: [_entry()])
    monkeypatch.setattr(usage_cli.console, "print", lambda value: printed.append(str(value)))
    monkeypatch.setattr(usage_cli, "render_dashboard", lambda **kwargs: None)

    usage_cli.main()

    assert not any("hook_not_installed" in line for line in printed)
    assert not any("Status line not configured" in line for line in printed)


@pytest.mark.parametrize(
    ("argv", "expected_period"),
    [
        (["usage", "report"], "last30"),
        (["usage", "report", "--last30"], "last30"),
        (["usage", "report", "--last7"], "last7"),
        (["usage", "report", "--all"], "all"),
    ],
)
def test_main_report_parses_period(
    monkeypatch: pytest.MonkeyPatch,
    argv: list[str],
    expected_period: str,
) -> None:
    from analyzer import reporter
    from ui import html_report

    agent = AgentInfo("codex", "Codex", "~/.codex", True)
    calls: dict[str, Any] = {}

    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setattr(usage_cli, "detect_agents", lambda: [agent])
    monkeypatch.setattr(usage_cli, "is_setup", lambda: True)
    monkeypatch.setattr(
        reporter,
        "build_report_data",
        lambda agents, period: calls.update(agents=agents, period=period) or {},
    )
    monkeypatch.setattr(html_report, "save_and_open", lambda data, out_path=None: "report.html")

    usage_cli.main()

    assert calls == {"agents": [agent], "period": expected_period}


def test_main_report_help_does_not_build_report(monkeypatch: pytest.MonkeyPatch) -> None:
    from analyzer import reporter

    printed: list[str] = []

    monkeypatch.setattr(sys, "argv", ["usage", "report", "--help"])
    monkeypatch.setattr(
        usage_cli,
        "detect_agents",
        lambda: pytest.fail("report help should not detect agents"),
    )
    monkeypatch.setattr(usage_cli, "is_setup", lambda: True)
    monkeypatch.setattr(usage_cli.console, "print", lambda value: printed.append(str(value)))
    monkeypatch.setattr(
        reporter,
        "build_report_data",
        lambda agents, period: pytest.fail("report help should not build a report"),
    )

    usage_cli.main()

    assert any("Usage: usage report" in line for line in printed)


def test_main_report_rejects_unknown_option(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = AgentInfo("codex", "Codex", "~/.codex", True)
    printed: list[str] = []

    monkeypatch.setattr(sys, "argv", ["usage", "report", "--bogus"])
    monkeypatch.setattr(usage_cli, "detect_agents", lambda: [agent])
    monkeypatch.setattr(usage_cli, "is_setup", lambda: True)
    monkeypatch.setattr(usage_cli.console, "print", lambda value: printed.append(str(value)))

    with pytest.raises(SystemExit) as exc_info:
        usage_cli.main()

    assert exc_info.value.code == 1
    assert any("unknown report option" in line for line in printed)


def test_main_export_defaults_to_daily_stdout(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    agent = AgentInfo("codex", "Codex", "~/.codex", True)
    entry = _entry()

    monkeypatch.setattr(sys, "argv", ["usage", "export"])
    monkeypatch.setattr(usage_cli, "detect_agents", lambda: [agent])
    monkeypatch.setattr(usage_cli, "is_setup", lambda: False)
    monkeypatch.setattr(usage_cli, "_load_entries", lambda agent_id: [entry])

    usage_cli.main()

    assert capsys.readouterr().out == (
        "agent_id,date,input_tokens,output_tokens,cache_creation_tokens,"
        "cache_read_tokens,total_tokens,cost_usd,session_count,message_count\n"
        "codex,2026-01-01,10,5,2,3,20,0.01,1,1\n"
    )


def test_main_export_weekly_uses_weekly_aggregation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = AgentInfo("codex", "Codex", "~/.codex", True)
    calls: list[str] = []

    def fake_aggregate(agents: list[AgentInfo], agg_fn: Any) -> list[Any]:
        calls.append(agg_fn.__name__)
        return []

    monkeypatch.setattr(sys, "argv", ["usage", "export", "--weekly"])
    monkeypatch.setattr(usage_cli, "detect_agents", lambda: [agent])
    monkeypatch.setattr(usage_cli, "is_setup", lambda: True)
    monkeypatch.setattr(usage_cli, "_aggregate_per_agent", fake_aggregate)

    usage_cli.main()

    assert calls == ["aggregate_weekly"]


def test_main_export_sessions_writes_csv_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    agent = AgentInfo("codex", "Codex", "~/.codex", True)
    printed: list[str] = []
    out_path = tmp_path / "sessions.csv"
    first = _entry()
    second = _entry()
    second.timestamp = datetime(2026, 1, 1, 12, 30, tzinfo=UTC)
    second.message_id = "message-2"
    second.request_id = "request-2"

    monkeypatch.setattr(
        sys,
        "argv",
        ["usage", "export", "--sessions", "--out", str(out_path)],
    )
    monkeypatch.setattr(usage_cli, "detect_agents", lambda: [agent])
    monkeypatch.setattr(usage_cli, "is_setup", lambda: True)
    monkeypatch.setattr(usage_cli, "_load_entries", lambda agent_id: [first, second])
    monkeypatch.setattr(usage_cli.console, "print", lambda value: printed.append(str(value)))

    usage_cli.main()

    assert out_path.read_text(encoding="utf-8") == (
        "agent_id,session_id,project,model,start_time,end_time,duration_minutes,"
        "input_tokens,output_tokens,cache_creation_tokens,cache_read_tokens,"
        "total_tokens,cost_usd,message_count\n"
        "codex,session-1,project,gpt-test,2026-01-01T12:00:00+00:00,"
        "2026-01-01T12:30:00+00:00,30.0,20,10,4,6,40,0.02,2\n"
    )
    assert printed == [f"[green]✓[/green] Export saved: {out_path}"]


def test_main_export_help_does_not_detect_agents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    printed: list[str] = []

    monkeypatch.setattr(sys, "argv", ["usage", "export", "--help"])
    monkeypatch.setattr(
        usage_cli,
        "detect_agents",
        lambda: pytest.fail("export help should not detect agents"),
    )
    monkeypatch.setattr(usage_cli.console, "print", lambda value: printed.append(str(value)))

    usage_cli.main()

    assert any("Usage: usage export" in line for line in printed)


def test_main_export_rejects_unknown_option(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = AgentInfo("codex", "Codex", "~/.codex", True)
    printed: list[str] = []

    monkeypatch.setattr(sys, "argv", ["usage", "export", "--bogus"])
    monkeypatch.setattr(usage_cli, "detect_agents", lambda: [agent])
    monkeypatch.setattr(usage_cli, "is_setup", lambda: True)
    monkeypatch.setattr(usage_cli.console, "print", lambda value: printed.append(str(value)))

    with pytest.raises(SystemExit) as exc_info:
        usage_cli.main()

    assert exc_info.value.code == 1
    assert any("unknown export option" in line for line in printed)


def test_main_exits_when_no_agents_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["usage", "dashboard"])
    monkeypatch.setattr(usage_cli, "detect_agents", lambda: [])

    with pytest.raises(SystemExit) as exc_info:
        usage_cli.main()

    assert exc_info.value.code == 1


def test_parse_report_args_defaults_to_last30() -> None:
    assert usage_cli._parse_report_args([]) == ("last30", None, False)


def test_parse_export_args_defaults_to_daily() -> None:
    assert usage_cli._parse_export_args([]) == ("daily", None, False)


@pytest.mark.parametrize(
    ("flag", "expected_period"),
    [
        ("--today", "today"),
        ("--last7", "last7"),
        ("--week", "week"),
        ("--month", "month"),
        ("--all", "all"),
        ("--last30", "last30"),
    ],
)
def test_parse_report_args_sets_period(flag: str, expected_period: str) -> None:
    period, out_path, show_help = usage_cli._parse_report_args([flag])

    assert period == expected_period
    assert out_path is None
    assert show_help is False


@pytest.mark.parametrize("flag", ["--help", "-h"])
def test_parse_report_args_detects_help(flag: str) -> None:
    assert usage_cli._parse_report_args([flag]) == ("last30", None, True)


@pytest.mark.parametrize(
    ("flag", "expected_export_type"),
    [
        ("--daily", "daily"),
        ("--weekly", "weekly"),
        ("--monthly", "monthly"),
        ("--sessions", "sessions"),
    ],
)
def test_parse_export_args_sets_export_type(
    flag: str,
    expected_export_type: str,
) -> None:
    export_type, out_path, show_help = usage_cli._parse_export_args([flag])

    assert export_type == expected_export_type
    assert out_path is None
    assert show_help is False


@pytest.mark.parametrize("flag", ["--help", "-h"])
def test_parse_export_args_detects_help(flag: str) -> None:
    assert usage_cli._parse_export_args([flag]) == ("daily", None, True)


@pytest.mark.parametrize(
    ("args", "expected_path"),
    [
        (["--out=report.html"], "report.html"),
        (["--out", "report.html"], "report.html"),
    ],
)
def test_parse_report_args_sets_out_path(args: list[str], expected_path: str) -> None:
    assert usage_cli._parse_report_args(args) == ("last30", expected_path, False)


@pytest.mark.parametrize(
    ("args", "expected_path"),
    [
        (["--out=export.csv"], "export.csv"),
        (["--out", "export.csv"], "export.csv"),
    ],
)
def test_parse_export_args_sets_out_path(args: list[str], expected_path: str) -> None:
    assert usage_cli._parse_export_args(args) == ("daily", expected_path, False)


@pytest.mark.parametrize(
    "args",
    [
        ["--out"],
        ["--out", "--today"],
    ],
)
def test_parse_report_args_rejects_missing_out_path(
    monkeypatch: pytest.MonkeyPatch,
    args: list[str],
) -> None:
    printed: list[str] = []
    monkeypatch.setattr(usage_cli.console, "print", lambda value: printed.append(str(value)))

    with pytest.raises(SystemExit) as exc_info:
        usage_cli._parse_report_args(args)

    assert exc_info.value.code == 1
    assert any("--out requires a path" in line for line in printed)


@pytest.mark.parametrize(
    "args",
    [
        ["--out"],
        ["--out", "--daily"],
    ],
)
def test_parse_export_args_rejects_missing_out_path(
    monkeypatch: pytest.MonkeyPatch,
    args: list[str],
) -> None:
    printed: list[str] = []
    monkeypatch.setattr(usage_cli.console, "print", lambda value: printed.append(str(value)))

    with pytest.raises(SystemExit) as exc_info:
        usage_cli._parse_export_args(args)

    assert exc_info.value.code == 1
    assert any("--out requires a path" in line for line in printed)


@pytest.mark.parametrize(
    ("args", "expected_message"),
    [
        (["--bogus"], "unknown report option"),
        (["random"], "unexpected report argument"),
    ],
)
def test_parse_report_args_rejects_invalid_args(
    monkeypatch: pytest.MonkeyPatch,
    args: list[str],
    expected_message: str,
) -> None:
    printed: list[str] = []
    monkeypatch.setattr(usage_cli.console, "print", lambda value: printed.append(str(value)))

    with pytest.raises(SystemExit) as exc_info:
        usage_cli._parse_report_args(args)

    assert exc_info.value.code == 1
    assert any(expected_message in line for line in printed)


@pytest.mark.parametrize(
    ("args", "expected_message"),
    [
        (["--bogus"], "unknown export option"),
        (["random"], "unexpected export argument"),
    ],
)
def test_parse_export_args_rejects_invalid_args(
    monkeypatch: pytest.MonkeyPatch,
    args: list[str],
    expected_message: str,
) -> None:
    printed: list[str] = []
    monkeypatch.setattr(usage_cli.console, "print", lambda value: printed.append(str(value)))

    with pytest.raises(SystemExit) as exc_info:
        usage_cli._parse_export_args(args)

    assert exc_info.value.code == 1
    assert any(expected_message in line for line in printed)


def test_apply_sort_uses_default_when_sort_key_is_none() -> None:
    stats = [
        SimpleNamespace(start_time=3, total_tokens=0, cost_usd=0.0, message_count=0),
        SimpleNamespace(start_time=1, total_tokens=0, cost_usd=0.0, message_count=0),
        SimpleNamespace(start_time=2, total_tokens=0, cost_usd=0.0, message_count=0),
    ]

    usage_cli._apply_sort(stats, None, True, "start_time", False)

    assert [stat.start_time for stat in stats] == [1, 2, 3]


@pytest.mark.parametrize(
    ("descending", "expected_costs"),
    [
        (True, [3.0, 2.0, 1.0]),
        (False, [1.0, 2.0, 3.0]),
    ],
)
def test_apply_sort_uses_known_sort_key(descending: bool, expected_costs: list[float]) -> None:
    assert "cost" in usage_cli.SORT_KEYS
    stats = [
        SimpleNamespace(start_time=1, total_tokens=0, cost_usd=2.0, message_count=0),
        SimpleNamespace(start_time=2, total_tokens=0, cost_usd=1.0, message_count=0),
        SimpleNamespace(start_time=3, total_tokens=0, cost_usd=3.0, message_count=0),
    ]

    usage_cli._apply_sort(stats, "cost", descending, "start_time", False)

    assert [stat.cost_usd for stat in stats] == expected_costs


def test_apply_sort_time_key_sorts_default_attr_by_descending() -> None:
    # "time" maps to None in SORT_KEYS (handled per-command): falls back to
    # default_attr but honours the caller's `descending`, not default_reverse.
    assert usage_cli.SORT_KEYS["time"] is None
    stats = [
        SimpleNamespace(start_time=1, total_tokens=0, cost_usd=0.0, message_count=0),
        SimpleNamespace(start_time=3, total_tokens=0, cost_usd=0.0, message_count=0),
        SimpleNamespace(start_time=2, total_tokens=0, cost_usd=0.0, message_count=0),
    ]

    usage_cli._apply_sort(stats, "time", True, "start_time", default_reverse=False)

    assert [stat.start_time for stat in stats] == [3, 2, 1]


def test_apply_sort_unknown_key_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    printed: list[str] = []
    stats = [
        SimpleNamespace(start_time=3, total_tokens=0, cost_usd=1.0, message_count=0),
        SimpleNamespace(start_time=1, total_tokens=0, cost_usd=3.0, message_count=0),
        SimpleNamespace(start_time=2, total_tokens=0, cost_usd=2.0, message_count=0),
    ]
    monkeypatch.setattr(usage_cli.console, "print", lambda value: printed.append(str(value)))

    usage_cli._apply_sort(stats, "unknown_key", True, "start_time", False)

    assert [stat.start_time for stat in stats] == [1, 2, 3]
    assert any("unknown_key" in line for line in printed)


@pytest.mark.parametrize(
    ("env_name", "expected_id"),
    [
        ("CODEX_THREAD_ID", "codex"),
        ("CODEX_SANDBOX", "codex"),
        ("CLAUDE_CONFIG_DIR", "claude-code"),
        ("CLAUDECODE", "claude-code"),
    ],
)
def test_initial_agent_index_uses_environment_preference(
    monkeypatch: pytest.MonkeyPatch,
    env_name: str,
    expected_id: str,
) -> None:
    for name in ("CODEX_THREAD_ID", "CODEX_SANDBOX", "CLAUDE_CONFIG_DIR", "CLAUDECODE"):
        monkeypatch.delenv(name, raising=False)
    agents = [SimpleNamespace(id="other"), SimpleNamespace(id=expected_id)]

    monkeypatch.setenv(env_name, "1")

    assert usage_cli._initial_agent_index(agents) == 1


def test_initial_agent_index_defaults_to_first_without_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("CODEX_THREAD_ID", "CODEX_SANDBOX", "CLAUDE_CONFIG_DIR", "CLAUDECODE"):
        monkeypatch.delenv(name, raising=False)

    assert usage_cli._initial_agent_index([SimpleNamespace(id="codex")]) == 0


def test_initial_agent_index_defaults_to_first_when_preferred_agent_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("CODEX_THREAD_ID", "CODEX_SANDBOX", "CLAUDE_CONFIG_DIR", "CLAUDECODE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CODEX_THREAD_ID", "1")

    assert usage_cli._initial_agent_index([SimpleNamespace(id="claude-code")]) == 0


def test_fit_screen_returns_empty_text() -> None:
    assert usage_cli._fit_screen("", 10, 0) == ("", 0)


def test_fit_screen_returns_full_text_when_it_fits() -> None:
    assert usage_cli._fit_screen("header\nbody", 5, 0) == ("header\nbody", 0)


def test_fit_screen_limits_body_to_scroll_window() -> None:
    screen, max_scroll = usage_cli._fit_screen("h\nb1\nb2\nb3\nb4", 4, 1)

    assert screen == "h\nb2\nb3"
    assert max_scroll == 2


def test_fit_screen_clamps_scroll_offset() -> None:
    screen, max_scroll = usage_cli._fit_screen("h\nb1\nb2\nb3\nb4", 4, 99)

    assert screen == "h\nb3\nb4"
    assert max_scroll == 2


def test_dashboard_sort_cycle_shape_and_order() -> None:
    sort_cycle = usage_cli._dashboard_sort_cycle()

    assert len(sort_cycle) == 4
    assert all(len(item) == 3 for item in sort_cycle)
    assert [item[0] for item in sort_cycle] == ["time", "tokens", "cost", "messages"]
    assert [item[1] for item in sort_cycle] == [
        "start_time",
        "total_tokens",
        "cost_usd",
        "message_count",
    ]

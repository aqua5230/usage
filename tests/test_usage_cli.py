from __future__ import annotations

import sys
from datetime import UTC, datetime
from importlib import import_module
from typing import Any

import pytest

from adapters.types import AgentInfo, RateLimits, UsageEntry

usage_cli: Any = import_module("usage_cli")


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


def test_parse_sort_args_extracts_major_flags() -> None:
    remaining, sort_key, descending = usage_cli._parse_sort_args(
        ["30", "--sort", "cost", "--asc"]
    )

    assert remaining == ["30"]
    assert sort_key == "cost"
    assert descending is False


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


@pytest.mark.parametrize(
    ("argv", "expected_period"),
    [
        (["usage", "report"], "last30"),
        (["usage", "report", "--last30"], "last30"),
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


def test_main_exits_when_no_agents_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["usage", "dashboard"])
    monkeypatch.setattr(usage_cli, "detect_agents", lambda: [])

    with pytest.raises(SystemExit) as exc_info:
        usage_cli.main()

    assert exc_info.value.code == 1

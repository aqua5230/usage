# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from datetime import UTC, date, datetime, tzinfo
from pathlib import Path
from typing import Any, Self

import pytest

import codex_loader
import history_loader
import pricing
from adapters.types import AgentInfo, UsageEntry
from analyzer import persona_loader, reporter, subscription


def _empty_year_payload() -> dict[str, Any]:
    return {
        "contribution": {
            "weeks": [],
            "start": "2026-01-01",
            "end": "2026-01-01",
            "max_tokens": 0,
            "total_tokens": 0,
            "active_days": 0,
            "current_streak": 0,
            "longest_streak": 0,
            "busiest_day": None,
        },
        "wrapped": {
            "year_label": "2026",
            "total_tokens": 0,
            "total_cost": 0.0,
            "active_days": 0,
            "total_sessions": 0,
            "top_model": None,
            "top_project": None,
            "busiest_day": None,
            "longest_streak": 0,
            "claude_tokens": 0,
            "codex_tokens": 0,
            "beast": None,
        },
    }


def _fixed_datetime(fixed: datetime) -> type:
    # build_report_data derives "today" via datetime.now().astimezone(); pin the
    # no-arg astimezone() to UTC so the pinned clock is machine-zone-proof
    # (Windows cannot pin the process zone through TZ + tzset).
    class _FixedLocalDateTime(datetime):
        def astimezone(self, tz: tzinfo | None = None) -> Self:
            return super().astimezone(tz if tz is not None else UTC)

    class _FixedDateTime:
        @staticmethod
        def now(tz: tzinfo | None = None) -> datetime:
            if tz:
                return fixed.astimezone(tz)
            return _FixedLocalDateTime.fromtimestamp(fixed.timestamp(), tz=UTC)

    return _FixedDateTime


def _entry(
    *,
    when: datetime,
    session_id: str,
    model: str,
    project: str,
    agent_id: str,
    input_tokens: int,
    output_tokens: int = 0,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
    cost_usd: float = 0.0,
    message_count: int = 1,
) -> UsageEntry:
    return UsageEntry(
        timestamp=when,
        session_id=session_id,
        message_id=f"{session_id}-{when.isoformat()}",
        request_id=f"req-{session_id}-{when.isoformat()}",
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_tokens=cache_creation_tokens,
        cache_read_tokens=cache_read_tokens,
        cost_usd=cost_usd,
        project=project,
        agent_id=agent_id,
        message_count=message_count,
    )


@pytest.fixture(autouse=True)
def _sandbox_reporter_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[None]:
    original_tz = os.environ.get("TZ")
    os.environ["TZ"] = "UTC"
    if hasattr(time, "tzset"):
        time.tzset()

    # TZ + tzset only pins the local zone on POSIX — Windows has no tzset, so
    # entry dates would still be bucketed in the machine's zone there. Pin the
    # conversion point itself to UTC as well.
    def _entry_date_utc(entry: UsageEntry) -> date:
        ts = entry.timestamp
        if ts.tzinfo:
            ts = ts.astimezone(UTC)
        return ts.date()

    monkeypatch.setattr(reporter, "_entry_date", _entry_date_utc)

    monkeypatch.setattr(reporter, "YEAR_CACHE_PATH", tmp_path / ".usage" / "year_cache.json")
    monkeypatch.setattr(reporter, "YEAR_LEDGER_PATH", tmp_path / ".usage" / "year_ledger.json")
    monkeypatch.setattr(reporter, "_load_year_data_cached", lambda _agents: _empty_year_payload())
    monkeypatch.setattr(reporter, "_load_persona_for_period", lambda _period: None)
    monkeypatch.setattr(reporter, "is_model_priced", lambda model: model != "unknown")
    monkeypatch.setattr("analyzer.reporter.subscription.load_subscriptions", lambda: [])

    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", tmp_path / ".codex" / "sessions")
    monkeypatch.setattr(
        codex_loader,
        "ARCHIVED_SESSIONS_DIR",
        tmp_path / ".codex" / "archived_sessions",
    )
    monkeypatch.setattr(codex_loader, "STATE_DB", tmp_path / ".codex" / "state_5.sqlite")
    monkeypatch.setattr(codex_loader, "LOGS_DB", tmp_path / ".codex" / "logs_2.sqlite")
    monkeypatch.setattr(codex_loader, "JSONL_CACHE_PATH", tmp_path / ".usage" / "codex_cache.json")
    monkeypatch.setattr(history_loader, "CLAUDE_PROJECTS_DIR", tmp_path / ".claude" / "projects")
    monkeypatch.setattr(persona_loader, "CLAUDE_PROJECTS_DIR", tmp_path / ".claude" / "projects")
    monkeypatch.setattr(subscription, "CLAUDE_CONFIG", tmp_path / ".claude.json")
    monkeypatch.setattr(subscription, "CODEX_AUTH", tmp_path / ".codex" / "auth.json")
    monkeypatch.setattr(pricing, "CACHE_PATH", tmp_path / ".usage" / "pricing_cache.json")
    monkeypatch.setattr(pricing, "LEGACY_CACHE_PATH", tmp_path / ".claude" / "pricing_cache.json")

    try:
        yield
    finally:
        if original_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = original_tz
        if hasattr(time, "tzset"):
            time.tzset()


def test_build_report_data_calculates_each_entry_date_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixed_now = datetime(2026, 5, 21, 12, tzinfo=UTC)
    agent = AgentInfo("codex", "Codex", "~/.codex", True)
    entries = [
        _entry(
            when=datetime(2026, 5, 20, 12, tzinfo=UTC),
            session_id="current",
            model="gpt-5-codex",
            project="usage",
            agent_id="codex",
            input_tokens=100,
        ),
        _entry(
            when=datetime(2026, 4, 20, 12, tzinfo=UTC),
            session_id="previous",
            model="gpt-5-codex",
            project="usage",
            agent_id="codex",
            input_tokens=50,
        ),
    ]
    entry_date = reporter._entry_date
    calls = 0

    def count_entry_date(entry: UsageEntry) -> date:
        nonlocal calls
        calls += 1
        return entry_date(entry)

    monkeypatch.setattr(reporter, "datetime", _fixed_datetime(fixed_now))
    monkeypatch.setattr(reporter, "_load_agent_entries", lambda _agent, _hours: entries)
    monkeypatch.setattr(reporter, "_entry_date", count_entry_date)

    reporter.build_report_data([agent], "month")

    assert calls == len(entries)


def test_build_report_data_week_window_includes_boundaries_and_zero_fill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixed_now = datetime(2026, 5, 21, 12, tzinfo=UTC)
    agent = AgentInfo("codex", "Codex", "~/.codex", True)
    entries = [
        _entry(
            when=datetime(2026, 5, 11, 9, tzinfo=UTC),
            session_id="too-old",
            model="gpt-5-codex",
            project="old",
            agent_id="codex",
            input_tokens=999,
            cost_usd=9.99,
        ),
        _entry(
            when=datetime(2026, 5, 17, 23, 59, tzinfo=UTC),
            session_id="before-window",
            model="gpt-5-codex",
            project="old",
            agent_id="codex",
            input_tokens=40,
            cost_usd=0.4,
        ),
        _entry(
            when=datetime(2026, 5, 18, 0, 0, tzinfo=UTC),
            session_id="start-boundary",
            model="gpt-5-codex",
            project="usage",
            agent_id="codex",
            input_tokens=100,
            cost_usd=1.0,
        ),
        _entry(
            when=datetime(2026, 5, 20, 12, tzinfo=UTC),
            session_id="middle",
            model="gpt-5-codex",
            project="usage",
            agent_id="codex",
            input_tokens=50,
            cost_usd=0.5,
        ),
        _entry(
            when=datetime(2026, 5, 21, 23, 59, tzinfo=UTC),
            session_id="end-boundary",
            model="gpt-5-codex",
            project="usage",
            agent_id="codex",
            input_tokens=25,
            cost_usd=0.25,
        ),
        _entry(
            when=datetime(2026, 5, 22, 0, 0, tzinfo=UTC),
            session_id="future",
            model="gpt-5-codex",
            project="future",
            agent_id="codex",
            input_tokens=500,
            cost_usd=5.0,
        ),
    ]

    monkeypatch.setattr(reporter, "datetime", _fixed_datetime(fixed_now))
    monkeypatch.setattr(reporter, "_load_agent_entries", lambda _agent, _hours_back=0: entries)

    data = reporter.build_report_data([agent], "week")

    assert data["date_from"] == "2026-05-18"
    assert data["date_to"] == "2026-05-21"
    assert data["period_label"] == "2026-05-18 -> 2026-05-21"
    assert data["summary"]["total_tokens"] == 175
    assert data["summary"]["sessions"] == 3
    assert data["summary"]["active_days"] == 3
    assert data["summary"]["total_days"] == 4
    assert data["daily_trend"] == [
        {"date": "2026-05-18", "tokens": 100, "cost": 1.0},
        {"date": "2026-05-19", "tokens": 0, "cost": 0.0},
        {"date": "2026-05-20", "tokens": 50, "cost": 0.5},
        {"date": "2026-05-21", "tokens": 25, "cost": 0.25},
    ]


def test_build_report_data_month_comparison_uses_previous_full_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixed_now = datetime(2026, 5, 21, 12, tzinfo=UTC)
    agent = AgentInfo("codex", "Codex", "~/.codex", True)
    entries = [
        _entry(
            when=datetime(2026, 4, 9, 23, 59, tzinfo=UTC),
            session_id="ignored-prev",
            model="gpt-5-codex",
            project="ignore-me",
            agent_id="codex",
            input_tokens=999,
            cost_usd=9.99,
        ),
        _entry(
            when=datetime(2026, 4, 10, 0, 0, tzinfo=UTC),
            session_id="prev-start",
            model="gpt-5-mini",
            project="legacy",
            agent_id="codex",
            input_tokens=80,
            cost_usd=0.8,
        ),
        _entry(
            when=datetime(2026, 4, 30, 23, 59, tzinfo=UTC),
            session_id="prev-end",
            model="gpt-5-codex",
            project="usage",
            agent_id="codex",
            input_tokens=120,
            cost_usd=1.2,
        ),
        _entry(
            when=datetime(2026, 5, 1, 0, 0, tzinfo=UTC),
            session_id="cur-start",
            model="gpt-5-codex",
            project="usage",
            agent_id="codex",
            input_tokens=200,
            cost_usd=2.0,
        ),
        _entry(
            when=datetime(2026, 5, 21, 23, 59, tzinfo=UTC),
            session_id="cur-end",
            model="gpt-5-codex",
            project="ops",
            agent_id="codex",
            input_tokens=50,
            cost_usd=0.5,
        ),
    ]

    monkeypatch.setattr(reporter, "datetime", _fixed_datetime(fixed_now))
    monkeypatch.setattr(reporter, "_load_agent_entries", lambda _agent, _hours_back=0: entries)

    data = reporter.build_report_data([agent], "month")

    assert data["date_from"] == "2026-05-01"
    assert data["date_to"] == "2026-05-21"
    assert data["summary"]["total_tokens"] == 250
    assert data["comparison"] == {
        "period": "month",
        "has_prev": True,
        "prev_tokens": 200,
        "prev_cost": 2.0,
        "prev_projects": ["legacy", "usage"],
        "prev_model_share": {"gpt-5-codex": 60.0, "gpt-5-mini": 40.0},
    }


def test_build_report_data_sorts_projects_by_tokens_and_sessions_by_cost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixed_now = datetime(2026, 5, 21, 18, tzinfo=UTC)
    agent = AgentInfo("codex", "Codex", "~/.codex", True)
    entries = [
        _entry(
            when=datetime(2026, 5, 21, 9, tzinfo=UTC),
            session_id="high-cost",
            model="gpt-5-codex",
            project="beta",
            agent_id="codex",
            input_tokens=80,
            cost_usd=9.0,
        ),
        _entry(
            when=datetime(2026, 5, 21, 11, tzinfo=UTC),
            session_id="high-token",
            model="gpt-5-codex",
            project="alpha",
            agent_id="codex",
            input_tokens=300,
            cost_usd=3.0,
        ),
        _entry(
            when=datetime(2026, 5, 21, 14, tzinfo=UTC),
            session_id="mid-cost",
            model="gpt-5-codex",
            project="alpha",
            agent_id="codex",
            input_tokens=100,
            cost_usd=6.0,
        ),
    ]

    monkeypatch.setattr(reporter, "datetime", _fixed_datetime(fixed_now))
    monkeypatch.setattr(reporter, "_load_agent_entries", lambda _agent, _hours_back=0: entries)

    data = reporter.build_report_data([agent], "today")

    assert [row["project"] for row in data["by_project"]] == ["alpha", "beta"]
    assert [row["tokens"] for row in data["by_project"]] == [400, 80]
    assert [row["project"] for row in data["top_sessions"]] == ["beta", "alpha", "alpha"]
    assert [row["cost"] for row in data["top_sessions"]] == [9.0, 6.0, 3.0]
    assert [row["tokens"] for row in data["top_sessions"]] == [80, 100, 300]


def test_build_report_data_aggregates_agent_and_model_totals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixed_now = datetime(2026, 5, 21, 20, tzinfo=UTC)
    agents = [
        AgentInfo("claude-code", "Claude Code", "~/.claude", True),
        AgentInfo("codex", "Codex", "~/.codex", True),
    ]
    all_entries = [
        _entry(
            when=datetime(2026, 5, 21, 8, tzinfo=UTC),
            session_id="codex-session",
            model="gpt-5-codex",
            project="usage",
            agent_id="codex",
            input_tokens=100,
            cost_usd=1.0,
            message_count=2,
        ),
        _entry(
            when=datetime(2026, 5, 21, 9, tzinfo=UTC),
            session_id="codex-session",
            model="gpt-5-codex",
            project="usage",
            agent_id="codex",
            input_tokens=50,
            cost_usd=0.5,
            message_count=1,
        ),
        _entry(
            when=datetime(2026, 5, 21, 10, tzinfo=UTC),
            session_id="claude-main",
            model="claude-sonnet-4",
            project="ops",
            agent_id="claude-code",
            input_tokens=200,
            cost_usd=4.0,
            message_count=3,
        ),
        _entry(
            when=datetime(2026, 5, 21, 11, tzinfo=UTC),
            session_id="claude-side",
            model="claude-sonnet-4",
            project="usage",
            agent_id="claude-code",
            input_tokens=20,
            cost_usd=0.2,
            message_count=1,
        ),
    ]

    def fake_load_agent_entries(
        received_agent: AgentInfo,
        _hours_back: int = 0,
    ) -> list[UsageEntry]:
        return [entry for entry in all_entries if entry.agent_id == received_agent.id]

    monkeypatch.setattr(reporter, "datetime", _fixed_datetime(fixed_now))
    monkeypatch.setattr(reporter, "_load_agent_entries", fake_load_agent_entries)

    data = reporter.build_report_data(agents, "today")

    assert data["summary"] == {
        "total_tokens": 370,
        "cost_usd": 5.7,
        "sessions": 3,
        "messages": 7,
        "active_days": 1,
        "total_days": 1,
    }
    assert data["by_agent"] == [
        {
            "id": "claude-code",
            "name": "Claude Code",
            "tokens": 220,
            "cost": 4.2,
            "sessions": 2,
            "messages": 4,
            "pct": 59.5,
        },
        {
            "id": "codex",
            "name": "Codex",
            "tokens": 150,
            "cost": 1.5,
            "sessions": 1,
            "messages": 3,
            "pct": 40.5,
        },
    ]
    assert data["by_model"] == [
        {
            "model": "claude-sonnet-4",
            "tokens": 220,
            "cost": 4.2,
            "cost_known": True,
            "pct": 59.5,
            "top_project": "ops",
        },
        {
            "model": "gpt-5-codex",
            "tokens": 150,
            "cost": 1.5,
            "cost_known": True,
            "pct": 40.5,
            "top_project": "usage",
        },
    ]

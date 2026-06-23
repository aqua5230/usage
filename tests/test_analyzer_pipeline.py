# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

import codex_loader
import history_loader
import menubar
import persona_loader
from adapters.types import AgentInfo, UsageEntry
from analyzer import reporter

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _stub_persona_loader(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def fake_load_profile(days_back: int = 30) -> persona_loader.PersonaProfile:
        return persona_loader.PersonaProfile(
            hour_histogram=[0] * 24,
            top_projects=[],
            recent_titles=[],
            total_sessions=0,
            total_messages=0,
        )

    monkeypatch.setattr("analyzer.reporter.persona_loader.load_profile", fake_load_profile)
    monkeypatch.setattr(reporter, "YEAR_CACHE_PATH", tmp_path / "year_cache.json")
    monkeypatch.setattr(reporter, "YEAR_LEDGER_PATH", tmp_path / "year_ledger.json")


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


def test_all_languages_have_analyze_label() -> None:
    bundle = json.loads((ROOT / "i18n.json").read_text(encoding="utf-8"))

    assert bundle["zh-TW"]["analyze_usage"] == "報告"
    assert bundle["zh-CN"]["analyze_usage"] == "报告"
    assert bundle["en"]["analyze_usage"] == "Report"
    assert bundle["ja"]["analyze_usage"] == "レポート"
    assert bundle["ko"]["analyze_usage"] == "리포트"
    assert bundle["zh-TW"]["report_ai_updates_original"] == "原文"
    assert bundle["zh-CN"]["report_ai_updates_original"] == "原文"
    assert bundle["en"]["report_ai_updates_original"] == "Original"
    assert bundle["ja"]["report_ai_updates_original"] == "原文"
    assert bundle["ko"]["report_ai_updates_original"] == "원문"
    for table in bundle.values():
        assert table["project_range_all"]


def test_all_languages_have_cli_statusline_labels() -> None:
    bundle = json.loads((ROOT / "i18n.json").read_text(encoding="utf-8"))

    expected = {
        "zh-TW": "終端",
        "zh-CN": "终端",
        "en": "Terminal",
        "ja": "ターミナル",
        "ko": "터미널",
    }
    for lang, table in bundle.items():
        label = expected[lang]
        assert table["cli"] == label
        assert table["cli_disabled"] == label
        assert table["cli_enabled"] == f"{label} ✓"
        removed_statusline_message_keys = {
            "statusline_" + suffix for suffix in ("installed", "uninstalled")
        }
        assert removed_statusline_message_keys.isdisjoint(table)
        assert not any(key.startswith("cli_five_hour") for key in table)


def test_load_year_data_cached_writes_missing_cache(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / ".usage" / "year_cache.json"
    agents = [AgentInfo("codex", "Codex", "~/.codex", True)]
    payload = _empty_year_payload()
    calls = 0

    def fake_build_year_data(received_agents: list[AgentInfo]) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        assert received_agents == agents
        return payload

    monkeypatch.setattr(reporter, "YEAR_CACHE_PATH", cache_path)
    monkeypatch.setattr(reporter, "build_year_data", fake_build_year_data)

    assert reporter._load_year_data_cached(agents) == payload

    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    assert calls == 1
    assert cache["schema_version"] == reporter._YEAR_CACHE_SCHEMA
    assert isinstance(cache["cached_at"], float)
    assert cache["data"] == payload


def test_load_year_data_cached_uses_fresh_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_path = reporter.YEAR_CACHE_PATH
    payload = _empty_year_payload()
    cache_path.write_text(
        json.dumps(
            {
                "schema_version": reporter._YEAR_CACHE_SCHEMA,
                "cached_at": time.time(),
                "data": payload,
            }
        ),
        encoding="utf-8",
    )

    def fail_build_year_data(_agents: list[AgentInfo]) -> dict[str, Any]:
        raise AssertionError("fresh year cache should not rebuild")

    monkeypatch.setattr(reporter, "build_year_data", fail_build_year_data)

    assert reporter._load_year_data_cached([]) == payload


def test_load_year_data_cached_rebuilds_expired_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_path = reporter.YEAR_CACHE_PATH
    stale_payload = _empty_year_payload()
    fresh_payload = _empty_year_payload()
    fresh_payload["wrapped"] = {**fresh_payload["wrapped"], "total_tokens": 99}
    cache_path.write_text(
        json.dumps(
            {
                "schema_version": reporter._YEAR_CACHE_SCHEMA,
                "cached_at": time.time() - reporter.YEAR_CACHE_TTL_SECONDS - 1,
                "data": stale_payload,
            }
        ),
        encoding="utf-8",
    )
    calls = 0

    def fake_build_year_data(_agents: list[AgentInfo]) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return fresh_payload

    monkeypatch.setattr(reporter, "build_year_data", fake_build_year_data)

    assert reporter._load_year_data_cached([]) == fresh_payload
    assert calls == 1
    assert json.loads(cache_path.read_text(encoding="utf-8"))["data"] == fresh_payload


def test_load_year_data_cached_rebuilds_bad_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_path = reporter.YEAR_CACHE_PATH
    payload = _empty_year_payload()
    cache_path.write_text("{bad json", encoding="utf-8")
    calls = 0

    def fake_build_year_data(_agents: list[AgentInfo]) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return payload

    monkeypatch.setattr(reporter, "build_year_data", fake_build_year_data)

    assert reporter._load_year_data_cached([]) == payload
    assert calls == 1


def test_load_year_data_cached_rebuilds_schema_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_path = reporter.YEAR_CACHE_PATH
    stale_payload = _empty_year_payload()
    fresh_payload = _empty_year_payload()
    fresh_payload["wrapped"] = {**fresh_payload["wrapped"], "active_days": 3}
    cache_path.write_text(
        json.dumps(
            {
                "schema_version": reporter._YEAR_CACHE_SCHEMA + 1,
                "cached_at": time.time(),
                "data": stale_payload,
            }
        ),
        encoding="utf-8",
    )
    calls = 0

    def fake_build_year_data(_agents: list[AgentInfo]) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return fresh_payload

    monkeypatch.setattr(reporter, "build_year_data", fake_build_year_data)

    assert reporter._load_year_data_cached([]) == fresh_payload
    assert calls == 1


def test_html_panels_expose_analyze_action() -> None:
    panels_dir = ROOT / "assets" / "panels"

    for path in panels_dir.glob("*.html"):
        html = path.read_text(encoding="utf-8")
        assert 'data-action="analyze"' in html, path.name
        assert 'data-i18n="analyze_usage"' in html, path.name
        assert "analyze_all" not in html, path.name
        assert "projectsAll" in html, path.name
        assert 'data-action="toggle-statusline"' in html, path.name


def test_generate_analysis_report_uses_analyzer_pipeline(
    monkeypatch: Any,
) -> None:
    agents = [AgentInfo("codex", "Codex", "~/.codex", True)]
    report_data: dict[str, object] = {"summary": {"total_tokens": 123}}
    calls: dict[str, object] = {}

    def fake_build_report_data(received_agents: list[AgentInfo], period: str) -> dict[str, object]:
        calls["agents"] = received_agents
        calls["period"] = period
        return report_data

    def fake_save_and_open(
        received_data: dict[str, object],
        *,
        language: str | None = None,
    ) -> str:
        calls["data"] = received_data
        calls["language"] = language
        return "~/.usage-reports/usage-report-test.html"

    monkeypatch.setattr("adapters.registry.detect_agents", lambda: agents)
    monkeypatch.setattr("analyzer.reporter.build_report_data", fake_build_report_data)
    monkeypatch.setattr("ui.html_report.save_and_open", fake_save_and_open)

    assert menubar._generate_analysis_report() == "~/.usage-reports/usage-report-test.html"
    assert calls == {"agents": agents, "period": "month", "data": report_data, "language": None}


def test_generate_analysis_report_propagates_language(
    monkeypatch: Any,
) -> None:
    agents = [AgentInfo("codex", "Codex", "~/.codex", True)]
    report_data: dict[str, object] = {"summary": {"total_tokens": 123}}
    calls: dict[str, object] = {}

    def fake_build_report_data(received_agents: list[AgentInfo], period: str) -> dict[str, object]:
        calls["agents"] = received_agents
        calls["period"] = period
        return report_data

    def fake_save_and_open(
        received_data: dict[str, object],
        *,
        language: str | None = None,
    ) -> str:
        calls["data"] = received_data
        calls["language"] = language
        return "~/.usage-reports/usage-report-test.html"

    monkeypatch.setattr("adapters.registry.detect_agents", lambda: agents)
    monkeypatch.setattr("analyzer.reporter.build_report_data", fake_build_report_data)
    monkeypatch.setattr("ui.html_report.save_and_open", fake_save_and_open)

    assert (
        menubar._generate_analysis_report(language="zh-TW")
        == "~/.usage-reports/usage-report-test.html"
    )
    assert calls == {"agents": agents, "period": "month", "data": report_data, "language": "zh-TW"}


def test_app_analyze_uses_project_range_period(
    monkeypatch: Any,
) -> None:
    calls: list[str] = []

    class InlineThread:
        def __init__(
            self,
            *,
            target: Any,
            args: tuple[Any, ...] = (),
            daemon: bool = False,
        ) -> None:
            self.target = target
            self.args = args

        def start(self) -> None:
            self.target(*self.args)

    delegate = menubar.AppDelegate.alloc().initWithMock_interval_(False, 60)
    monkeypatch.setattr("menubar.threading.Thread", InlineThread)

    def fake_generate_analysis_report(
        period: str = "month",
        language: str | None = None,
    ) -> str:
        calls.append(period)
        return "~/.usage-reports/report.html"

    monkeypatch.setattr(menubar, "_generate_analysis_report", fake_generate_analysis_report)
    monkeypatch.setattr(
        delegate,
        "performSelectorOnMainThread_withObject_waitUntilDone_",
        lambda *args: None,
    )

    delegate.analyzeUsage_(None)
    delegate.analyzeUsage_("all")

    assert calls == ["last30", "all"]


def test_analysis_period_from_project_range() -> None:
    assert menubar._analysis_period_from_project_range("1d") == "today"
    assert menubar._analysis_period_from_project_range("7d") == "last7"
    assert menubar._analysis_period_from_project_range("30d") == "last30"
    assert menubar._analysis_period_from_project_range("all") == "all"


def test_report_codex_entries_use_shared_loader(monkeypatch: Any) -> None:
    source_entry = history_loader.UsageEntry(
        timestamp=datetime(2026, 5, 21, tzinfo=UTC),
        session_id="s1",
        message_id="m1",
        request_id="r1",
        model="gpt-test",
        input_tokens=1,
        output_tokens=2,
        cache_creation_tokens=3,
        cache_read_tokens=4,
        cost_usd=0.5,
        project="usage",
    )
    calls: dict[str, int] = {}

    def fake_load_entries(*, hours_back: int = 0) -> list[history_loader.UsageEntry]:
        calls["hours_back"] = hours_back
        return [source_entry]

    monkeypatch.setattr("analyzer.reporter.codex_loader.load_entries", fake_load_entries)

    entries = reporter._load_agent_entries(AgentInfo("codex", "Codex", "~/.codex", True), 24)

    assert calls == {"hours_back": 24}
    assert len(entries) == 1
    assert entries[0].agent_id == "codex"
    assert entries[0].total_tokens == source_entry.total_tokens


def test_report_today_uses_expected_codex_hours_back(monkeypatch: Any) -> None:
    today = datetime.now(tz=UTC)
    agent = AgentInfo("codex", "Codex", "~/.codex", True)
    recent_entry = history_loader.UsageEntry(
        timestamp=today,
        session_id="recent",
        message_id="recent",
        request_id="",
        model="gpt-test",
        input_tokens=1,
        output_tokens=2,
        cache_creation_tokens=0,
        cache_read_tokens=0,
        cost_usd=0.01,
        project="usage",
    )
    calls: dict[str, int] = {}

    def fake_load_entries(*, hours_back: int = 0) -> list[history_loader.UsageEntry]:
        calls["hours_back"] = hours_back
        return [recent_entry]

    monkeypatch.setattr("analyzer.reporter.codex_loader.load_entries", fake_load_entries)
    monkeypatch.setattr(reporter, "build_year_data", lambda _agents: _empty_year_payload())

    data = reporter.build_report_data([agent], "today")

    assert data["summary"]["total_tokens"] == 3
    assert data["comparison"]["has_prev"] is False
    assert calls == {"hours_back": 48}


def test_report_week_includes_previous_period_comparison(monkeypatch: Any) -> None:
    class FixedDateTime:
        @staticmethod
        def now() -> datetime:
            return datetime(2026, 5, 21, 12, tzinfo=UTC)

    agent = AgentInfo("codex", "Codex", "~/.codex", True)
    entries = [
        UsageEntry(
            timestamp=datetime(2026, 5, 14, tzinfo=UTC),
            session_id="prev-1",
            message_id="prev-1",
            request_id="",
            model="gpt-5-mini",
            input_tokens=100,
            output_tokens=0,
            cache_creation_tokens=0,
            cache_read_tokens=0,
            cost_usd=1.0,
            project="old",
            agent_id="codex",
        ),
        UsageEntry(
            timestamp=datetime(2026, 5, 15, tzinfo=UTC),
            session_id="prev-2",
            message_id="prev-2",
            request_id="",
            model="gpt-5-codex",
            input_tokens=300,
            output_tokens=0,
            cache_creation_tokens=0,
            cache_read_tokens=0,
            cost_usd=3.0,
            project="usage",
            agent_id="codex",
        ),
        UsageEntry(
            timestamp=datetime(2026, 5, 18, tzinfo=UTC),
            session_id="cur-1",
            message_id="cur-1",
            request_id="",
            model="gpt-5-codex",
            input_tokens=600,
            output_tokens=0,
            cache_creation_tokens=0,
            cache_read_tokens=0,
            cost_usd=6.0,
            project="usage",
            agent_id="codex",
        ),
    ]
    calls: dict[str, int] = {}

    def fake_load_agent_entries(
        received_agent: AgentInfo,
        hours_back: int = 0,
    ) -> list[UsageEntry]:
        assert received_agent == agent
        calls["hours_back"] = hours_back
        return entries

    monkeypatch.setattr(reporter, "datetime", FixedDateTime)
    monkeypatch.setattr(reporter, "_load_agent_entries", fake_load_agent_entries)
    monkeypatch.setattr("analyzer.reporter.subscription.load_subscriptions", lambda: [])
    monkeypatch.setattr(reporter, "build_year_data", lambda _agents: _empty_year_payload())

    data = reporter.build_report_data([agent], "week")

    assert calls == {"hours_back": 216}
    assert data["summary"]["total_tokens"] == 600
    assert data["comparison"] == {
        "period": "week",
        "has_prev": True,
        "prev_tokens": 400,
        "prev_cost": 4.0,
        "prev_projects": ["old", "usage"],
        "prev_model_share": {"gpt-5-codex": 75.0, "gpt-5-mini": 25.0},
    }


def test_report_last7_includes_previous_period_comparison(monkeypatch: Any) -> None:
    class FixedDateTime:
        @staticmethod
        def now() -> datetime:
            return datetime(2026, 5, 21, 12, tzinfo=UTC)

    agent = AgentInfo("codex", "Codex", "~/.codex", True)
    entries = [
        UsageEntry(
            timestamp=datetime(2026, 5, 8, tzinfo=UTC),
            session_id="prev-1",
            message_id="prev-1",
            request_id="",
            model="gpt-5-mini",
            input_tokens=100,
            output_tokens=0,
            cache_creation_tokens=0,
            cache_read_tokens=0,
            cost_usd=1.0,
            project="old",
            agent_id="codex",
        ),
        UsageEntry(
            timestamp=datetime(2026, 5, 14, tzinfo=UTC),
            session_id="prev-2",
            message_id="prev-2",
            request_id="",
            model="gpt-5-codex",
            input_tokens=300,
            output_tokens=0,
            cache_creation_tokens=0,
            cache_read_tokens=0,
            cost_usd=3.0,
            project="usage",
            agent_id="codex",
        ),
        UsageEntry(
            timestamp=datetime(2026, 5, 15, tzinfo=UTC),
            session_id="cur-1",
            message_id="cur-1",
            request_id="",
            model="gpt-5-codex",
            input_tokens=600,
            output_tokens=0,
            cache_creation_tokens=0,
            cache_read_tokens=0,
            cost_usd=6.0,
            project="usage",
            agent_id="codex",
        ),
    ]
    calls: dict[str, int] = {}

    def fake_load_agent_entries(
        received_agent: AgentInfo,
        hours_back: int = 0,
    ) -> list[UsageEntry]:
        assert received_agent == agent
        calls["hours_back"] = hours_back
        return entries

    monkeypatch.setattr(reporter, "datetime", FixedDateTime)
    monkeypatch.setattr(reporter, "_load_agent_entries", fake_load_agent_entries)
    monkeypatch.setattr("analyzer.reporter.subscription.load_subscriptions", lambda: [])
    monkeypatch.setattr(reporter, "build_year_data", lambda _agents: _empty_year_payload())

    data = reporter.build_report_data([agent], "last7")

    assert calls == {"hours_back": 360}
    assert data["summary"]["total_tokens"] == 600
    assert data["comparison"] == {
        "period": "last7",
        "has_prev": True,
        "prev_tokens": 400,
        "prev_cost": 4.0,
        "prev_projects": ["old", "usage"],
        "prev_model_share": {"gpt-5-codex": 75.0, "gpt-5-mini": 25.0},
    }


def test_build_report_data_includes_serialized_persona(monkeypatch: Any) -> None:
    histogram = [0] * 24
    histogram[9] = 3
    calls: list[int] = []

    def fake_load_profile(days_back: int = 30) -> persona_loader.PersonaProfile:
        calls.append(days_back)
        return persona_loader.PersonaProfile(
            hour_histogram=histogram,
            top_projects=[("do-not-render-here", 9)],
            recent_titles=["Ship HTML report"],
            total_sessions=2,
            total_messages=3,
        )

    monkeypatch.setattr("analyzer.reporter.persona_loader.load_profile", fake_load_profile)
    monkeypatch.setattr("analyzer.reporter.subscription.load_subscriptions", lambda: [])

    data = reporter.build_report_data([], "last7")

    assert calls == [7]
    assert data["persona"] == {
        "hour_histogram": histogram,
        "recent_titles": ["Ship HTML report"],
    }
    assert len(data["persona"]["hour_histogram"]) == 24
    assert isinstance(data["persona"]["recent_titles"], list)


def test_build_report_data_includes_ai_updates(monkeypatch: Any) -> None:
    monkeypatch.setattr("analyzer.reporter.subscription.load_subscriptions", lambda: [])
    monkeypatch.setattr(
        "analyzer.reporter.ai_updates_loader.load_ai_updates",
        lambda: [{"id": "codex"}],
    )

    data = reporter.build_report_data([], "last7")

    assert data["ai_updates"] == [{"id": "codex"}]


def test_report_today_uses_codex_token_count_deltas(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    codex_loader._jsonl_cache.clear()
    sessions_dir = tmp_path / "sessions"
    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(codex_loader, "LOGS_DB", tmp_path / "missing-logs.sqlite")
    monkeypatch.setattr(codex_loader, "_load_thread_models", lambda: {"session-1": "gpt-test"})
    now = datetime.now().astimezone()
    yesterday = now - timedelta(days=1)
    lines = [
        {
            "type": "session_meta",
            "payload": {
                "id": "session-1",
                "timestamp": yesterday.isoformat(),
                "cwd": "/tmp/usage",
            },
        },
        {
            "type": "event_msg",
            "timestamp": yesterday.isoformat(),
            "payload": {
                "type": "token_count",
                "info": {
                    "total_token_usage": {
                        "input_tokens": 100,
                        "cached_input_tokens": 10,
                        "output_tokens": 20,
                    }
                },
            },
        },
        {
            "type": "event_msg",
            "timestamp": now.isoformat(),
            "payload": {
                "type": "token_count",
                "info": {
                    "total_token_usage": {
                        "input_tokens": 150,
                        "cached_input_tokens": 15,
                        "output_tokens": 35,
                    }
                },
            },
        },
    ]
    path = sessions_dir / "session-1.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")

    data = reporter.build_report_data(
        [AgentInfo("codex", "Codex", "~/.codex", True)],
        "today",
    )

    assert data["summary"]["total_tokens"] == 65


def test_build_year_data_computes_streaks_across_month_boundary(monkeypatch: Any) -> None:
    class FixedDateTime:
        @staticmethod
        def now() -> datetime:
            return datetime(2026, 6, 3, 9, tzinfo=UTC)

    agent = AgentInfo("codex", "Codex", "~/.codex", True)
    entries = [
        UsageEntry(
            timestamp=datetime(2026, 5, 29, 12, tzinfo=UTC),
            session_id="s1",
            message_id="m1",
            request_id="",
            model="gpt-5-codex",
            input_tokens=20,
            output_tokens=0,
            cache_creation_tokens=0,
            cache_read_tokens=0,
            cost_usd=1.0,
            project="usage",
            agent_id="codex",
        ),
        UsageEntry(
            timestamp=datetime(2026, 5, 30, 12, tzinfo=UTC),
            session_id="s2",
            message_id="m2",
            request_id="",
            model="gpt-5-codex",
            input_tokens=30,
            output_tokens=0,
            cache_creation_tokens=0,
            cache_read_tokens=0,
            cost_usd=1.0,
            project="usage",
            agent_id="codex",
        ),
        UsageEntry(
            timestamp=datetime(2026, 5, 31, 12, tzinfo=UTC),
            session_id="s3",
            message_id="m3",
            request_id="",
            model="gpt-5-codex",
            input_tokens=40,
            output_tokens=0,
            cache_creation_tokens=0,
            cache_read_tokens=0,
            cost_usd=1.0,
            project="usage",
            agent_id="codex",
        ),
        UsageEntry(
            timestamp=datetime(2026, 6, 1, 12, tzinfo=UTC),
            session_id="s4",
            message_id="m4",
            request_id="",
            model="gpt-5-codex",
            input_tokens=50,
            output_tokens=0,
            cache_creation_tokens=0,
            cache_read_tokens=0,
            cost_usd=1.0,
            project="usage",
            agent_id="codex",
        ),
        UsageEntry(
            timestamp=datetime(2026, 6, 3, 12, tzinfo=UTC),
            session_id="s5",
            message_id="m5",
            request_id="",
            model="gpt-5-codex",
            input_tokens=90,
            output_tokens=0,
            cache_creation_tokens=0,
            cache_read_tokens=0,
            cost_usd=1.0,
            project="usage",
            agent_id="codex",
        ),
    ]

    monkeypatch.setattr(reporter, "datetime", FixedDateTime)
    monkeypatch.setattr(reporter, "_load_agent_entries", lambda _agent, _hours_back=0: entries)
    monkeypatch.setattr(reporter, "calculate_cost", lambda entry: float(entry.input_tokens) / 10)

    data = reporter.build_year_data([agent])

    assert data["contribution"]["active_days"] == 5
    assert data["contribution"]["current_streak"] == 1
    assert data["contribution"]["longest_streak"] == 4
    assert data["contribution"]["busiest_day"] == {"date": "2026-06-03", "tokens": 90}
    assert data["wrapped"]["longest_streak"] == 4


def test_build_year_data_keeps_ledger_days_missing_from_current_entries(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    class FixedDateTime:
        @staticmethod
        def now() -> datetime:
            return datetime(2026, 6, 21, 12, tzinfo=UTC)

    agent = AgentInfo("codex", "Codex", "~/.codex", True)
    first_day = UsageEntry(
        timestamp=datetime(2026, 6, 17, 10, tzinfo=UTC),
        session_id="a",
        message_id="a",
        request_id="",
        model="gpt-5-codex",
        input_tokens=100,
        output_tokens=0,
        cache_creation_tokens=0,
        cache_read_tokens=0,
        cost_usd=1.0,
        project="usage",
        agent_id="codex",
    )
    second_day = UsageEntry(
        timestamp=datetime(2026, 6, 18, 10, tzinfo=UTC),
        session_id="b",
        message_id="b",
        request_id="",
        model="gpt-5-codex",
        input_tokens=200,
        output_tokens=0,
        cache_creation_tokens=0,
        cache_read_tokens=0,
        cost_usd=2.0,
        project="usage",
        agent_id="codex",
    )
    entry_batches = [[first_day, second_day], [second_day]]

    def fake_load_agent_entries(
        received_agent: AgentInfo,
        hours_back: int = 0,
    ) -> list[UsageEntry]:
        assert received_agent == agent
        assert hours_back > 0
        return entry_batches.pop(0)

    ledger_path = tmp_path / ".usage" / "year_ledger.json"
    monkeypatch.setattr(reporter, "YEAR_LEDGER_PATH", ledger_path)
    monkeypatch.setattr(reporter, "datetime", FixedDateTime)
    monkeypatch.setattr(reporter, "_load_agent_entries", fake_load_agent_entries)
    monkeypatch.setattr(reporter, "calculate_cost", lambda entry: float(entry.cost_usd or 0.0))

    reporter.build_year_data([agent])
    data = reporter.build_year_data([agent])

    cells = {
        cell["date"]: cell
        for week in data["contribution"]["weeks"]
        for cell in week
    }
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))

    assert cells["2026-06-17"]["tokens"] == 100
    assert cells["2026-06-18"]["tokens"] == 200
    assert data["wrapped"]["total_tokens"] == 300
    assert data["wrapped"]["active_days"] == 2
    assert ledger["days"]["2026-06-17"]["total_tokens"] == 100


def test_contribution_level_uses_quantile_thresholds_for_edges() -> None:
    assert reporter._contribution_thresholds([]) == []
    assert reporter._contribution_level(0, []) == 0

    one_day_thresholds = reporter._contribution_thresholds([100])
    assert one_day_thresholds == [100, 100, 100, 100]
    assert reporter._contribution_level(100, one_day_thresholds) == 1

    same_thresholds = reporter._contribution_thresholds([50, 50, 50])
    assert same_thresholds == [50, 50, 50, 50]
    assert [reporter._contribution_level(50, same_thresholds) for _ in range(3)] == [1, 1, 1]

    sparse_thresholds = reporter._contribution_thresholds([10, 20, 30])
    assert sparse_thresholds == [10, 20, 30, 30]
    sparse_levels = [
        reporter._contribution_level(tokens, sparse_thresholds)
        for tokens in [10, 20, 30]
    ]
    assert sparse_levels == [1, 2, 3]


def test_build_year_data_uses_quantile_levels_and_selects_dragon(monkeypatch: Any) -> None:
    class FixedDateTime:
        @staticmethod
        def now() -> datetime:
            return datetime(2026, 6, 21, 12, tzinfo=UTC)

    agent = AgentInfo("codex", "Codex", "~/.codex", True)
    entries = [
        UsageEntry(
            timestamp=datetime(2026, 6, 15, 10, tzinfo=UTC),
            session_id="s1",
            message_id="m1",
            request_id="",
            model="gpt-5-codex",
            input_tokens=1000,
            output_tokens=0,
            cache_creation_tokens=0,
            cache_read_tokens=0,
            cost_usd=0.1,
            project="tiny",
            agent_id="codex",
        ),
        UsageEntry(
            timestamp=datetime(2026, 6, 16, 10, tzinfo=UTC),
            session_id="s2",
            message_id="m2",
            request_id="",
            model="gpt-5-codex",
            input_tokens=2000,
            output_tokens=0,
            cache_creation_tokens=0,
            cache_read_tokens=0,
            cost_usd=0.1,
            project="small",
            agent_id="codex",
        ),
        UsageEntry(
            timestamp=datetime(2026, 6, 17, 10, tzinfo=UTC),
            session_id="s3",
            message_id="m3",
            request_id="",
            model="gpt-5-codex",
            input_tokens=3000,
            output_tokens=0,
            cache_creation_tokens=0,
            cache_read_tokens=0,
            cost_usd=0.1,
            project="medium",
            agent_id="codex",
        ),
        UsageEntry(
            timestamp=datetime(2026, 6, 18, 10, tzinfo=UTC),
            session_id="s4",
            message_id="m4",
            request_id="",
            model="gpt-5-codex",
            input_tokens=4000,
            output_tokens=0,
            cache_creation_tokens=0,
            cache_read_tokens=0,
            cost_usd=0.1,
            project="huge",
            agent_id="codex",
        ),
        UsageEntry(
            timestamp=datetime(2026, 6, 18, 11, tzinfo=UTC),
            session_id="c1",
            message_id="c1",
            request_id="",
            model="claude-sonnet-4",
            input_tokens=500,
            output_tokens=0,
            cache_creation_tokens=0,
            cache_read_tokens=0,
            cost_usd=0.1,
            project="claude-side",
            agent_id="claude-code",
        ),
    ]

    monkeypatch.setattr(reporter, "datetime", FixedDateTime)
    monkeypatch.setattr(reporter, "_load_agent_entries", lambda _agent, _hours_back=0: entries)
    monkeypatch.setattr(reporter, "calculate_cost", lambda _entry: 0.25)

    data = reporter.build_year_data([agent])
    levels = {
        cell["date"]: cell["level"]
        for week in data["contribution"]["weeks"]
        for cell in week
        if cell["tokens"] > 0
    }

    assert levels["2026-06-15"] == 1
    assert levels["2026-06-16"] == 2
    assert levels["2026-06-17"] == 3
    assert levels["2026-06-18"] == 4
    assert data["wrapped"]["beast"] == "dragon"
    assert data["wrapped"]["top_project"] == "huge"


def test_build_year_data_prefers_phoenix_on_tie(monkeypatch: Any) -> None:
    class FixedDateTime:
        @staticmethod
        def now() -> datetime:
            return datetime(2026, 6, 21, 12, tzinfo=UTC)

    agents = [
        AgentInfo("claude-code", "Claude Code", "~/.claude", True),
        AgentInfo("codex", "Codex", "~/.codex", True),
    ]
    entries = [
        UsageEntry(
            timestamp=datetime(2026, 6, 20, 10, tzinfo=UTC),
            session_id="claude",
            message_id="claude",
            request_id="",
            model="claude-sonnet-4",
            input_tokens=100,
            output_tokens=0,
            cache_creation_tokens=0,
            cache_read_tokens=0,
            cost_usd=1.0,
            project="shared",
            agent_id="claude-code",
        ),
        UsageEntry(
            timestamp=datetime(2026, 6, 20, 11, tzinfo=UTC),
            session_id="codex",
            message_id="codex",
            request_id="",
            model="gpt-5-codex",
            input_tokens=100,
            output_tokens=0,
            cache_creation_tokens=0,
            cache_read_tokens=0,
            cost_usd=1.0,
            project="shared",
            agent_id="codex",
        ),
    ]

    monkeypatch.setattr(reporter, "datetime", FixedDateTime)
    monkeypatch.setattr(
        reporter,
        "_load_agent_entries",
        lambda agent, _hours_back=0: [
            entry for entry in entries if entry.agent_id == agent.id
        ],
    )
    monkeypatch.setattr(reporter, "calculate_cost", lambda _entry: 1.0)

    data = reporter.build_year_data(agents)

    assert data["wrapped"]["beast"] == "phoenix"
    assert data["wrapped"]["claude_tokens"] == 100
    assert data["wrapped"]["codex_tokens"] == 100


def test_report_last30_uses_expected_codex_hours_back(monkeypatch: Any) -> None:
    agent = AgentInfo("codex", "Codex", "~/.codex", True)
    calls: dict[str, int] = {}

    def fake_full(*, hours_back: int = 0) -> list[history_loader.UsageEntry]:
        calls["full_hours_back"] = hours_back
        return []

    monkeypatch.setattr("analyzer.reporter.codex_loader.load_entries", fake_full)
    monkeypatch.setattr(reporter, "build_year_data", lambda _agents: _empty_year_payload())

    reporter.build_report_data([agent], "last30")

    assert calls == {"full_hours_back": 744}


def test_build_report_data_by_model_includes_cost_known(monkeypatch: Any) -> None:
    """by_model entries include cost_known field for pricing availability."""
    from datetime import UTC, datetime

    from adapters.types import UsageEntry

    # Mix of priced and unpriced models
    fixed_date = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    entries = [
        UsageEntry(
            timestamp=fixed_date,
            session_id="s1",
            message_id="m1",
            request_id="r1",
            model="claude-opus-4-8",
            input_tokens=1000,
            output_tokens=500,
            cache_creation_tokens=0,
            cache_read_tokens=0,
            cost_usd=None,
            project="test",
            agent_id="claude-code",
            message_count=1,
        ),
        UsageEntry(
            timestamp=fixed_date.replace(hour=13),
            session_id="s2",
            message_id="m2",
            request_id="r2",
            model="glm-5.2",  # Unpriced model
            input_tokens=2000,
            output_tokens=1000,
            cache_creation_tokens=0,
            cache_read_tokens=0,
            cost_usd=None,
            project="test",
            agent_id="claude-code",
            message_count=1,
        ),
    ]

    # Mock _load_agent_entries directly to avoid loading real data
    monkeypatch.setattr("analyzer.reporter._load_agent_entries", lambda agent, hours_back: entries)
    monkeypatch.setattr("analyzer.reporter.subscription.load_subscriptions", lambda: [])
    # Mock _load_persona_for_period to return None directly
    monkeypatch.setattr("analyzer.reporter._load_persona_for_period", lambda period: None)
    # cost_known must not depend on real LiteLLM pricing (offline CI has none)
    monkeypatch.setattr(
        "analyzer.reporter.is_model_priced",
        lambda model: model == "claude-opus-4-8",
    )
    # Pin datetime.now() to fixed_date
    from datetime import tzinfo

    class _FixedDateTime:
        @staticmethod
        def now(tz: tzinfo | None = None) -> datetime:
            return fixed_date.astimezone(tz) if tz else fixed_date.replace(tzinfo=None)

    monkeypatch.setattr("analyzer.reporter.datetime", _FixedDateTime)

    agent = AgentInfo("claude-code", "Claude Code", "~/.claude", True)
    data = reporter.build_report_data([agent], "today")

    by_model = data.get("by_model", [])
    assert len(by_model) == 2

    # Find the priced model (claude-opus-4-8)
    priced_model = next((m for m in by_model if m["model"] == "claude-opus-4-8"), None)
    assert priced_model is not None
    assert priced_model.get("cost_known") is True

    # Find the unpriced model (glm-5.2)
    unpriced_model = next((m for m in by_model if m["model"] == "glm-5.2"), None)
    assert unpriced_model is not None
    assert unpriced_model.get("cost_known") is False

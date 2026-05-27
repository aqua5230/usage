from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import codex_loader
import history_loader
import menubar
from adapters.types import AgentInfo
from analyzer import reporter

ROOT = Path(__file__).resolve().parents[1]


def test_all_languages_have_analyze_label() -> None:
    bundle = json.loads((ROOT / "i18n.json").read_text(encoding="utf-8"))

    assert bundle["zh-TW"]["analyze_usage"] == "報告"
    assert bundle["zh-CN"]["analyze_usage"] == "报告"
    assert bundle["en"]["analyze_usage"] == "Report"
    assert bundle["ja"]["analyze_usage"] == "レポート"
    assert bundle["ko"]["analyze_usage"] == "리포트"
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

    assert calls == ["month", "all"]


def test_analysis_period_from_project_range() -> None:
    assert menubar._analysis_period_from_project_range("1d") == "today"
    assert menubar._analysis_period_from_project_range("7d") == "week"
    assert menubar._analysis_period_from_project_range("30d") == "month"
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


def test_report_short_periods_use_recent_codex_loader(monkeypatch: Any) -> None:
    today = datetime.now(tz=UTC)
    agent = AgentInfo("codex", "Codex", "~/.codex", True)
    recent_entry = reporter.UsageEntry(
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
        agent_id="codex",
    )
    calls: dict[str, int] = {}

    def fake_load_entries(*, hours_back: int = 0) -> list[history_loader.UsageEntry]:
        calls["hours_back"] = hours_back
        return [recent_entry]

    monkeypatch.setattr("analyzer.reporter.codex_loader.load_entries", fake_load_entries)

    data = reporter.build_report_data([agent], "today")

    assert data["summary"]["total_tokens"] == 3
    assert calls == {"hours_back": 48}


def test_report_today_uses_codex_token_count_deltas(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    codex_loader._jsonl_cache.clear()
    sessions_dir = tmp_path / "sessions"
    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", sessions_dir)
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


def test_report_last30_keeps_full_codex_loader(monkeypatch: Any) -> None:
    agent = AgentInfo("codex", "Codex", "~/.codex", True)
    calls: dict[str, int] = {}

    def fake_recent(hours_back: int) -> list[reporter.UsageEntry]:
        calls["recent_hours_back"] = hours_back
        return []

    def fake_full(*, hours_back: int = 0) -> list[history_loader.UsageEntry]:
        calls["full_hours_back"] = hours_back
        return []

    monkeypatch.setattr(reporter, "_load_recent_codex_entries", fake_recent)
    monkeypatch.setattr("analyzer.reporter.codex_loader.load_entries", fake_full)

    reporter.build_report_data([agent], "last30")

    assert calls == {"full_hours_back": 744}

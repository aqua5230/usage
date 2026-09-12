# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any, Self

import pytest

from adapters.types import AgentInfo, UsageEntry
from analyzer import reporter, usage_snapshot
from analyzer.aggregator import aggregate_sessions
from loaders import cache_quarantine
from ui import html_report

_GENERATED_AT = re.compile(
    r"(產生時間|Generated|生成时间|生成日時|생성 시간) [^<\n]+"
)


@pytest.fixture
def snapshot_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    path = tmp_path / "usage_snapshot.json"
    monkeypatch.setattr(usage_snapshot, "SNAPSHOT_PATH", path)
    monkeypatch.setattr(cache_quarantine, "QUARANTINE_DIR", tmp_path / "quarantine")
    return path


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


def _fixed_datetime(fixed: datetime) -> type[Any]:
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
    session_id: str = "sess-1",
    model: str = "gpt-5",
    project: str = "usage",
    agent_id: str = "codex",
    input_tokens: int = 100,
    output_tokens: int = 0,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
    cost_usd: float = 1.0,
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


def _entry_date_utc(entry: UsageEntry) -> date:
    ts = entry.timestamp
    if ts.tzinfo:
        ts = ts.astimezone(UTC)
    return ts.date()


@pytest.fixture
def _sandbox_report(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    snapshot_path: Path,
) -> Iterator[None]:
    original_tz = os.environ.get("TZ")
    os.environ["TZ"] = "UTC"
    if hasattr(time, "tzset"):
        time.tzset()

    def _date_utc(ts: datetime) -> date:
        if ts.tzinfo:
            ts = ts.astimezone(UTC)
        return ts.date()

    monkeypatch.setattr(reporter, "_entry_date", _entry_date_utc)
    monkeypatch.setattr(usage_snapshot, "_entry_date", _entry_date_utc)
    monkeypatch.setattr(usage_snapshot, "_datetime_local_date", _date_utc)
    monkeypatch.setattr(usage_snapshot, "_local_tz", lambda: UTC)
    monkeypatch.setattr(reporter, "YEAR_CACHE_PATH", tmp_path / "year_cache.json")
    monkeypatch.setattr(reporter, "YEAR_LEDGER_PATH", tmp_path / "year_ledger.json")
    monkeypatch.setattr(reporter, "_load_year_data_cached", lambda _agents: _empty_year_payload())
    monkeypatch.setattr(reporter, "_load_persona_for_period", lambda _period: None)
    monkeypatch.setattr(reporter, "is_model_priced", lambda model: model != "unknown")
    monkeypatch.setattr("analyzer.reporter.subscription.load_subscriptions", lambda: [])
    monkeypatch.setattr(html_report, "_detect_lang", lambda env=None: "zh-TW")
    monkeypatch.setattr(html_report, "_version", lambda: "0.30.14")
    yield
    if original_tz is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = original_tz
    if hasattr(time, "tzset"):
        time.tzset()


def _without_generated(html: str) -> str:
    return _GENERATED_AT.sub(r"\1", html, count=1)


def test_replay_empty_snapshot_returns_nothing(snapshot_path: Path) -> None:
    assert usage_snapshot.replay_entries(date(2026, 9, 1), date(2026, 9, 30)) == []


def test_replay_single_row_duration_zero(snapshot_path: Path) -> None:
    entry = _entry(when=datetime(2026, 9, 1, 12, 0), input_tokens=40, output_tokens=10)
    usage_snapshot.record_entries([entry])

    replayed = usage_snapshot.replay_entries(date(2026, 9, 1), date(2026, 9, 1))

    assert len(replayed) == 1
    assert replayed[0].input_tokens == 40
    assert replayed[0].output_tokens == 10
    assert replayed[0].cost_usd == 1.0
    assert replayed[0].message_count == 1
    assert replayed[0].timestamp == datetime(2026, 9, 1, 12, 0)
    assert replayed[0].message_id.startswith("usage-snapshot:")


def test_replay_duration_placeholder_same_day(snapshot_path: Path) -> None:
    first = _entry(when=datetime(2026, 9, 1, 12, 0), input_tokens=10, cost_usd=0.5)
    last = _entry(when=datetime(2026, 9, 1, 12, 30), input_tokens=20, cost_usd=0.5)
    usage_snapshot.record_entries([first, last])

    replayed = usage_snapshot.replay_entries(date(2026, 9, 1), date(2026, 9, 1))

    assert len(replayed) == 2
    assert replayed[0].total_tokens == 30
    assert replayed[0].message_count == 2
    assert replayed[1].total_tokens == 0
    assert replayed[1].message_count == 0
    assert replayed[1].cost_usd == 0.0
    sessions = aggregate_sessions(replayed)
    assert len(sessions) == 1
    assert sessions[0].duration_minutes == 30.0


def test_replay_cost_zero_row(snapshot_path: Path) -> None:
    entry = _entry(when=datetime(2026, 9, 1, 12, 0), cost_usd=0.0, input_tokens=7)
    usage_snapshot.record_entries([entry])

    replayed = usage_snapshot.replay_entries(date(2026, 9, 1), date(2026, 9, 1))

    assert len(replayed) == 1
    assert replayed[0].cost_usd == 0.0
    assert replayed[0].input_tokens == 7


def test_replay_skips_days_outside_range(snapshot_path: Path) -> None:
    usage_snapshot.record_entries(
        [
            _entry(when=datetime(2026, 9, 1, 12, 0), session_id="a"),
            _entry(when=datetime(2026, 9, 3, 12, 0), session_id="b"),
        ]
    )

    replayed = usage_snapshot.replay_entries(date(2026, 9, 2), date(2026, 9, 2))

    assert replayed == []


def test_replay_cross_midnight_keeps_day_split_and_duration(
    snapshot_path: Path, _sandbox_report: None
) -> None:
    first = _entry(
        when=datetime(2026, 9, 1, 23, 0, tzinfo=UTC),
        input_tokens=10,
        cost_usd=0.25,
    )
    second = _entry(
        when=datetime(2026, 9, 2, 1, 0, tzinfo=UTC),
        input_tokens=20,
        cost_usd=0.75,
    )
    usage_snapshot.record_entries([first, second])

    replayed = usage_snapshot.replay_entries(date(2026, 9, 1), date(2026, 9, 2))
    by_date: dict[date, int] = {}
    for entry in replayed:
        day = _entry_date_utc(entry)
        by_date[day] = by_date.get(day, 0) + entry.total_tokens

    assert by_date[date(2026, 9, 1)] == 10
    assert by_date[date(2026, 9, 2)] == 20
    sessions = aggregate_sessions(replayed)
    assert len(sessions) == 1
    assert sessions[0].duration_minutes == 120.0
    assert sessions[0].start_time == datetime(2026, 9, 1, 23, 0, tzinfo=UTC)


def test_replay_same_session_two_days_two_models(
    snapshot_path: Path, _sandbox_report: None
) -> None:
    first = _entry(
        when=datetime(2026, 9, 1, 23, 0, tzinfo=UTC),
        model="gpt-5",
        input_tokens=10,
        cost_usd=1.0,
    )
    second = _entry(
        when=datetime(2026, 9, 2, 1, 0, tzinfo=UTC),
        model="gpt-5-codex",
        input_tokens=50,
        cost_usd=2.0,
    )
    usage_snapshot.record_entries([first, second])

    replayed = usage_snapshot.replay_entries(date(2026, 9, 1), date(2026, 9, 2))
    sessions = aggregate_sessions(replayed)
    assert len(sessions) == 1
    assert sessions[0].model == "gpt-5-codex"
    assert sessions[0].duration_minutes == 120.0
    assert sessions[0].total_tokens == 60


def test_html_identical_after_entries_cleared(
    monkeypatch: pytest.MonkeyPatch,
    snapshot_path: Path,
    _sandbox_report: None,
) -> None:
    fixed_now = datetime(2026, 9, 10, 18, tzinfo=UTC)
    agent = AgentInfo("codex", "Codex", "~/.codex", True)
    entries = [
        _entry(
            when=datetime(2026, 9, 5, 9, 0, tzinfo=UTC),
            session_id="long",
            input_tokens=10,
            output_tokens=5,
            cache_creation_tokens=2,
            cache_read_tokens=3,
            cost_usd=1.25,
        ),
        _entry(
            when=datetime(2026, 9, 5, 9, 45, tzinfo=UTC),
            session_id="long",
            input_tokens=20,
            output_tokens=10,
            cost_usd=2.5,
        ),
        _entry(
            when=datetime(2026, 9, 8, 14, 0, tzinfo=UTC),
            session_id="short",
            model="gpt-5-codex",
            project="ops",
            input_tokens=40,
            cost_usd=0.0,
        ),
        _entry(
            when=datetime(2026, 9, 9, 23, 0, tzinfo=UTC),
            session_id="overnight",
            project="client",
            input_tokens=8,
            cost_usd=0.4,
        ),
        _entry(
            when=datetime(2026, 9, 10, 1, 0, tzinfo=UTC),
            session_id="overnight",
            project="client",
            input_tokens=12,
            cost_usd=0.6,
        ),
    ]

    monkeypatch.setattr(reporter, "datetime", _fixed_datetime(fixed_now))
    monkeypatch.setattr(html_report, "datetime", _fixed_datetime(fixed_now))
    monkeypatch.setattr(reporter, "_load_agent_entries", lambda _agent, _hours: entries)

    data_a = reporter.build_report_data([agent], "all")
    html_a = html_report.generate_html(data_a, language="zh-TW")

    monkeypatch.setattr(reporter, "_load_agent_entries", lambda _agent, _hours: [])
    data_b = reporter.build_report_data([agent], "all")
    html_b = html_report.generate_html(data_b, language="zh-TW")

    stripped_a = _without_generated(html_a)
    stripped_b = _without_generated(html_b)
    if stripped_a != stripped_b:
        for index, (char_a, char_b) in enumerate(zip(stripped_a, stripped_b, strict=False)):
            if char_a != char_b:
                start = max(0, index - 80)
                pytest.fail(
                    f"HTML differed at {index}:\n"
                    f"A: {stripped_a[start:index + 80]!r}\n"
                    f"B: {stripped_b[start:index + 80]!r}"
                )
        pytest.fail(
            f"HTML length differed: {len(stripped_a)} vs {len(stripped_b)}"
        )

    assert data_a["top_sessions"][0]["duration_min"] == data_b["top_sessions"][0]["duration_min"]
    assert {row["duration_min"] for row in data_a["top_sessions"]} == {
        row["duration_min"] for row in data_b["top_sessions"]
    }


def test_comparison_period_filled_from_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    snapshot_path: Path,
    _sandbox_report: None,
) -> None:
    fixed_now = datetime(2026, 9, 10, 18, tzinfo=UTC)
    agent = AgentInfo("codex", "Codex", "~/.codex", True)
    prev = _entry(
        when=datetime(2026, 8, 30, 12, tzinfo=UTC),
        session_id="prev",
        input_tokens=100,
        output_tokens=20,
        cost_usd=5.0,
        project="legacy",
        model="gpt-5-mini",
    )
    current = _entry(
        when=datetime(2026, 9, 8, 12, tzinfo=UTC),
        session_id="cur",
        input_tokens=50,
        cost_usd=2.0,
    )
    usage_snapshot.record_entries([prev, current])

    monkeypatch.setattr(reporter, "datetime", _fixed_datetime(fixed_now))
    monkeypatch.setattr(reporter, "_load_agent_entries", lambda _agent, _hours: [])

    data = reporter.build_report_data([agent], "last7")

    assert data["summary"]["total_tokens"] == 50
    assert data["comparison"]["has_prev"] is True
    assert data["comparison"]["prev_tokens"] == 120
    assert data["comparison"]["prev_cost"] == 5.0
    assert data["comparison"]["prev_projects"] == ["legacy"]


def test_period_all_uses_snapshot_earliest_date(
    monkeypatch: pytest.MonkeyPatch,
    snapshot_path: Path,
    _sandbox_report: None,
) -> None:
    fixed_now = datetime(2026, 9, 10, 18, tzinfo=UTC)
    agent = AgentInfo("codex", "Codex", "~/.codex", True)
    old = _entry(
        when=datetime(2026, 8, 1, 12, tzinfo=UTC),
        session_id="old",
        input_tokens=80,
        cost_usd=3.0,
    )
    recent = _entry(
        when=datetime(2026, 9, 10, 12, tzinfo=UTC),
        session_id="new",
        input_tokens=20,
        cost_usd=1.0,
    )
    usage_snapshot.record_entries([old, recent])

    monkeypatch.setattr(reporter, "datetime", _fixed_datetime(fixed_now))
    monkeypatch.setattr(reporter, "_load_agent_entries", lambda _agent, _hours: [recent])

    data = reporter.build_report_data([agent], "all")

    assert data["date_from"] == "2026-08-01"
    assert data["summary"]["total_tokens"] == 100
    assert data["summary"]["sessions"] == 2


def test_merge_keeps_live_when_tokens_not_short(
    monkeypatch: pytest.MonkeyPatch,
    snapshot_path: Path,
    _sandbox_report: None,
) -> None:
    fixed_now = datetime(2026, 9, 10, 18, tzinfo=UTC)
    agent = AgentInfo("codex", "Codex", "~/.codex", True)
    live = _entry(
        when=datetime(2026, 9, 10, 12, tzinfo=UTC),
        session_id="live",
        input_tokens=50,
        cost_usd=2.0,
    )
    # Force a stored row with fewer tokens than live for the same day.
    usage_snapshot.record_entries(
        [
            _entry(
                when=datetime(2026, 9, 10, 8, tzinfo=UTC),
                session_id="old",
                input_tokens=10,
                cost_usd=0.5,
            )
        ]
    )

    monkeypatch.setattr(reporter, "datetime", _fixed_datetime(fixed_now))
    monkeypatch.setattr(reporter, "_load_agent_entries", lambda _agent, _hours: [live])

    data = reporter.build_report_data([agent], "today")

    assert data["summary"]["total_tokens"] == 50
    assert data["summary"]["sessions"] == 1
    assert data["top_sessions"][0]["tokens"] == 50


def test_replay_same_day_multi_project_keeps_earliest_project(
    snapshot_path: Path,
) -> None:
    session_id = "118d641f"
    original = [
        _entry(
            when=datetime(2026, 9, 1, 10, 0),
            session_id=session_id,
            project="usage",
            input_tokens=10,
        ),
        _entry(
            when=datetime(2026, 9, 1, 11, 0),
            session_id=session_id,
            project="panels",
            input_tokens=20,
        ),
        _entry(
            when=datetime(2026, 9, 1, 12, 0),
            session_id=session_id,
            project=".scout-v2",
            input_tokens=30,
        ),
    ]
    expected = aggregate_sessions(original)[0].project
    assert expected == "usage"
    assert sorted(entry.project for entry in original)[0] == ".scout-v2"

    usage_snapshot.record_entries(original)
    replayed = usage_snapshot.replay_entries(date(2026, 9, 1), date(2026, 9, 1))
    assert aggregate_sessions(replayed)[0].project == expected


def test_month_period_cross_midnight_session_matches_live_after_replay(
    monkeypatch: pytest.MonkeyPatch,
    snapshot_path: Path,
    _sandbox_report: None,
) -> None:
    """A session spanning 8/31 afternoon → 9/01 morning must keep the 9/01
    slice's start/duration when the month report only sees that second day.
    """
    fixed_now = datetime(2026, 9, 10, 18, tzinfo=UTC)
    agent = AgentInfo("codex", "Codex", "~/.codex", True)
    session_id = "b77e0704-3b1c-498b-bfe3-09a8ccc347bc"
    entries = [
        _entry(
            when=datetime(2026, 8, 31, 14, 36, 48, 738000, tzinfo=UTC),
            session_id=session_id,
            input_tokens=80,
            cost_usd=3.0,
        ),
        _entry(
            when=datetime(2026, 9, 1, 0, 0, tzinfo=UTC),
            session_id=session_id,
            input_tokens=10,
            cost_usd=0.4,
        ),
        _entry(
            when=datetime(2026, 9, 1, 0, 14, 48, tzinfo=UTC),
            session_id=session_id,
            input_tokens=20,
            cost_usd=0.6,
        ),
    ]
    usage_snapshot.record_entries(entries)

    monkeypatch.setattr(reporter, "datetime", _fixed_datetime(fixed_now))
    monkeypatch.setattr(html_report, "datetime", _fixed_datetime(fixed_now))
    monkeypatch.setattr(reporter, "_load_agent_entries", lambda _agent, _hours: entries)

    data_live = reporter.build_report_data([agent], "month")

    monkeypatch.setattr(reporter, "_load_agent_entries", lambda _agent, _hours: [])
    data_replay = reporter.build_report_data([agent], "month")

    assert data_live["top_sessions"]
    assert data_replay["top_sessions"]
    live_row = data_live["top_sessions"][0]
    replay_row = data_replay["top_sessions"][0]
    assert live_row["start_time"] == "2026-09-01 00:00"
    assert live_row["duration_min"] == 14.8
    assert replay_row["start_time"] == live_row["start_time"]
    assert replay_row["duration_min"] == live_row["duration_min"]


def test_replay_old_row_without_first_last_ts_uses_session_header(
    snapshot_path: Path,
) -> None:
    snapshot_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "rows": [
                    {
                        "session_id": "legacy",
                        "date": "2026-09-01",
                        "agent_id": "codex",
                        "model": "gpt-5",
                        "project": "usage",
                        "input_tokens": 30,
                        "output_tokens": 0,
                        "cache_creation_tokens": 0,
                        "cache_read_tokens": 0,
                        "cost": 1.0,
                        "message_count": 2,
                    }
                ],
                "sessions": {
                    "legacy": {
                        "start_time": "2026-09-01T12:00:00",
                        "duration_min": 30.0,
                        "project": "usage",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    replayed = usage_snapshot.replay_entries(date(2026, 9, 1), date(2026, 9, 1))

    assert len(replayed) == 2
    assert replayed[0].timestamp == datetime(2026, 9, 1, 12, 0)
    assert replayed[0].message_count == 2
    assert replayed[1].timestamp == datetime(2026, 9, 1, 12, 30)
    assert replayed[1].total_tokens == 0
    assert replayed[1].message_count == 0
    assert replayed[1].cost_usd == 0.0
    sessions = aggregate_sessions(replayed)
    assert len(sessions) == 1
    assert sessions[0].duration_minutes == 30.0


def test_replay_single_entry_row_does_not_add_placeholder(snapshot_path: Path) -> None:
    entry = _entry(when=datetime(2026, 9, 1, 12, 0), input_tokens=40, output_tokens=10)
    usage_snapshot.record_entries([entry])
    row = usage_snapshot.read_snapshot()["rows"][0]
    assert row["first_ts"] == row["last_ts"] == "2026-09-01T12:00:00"

    replayed = usage_snapshot.replay_entries(date(2026, 9, 1), date(2026, 9, 1))

    assert len(replayed) == 1
    assert replayed[0].timestamp == datetime(2026, 9, 1, 12, 0)
    assert replayed[0].input_tokens == 40


def test_replay_preserves_offset_timestamps(
    snapshot_path: Path, _sandbox_report: None
) -> None:
    tz = timezone(timedelta(hours=8))
    first = _entry(
        when=datetime(2026, 9, 1, 12, 0, tzinfo=tz),
        input_tokens=10,
        cost_usd=0.5,
    )
    last = _entry(
        when=datetime(2026, 9, 1, 12, 45, tzinfo=tz),
        input_tokens=20,
        cost_usd=0.5,
    )
    usage_snapshot.record_entries([first, last])

    row = usage_snapshot.read_snapshot()["rows"][0]
    assert row["first_ts"] == "2026-09-01T12:00:00+08:00"
    assert row["last_ts"] == "2026-09-01T12:45:00+08:00"

    replayed = usage_snapshot.replay_entries(date(2026, 9, 1), date(2026, 9, 1))
    assert replayed[0].timestamp == datetime(2026, 9, 1, 12, 0, tzinfo=tz)
    assert replayed[1].timestamp == datetime(2026, 9, 1, 12, 45, tzinfo=tz)
    sessions = aggregate_sessions(replayed)
    assert sessions[0].duration_minutes == 45.0


def test_replay_old_header_without_project_does_not_crash(
    snapshot_path: Path,
) -> None:
    snapshot_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "rows": [
                    {
                        "session_id": "118d641f",
                        "date": "2026-09-01",
                        "agent_id": "codex",
                        "model": "gpt-5",
                        "project": ".scout-v2",
                        "input_tokens": 30,
                        "output_tokens": 0,
                        "cache_creation_tokens": 0,
                        "cache_read_tokens": 0,
                        "cost": 1.0,
                        "message_count": 1,
                    },
                    {
                        "session_id": "118d641f",
                        "date": "2026-09-01",
                        "agent_id": "codex",
                        "model": "gpt-5",
                        "project": "panels",
                        "input_tokens": 20,
                        "output_tokens": 0,
                        "cache_creation_tokens": 0,
                        "cache_read_tokens": 0,
                        "cost": 1.0,
                        "message_count": 1,
                    },
                    {
                        "session_id": "118d641f",
                        "date": "2026-09-01",
                        "agent_id": "codex",
                        "model": "gpt-5",
                        "project": "usage",
                        "input_tokens": 10,
                        "output_tokens": 0,
                        "cache_creation_tokens": 0,
                        "cache_read_tokens": 0,
                        "cost": 1.0,
                        "message_count": 1,
                    },
                ],
                "sessions": {
                    "118d641f": {
                        "start_time": "2026-09-01T10:00:00",
                        "duration_min": 120.0,
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    replayed = usage_snapshot.replay_entries(date(2026, 9, 1), date(2026, 9, 1))

    assert len(replayed) >= 1
    sessions = aggregate_sessions(replayed)
    assert len(sessions) == 1
    assert sessions[0].project == ".scout-v2"

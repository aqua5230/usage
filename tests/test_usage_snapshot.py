# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import importlib.util
import json
from collections.abc import Iterator
from datetime import UTC, date, datetime, tzinfo
from pathlib import Path
from types import ModuleType
from typing import Any, Self

import pytest

from adapters.types import AgentInfo, UsageEntry
from analyzer import reporter, usage_snapshot
from loaders import cache_quarantine


@pytest.fixture
def snapshot_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    path = tmp_path / "usage_snapshot.json"
    monkeypatch.setattr(usage_snapshot, "SNAPSHOT_PATH", path)
    monkeypatch.setattr(cache_quarantine, "QUARANTINE_DIR", tmp_path / "quarantine")
    return path


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


def test_empty_entries_writes_empty_snapshot(snapshot_path: Path) -> None:
    result = usage_snapshot.record_entries([])

    assert result["schema_version"] == 1
    assert result["rows"] == []
    assert result["sessions"] == {}
    on_disk = usage_snapshot.read_snapshot()
    assert on_disk["schema_version"] == 1
    assert on_disk["rows"] == []
    assert on_disk["sessions"] == {}


def test_single_entry_writes_row_and_session_header(snapshot_path: Path) -> None:
    entry = _entry(when=datetime(2026, 9, 1, 12, 0))

    usage_snapshot.record_entries([entry])

    snapshot = usage_snapshot.read_snapshot()
    assert snapshot["rows"] == [
        {
            "agent_id": "codex",
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
            "cost": 1.0,
            "date": "2026-09-01",
            "first_ts": "2026-09-01T12:00:00",
            "input_tokens": 100,
            "last_ts": "2026-09-01T12:00:00",
            "message_count": 1,
            "model": "gpt-5",
            "output_tokens": 0,
            "project": "usage",
            "session_id": "sess-1",
        }
    ]
    assert snapshot["sessions"] == {
        "sess-1": {
            "duration_min": 0.0,
            "project": "usage",
            "start_time": "2026-09-01T12:00:00",
        }
    }


def test_same_day_twice_does_not_double(snapshot_path: Path) -> None:
    entry = _entry(when=datetime(2026, 9, 1, 12, 0), input_tokens=40, output_tokens=10)

    usage_snapshot.record_entries([entry])
    usage_snapshot.record_entries([entry])

    rows = usage_snapshot.read_snapshot()["rows"]
    assert len(rows) == 1
    assert rows[0]["input_tokens"] == 40
    assert rows[0]["output_tokens"] == 10
    assert rows[0]["cost"] == 1.0
    assert usage_snapshot.read_snapshot()["sessions"].keys() == {"sess-1"}


def test_cross_midnight_session_keeps_date_in_key(snapshot_path: Path) -> None:
    first = _entry(
        when=datetime(2026, 9, 1, 23, 0),
        input_tokens=10,
        cost_usd=0.25,
    )
    second = _entry(
        when=datetime(2026, 9, 2, 1, 0),
        input_tokens=20,
        cost_usd=0.75,
    )

    usage_snapshot.record_entries([first, second])

    snapshot = usage_snapshot.read_snapshot()
    assert [(row["date"], row["input_tokens"]) for row in snapshot["rows"]] == [
        ("2026-09-01", 10),
        ("2026-09-02", 20),
    ]
    assert all(row["session_id"] == "sess-1" for row in snapshot["rows"])
    assert snapshot["rows"][0]["first_ts"] == "2026-09-01T23:00:00"
    assert snapshot["rows"][0]["last_ts"] == "2026-09-01T23:00:00"
    assert snapshot["rows"][1]["first_ts"] == "2026-09-02T01:00:00"
    assert snapshot["rows"][1]["last_ts"] == "2026-09-02T01:00:00"
    header = snapshot["sessions"]["sess-1"]
    assert header["start_time"] == "2026-09-01T23:00:00"
    assert header["duration_min"] == 120.0


def test_row_stores_min_max_timestamps_on_same_day(snapshot_path: Path) -> None:
    first = _entry(when=datetime(2026, 9, 1, 12, 0), input_tokens=10)
    last = _entry(when=datetime(2026, 9, 1, 12, 30), input_tokens=20)
    usage_snapshot.record_entries([first, last])

    row = usage_snapshot.read_snapshot()["rows"][0]
    assert row["first_ts"] == "2026-09-01T12:00:00"
    assert row["last_ts"] == "2026-09-01T12:30:00"
    assert row["input_tokens"] == 30


def test_dates_outside_this_load_are_kept(snapshot_path: Path) -> None:
    old = _entry(
        when=datetime(2026, 8, 1, 12, 0),
        session_id="old",
        input_tokens=50,
        cost_usd=2.0,
    )
    new = _entry(
        when=datetime(2026, 9, 1, 12, 0),
        session_id="new",
        input_tokens=80,
        cost_usd=3.0,
    )
    usage_snapshot.record_entries([old])
    usage_snapshot.record_entries([new])

    rows = usage_snapshot.read_snapshot()["rows"]
    assert {row["date"] for row in rows} == {"2026-08-01", "2026-09-01"}
    assert {row["session_id"] for row in rows} == {"old", "new"}
    by_date = {row["date"]: row["input_tokens"] for row in rows}
    assert by_date["2026-08-01"] == 50
    assert by_date["2026-09-01"] == 80


def test_day_with_fewer_tokens_keeps_stored_rows(snapshot_path: Path) -> None:
    first = _entry(when=datetime(2026, 9, 1, 12, 0), input_tokens=100, cost_usd=5.0)
    second = _entry(when=datetime(2026, 9, 1, 18, 0), input_tokens=40, cost_usd=1.0)
    usage_snapshot.record_entries([first])
    usage_snapshot.record_entries([second])

    rows = usage_snapshot.read_snapshot()["rows"]
    assert len(rows) == 1
    assert rows[0]["input_tokens"] == 100
    assert rows[0]["cost"] == 5.0


def test_schema_mismatch_rebuilds_without_quarantine(
    snapshot_path: Path, tmp_path: Path
) -> None:
    snapshot_path.write_text(
        json.dumps(
            {
                "schema_version": 99,
                "rows": [
                    {
                        "session_id": "stale",
                        "date": "2026-01-01",
                        "agent_id": "codex",
                        "model": "old",
                        "project": "gone",
                        "input_tokens": 999,
                        "output_tokens": 0,
                        "cache_creation_tokens": 0,
                        "cache_read_tokens": 0,
                        "cost": 9.0,
                        "message_count": 9,
                    }
                ],
                "sessions": {"stale": {"start_time": "2026-01-01T00:00:00", "duration_min": 1}},
            }
        ),
        encoding="utf-8",
    )
    entry = _entry(when=datetime(2026, 9, 1, 12, 0), input_tokens=7)

    usage_snapshot.record_entries([entry])

    snapshot = usage_snapshot.read_snapshot()
    assert snapshot["schema_version"] == 1
    assert len(snapshot["rows"]) == 1
    assert snapshot["rows"][0]["session_id"] == "sess-1"
    assert snapshot["rows"][0]["input_tokens"] == 7
    assert not (tmp_path / "quarantine").exists()


def test_unreadable_snapshot_is_quarantined(
    snapshot_path: Path, tmp_path: Path
) -> None:
    snapshot_path.write_text("{not-json", encoding="utf-8")
    entry = _entry(when=datetime(2026, 9, 1, 12, 0), input_tokens=3)

    usage_snapshot.record_entries([entry])

    rows = usage_snapshot.read_snapshot()["rows"]
    assert rows[0]["input_tokens"] == 3
    backups = list((tmp_path / "quarantine").glob("*.bak"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "{not-json"


def test_period_totals_and_match(snapshot_path: Path) -> None:
    entries = [
        _entry(
            when=datetime(2026, 9, 1, 12, 0),
            session_id="a",
            input_tokens=10,
            output_tokens=5,
            cost_usd=1.23456,
        ),
        _entry(
            when=datetime(2026, 9, 2, 12, 0),
            session_id="b",
            input_tokens=20,
            cost_usd=2.0,
        ),
        _entry(
            when=datetime(2026, 9, 3, 12, 0),
            session_id="c",
            input_tokens=99,
            cost_usd=9.0,
        ),
    ]
    snapshot = usage_snapshot.record_entries(entries)
    totals = usage_snapshot.period_totals(
        snapshot, date(2026, 9, 1), date(2026, 9, 2)
    )

    assert totals.total_tokens == 35
    assert totals.sessions == 2
    assert totals.cost == pytest.approx(3.23456)
    assert usage_snapshot.totals_match(
        totals, total_tokens=35, cost=3.2346, sessions=2
    )
    assert not usage_snapshot.totals_match(
        totals, total_tokens=36, cost=3.2346, sessions=2
    )


def test_truncated_reload_does_not_shrink_session_header(snapshot_path: Path) -> None:
    first = _entry(when=datetime(2026, 9, 1, 23, 0), input_tokens=10)
    second = _entry(when=datetime(2026, 9, 2, 1, 0), input_tokens=20)
    usage_snapshot.record_entries([first, second])
    usage_snapshot.record_entries([second])

    header = usage_snapshot.read_snapshot()["sessions"]["sess-1"]
    assert header["start_time"] == "2026-09-01T23:00:00"
    assert header["duration_min"] == 120.0


@pytest.fixture
def _sandbox_report_write(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    snapshot_path: Path,
) -> Iterator[None]:
    def _entry_date_naive_or_utc(entry: UsageEntry) -> date:
        ts = entry.timestamp
        if ts.tzinfo:
            ts = ts.astimezone(UTC)
        return ts.date()

    monkeypatch.setattr(reporter, "_entry_date", _entry_date_naive_or_utc)
    monkeypatch.setattr(reporter, "YEAR_CACHE_PATH", tmp_path / "year_cache.json")
    monkeypatch.setattr(reporter, "YEAR_LEDGER_PATH", tmp_path / "year_ledger.json")
    monkeypatch.setattr(
        reporter, "_load_year_data_cached", lambda _agents: {
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
    )
    monkeypatch.setattr(reporter, "_load_persona_for_period", lambda _period: None)
    monkeypatch.setattr("analyzer.reporter.subscription.load_subscriptions", lambda: [])
    yield


def test_build_report_data_twice_does_not_duplicate_days(
    monkeypatch: pytest.MonkeyPatch,
    snapshot_path: Path,
    _sandbox_report_write: None,
) -> None:
    fixed_now = datetime(2026, 9, 2, 12, tzinfo=UTC)
    agent = AgentInfo("codex", "Codex", "~/.codex", True)
    entries = [
        _entry(
            when=datetime(2026, 9, 1, 12, tzinfo=UTC),
            session_id="a",
            input_tokens=10,
            output_tokens=5,
            cost_usd=1.5,
        ),
        _entry(
            when=datetime(2026, 9, 2, 8, tzinfo=UTC),
            session_id="b",
            input_tokens=20,
            cost_usd=2.5,
        ),
    ]

    monkeypatch.setattr(reporter, "datetime", _fixed_datetime(fixed_now))
    monkeypatch.setattr(reporter, "_load_agent_entries", lambda _agent, _hours: entries)

    first = reporter.build_report_data([agent], "last7")
    second = reporter.build_report_data([agent], "last7")
    rows = usage_snapshot.read_snapshot()["rows"]
    dates = [row["date"] for row in rows]
    assert dates == ["2026-09-01", "2026-09-02"]
    assert sum(row["input_tokens"] + row["output_tokens"] for row in rows) == 35
    assert first["summary"]["total_tokens"] == second["summary"]["total_tokens"] == 35
    totals = usage_snapshot.period_totals(
        usage_snapshot.read_snapshot(),
        date.fromisoformat(first["date_from"]),
        date.fromisoformat(first["date_to"]),
    )
    assert usage_snapshot.totals_match(
        totals,
        total_tokens=first["summary"]["total_tokens"],
        cost=first["summary"]["cost_usd"],
        sessions=first["summary"]["sessions"],
    )


def _load_verify_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "verify_snapshot",
        Path(__file__).resolve().parents[1] / "scripts" / "verify_snapshot.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_verify_snapshot_script_ok_and_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    snapshot_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    usage_snapshot.record_entries(
        [_entry(when=datetime(2026, 9, 1, 12, 0), input_tokens=10, cost_usd=1.0)]
    )
    module = _load_verify_script()
    report = {
        "period_label": "2026-09-01 -> 2026-09-01",
        "date_from": "2026-09-01",
        "date_to": "2026-09-01",
        "summary": {"total_tokens": 10, "cost_usd": 1.0, "sessions": 1},
    }
    monkeypatch.setattr(module, "detect_agents", lambda: [])
    monkeypatch.setattr(module, "build_report_data", lambda _agents, _period: report)

    assert module.main([]) == 0
    ok_output = capsys.readouterr().out
    assert "OK" in ok_output
    assert "10" in ok_output

    report["summary"] = {"total_tokens": 99, "cost_usd": 1.0, "sessions": 1}
    assert module.main([]) == 1
    mismatch_output = capsys.readouterr().out
    assert "MISMATCH" in mismatch_output
    assert "99" in mismatch_output

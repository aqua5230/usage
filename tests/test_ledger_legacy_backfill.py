from __future__ import annotations

import copy
import json
import sqlite3
import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta, tzinfo
from pathlib import Path

import pytest

from analyzer import ledger_legacy_backfill, reporter
from loaders import codex_loader
from ui.html_report import _date_filter


@pytest.fixture(autouse=True)
def _ledger_directory() -> None:
    reporter.YEAR_LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)


def _day(total: int = 100) -> reporter._YearDay:
    return {
        "total_tokens": total,
        "agent_tokens": {},
        "model_tokens": {},
        "project_tokens": {},
        "cost": 2.5,
        "sessions": 7,
    }


@pytest.fixture
def state_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "state_5.sqlite"
    monkeypatch.setattr(codex_loader, "STATE_DB", path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE threads (created_at INTEGER, tokens_used INTEGER, model TEXT, cwd TEXT)"
        )
    return path


def _thread(path: Path, tokens: int, model: str | None, cwd: str | None, day: str) -> None:
    stamp = datetime.fromisoformat(f"{day}T12:00:00").timestamp()
    with sqlite3.connect(path) as connection:
        connection.execute("INSERT INTO threads VALUES (?, ?, ?, ?)", (stamp, tokens, model, cwd))


@pytest.mark.parametrize("agents", [{}, {"claude-code": 0, "codex": 0}])
def test_fills_only_total_only_days(state_db: Path, tmp_path: Path, agents: dict[str, int]) -> None:
    days = {"2026-04-21": _day(), "2026-04-22": _day(), "2026-04-23": _day(0)}
    days["2026-04-21"]["agent_tokens"] = agents.copy()
    days["2026-04-22"]["agent_tokens"] = {"claude-code": 1}
    preserved = copy.deepcopy({key: days[key] for key in ("2026-04-22", "2026-04-23")})
    for day in days:
        _thread(state_db, 60, "gpt-demo", str(tmp_path / "project-a"), day)
    _thread(state_db, 999, "outside", str(tmp_path), "2026-04-20")

    assert ledger_legacy_backfill.backfill_days(days)
    filled = days["2026-04-21"]
    assert filled["agent_tokens"] == {"codex": 60, "unknown": 40}
    assert filled["model_tokens"] == {"gpt-demo": 60, "unknown": 40}
    assert filled["project_tokens"] == {"project-a": 60, "unknown": 40}
    assert filled["cost"] == 2.5
    assert filled["sessions"] == 7
    assert filled["total_tokens"] == 100
    assert {key: days[key] for key in preserved} == preserved
    before = copy.deepcopy(days)
    assert not ledger_legacy_backfill.backfill_days(days)
    assert days == before


def test_scales_proportionally_with_exact_integer_totals(state_db: Path, tmp_path: Path) -> None:
    _thread(state_db, 10, "model-a", str(tmp_path / "project-a"), "2026-04-21")
    _thread(state_db, 20, "model-b", str(tmp_path / "project-b"), "2026-04-21")
    days = {"2026-04-21": _day(7)}

    assert ledger_legacy_backfill.backfill_days(days)
    day = days["2026-04-21"]
    assert day["agent_tokens"] == {"codex": 7}
    assert day["model_tokens"] == {"model-a": 2, "model-b": 5}
    assert day["project_tokens"] == {"project-a": 2, "project-b": 5}
    assert day["cost"] == 2.5


def test_missing_metadata_and_no_threads_use_unknown(state_db: Path) -> None:
    _thread(state_db, 60, None, None, "2026-04-21")
    _thread(state_db, 0, "ignored", "/unused", "2026-04-22")
    _thread(state_db, -5, "ignored", "/unused", "2026-04-22")
    days = {"2026-04-21": _day(), "2026-04-22": _day()}
    assert ledger_legacy_backfill.backfill_days(days)
    assert days["2026-04-21"]["agent_tokens"] == {"codex": 60, "unknown": 40}
    for day in days.values():
        assert day["model_tokens"] == day["project_tokens"] == {"unknown": 100}
    assert days["2026-04-22"]["agent_tokens"] == {"unknown": 100}


def test_uses_existing_project_normalizer(state_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen = []

    def normalize(cwd: str) -> str:
        seen.append(cwd)
        return "canonical-project"

    monkeypatch.setattr(codex_loader, "_project_from_cwd", normalize)
    _thread(state_db, 100, "gpt-demo", "/worktree/subdirectory", "2026-04-21")
    days = {"2026-04-21": _day()}
    assert ledger_legacy_backfill.backfill_days(days)
    assert seen == ["/worktree/subdirectory"]
    assert days["2026-04-21"]["project_tokens"] == {"canonical-project": 100}


@pytest.mark.skipif(not hasattr(time, "tzset"), reason="requires time.tzset")
def test_thread_uses_local_start_date(state_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stamp = datetime(2026, 4, 20, 17, tzinfo=UTC).timestamp()
    with sqlite3.connect(state_db) as connection:
        connection.execute("INSERT INTO threads VALUES (?, 60, NULL, NULL)", (stamp,))
    days = {"2026-04-20": _day(), "2026-04-21": _day()}
    try:
        with monkeypatch.context() as patch:
            patch.setenv("TZ", "Asia/Taipei")
            getattr(time, "tzset", lambda: None)()
            assert ledger_legacy_backfill.backfill_days(days)
    finally:
        getattr(time, "tzset", lambda: None)()
    assert days["2026-04-20"]["agent_tokens"] == {"unknown": 100}
    assert days["2026-04-21"]["agent_tokens"] == {"codex": 60, "unknown": 40}


@pytest.mark.parametrize("source", ["missing", "corrupt", "wrong-schema"])
def test_unavailable_sqlite_preserves_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str
) -> None:
    path = tmp_path / "unavailable.sqlite"
    monkeypatch.setattr(codex_loader, "STATE_DB", path)
    if source == "corrupt":
        path.write_text("not sqlite")
    elif source == "wrong-schema":
        with sqlite3.connect(path) as connection:
            connection.execute("CREATE TABLE other (id INTEGER)")
    ledger: reporter._YearLedger = {"schema_version": 1, "days": {"2026-04-21": _day()}}
    reporter.YEAR_LEDGER_PATH.write_text(json.dumps(ledger))
    before = reporter.YEAR_LEDGER_PATH.read_bytes()

    assert reporter._read_year_ledger() == ledger
    assert reporter.YEAR_LEDGER_PATH.read_bytes() == before
    assert path.exists() == (source != "missing")


def test_read_backfills_once_and_persists(state_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _thread(state_db, 60, "gpt-demo", None, "2026-04-21")
    reporter.YEAR_LEDGER_PATH.write_text(
        json.dumps({"schema_version": 1, "days": {"2026-04-21": _day()}})
    )
    original_uri = codex_loader._readonly_sqlite_uri
    calls = []

    def readonly(path: Path) -> str:
        calls.append(path)
        uri = original_uri(path)
        assert uri.endswith("?mode=ro")
        return uri

    monkeypatch.setattr(codex_loader, "_readonly_sqlite_uri", readonly)
    ledger = reporter._read_year_ledger()
    before = reporter.YEAR_LEDGER_PATH.read_bytes()
    _thread(state_db, 100, "later", None, "2026-04-21")
    assert reporter._read_year_ledger() == ledger
    assert reporter.YEAR_LEDGER_PATH.read_bytes() == before
    assert json.loads(before) == ledger
    assert calls == [state_db]


@pytest.mark.parametrize("reader", ["report", "year", "persist"])
def test_readers_accept_backfilled_100_days(
    state_db: Path, monkeypatch: pytest.MonkeyPatch, reader: str
) -> None:
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> FixedDateTime:
            return cls(2026, 8, 12, 12, tzinfo=tz)

    monkeypatch.setattr(reporter, "datetime", FixedDateTime)
    monkeypatch.setattr(reporter, "_load_agent_entries", lambda *_args: [])
    days = {(date(2026, 4, 21) + timedelta(days=index)).isoformat(): _day() for index in range(100)}
    for value in days.values():
        value["cost"] = 0.0
    _thread(state_db, 60, "gpt-demo", None, "2026-04-21")
    reporter.YEAR_LEDGER_PATH.write_text(json.dumps({"schema_version": 1, "days": days}))

    readers: dict[str, Callable[[], object]] = {
        "report": lambda: reporter.build_report_data([], "all"),
        "year": lambda: reporter.build_year_data([]),
        "persist": lambda: reporter.persist_year_entries([], date(2026, 8, 12)),
    }
    readers[reader]()
    persisted = json.loads(reporter.YEAR_LEDGER_PATH.read_text())
    assert all(sum(day["agent_tokens"].values()) == 100 for day in persisted["days"].values())
    data = reporter.build_report_data([], "all")
    assert data["date_from"] == "2026-04-21"
    assert data["cube"]["dates"][0] == "2026-04-21"
    assert len(data["cube"]["dates"]) == 100
    assert data["summary"]["total_tokens"] == 10_000
    assert data["summary"]["cost_usd"] == 0.0
    assert data["summary"]["sessions"] == 0
    assert sum(sum(row[4:8]) for row in data["cube"]["rows"]) == 10_000
    assert {row["id"]: row["tokens"] for row in data["by_agent"]} == {
        "codex": 60,
        "unknown": 9940,
    }
    assert 'min="2026-04-21"' in _date_filter(data, "en")
    assert "data-history-note" not in _date_filter(data, "en")
    assert data["wrapped"]["codex_tokens"] == 60
    assert data["wrapped"]["total_cost"] == 0.0

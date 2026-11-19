from __future__ import annotations

import json
import threading
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, tzinfo
from typing import Any, Self

import pytest

from adapters.types import AgentInfo, UsageEntry
from analyzer import claude_activity, history_persist, reporter, usage_snapshot


class _UtcLocalDateTime(datetime):
    # Pin no-arg astimezone() to UTC so tests remain deterministic across timezones and on Windows.
    def astimezone(self, tz: tzinfo | None = None) -> Self:
        return super().astimezone(tz if tz is not None else UTC)


def _entry_date_utc(entry: UsageEntry) -> date:
    ts = entry.timestamp
    if ts.tzinfo:
        ts = ts.astimezone(UTC)
    return ts.date()


NOW = _UtcLocalDateTime(2026, 8, 12, 12, tzinfo=UTC)
_AGY_AGENT = AgentInfo(id="antigravity", name="Antigravity", installed=True, data_dir="")
_REAL_SCHEDULE_NEXT = history_persist._schedule_next_locked


def _entry(when: datetime = NOW, session: str = "real") -> UsageEntry:
    return UsageEntry(
        timestamp=when,
        session_id=session,
        message_id=session,
        request_id=session,
        model="test",
        project="project",
        agent_id="claude-code",
        input_tokens=100,
        output_tokens=20,
        cache_creation_tokens=10,
        cache_read_tokens=70,
        cost_usd=1.0,
    )


def _agy_entry(tokens: int, session: str = "agy") -> UsageEntry:
    return replace(
        _entry(session=session),
        agent_id="antigravity",
        input_tokens=tokens,
        output_tokens=0,
        cache_creation_tokens=0,
        cache_read_tokens=0,
    )


def _write_stale_agy_ledger(entries: list[UsageEntry]) -> None:
    days = reporter._aggregate_year_days(entries)
    days[NOW.date().isoformat()]["agent_versions"] = {"antigravity": 1}
    reporter._write_year_ledger({"schema_version": reporter._YEAR_LEDGER_SCHEMA, "days": days})


@pytest.fixture(autouse=True)
def _isolate_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(history_persist, "_refresh_in_flight", False)
    monkeypatch.setattr(history_persist, "_timer", None)
    monkeypatch.setattr(reporter, "_entry_date", _entry_date_utc)
    monkeypatch.setattr(usage_snapshot, "_entry_date", _entry_date_utc)
    monkeypatch.setattr(
        history_persist,
        "detect_agents",
        lambda: [AgentInfo(id="claude-code", name="Claude Code", installed=True, data_dir="")],
    )


def test_missing_state_persists_real_recent_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    hours: list[int] = []

    def load(_agent: AgentInfo, hours_back: int) -> list[UsageEntry]:
        hours.append(hours_back)
        return [
            _entry(),
            _entry(NOW - timedelta(days=45), "old"),
            _entry(session="usage-ledger:2026-08-12"),
        ]

    monkeypatch.setattr(reporter, "_load_agent_entries", load)
    assert history_persist.refresh_history(NOW)
    assert hours == [46 * 24]
    snapshot = json.loads(usage_snapshot.SNAPSHOT_PATH.read_text())
    assert {row["session_id"] for row in snapshot["rows"]} == {"real"}
    ledger = json.loads(reporter.YEAR_LEDGER_PATH.read_text())
    assert ledger["days"]["2026-08-12"]["total_tokens"] == 200
    assert json.loads(history_persist.STATE_PATH.read_text())["last_success"] == NOW.isoformat()


def test_year_ledger_lock_timeout_does_not_record_success(monkeypatch: pytest.MonkeyPatch) -> None:
    from usage_common import file_lock

    def timed_out(_path: object) -> Any:
        raise file_lock.LockTimeout("held")

    monkeypatch.setattr(reporter, "_load_agent_entries", lambda *_args: [_entry()])
    monkeypatch.setattr(reporter, "exclusive_file_lock", timed_out)

    with pytest.raises(file_lock.LockTimeout):
        history_persist.refresh_history(NOW)
    assert not history_persist.STATE_PATH.exists()


def test_load_year_data_cached_reuses_cache_after_snapshot_verified_agy_recount(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FixedDateTime:
        @staticmethod
        def now(tz: tzinfo | None = None) -> datetime:
            return NOW if tz is None else NOW.astimezone(tz)

    monkeypatch.setattr(reporter, "datetime", FixedDateTime)
    monkeypatch.setattr(claude_activity, "activity_dates", frozenset)
    current = [_agy_entry(4000)]
    usage_snapshot.record_entries(current)
    _write_stale_agy_ledger([_agy_entry(6000)])
    agents = [_AGY_AGENT]
    monkeypatch.setattr(reporter, "_load_agent_entries", lambda *_args: current)

    data = reporter._load_year_data_cached(agents)

    day_key = NOW.date().isoformat()
    saved = json.loads(reporter.YEAR_LEDGER_PATH.read_text())["days"][day_key]
    assert saved["total_tokens"] == 4000
    assert saved["agent_versions"] == usage_snapshot.AGENT_VERSIONS
    assert data["contribution"]["busiest_day"] == {"date": day_key, "tokens": 4000}

    def fail_rebuild(_agents: list[AgentInfo]) -> reporter.YearReportData:
        pytest.fail("the corrected year ledger should allow a year cache hit")

    monkeypatch.setattr(reporter, "_build_year_data", fail_rebuild)
    assert reporter._load_year_data_cached(agents) == data


def test_merge_year_ledger_drops_year_cache_when_snapshot_verifies_lower_agy_day() -> None:
    today = NOW.date()
    agy = _agy_entry(4000)
    usage_snapshot.record_entries([agy])
    _write_stale_agy_ledger([_agy_entry(6000)])
    reporter.YEAR_CACHE_PATH.write_text("{}", encoding="utf-8")

    reporter._merge_year_ledger(reporter._aggregate_year_days([agy]), trim_before=today)

    assert not reporter.YEAR_CACHE_PATH.exists()


@pytest.mark.parametrize("snapshot_difference", ["stale-version", "agent-totals"])
def test_merge_year_ledger_requires_current_snapshot_version_and_matching_agent_totals(
    snapshot_difference: str,
) -> None:
    today = NOW.date()
    day_key = today.isoformat()
    agy = _agy_entry(3000)
    codex = replace(_agy_entry(1000, "codex"), agent_id="codex")
    current_days = reporter._aggregate_year_days([agy, codex])
    _write_stale_agy_ledger([replace(agy, input_tokens=5000), codex])
    verified = usage_snapshot.record_entries([agy, codex])
    if snapshot_difference == "stale-version":
        usage_snapshot._write_snapshot({**verified, "day_versions": {day_key: {"antigravity": 1}}})
    else:
        # Same total across the day, but different totals for both agents.
        usage_snapshot.record_entries(
            [replace(agy, input_tokens=2000), replace(codex, input_tokens=2000)]
        )

    kept = reporter._merge_year_ledger(current_days, trim_before=today)["days"][day_key]
    assert kept["total_tokens"] == 6000
    assert kept["agent_versions"] == {"antigravity": 1}

    usage_snapshot._write_snapshot(verified)
    replaced = reporter._merge_year_ledger(current_days, trim_before=today)["days"][day_key]
    assert replaced == current_days[day_key]


def test_refresh_history_lowers_stale_agy_ledger_after_snapshot_recount(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    day_key = NOW.date().isoformat()
    old_entries = [_agy_entry(3000, "A"), _agy_entry(2000, "B")]
    old_snapshot = usage_snapshot.record_entries(old_entries)
    usage_snapshot._write_snapshot({**old_snapshot, "day_versions": {day_key: {"antigravity": 1}}})
    _write_stale_agy_ledger(old_entries)
    current = [_agy_entry(2000, "A"), _agy_entry(1000, "B")]
    monkeypatch.setattr(history_persist, "detect_agents", lambda: [_AGY_AGENT])
    monkeypatch.setattr(reporter, "_load_agent_entries", lambda *_args: current)

    assert history_persist.refresh_history(NOW)

    snapshot = usage_snapshot.read_snapshot()
    assert usage_snapshot.period_totals(snapshot, NOW.date(), NOW.date()).total_tokens == 3000
    assert {row["session_id"] for row in snapshot["rows"]} == {"A", "B"}
    assert snapshot["day_versions"][day_key] == usage_snapshot.AGENT_VERSIONS
    saved = json.loads(reporter.YEAR_LEDGER_PATH.read_text())["days"][day_key]
    assert saved["total_tokens"] == 3000
    assert saved["agent_versions"] == usage_snapshot.AGENT_VERSIONS


def test_refresh_history_marks_live_recount_with_unchanged_snapshot_totals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    day_key = NOW.date().isoformat()
    live = [_agy_entry(20_000)]
    previous = usage_snapshot.record_entries(live)
    previous.pop("day_versions")
    usage_snapshot._write_snapshot(previous)
    _write_stale_agy_ledger([_agy_entry(100_000)])
    monkeypatch.setattr(history_persist, "detect_agents", lambda: [_AGY_AGENT])
    monkeypatch.setattr(reporter, "_load_agent_entries", lambda *_args: live)

    assert history_persist.refresh_history(NOW)

    snapshot = usage_snapshot.read_snapshot()
    assert snapshot["rows"] == previous["rows"]
    assert snapshot["day_versions"][day_key] == usage_snapshot.AGENT_VERSIONS
    assert reporter._read_year_ledger()["days"][day_key]["total_tokens"] == 20_000


def test_recent_success_skips_and_six_hours_refreshes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reporter, "_load_agent_entries", lambda *_args: [_entry()])
    assert history_persist.refresh_history(NOW)
    before = history_persist.STATE_PATH.read_text()
    assert not history_persist.refresh_history(NOW + timedelta(hours=5, minutes=59))
    assert history_persist.STATE_PATH.read_text() == before
    assert history_persist.refresh_history(NOW + timedelta(hours=6))


def test_two_calls_only_start_one_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    entered, release = threading.Event(), threading.Event()
    workers: list[threading.Thread] = []
    real_thread = threading.Thread

    def refresh() -> None:
        entered.set()
        assert release.wait(5)

    def make_thread(**kwargs: Any) -> threading.Thread:
        worker = real_thread(**kwargs)
        workers.append(worker)
        return worker

    monkeypatch.setattr(history_persist, "refresh_history", refresh)
    monkeypatch.setattr(threading, "Thread", make_thread)
    try:
        history_persist.maybe_schedule_refresh()
        assert entered.wait(5)
        history_persist.maybe_schedule_refresh()
        assert len(workers) == 1
        assert workers[0].daemon
    finally:
        release.set()
        for worker in workers:
            worker.join(5)
    assert not history_persist._refresh_in_flight


def test_loader_failure_logs_without_updating_state(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def fail(*_args: object) -> list[UsageEntry]:
        raise OSError("loader failed")

    monkeypatch.setattr(reporter, "_load_agent_entries", fail)
    history_persist._refresh_in_background()
    assert not history_persist.STATE_PATH.exists()
    assert not history_persist._refresh_in_flight
    assert "loader failed" in caplog.text


@pytest.mark.parametrize("writer", ["snapshot", "ledger"])
def test_silent_write_failure_does_not_mark_success(
    monkeypatch: pytest.MonkeyPatch, writer: str, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(reporter, "_load_agent_entries", lambda *_args: [_entry()])
    if writer == "snapshot":
        monkeypatch.setattr(usage_snapshot, "_write_snapshot", lambda _snapshot: None)
    else:
        monkeypatch.setattr(reporter, "_write_year_ledger", lambda _ledger: None)
    history_persist._refresh_in_background()
    assert not history_persist.STATE_PATH.exists()
    assert "Failed to persist usage history" in caplog.text


def test_scheduler_rearms_when_fresh_and_after_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delays: list[float] = []
    monkeypatch.setattr(history_persist, "_schedule_next_locked", delays.append)
    history_persist.STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    history_persist.STATE_PATH.write_text(
        json.dumps({"last_success": datetime.now(UTC).isoformat()})
    )
    history_persist.maybe_schedule_refresh()
    assert 21590 < delays[-1] <= 21600
    history_persist._refresh_in_background()
    assert delays[-1] == 21600


def test_timer_is_daemon_and_fires_scheduler(monkeypatch: pytest.MonkeyPatch) -> None:
    from collections.abc import Callable

    timers: list[Any] = []
    calls: list[str] = []

    class FakeTimer:
        daemon = False

        def __init__(self, delay: float, callback: Callable[[], None]) -> None:
            self.delay = delay
            self.callback = callback
            timers.append(self)

        def start(self) -> None:
            calls.append("started")

    monkeypatch.setattr(threading, "Timer", FakeTimer)
    monkeypatch.setattr(history_persist, "maybe_schedule_refresh", lambda: calls.append("refresh"))
    _REAL_SCHEDULE_NEXT(21600)
    _REAL_SCHEDULE_NEXT(21600)
    assert len(timers) == 1
    assert timers[0].daemon
    assert timers[0].delay == 21600
    timers[0].callback()
    assert calls == ["started", "refresh"]
    assert history_persist._timer is None


@pytest.mark.parametrize("writer", ["snapshot", "ledger"])
def test_concurrent_history_writes_preserve_both_entries(
    monkeypatch: pytest.MonkeyPatch, writer: str
) -> None:
    read_entered = threading.Event()
    release_first = threading.Event()
    second_started = threading.Event()
    second_done = threading.Event()
    errors: list[BaseException] = []
    if writer == "snapshot":
        module: Any = usage_snapshot
        reader_name = "_read_snapshot"

        def write(entry: UsageEntry) -> None:
            usage_snapshot.record_entries([entry])

        path = usage_snapshot.SNAPSHOT_PATH
    else:
        module = reporter
        reader_name = "_read_year_ledger"

        def write(entry: UsageEntry) -> None:
            reporter.persist_year_entries([entry], NOW.date())

        path = reporter.YEAR_LEDGER_PATH
    original_read = getattr(module, reader_name)

    def paused_read() -> Any:
        result = original_read()
        if threading.current_thread().name == "first-writer":
            read_entered.set()
            assert release_first.wait(5)
        return result

    def run(entry: UsageEntry, second: bool = False) -> None:
        try:
            if second:
                second_started.set()
            write(entry)
        except BaseException as exc:
            errors.append(exc)
        finally:
            if second:
                second_done.set()

    monkeypatch.setattr(module, reader_name, paused_read)
    first = threading.Thread(target=run, args=(_entry(session="first"),), name="first-writer")
    second = threading.Thread(target=run, args=(_entry(NOW - timedelta(days=1), "second"), True))
    first.start()
    try:
        assert read_entered.wait(5)
        second.start()
        assert second_started.wait(5)
        # Unlocked code lets the second writer finish before the first replaces its file.
        # Locked code holds the second writer until the first transaction completes.
        second_done.wait(0.2)
    finally:
        release_first.set()
        first.join(5)
        if second.ident is not None:
            second.join(5)
    assert not first.is_alive() and not second.is_alive()
    assert not errors
    saved = json.loads(path.read_text())
    if writer == "snapshot":
        assert {row["session_id"] for row in saved["rows"]} == {"first", "second"}
    else:
        assert set(saved["days"]) == {
            NOW.date().isoformat(),
            (NOW - timedelta(days=1)).date().isoformat(),
        }

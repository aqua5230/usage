from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from adapters.types import AgentInfo, UsageEntry
from analyzer import history_persist, reporter, usage_snapshot

NOW = datetime(2026, 8, 12, 12, tzinfo=UTC)
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


@pytest.fixture(autouse=True)
def _isolate_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(history_persist, "_refresh_in_flight", False)
    monkeypatch.setattr(history_persist, "_timer", None)
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

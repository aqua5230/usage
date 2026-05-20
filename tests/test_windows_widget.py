from __future__ import annotations

import time
from datetime import UTC, datetime

import pytest

import windows_widget
from history_loader import UsageEntry


def _entry(session_id: str, year: int, month: int, cost: float | None) -> UsageEntry:
    ts = datetime(year, month, 15, 12, 0, 0, tzinfo=UTC)
    return UsageEntry(
        timestamp=ts,
        session_id=session_id,
        message_id="msg1",
        request_id="req1",
        model="claude-sonnet-4-6",
        input_tokens=100,
        output_tokens=50,
        cache_creation_tokens=0,
        cache_read_tokens=0,
        cost_usd=cost,
        project="test",
    )


def test_format_reset_minutes_only() -> None:
    resets_at = time.time() + 45 * 60
    assert windows_widget.format_reset(resets_at) == "45min"


def test_format_reset_hours_and_minutes() -> None:
    resets_at = time.time() + 2 * 3600 + 30 * 60
    assert windows_widget.format_reset(resets_at) == "2hr 30min"


def test_format_reset_days_and_hours() -> None:
    resets_at = time.time() + 2 * 86400 + 3 * 3600
    assert windows_widget.format_reset(resets_at) == "2d 3hr"


def test_format_reset_past_returns_zero() -> None:
    resets_at = time.time() - 100
    assert windows_widget.format_reset(resets_at) == "0min"


def test_compute_month_stats_sums_current_month(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 5, 20, 12, 0, 0, tzinfo=UTC)
    monkeypatch.setattr("windows_widget._utcnow", lambda: now)

    entries = [
        _entry("s1", 2026, 5, 1.50),
        _entry("s2", 2026, 5, 2.00),
        _entry("s3", 2026, 4, 5.00),  # last month — excluded
    ]
    cost, sessions = windows_widget.compute_month_stats(entries)

    assert abs(cost - 3.50) < 0.001
    assert sessions == 2


def test_compute_month_stats_deduplicates_sessions(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 5, 20, 12, 0, 0, tzinfo=UTC)
    monkeypatch.setattr("windows_widget._utcnow", lambda: now)

    entries = [
        _entry("same-session", 2026, 5, 1.00),
        _entry("same-session", 2026, 5, 1.00),
    ]
    _cost, sessions = windows_widget.compute_month_stats(entries)

    assert sessions == 1


def test_compute_month_stats_handles_none_cost(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 5, 20, 12, 0, 0, tzinfo=UTC)
    monkeypatch.setattr("windows_widget._utcnow", lambda: now)

    entries = [_entry("s1", 2026, 5, None)]
    cost, sessions = windows_widget.compute_month_stats(entries)

    assert cost == 0.0
    assert sessions == 1

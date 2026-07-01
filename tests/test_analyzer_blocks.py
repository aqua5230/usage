from __future__ import annotations

from datetime import UTC, datetime, timedelta, tzinfo
from typing import Self

import pytest

from adapters.types import DailyStats, UsageEntry
from analyzer import blocks


def _entry(
    *,
    timestamp: datetime,
    total_tokens: int = 10,
    cost_usd: float | None = None,
    session_id: str = "session",
) -> UsageEntry:
    return UsageEntry(
        timestamp=timestamp,
        session_id=session_id,
        message_id=f"message-{timestamp.timestamp()}",
        request_id=f"request-{timestamp.timestamp()}",
        model="claude-sonnet",
        input_tokens=total_tokens,
        output_tokens=0,
        cache_creation_tokens=0,
        cache_read_tokens=0,
        cost_usd=cost_usd,
        project="project",
        agent_id="agent",
    )


def test_analyze_blocks_merges_entries_within_five_hour_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
    monkeypatch.setattr(blocks, "calculate_cost", lambda entry: 1.5)

    result = blocks.analyze_blocks(
        [
            _entry(timestamp=start, total_tokens=100),
            _entry(timestamp=start + timedelta(hours=4, minutes=59), total_tokens=50),
        ]
    )

    assert len(result) == 1
    assert result[0].start_time == start
    assert result[0].end_time == start + timedelta(hours=5)
    assert len(result[0].entries) == 2
    assert result[0].total_tokens == 150
    assert result[0].cost_usd == 3.0


def test_analyze_blocks_inserts_gap_and_starts_new_block_after_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
    monkeypatch.setattr(blocks, "calculate_cost", lambda entry: 0.0)

    result = blocks.analyze_blocks(
        [
            _entry(timestamp=start, total_tokens=10, session_id="a"),
            _entry(
                timestamp=start + timedelta(hours=5, minutes=6),
                total_tokens=20,
                session_id="b",
            ),
        ]
    )

    assert len(result) == 3
    assert result[0].is_gap is False
    assert result[1].is_gap is True
    assert result[1].start_time == start + timedelta(hours=5)
    assert result[1].end_time == start + timedelta(hours=5, minutes=6)
    assert result[2].is_gap is False
    assert result[2].start_time == start + timedelta(hours=5, minutes=6)
    assert result[2].entries[0].session_id == "b"


def test_analyze_blocks_sets_burn_rate_for_active_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> Self:
            current = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
            value = current if tz is None else current.astimezone(tz)
            return cls.fromtimestamp(value.timestamp(), value.tzinfo)

    monkeypatch.setattr(blocks, "datetime", _FrozenDateTime)
    monkeypatch.setattr(blocks, "calculate_cost", lambda entry: 0.0)
    start = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)

    result = blocks.analyze_blocks([_entry(timestamp=start, total_tokens=120)])

    assert len(result) == 1
    assert result[0].is_active is True
    assert result[0].burn_rate == 1.0


def test_calculate_p90_returns_defaults_for_insufficient_samples() -> None:
    result = blocks.calculate_p90(
        [
            DailyStats(date="2026-01-01", total_tokens=10, cost_usd=1.11, message_count=1),
            DailyStats(date="2026-01-02", total_tokens=20, cost_usd=2.22, message_count=2),
        ]
    )

    assert result.token_limit == 0
    assert result.cost_limit == 0.0
    assert result.message_limit == 0


def test_calculate_p90_uses_upper_boundary_index() -> None:
    result = blocks.calculate_p90(
        [
            DailyStats(date="2026-01-01", total_tokens=10, cost_usd=1.11, message_count=1),
            DailyStats(date="2026-01-02", total_tokens=20, cost_usd=2.22, message_count=2),
            DailyStats(date="2026-01-03", total_tokens=30, cost_usd=3.33, message_count=3),
            DailyStats(date="2026-01-04", total_tokens=40, cost_usd=4.44, message_count=4),
            DailyStats(date="2026-01-05", total_tokens=50, cost_usd=5.55, message_count=5),
            DailyStats(date="2026-01-06", total_tokens=60, cost_usd=6.66, message_count=6),
            DailyStats(date="2026-01-07", total_tokens=70, cost_usd=7.77, message_count=7),
            DailyStats(date="2026-01-08", total_tokens=80, cost_usd=8.88, message_count=8),
            DailyStats(date="2026-01-09", total_tokens=90, cost_usd=9.99, message_count=9),
            DailyStats(date="2026-01-10", total_tokens=100, cost_usd=10.01, message_count=10),
        ]
    )

    assert result.token_limit == 100
    assert result.cost_limit == 10.01
    assert result.message_limit == 10

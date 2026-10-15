from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime

import pytest

from adapters.types import UsageEntry
from analyzer import ledger_backfill, reporter, usage_snapshot

DAY = date(2026, 8, 6)


def _entry(tokens: int, cost: float = 0.0) -> UsageEntry:
    return UsageEntry(
        timestamp=datetime(2026, 8, 6),
        session_id="live",
        message_id="live",
        request_id="live",
        model="model-a",
        input_tokens=tokens,
        output_tokens=0,
        cache_creation_tokens=0,
        cache_read_tokens=0,
        cost_usd=cost,
        project="project-a",
        agent_id="claude-code",
    )


def _day(tokens: int = 100, cost: float = 10.0) -> reporter._YearDay:
    return {
        "total_tokens": tokens,
        "cost": cost,
        "agent_tokens": {"claude-code": 60, "codex": 40},
        "project_tokens": {"project-a": 70, "project-b": 30},
        "model_tokens": {"model-a": 80, "model-b": 20},
        "sessions": 2,
    }


def _merge(entries: list[UsageEntry], day: reporter._YearDay) -> list[UsageEntry]:
    result, dates = ledger_backfill.merge_with_ledger(
        entries, {id(entry): DAY for entry in entries}, {DAY.isoformat(): day}, DAY, DAY
    )
    assert all(dates[id(entry)] == DAY for entry in result)
    return result


def test_gap_preserves_all_dimension_totals_and_cost() -> None:
    live = _entry(20, 2.0)
    merged = _merge([live], _day())
    assert merged[0] is live
    assert sum(entry.total_tokens for entry in merged) == 100
    assert sum(entry.cost_usd or 0 for entry in merged) == pytest.approx(10)
    for attr, expected in (
        ("agent_id", {"claude-code": 60, "codex": 40}),
        ("project", {"project-a": 70, "project-b": 30}),
        ("model", {"model-a": 80, "model-b": 20}),
    ):
        actual: dict[str, int] = defaultdict(int)
        for entry in merged:
            actual[getattr(entry, attr)] += entry.total_tokens
        assert actual == expected
    assert all(entry.message_count == 0 for entry in merged[1:])
    assert all(entry.cost_usd == pytest.approx(8 * entry.total_tokens / 80) for entry in merged[1:])


@pytest.mark.parametrize("tokens", [100, 120])
def test_ledger_at_or_below_live_is_unchanged(tokens: int) -> None:
    live = _entry(tokens)
    assert _merge([live], _day()) == [live]


def test_legacy_ledger_without_agents_is_unchanged() -> None:
    day = _day()
    day["agent_tokens"] = {}
    assert _merge([], day) == []


@pytest.mark.parametrize("tokens", [0, -1])
def test_ledger_without_positive_agent_counts_is_unchanged(tokens: int) -> None:
    day = _day()
    day["agent_tokens"] = {"claude-code": tokens}
    assert _merge([], day) == []


def test_snapshot_replay_only_leaves_remaining_gap() -> None:
    usage_snapshot.record_entries([_entry(60, 6.0)])
    replay, dates = usage_snapshot.merge_live_with_snapshot([], {}, DAY, DAY)
    merged, _ = ledger_backfill.merge_with_ledger(
        replay, dates, {DAY.isoformat(): _day()}, DAY, DAY
    )
    assert sum(entry.total_tokens for entry in replay) == 60
    assert sum(entry.total_tokens for entry in merged[len(replay) :]) == 40
    assert sum(entry.total_tokens for entry in merged) == 100
    assert _merge(merged, _day()) == merged


def test_negative_cost_gap_is_zero() -> None:
    merged = _merge([_entry(20, 20.0)], _day())
    assert sum(entry.total_tokens for entry in merged) == 100
    assert all(entry.cost_usd == 0.0 for entry in merged[1:])


def test_no_positive_dimension_gap_falls_back_to_ledger_proportions() -> None:
    day = _day()
    day["agent_tokens"] = {"claude-code": 1}
    day["project_tokens"] = {"project-a": 1}
    day["model_tokens"] = {"model-a": 1}
    merged = _merge([_entry(20)], day)
    assert sum(entry.total_tokens for entry in merged) == 100
    assert all(entry.agent_id == "claude-code" for entry in merged)
    assert all(entry.model == "model-a" for entry in merged)
    assert all(entry.project == "project-a" for entry in merged)


def test_missing_dimensions_use_unknown_and_integer_rounding_keeps_gap() -> None:
    day = _day(7)
    day["project_tokens"] = {}
    day["model_tokens"] = {}
    merged = _merge([], day)
    assert sum(entry.total_tokens for entry in merged) == 7
    assert all(entry.project == entry.model == "unknown" for entry in merged)
    assert {entry.agent_id: entry.total_tokens for entry in merged} == {
        "claude-code": 4,
        "codex": 3,
    }


def test_outside_period_is_unchanged() -> None:
    merged, dates = ledger_backfill.merge_with_ledger(
        [], {}, {DAY.isoformat(): _day()}, date(2026, 8, 7), date(2026, 8, 8)
    )
    assert merged == []
    assert dates == {}

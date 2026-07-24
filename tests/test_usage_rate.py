# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

from datetime import UTC, datetime

import pytest

import usage_rate
from history_loader import UsageEntry


def _entry(total_tokens: int) -> UsageEntry:
    return UsageEntry(
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        session_id="session",
        message_id="message",
        request_id="request",
        model="claude-sonnet",
        input_tokens=total_tokens,
        output_tokens=0,
        cache_creation_tokens=0,
        cache_read_tokens=0,
        cost_usd=None,
        project="project",
    )


def test_group_returns_forced_group() -> None:
    assert usage_rate.UsageRateTracker(forced_group=2).group() == 2


def test_group_returns_idle_for_mock() -> None:
    assert usage_rate.UsageRateTracker(mock=True).group() == 0


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0", 0),
        ("3", 3),
        ("bad", 0),
        ("4", 0),
        ("-1", 0),
    ],
)
def test_group_reads_force_group_env(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
    expected: int,
) -> None:
    monkeypatch.setenv("USAGE_FORCE_GROUP", value)
    monkeypatch.setattr(usage_rate, "load_entries", lambda hours_back: [_entry(10)])

    assert usage_rate.UsageRateTracker().group() == expected


@pytest.mark.parametrize(
    ("tokens", "expected_group"),
    [
        (499, 0),
        (500, 1),
        (2500, 2),
        (6000, 3),
    ],
)
def test_group_burn_rate_buckets(
    monkeypatch: pytest.MonkeyPatch,
    tokens: int,
    expected_group: int,
) -> None:
    monkeypatch.setattr(usage_rate, "load_entries", lambda hours_back: [_entry(tokens)])

    assert usage_rate.UsageRateTracker().group() == expected_group


def test_group_excludes_cache_read_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    entry = UsageEntry(
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        session_id="session",
        message_id="message",
        request_id="request",
        model="claude-sonnet",
        input_tokens=100,
        output_tokens=100,
        cache_creation_tokens=0,
        cache_read_tokens=5_000_000,
        cost_usd=None,
        project="project",
    )
    monkeypatch.setattr(usage_rate, "load_entries", lambda hours_back: [entry])

    assert usage_rate.UsageRateTracker().group() == 0


def test_group_caches_result(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def fake_load_entries(hours_back: int) -> list[UsageEntry]:
        nonlocal calls
        calls += 1
        return [_entry(1000)]

    monkeypatch.setattr(usage_rate, "load_entries", fake_load_entries)
    tracker = usage_rate.UsageRateTracker()

    assert tracker.group() == 1
    assert tracker.group() == 1
    assert calls == 1


def test_group_uses_custom_loader() -> None:
    tracker = usage_rate.UsageRateTracker(load=lambda hours_back: [_entry(3000)])

    assert tracker.group() == 2

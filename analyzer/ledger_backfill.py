# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Rehydrate only the daily token gap left after snapshot replay."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import TYPE_CHECKING

from adapters.types import UsageEntry
from usage_common.pricing import calculate_cost

if TYPE_CHECKING:
    from analyzer.reporter import _YearDay


def is_ledger_entry(entry: UsageEntry) -> bool:
    return entry.session_id.startswith("usage-ledger:")


def _allocate(
    ledger: Mapping[str, int], current: Mapping[str, int], gap: int
) -> list[tuple[str, int]]:
    weights = {key: max(tokens - current.get(key, 0), 0) for key, tokens in ledger.items()}
    if not any(weights.values()):
        weights = {key: max(tokens, 0) for key, tokens in ledger.items()}
    total = sum(weights.values())
    if total == 0:
        return [("unknown", gap)]
    # Integer largest-remainder allocation keeps every dimension's sum exact.
    shares = {key: gap * weight // total for key, weight in weights.items()}
    ranked = sorted(weights, key=lambda key: (-(gap * weights[key] % total), key))
    for key in ranked[: gap - sum(shares.values())]:
        shares[key] += 1
    return [(key, shares[key]) for key in sorted(shares) if shares[key] > 0]


def merge_with_ledger(
    entries: Sequence[UsageEntry],
    entry_dates: Mapping[int, date],
    days: Mapping[str, _YearDay],
    date_from: date,
    date_to: date,
) -> tuple[list[UsageEntry], dict[int, date]]:
    merged = list(entries)
    dates = dict(entry_dates)
    by_day: dict[date, list[UsageEntry]] = defaultdict(list)
    for entry in entries:
        by_day[entry_dates[id(entry)]].append(entry)
    for day_key, ledger in sorted(days.items()):
        day = date.fromisoformat(day_key)
        if not date_from <= day <= date_to or not any(
            tokens > 0 for tokens in ledger["agent_tokens"].values()
        ):
            continue
        current = by_day.get(day, [])
        gap = ledger["total_tokens"] - sum(entry.total_tokens for entry in current)
        if gap <= 0:
            continue
        dimensions: list[list[tuple[str, int]]] = []
        for attribute, ledger_tokens in (
            ("agent_id", ledger["agent_tokens"]),
            ("project", ledger["project_tokens"]),
            ("model", ledger["model_tokens"]),
        ):
            totals: dict[str, int] = defaultdict(int)
            for entry in current:
                totals[getattr(entry, attribute) or "unknown"] += entry.total_tokens
            dimensions.append(_allocate(ledger_tokens, totals, gap))
        cost_gap = max(ledger["cost"] - sum(calculate_cost(entry) for entry in current), 0.0)
        # Intersect the three allocations without claiming historical correlations.
        indices = [0, 0, 0]
        remaining = [dimension[0][1] for dimension in dimensions]
        allocated = 0
        while allocated < gap:
            tokens = min(remaining)
            agent, project, model = (
                dimension[index][0] for dimension, index in zip(dimensions, indices, strict=True)
            )
            synthetic_id = f"usage-ledger:{day_key}:{allocated}"
            entry = UsageEntry(
                timestamp=datetime.combine(day, datetime.min.time()),
                session_id=f"usage-ledger:{day_key}",
                message_id=synthetic_id,
                request_id=synthetic_id,
                agent_id=agent,
                project=project,
                model=model,
                input_tokens=tokens,
                output_tokens=0,
                cache_creation_tokens=0,
                cache_read_tokens=0,
                cost_usd=cost_gap * tokens / gap,
                message_count=0,
            )
            merged.append(entry)
            dates[id(entry)] = day
            allocated += tokens
            for axis in range(3):
                remaining[axis] -= tokens
                if remaining[axis] == 0 and allocated < gap:
                    indices[axis] += 1
                    remaining[axis] = dimensions[axis][indices[axis]][1]
    return merged, dates

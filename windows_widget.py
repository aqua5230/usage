from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from history_loader import UsageEntry


def _utcnow() -> datetime:
    return datetime.now(UTC)


def format_reset(resets_at: float) -> str:
    delta = max(0, round(resets_at - time.time()))
    days, rem = divmod(delta, 86400)
    hours, rem = divmod(rem, 3600)
    mins = rem // 60
    if days:
        return f"{days}d {hours}hr"
    if hours:
        return f"{hours}hr {mins}min"
    return f"{mins}min"


def compute_month_stats(entries: list[UsageEntry]) -> tuple[float, int]:
    now = _utcnow()
    month_entries = [
        e for e in entries
        if e.timestamp.year == now.year and e.timestamp.month == now.month
    ]
    cost = sum(e.cost_usd or 0.0 for e in month_entries)
    sessions = len({e.session_id for e in month_entries})
    return cost, sessions


def run(mock: bool = False, interval: int = 60) -> None:
    pass  # implemented in Task 5

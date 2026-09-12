#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Compare ~/.usage/usage_snapshot.json with a fresh build_report_data period."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from adapters.registry import detect_agents  # noqa: E402
from analyzer.reporter import build_report_data  # noqa: E402
from analyzer.usage_snapshot import (  # noqa: E402
    period_totals,
    read_snapshot,
    replay_entries,
    totals_match,
)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    period = args[0] if args else "month"
    data = build_report_data(detect_agents(), period)
    date_from = date.fromisoformat(data["date_from"])
    date_to = date.fromisoformat(data["date_to"])
    snapshot = period_totals(read_snapshot(), date_from, date_to)
    report_tokens = data["summary"]["total_tokens"]
    report_cost = data["summary"]["cost_usd"]
    report_sessions = data["summary"]["sessions"]

    token_delta = snapshot.total_tokens - report_tokens
    cost_delta = round(snapshot.cost, 4) - round(report_cost, 4)
    session_delta = snapshot.sessions - report_sessions

    print(f"period: {data['period_label']}")
    print(f"{'metric':<14} {'report':>14} {'snapshot':>14} {'delta':>14}")
    print(
        f"{'total_tokens':<14} {report_tokens:>14} "
        f"{snapshot.total_tokens:>14} {token_delta:>14}"
    )
    print(
        f"{'cost':<14} {report_cost:>14.4f} "
        f"{round(snapshot.cost, 4):>14.4f} {cost_delta:>14.4f}"
    )
    print(
        f"{'sessions':<14} {report_sessions:>14} "
        f"{snapshot.sessions:>14} {session_delta:>14}"
    )

    replayed = replay_entries(date_from, date_to)
    replay_tokens = sum(entry.total_tokens for entry in replayed)
    replay_sessions = len({entry.session_id for entry in replayed})
    print(
        f"{'replay_tokens':<14} {replay_tokens:>14} "
        f"{snapshot.total_tokens:>14} {replay_tokens - snapshot.total_tokens:>14}"
    )
    print(
        f"{'replay_sess':<14} {replay_sessions:>14} "
        f"{snapshot.sessions:>14} {replay_sessions - snapshot.sessions:>14}"
    )
    top_sessions = data.get("top_sessions") or []
    if isinstance(top_sessions, list) and top_sessions:
        durations = ", ".join(str(row.get("duration_min", 0)) for row in top_sessions)
        print(f"top_sessions duration_min: {durations}")

    if totals_match(
        snapshot,
        total_tokens=report_tokens,
        cost=report_cost,
        sessions=report_sessions,
    ):
        print("OK")
        return 0
    print("MISMATCH")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

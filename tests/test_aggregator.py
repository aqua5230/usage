# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import os
import time
from datetime import datetime

import pytest

from adapters.types import UsageEntry
from analyzer.aggregator import aggregate_daily


def _tzset() -> None:
    # The test is skipif-gated on tzset, but calling time.tzset() directly
    # fails mypy's win32 run, where the attribute does not exist.
    getattr(time, "tzset", lambda: None)()


@pytest.mark.skipif(not hasattr(time, "tzset"), reason="tzset unavailable")
def test_aggregate_daily_groups_entries_by_local_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_tz = os.environ.get("TZ")
    monkeypatch.setenv("TZ", "Asia/Taipei")
    _tzset()
    try:
        entries = [
            UsageEntry(
                timestamp=datetime.fromisoformat("2026-06-26T23:30:00+00:00"),
                session_id="session-1",
                message_id="message-1",
                request_id="request-1",
                model="gpt-test",
                input_tokens=10,
                output_tokens=1,
                cache_creation_tokens=0,
                cache_read_tokens=0,
                cost_usd=0.0,
                project="demo",
                agent_id="codex",
            ),
            UsageEntry(
                timestamp=datetime.fromisoformat("2026-06-27T01:30:00+00:00"),
                session_id="session-2",
                message_id="message-2",
                request_id="request-2",
                model="gpt-test",
                input_tokens=20,
                output_tokens=2,
                cache_creation_tokens=0,
                cache_read_tokens=0,
                cost_usd=0.0,
                project="demo",
                agent_id="codex",
            ),
        ]

        daily = aggregate_daily(entries)
    finally:
        if original_tz is None:
            monkeypatch.delenv("TZ", raising=False)
        else:
            monkeypatch.setenv("TZ", original_tz)
        _tzset()

    assert len(daily) == 1
    assert daily[0].date == "2026-06-27"
    assert daily[0].total_tokens == 33
    assert daily[0].session_count == 2

# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from adapters import rate_limits
from loaders import claude_usage
from menubar.state import _quota_row
from quota.notifications import QuotaNotifier
from usage_common.i18n import _t
from usage_hooks import usage_statusline


@pytest.mark.parametrize("window", ["five_hour", "seven_day"])
def test_save_expired_window_reaches_readers_and_restored_notification(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, window: str
) -> None:
    now = datetime(2026, 11, 1, 12, tzinfo=UTC)
    now_ts = now.timestamp()
    reset_at = now_ts - 3600
    other = "seven_day" if window == "five_hour" else "five_hour"
    status_file = tmp_path / "usage-status.json"
    status_file.write_text(
        json.dumps({"rate_limits": {window: {"used_percentage": 100, "resets_at": reset_at}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(usage_statusline, "STATUS_FILE", str(status_file))
    monkeypatch.setattr(rate_limits, "STATUS_FILE", str(status_file))
    monkeypatch.setattr(time, "time", lambda: now_ts)
    channel = "claude_session" if window == "five_hour" else "claude_weekly"
    notifier = QuotaNotifier()
    notifier.update({channel: (100.0, True)})

    usage_statusline.save(
        {"rate_limits": {other: {"used_percentage": 46, "resets_at": now_ts + 7200}}}, now
    )

    data = json.loads(status_file.read_text(encoding="utf-8"))
    assert claude_usage._has_rate_limits(data)
    snapshot = claude_usage._build_snapshot(data)
    assert snapshot is not None
    percent = snapshot.current_percent if window == "five_hour" else snapshot.weekly_percent
    reset = snapshot.current_reset_at if window == "five_hour" else snapshot.weekly_reset_at
    assert percent == 0
    assert reset == reset_at
    row = _quota_row(window, percent, reset, now_ts, (0.0, 0.0, 0.0), "zh-TW")
    assert row.available
    assert row.percent == 0
    assert row.reset_done
    assert row.reset_text == _t("zh-TW", "reset_done")
    events = notifier.update({channel: (row.percent, row.available)})
    assert [(event.kind, event.channel) for event in events] == [("restored", channel)]

    monkeypatch.setenv("USAGE_LANG", "en")
    monkeypatch.setattr(usage_statusline, "get_width", lambda: 116)
    for name in ("PREFERENCES_FILE", "CONTEXT_BURN_FILE", "MIX_DIR"):
        monkeypatch.setattr(usage_statusline, name, str(tmp_path / name))
    output = re.sub(r"\x1b\[[0-9;]*m", "", usage_statusline.render(data, now))
    label = "5h" if window == "five_hour" else "7d"
    assert re.search(rf"{label}:[^\n]*?\b0%", output)
    assert "100%" not in output

    limits = rate_limits.load_rate_limits()
    assert limits is not None
    assert (limits.five_hour_pct if window == "five_hour" else limits.seven_day_pct) == 0


@pytest.mark.parametrize("offset, retained", [(-604799, True), (-604800, False), (-604801, False)])
def test_weekly_cache_retention_uses_a_week(offset: int, retained: bool) -> None:
    now = 1_800_000_000
    fresh = {"used_percentage": 46, "resets_at": now + 18000}
    weekly = {"used_percentage": 100, "resets_at": now + offset}
    merged = usage_statusline._merge_rate_limits({"five_hour": fresh}, {"seven_day": weekly}, now)
    assert merged["five_hour"] == fresh
    assert merged.get("seven_day") == (weekly if retained else None)

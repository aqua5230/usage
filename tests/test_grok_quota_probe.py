# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from loaders import grok_quota_probe

_NOW = datetime(2026, 8, 26, 12, tzinfo=UTC)


@pytest.fixture
def grok_log(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    grok_home = tmp_path / ".grok"
    log_path = grok_home / "logs" / "unified.jsonl"
    log_path.parent.mkdir(parents=True)
    monkeypatch.setattr(grok_quota_probe, "GROK_HOME", grok_home)
    monkeypatch.setattr(grok_quota_probe, "GROK_LOG_PATH", log_path)
    return log_path


def _billing(*, used: float, end: str = "2026-09-01T15:50:08+00:00") -> str:
    return json.dumps(
        {
            "ts": "2026-08-26T09:13:58.737Z",
            "msg": "billing: fetched credits config",
            "ctx": {
                "config": {
                    "creditUsagePercent": used,
                    "currentPeriod": {"end": end},
                },
                "subscriptionTier": "SuperGrok Lite",
            },
        }
    )


def test_load_quota_reads_latest_current_billing_snapshot(grok_log: Path) -> None:
    grok_log.write_text(_billing(used=18.0) + "\n", encoding="utf-8")

    result = grok_quota_probe.load_quota(_NOW)

    assert result is not None
    assert result.used_percent == 18.0
    assert result.subscription_tier == "SuperGrok Lite"


def test_load_quota_uses_last_billing_record(grok_log: Path) -> None:
    grok_log.write_text(
        "\n".join((_billing(used=8.0), _billing(used=33.5))) + "\n", encoding="utf-8"
    )

    result = grok_quota_probe.load_quota(_NOW)

    assert result is not None
    assert result.used_percent == 33.5


def test_load_quota_hides_expired_weekly_snapshot(grok_log: Path) -> None:
    grok_log.write_text(
        _billing(used=18.0, end="2026-08-25T15:50:08+00:00") + "\n", encoding="utf-8"
    )

    assert grok_quota_probe.load_quota(_NOW) is None


def test_load_quota_returns_none_without_billing_record(grok_log: Path) -> None:
    grok_log.write_text('{"msg":"startup complete"}\n', encoding="utf-8")

    assert grok_quota_probe.load_quota(_NOW) is None


def test_find_grok_returns_none_when_directory_is_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(grok_quota_probe, "GROK_HOME", tmp_path / ".grok")

    assert grok_quota_probe.find_grok() is None


def test_load_quota_skips_malformed_json_lines(grok_log: Path) -> None:
    grok_log.write_text(_billing(used=44.0) + "\n{not json}\n", encoding="utf-8")

    result = grok_quota_probe.load_quota(_NOW)

    assert result is not None
    assert result.used_percent == 44.0


# The Grok CLI's own log line right after a weekly reset: xAI leaves
# creditUsagePercent out of the snapshot when the used percentage is zero.
_RESET_WEEK_BILLING = (
    '{"ts":"2026-09-02T09:19:32.423Z","src":"shell","pid":83108,"ver":"1.0.13",'
    '"lvl":"info","msg":"billing: fetched credits config","ctx":{"config":'
    '{"currentPeriod":{"type":"USAGE_PERIOD_TYPE_WEEKLY",'
    '"start":"2026-09-01T15:50:08.729634+00:00","end":"2026-09-08T15:50:08.729634+00:00"},'
    '"onDemandCap":{"val":0},"onDemandUsed":{"val":0},"prepaidBalance":{"val":0},'
    '"isUnifiedBillingUser":true,"billingPeriodStart":"2026-09-01T15:50:08.729634+00:00",'
    '"billingPeriodEnd":"2026-09-08T15:50:08.729634+00:00","historyLen":0},'
    '"onDemandEnabled":null,"subscriptionTier":"SuperGrok Lite"}}'
)


def test_load_quota_reads_reset_week_snapshot_without_percent(grok_log: Path) -> None:
    grok_log.write_text(_RESET_WEEK_BILLING + "\n", encoding="utf-8")

    result = grok_quota_probe.load_quota(_NOW)

    assert result is not None
    assert result.used_percent == 0.0
    assert result.period_end == "2026-09-08T15:50:08.729634+00:00"


def test_load_quota_ignores_truncated_billing_snapshot(grok_log: Path) -> None:
    grok_log.write_text(
        '{"ts":"2026-08-25T15:38:22.946Z","msg":"billing: fetched credits config",'
        '"ctx":{"config":{"historyLen":0}}}\n',
        encoding="utf-8",
    )

    assert grok_quota_probe.load_quota(_NOW) is None

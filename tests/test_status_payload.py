from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from loaders import agy_quota_probe as probe
from quota import quota_snapshot, status_payload


@pytest.mark.parametrize("absolute_reset", [False, True])
def test_carried_weekly_snapshot_keeps_own_age_and_reset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, absolute_reset: bool
) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    old_at = now - timedelta(hours=2)
    original = probe.AgyQuotaResult(
        [probe.AgyQuotaGroup("GEMINI", [], probe.AgyQuotaWindow(2, "3h 0m", 180), None)],
        old_at.isoformat(),
    )
    fresh = probe.AgyQuotaResult(
        [probe.AgyQuotaGroup("GEMINI", [], None, probe.AgyQuotaWindow(90, "5h 0m", 300))],
        now.isoformat(),
    )
    carried = probe._carry_missing_weekly(fresh, original)
    payload = json.loads(json.dumps(probe._result_to_payload(carried)))
    if not absolute_reset:
        payload["groups"][0].pop("weekly_resets_at")
    else:
        # The absolute clock wins even if the rounded countdown disagrees.
        payload["groups"][0]["weekly"]["resets_in_minutes"] = 61
    probe.CACHE_PATH.write_text(json.dumps(payload))
    agent = status_payload._status_antigravity(int(now.timestamp()))
    assert agent["age_seconds"] == 0
    assert agent["updated_at"] == now.isoformat()
    group = agent["groups"][0]
    assert group["seven_day"] == {
        "used_percent": 98.0,
        "resets_in_seconds": 3600,
        "updated_at": old_at.isoformat(),
        "age_seconds": 7200,
    }
    assert group["five_hour"] == {"used_percent": 10.0, "resets_in_seconds": 18000}
    snapshot = {
        "schema_version": 1,
        "generated_at": now.isoformat(),
        "agents": {"antigravity": agent},
    }
    monkeypatch.setattr(status_payload, "_status_payload", lambda: snapshot)
    monkeypatch.setattr(quota_snapshot, "SNAPSHOT_PATH", tmp_path / "quota_snapshot.json")
    quota_snapshot.write_snapshot()
    assert json.loads(quota_snapshot.SNAPSHOT_PATH.read_text()) == snapshot


def test_weekly_snapshot_age_never_negative(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(UTC)
    group = probe.AgyQuotaGroup("GEMINI", [], None, None, weekly_fetched_at=now.isoformat())
    monkeypatch.setattr(
        probe, "_read_cache", lambda: probe.AgyQuotaResult([group], now.isoformat())
    )
    agent = status_payload._status_antigravity(int(now.timestamp()) - 10)
    assert agent["groups"][0]["seven_day"]["age_seconds"] == 0

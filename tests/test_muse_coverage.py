"""Muse consumers read synthetic quota snapshots without scheduling a probe."""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from loaders import muse_quota_probe as probe
from quota import status_payload


@pytest.fixture
def muse_cache(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    data = {
        "checked_at": 1_000_000.5,
        "window": {"used_percent": 82.5, "resets_at": 1_003_600.75},
        "weekly": {"used_percent": 96, "resets_at": 1_604_800},
    }
    probe.CACHE_PATH.write_text(json.dumps(data))

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("Muse status must never schedule or run a probe")

    monkeypatch.setattr(probe, "load_quota_snapshot", forbidden)
    monkeypatch.setattr(probe, "_probe_worker", forbidden)
    monkeypatch.setattr(probe, "find_muse", forbidden)
    return data


def test_status_muse_snapshot_only(muse_cache: dict[str, Any]) -> None:
    status = status_payload._status_muse(1_000_100)
    assert status == {
        "available": True,
        "five_hour": {
            "used_percent": 82.5,
            "resets_at": 1_003_600,
            "resets_in_seconds": 3500,
        },
        "seven_day": {
            "used_percent": 96.0,
            "resets_at": 1_604_800,
            "resets_in_seconds": 604700,
        },
        "updated_at": "1970-01-12T13:46:40.500000Z",
        "age_seconds": 100,
    }
    assert status_payload._status_muse(2_000_000)["five_hour"]["resets_in_seconds"] == 0
    assert status_payload._status_payload()["agents"]["muse"]["available"] is True


@pytest.mark.parametrize("contents", [None, "broken", "{}", '{"checked_at":true}'])
def test_status_muse_missing_invalid(contents: str | None) -> None:
    if contents is not None:
        probe.CACHE_PATH.write_text(contents)
    assert status_payload._status_muse(100) == status_payload._status_agent(None, 100)


@pytest.mark.parametrize("failure", [OSError, ValueError, OverflowError])
def test_status_muse_error(monkeypatch: pytest.MonkeyPatch, failure: type[Exception]) -> None:
    def fail() -> Any:
        raise failure("synthetic failure")

    monkeypatch.setattr(probe, "read_cache", fail)
    assert status_payload._status_muse(100)["reason"] == "error"


def test_dashboard_muse_quota(muse_cache: dict[str, Any]) -> None:
    limits = status_payload.RATE_LIMIT_LOADERS["muse"]()
    assert limits is not None
    assert limits.five_hour_pct == 82.5
    assert limits.seven_day_pct == 96
    assert limits.five_hour_resets_at == 1_003_600


def test_quota_hook_python39() -> None:
    source = Path("usage_hooks/usage_quota_aware.py").read_text()
    ast.parse(source, feature_version=(3, 9))
    assert "timezone.utc" in source


@pytest.mark.skipif(sys.platform != "darwin", reason="make_panel_demo imports PyObjC")
def test_demo_contains_muse() -> None:
    import runpy

    demo = runpy.run_path("scripts/make_panel_demo.py")
    state = demo["_demo_state"]("en")
    assert state.hide_muse is False
    assert state.muse_session.available
    assert state.muse_weekly.available

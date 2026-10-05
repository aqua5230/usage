from __future__ import annotations

from typing import Any

import pytest

from updates import checker as update_checker
from updates import gate as update_gate


def test_auto_check_is_due_for_missing_or_invalid_timestamp() -> None:
    assert update_gate.auto_check_is_due({}) is True
    assert update_gate.auto_check_is_due({"last_update_check": {"checked_at": "bad"}}) is True


def test_auto_check_is_due_only_after_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    now = 1_700_000_000.0
    monkeypatch.setattr("updates.gate.time.time", lambda: now)

    assert (
        update_gate.auto_check_is_due(
            {"last_update_check": {"checked_at": now - update_gate.AUTO_CHECK_TTL_SECONDS + 1}},
        )
        is False
    )
    assert (
        update_gate.auto_check_is_due(
            {"last_update_check": {"checked_at": now - update_gate.AUTO_CHECK_TTL_SECONDS}},
        )
        is True
    )


def test_stale_cache_reset_updates_after_upgrade() -> None:
    prefs: dict[str, Any] = {
        "last_update_check": {
            "checked_at": 1700000000.0,
            "current_version": "0.14.3",
            "latest_version": "0.15.0",
            "release_url": "https://x/v0.15.0",
        }
    }

    result = update_gate.stale_cache_reset(prefs, "0.15.0")

    assert result == {
        "checked_at": 1700000000.0,
        "current_version": "0.15.0",
        "latest_version": "0.15.0",
        "release_url": "https://x/v0.15.0",
    }


def test_stale_cache_reset_returns_none_for_pending_update() -> None:
    prefs: dict[str, Any] = {
        "last_update_check": {
            "checked_at": 1700000000.0,
            "current_version": "0.15.0",
            "latest_version": "0.16.0",
            "release_url": "https://x/v0.16.0",
        }
    }

    assert update_gate.stale_cache_reset(prefs, "0.15.0") is None


def test_build_check_cache_entry_with_release(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("updates.gate.time.time", lambda: 1700000000.0)

    result = update_gate.build_check_cache_entry(
        "0.11.3",
        update_checker.ReleaseInfo(version="0.12.0", html_url="https://x/v0.12.0", body=""),
    )

    assert result == {
        "checked_at": 1700000000.0,
        "current_version": "0.11.3",
        "latest_version": "0.12.0",
        "release_url": "https://x/v0.12.0",
    }


def test_build_check_cache_entry_without_release(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("updates.gate.time.time", lambda: 1700000000.0)

    result = update_gate.build_check_cache_entry("0.11.3", None)

    assert result == {
        "checked_at": 1700000000.0,
        "current_version": "0.11.3",
        "latest_version": "0.11.3",
        "release_url": None,
    }


@pytest.mark.parametrize(
    ("result_code", "expected"),
    [
        (1000, ("open", {})),
        (1002, ("skip", {"update_skipped_version": "0.12.0"})),
        (999, ("dismiss", {})),
    ],
)
def test_resolve_alert_choice(
    result_code: int,
    expected: tuple[str, dict[str, str]],
) -> None:
    assert update_gate.resolve_alert_choice(result_code, "0.12.0") == expected


@pytest.mark.parametrize(
    "failures,delay", [(0, 3600), (1, 3600), (2, 7200), (3, 14400), (4, 21600), (10, 21600)]
)
def test_schedule_backoff_and_reset(failures: int, delay: int) -> None:
    schedule = update_gate.AutoCheckSchedule()
    now = 100.0
    assert schedule.try_begin(now)
    assert not schedule.try_begin(now + 100000)
    for index in range(max(1, failures)):
        schedule.finish(now, failed=failures > 0)
        if index < failures - 1:
            now = schedule._next_at
            assert schedule.try_begin(now)
    assert not schedule.try_begin(now + delay - 0.01)
    assert schedule.try_begin(now + delay)
    schedule.finish(now + delay, failed=False)
    assert schedule._failures == 0
    assert not schedule.try_begin(now + delay + 3599)
    assert schedule.try_begin(now + delay + 3600)

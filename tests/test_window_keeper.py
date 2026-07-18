# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

import pytest

import window_keeper


class _SyncThread:
    """Stand-in for threading.Thread that runs the target synchronously.

    Lets tests assert deterministically on what ``maybe_ping`` dispatched,
    without racing a real daemon thread.
    """

    instances: list[_SyncThread] = []

    def __init__(
        self,
        target: Any = None,
        args: tuple[Any, ...] = (),
        daemon: bool = False,
    ) -> None:
        self.target = target
        self.args = args
        self.daemon = daemon
        self.started = False
        _SyncThread.instances.append(self)

    def start(self) -> None:
        self.started = True
        if self.target is not None:
            self.target(*self.args)


@pytest.fixture
def isolated_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Path:
    state_path = tmp_path / "window_keeper.json"
    monkeypatch.setattr(window_keeper, "WINDOW_KEEPER_STATE_PATH", state_path)
    monkeypatch.setattr(window_keeper, "_ping_in_flight", False)
    _SyncThread.instances.clear()
    monkeypatch.setattr(threading, "Thread", _SyncThread)
    return state_path


# --- should_ping (pure gate) ---


EXPIRED = -(window_keeper.PING_EXPIRY_GRACE_SECONDS + 1)


def test_should_ping_disabled() -> None:
    now = time.time()
    assert (
        window_keeper.should_ping(
            now, now + EXPIRED, enabled=False, last_ping_at=None,
            current_percent=0.0, data_source="hook",
        )
        is False
    )


def test_should_ping_window_still_running() -> None:
    now = time.time()
    assert (
        window_keeper.should_ping(
            now, now + 3600, enabled=True, last_ping_at=None,
            current_percent=50.0, data_source="hook",
        )
        is False
    )


def test_should_ping_missing_reset_at() -> None:
    now = time.time()
    assert (
        window_keeper.should_ping(
            now, None, enabled=True, last_ping_at=None,
            current_percent=0.0, data_source="hook",
        )
        is False
    )


def test_should_ping_within_cooldown() -> None:
    now = time.time()
    last_ping = now - 60  # pinged a minute ago
    assert (
        window_keeper.should_ping(
            now, now + EXPIRED, enabled=True, last_ping_at=last_ping,
            current_percent=0.0, data_source="hook",
        )
        is False
    )


def test_should_ping_fires_when_expired_and_cooled() -> None:
    now = time.time()
    last_ping = now - window_keeper.PING_COOLDOWN_SECONDS - 1  # past the cooldown
    assert (
        window_keeper.should_ping(
            now, now + EXPIRED, enabled=True, last_ping_at=last_ping,
            current_percent=0.0, data_source="hook",
        )
        is True
    )


def test_should_ping_fires_with_no_prior_ping() -> None:
    now = time.time()
    assert (
        window_keeper.should_ping(
            now, now + EXPIRED, enabled=True, last_ping_at=None,
            current_percent=0.0, data_source="hook",
        )
        is True
    )


def test_should_ping_within_grace_period_not_yet_expired() -> None:
    # A resets_at only a few seconds in the past looks like it could be the
    # "default to now" placeholder a fallback data source emits — must not fire.
    now = time.time()
    assert (
        window_keeper.should_ping(
            now, now - 5, enabled=True, last_ping_at=None,
            current_percent=0.0, data_source="hook",
        )
        is False
    )


def test_should_ping_ignores_non_hook_source() -> None:
    now = time.time()
    assert (
        window_keeper.should_ping(
            now, now + EXPIRED, enabled=True, last_ping_at=None,
            current_percent=0.0, data_source="claude-json",
        )
        is False
    )


def test_should_ping_missing_percent() -> None:
    now = time.time()
    assert (
        window_keeper.should_ping(
            now, now + EXPIRED, enabled=True, last_ping_at=None,
            current_percent=None, data_source="hook",
        )
        is False
    )


# --- state file read/write ---


def test_load_last_ping_missing_file(isolated_state: Path) -> None:
    assert window_keeper._load_last_ping() is None


def test_save_and_load_last_ping_roundtrip(isolated_state: Path) -> None:
    window_keeper._save_last_ping(12345.5)
    assert window_keeper._load_last_ping() == 12345.5
    payload = json.loads(isolated_state.read_text(encoding="utf-8"))
    assert payload == {"last_ping_at": 12345.5}


def test_load_last_ping_corrupt_json(isolated_state: Path) -> None:
    isolated_state.write_text("not json at all", encoding="utf-8")
    assert window_keeper._load_last_ping() is None


def test_load_last_ping_rejects_non_numeric(isolated_state: Path) -> None:
    isolated_state.write_text(
        json.dumps({"last_ping_at": "soon"}), encoding="utf-8"
    )
    assert window_keeper._load_last_ping() is None


# --- maybe_ping (integration) ---


def _arm_successful_ping(
    monkeypatch: pytest.MonkeyPatch, *, enabled: bool = True
) -> list[str]:
    """Wire every I/O collaborator to fakes so maybe_ping runs hermetically."""
    calls: list[str] = []
    monkeypatch.setattr(window_keeper, "_window_keeper_enabled", lambda: enabled)
    monkeypatch.setattr(
        window_keeper, "_resolve_claude_bin", lambda: "/fake/claude"
    )

    def fake_run(claude_bin: str) -> None:
        calls.append(claude_bin)

    monkeypatch.setattr(window_keeper, "_run_claude_ping", fake_run)
    return calls


def test_maybe_ping_fires_when_conditions_met(
    monkeypatch: pytest.MonkeyPatch, isolated_state: Path
) -> None:
    calls = _arm_successful_ping(monkeypatch)
    now = time.time()
    # Expired window, no prior ping on disk.
    window_keeper.maybe_ping(
        current_reset_at=now + EXPIRED, current_percent=0.0, data_source="hook", mock=False
    )

    assert calls == ["/fake/claude"]
    # last_ping_at stamped at dispatch even though subprocess "ran" synchronously.
    assert window_keeper._load_last_ping() is not None
    assert len(_SyncThread.instances) == 1
    assert _SyncThread.instances[0].started is True


def test_maybe_ping_mock_is_noop(
    monkeypatch: pytest.MonkeyPatch, isolated_state: Path
) -> None:
    calls = _arm_successful_ping(monkeypatch)
    now = time.time()
    window_keeper.maybe_ping(
        current_reset_at=now + EXPIRED, current_percent=0.0, data_source="hook", mock=True
    )

    assert calls == []
    assert isolated_state.exists() is False
    assert _SyncThread.instances == []


def test_maybe_ping_disabled_is_noop(
    monkeypatch: pytest.MonkeyPatch, isolated_state: Path
) -> None:
    # Opt-in switch is OFF — must not read/write state, must not spawn a thread.
    calls = _arm_successful_ping(monkeypatch, enabled=False)
    now = time.time()
    window_keeper.maybe_ping(
        current_reset_at=now + EXPIRED, current_percent=0.0, data_source="hook", mock=False
    )

    assert calls == []
    assert isolated_state.exists() is False
    assert _SyncThread.instances == []


def test_maybe_ping_skips_when_window_still_running(
    monkeypatch: pytest.MonkeyPatch, isolated_state: Path
) -> None:
    calls = _arm_successful_ping(monkeypatch)
    now = time.time()
    window_keeper.maybe_ping(
        current_reset_at=now + 3600, current_percent=50.0, data_source="hook", mock=False
    )

    assert calls == []
    assert isolated_state.exists() is False
    assert _SyncThread.instances == []


def test_maybe_ping_respects_cooldown(
    monkeypatch: pytest.MonkeyPatch, isolated_state: Path
) -> None:
    calls = _arm_successful_ping(monkeypatch)
    now = time.time()
    # Pretend we pinged 10 minutes ago — within the 5h cooldown.
    window_keeper._save_last_ping(now - 600)
    window_keeper.maybe_ping(
        current_reset_at=now + EXPIRED, current_percent=0.0, data_source="hook", mock=False
    )

    assert calls == []
    # State file untouched beyond the seed we wrote.
    assert window_keeper._load_last_ping() == now - 600
    assert _SyncThread.instances == []


def test_maybe_ping_inflight_guard_prevents_double_spawn(
    monkeypatch: pytest.MonkeyPatch, isolated_state: Path
) -> None:
    calls = _arm_successful_ping(monkeypatch)
    now = time.time()
    # Simulate a ping already running.
    monkeypatch.setattr(window_keeper, "_ping_in_flight", True)
    window_keeper.maybe_ping(
        current_reset_at=now + EXPIRED, current_percent=0.0, data_source="hook", mock=False
    )

    assert calls == []
    # Must not have stamped a new ping or spawned another worker.
    assert window_keeper._load_last_ping() is None
    assert _SyncThread.instances == []


def test_maybe_ping_does_not_crash_when_claude_missing(
    monkeypatch: pytest.MonkeyPatch, isolated_state: Path
) -> None:
    calls = _arm_successful_ping(monkeypatch)
    monkeypatch.setattr(window_keeper, "_resolve_claude_bin", lambda: None)
    now = time.time()
    # Should return cleanly, not raise — app must never crash on this path.
    window_keeper.maybe_ping(
        current_reset_at=now + EXPIRED, current_percent=0.0, data_source="hook", mock=False
    )
    # The worker ran (and released the in-flight flag) but fired no subprocess.
    assert calls == []
    assert len(_SyncThread.instances) == 1
    assert _SyncThread.instances[0].started is True
    assert window_keeper._ping_in_flight is False


def test_maybe_ping_ignores_non_hook_source(
    monkeypatch: pytest.MonkeyPatch, isolated_state: Path
) -> None:
    # claude-json / tt-fallback sources may default a missing resets_at to
    # parse time — must not be trusted as a real expiry signal.
    calls = _arm_successful_ping(monkeypatch)
    now = time.time()
    window_keeper.maybe_ping(
        current_reset_at=now + EXPIRED,
        current_percent=0.0,
        data_source="claude-json",
        mock=False,
    )

    assert calls == []
    assert isolated_state.exists() is False
    assert _SyncThread.instances == []

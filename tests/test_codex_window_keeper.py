# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import pytest

import quota.codex_window_keeper as codex_window_keeper
from loaders.codex_loader import CodexRateLimits


def test_resolve_codex_bin_uses_windows_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _: None)
    monkeypatch.setattr(os.path, "expanduser", lambda path: f"/fake/{Path(path).name}")
    monkeypatch.setattr(os.path, "isfile", lambda path: path == "/fake/codex.exe")
    monkeypatch.setattr(os, "access", lambda *_: True)

    assert codex_window_keeper._resolve_codex_bin() == "/fake/codex.exe"


def test_resolve_codex_bin_uses_homebrew_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _: None)
    monkeypatch.setattr(os.path, "expanduser", lambda path: path)
    monkeypatch.setattr(os.path, "isfile", lambda path: path == "/opt/homebrew/bin/codex")
    monkeypatch.setattr(os, "access", lambda *_: True)

    assert codex_window_keeper._resolve_codex_bin() == "/opt/homebrew/bin/codex"


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
    state_path = tmp_path / "codex_window_keeper.json"
    monkeypatch.setattr(
        codex_window_keeper, "CODEX_WINDOW_KEEPER_STATE_PATH", state_path
    )
    monkeypatch.setattr(codex_window_keeper, "_ping_in_flight", False)
    _SyncThread.instances.clear()
    monkeypatch.setattr(threading, "Thread", _SyncThread)
    return state_path


# --- should_ping (pure gate) ---


EXPIRED = -(codex_window_keeper.PING_EXPIRY_GRACE_SECONDS + 1)


def test_should_ping_disabled() -> None:
    now = time.time()
    assert (
        codex_window_keeper.should_ping(
            now, now + EXPIRED, enabled=False, last_pinged_reset_at=None,
            last_ping_at=None,
            current_percent=0.0, has_five_hour_window=True,
        )
        is False
    )


def test_should_ping_no_five_hour_window() -> None:
    now = time.time()
    assert (
        codex_window_keeper.should_ping(
            now, None, enabled=True, last_pinged_reset_at=None,
            last_ping_at=None,
            current_percent=None, has_five_hour_window=False,
        )
        is False
    )


def test_should_ping_window_still_running() -> None:
    now = time.time()
    assert (
        codex_window_keeper.should_ping(
            now, now + 3600, enabled=True, last_pinged_reset_at=None,
            last_ping_at=None,
            current_percent=50.0, has_five_hour_window=True,
        )
        is False
    )


def test_should_ping_missing_reset_at_with_five_hour_window() -> None:
    # Loader-cleared expiry: resets_at is None, window_minutes stayed.
    now = time.time()
    assert (
        codex_window_keeper.should_ping(
            now, None, enabled=True, last_pinged_reset_at=None,
            last_ping_at=None,
            current_percent=0.0, has_five_hour_window=True,
        )
        is True
    )


def test_should_ping_sqlite_cleared_percent_and_reset() -> None:
    now = time.time()
    assert (
        codex_window_keeper.should_ping(
            now, None, enabled=True, last_pinged_reset_at=None,
            last_ping_at=None,
            current_percent=None, has_five_hour_window=True,
        )
        is True
    )


def test_should_ping_rejects_already_handled_boundary() -> None:
    now = time.time()
    reset_at = now + EXPIRED
    assert (
        codex_window_keeper.should_ping(
            now, reset_at, enabled=True, last_pinged_reset_at=reset_at,
            last_ping_at=now - 60,
            current_percent=0.0, has_five_hour_window=True,
        )
        is False
    )


def test_should_ping_cleared_reset_respects_cooldown() -> None:
    now = time.time()
    assert (
        codex_window_keeper.should_ping(
            now, None, enabled=True, last_pinged_reset_at=None,
            last_ping_at=now - 60,
            current_percent=0.0, has_five_hour_window=True,
        )
        is False
    )


def test_should_ping_fires_for_new_boundary_despite_recent_ping() -> None:
    now = time.time()
    previous_reset_at = now - 10 * 60
    assert (
        codex_window_keeper.should_ping(
            now,
            now + EXPIRED,
            enabled=True,
            last_pinged_reset_at=previous_reset_at,
            last_ping_at=now - 60,
            current_percent=0.0, has_five_hour_window=True,
        )
        is True
    )


def test_should_ping_fires_with_no_prior_ping() -> None:
    now = time.time()
    assert (
        codex_window_keeper.should_ping(
            now, now + EXPIRED, enabled=True, last_pinged_reset_at=None,
            last_ping_at=None,
            current_percent=0.0, has_five_hour_window=True,
        )
        is True
    )


def test_should_ping_within_grace_period_not_yet_expired() -> None:
    # A resets_at only a few seconds in the past looks like it could be a
    # synthetic placeholder — must not fire.
    now = time.time()
    assert (
        codex_window_keeper.should_ping(
            now, now - 5, enabled=True, last_pinged_reset_at=None,
            last_ping_at=None,
            current_percent=0.0, has_five_hour_window=True,
        )
        is False
    )


def test_should_ping_missing_percent_with_timestamp() -> None:
    now = time.time()
    assert (
        codex_window_keeper.should_ping(
            now, now + EXPIRED, enabled=True, last_pinged_reset_at=None,
            last_ping_at=None,
            current_percent=None, has_five_hour_window=True,
        )
        is False
    )


def test_should_ping_stale_boundary_after_cooldown() -> None:
    now = time.time()
    reset_at = now + EXPIRED
    assert (
        codex_window_keeper.should_ping(
            now,
            reset_at,
            enabled=True,
            last_pinged_reset_at=reset_at,
            last_ping_at=now - codex_window_keeper.PING_COOLDOWN_SECONDS,
            current_percent=0.0,
            has_five_hour_window=True,
        )
        is True
    )


def test_should_ping_cleared_reset_after_cooldown() -> None:
    now = time.time()
    assert (
        codex_window_keeper.should_ping(
            now,
            None,
            enabled=True,
            last_pinged_reset_at=None,
            last_ping_at=now - codex_window_keeper.PING_COOLDOWN_SECONDS,
            current_percent=0.0,
            has_five_hour_window=True,
        )
        is True
    )


# --- state file read/write ---


def test_load_ping_state_missing_file(isolated_state: Path) -> None:
    assert codex_window_keeper._load_ping_state() == (None, None)


def test_save_and_load_ping_state_roundtrip(isolated_state: Path) -> None:
    codex_window_keeper._save_ping_state(12345.5, 12346.5)
    assert codex_window_keeper._load_ping_state() == (12345.5, 12346.5)
    payload = json.loads(isolated_state.read_text(encoding="utf-8"))
    assert payload == {
        "last_pinged_reset_at": 12345.5,
        "last_ping_at": 12346.5,
    }


def test_save_and_load_ping_state_none_reset_roundtrip(isolated_state: Path) -> None:
    codex_window_keeper._save_ping_state(None, 12346.5)
    assert codex_window_keeper._load_ping_state() == (None, 12346.5)
    payload = json.loads(isolated_state.read_text(encoding="utf-8"))
    assert payload == {
        "last_pinged_reset_at": None,
        "last_ping_at": 12346.5,
    }


def test_save_ping_state_cleans_temp_file_when_replace_fails(
    monkeypatch: pytest.MonkeyPatch, isolated_state: Path
) -> None:
    def fail_replace(*_: object) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", fail_replace)
    codex_window_keeper._save_ping_state(12345.5, 12346.5)

    assert isolated_state.exists() is False
    assert list(isolated_state.parent.glob("*.tmp")) == []


def test_load_ping_state_corrupt_json(isolated_state: Path) -> None:
    isolated_state.write_text("not json at all", encoding="utf-8")
    assert codex_window_keeper._load_ping_state() == (None, None)


def test_load_ping_state_non_utf8(isolated_state: Path) -> None:
    isolated_state.write_bytes(b"\xff\xfe\x00bad")
    assert codex_window_keeper._load_ping_state() == (None, None)


def test_load_ping_state_rejects_non_numeric(isolated_state: Path) -> None:
    isolated_state.write_text(
        json.dumps({"last_pinged_reset_at": "soon"}), encoding="utf-8"
    )
    assert codex_window_keeper._load_ping_state() == (None, None)


def test_load_ping_state_accepts_legacy_last_ping_at(isolated_state: Path) -> None:
    isolated_state.write_text(
        json.dumps({"last_ping_at": 12345.5}), encoding="utf-8"
    )
    assert codex_window_keeper._load_ping_state() == (None, 12345.5)


def test_load_ping_state_accepts_old_reset_only_state(isolated_state: Path) -> None:
    isolated_state.write_text(
        json.dumps({"last_pinged_reset_at": 12345.5}), encoding="utf-8"
    )
    assert codex_window_keeper._load_ping_state() == (12345.5, None)


# --- maybe_ping (integration) ---


def _limits(
    *,
    five_hour_pct: float | None = 0.0,
    five_hour_resets_at: float | None = None,
    five_hour_window_minutes: float | None = 300.0,
) -> CodexRateLimits:
    return CodexRateLimits(
        five_hour_pct=five_hour_pct,
        five_hour_resets_at=five_hour_resets_at,
        seven_day_pct=None,
        seven_day_resets_at=None,
        five_hour_window_minutes=five_hour_window_minutes,
    )


def _arm_successful_ping(
    monkeypatch: pytest.MonkeyPatch,
    *,
    enabled: bool = True,
    limits: CodexRateLimits | None = None,
) -> list[str]:
    """Wire every I/O collaborator to fakes so maybe_ping runs hermetically."""
    calls: list[str] = []
    monkeypatch.setattr(codex_window_keeper, "_window_keeper_enabled", lambda: enabled)
    monkeypatch.setattr(
        codex_window_keeper, "_resolve_codex_bin", lambda: "/fake/codex"
    )
    monkeypatch.setattr(
        codex_window_keeper,
        "load_rate_limits",
        lambda: _limits() if limits is None else limits,
    )

    def fake_run(codex_bin: str) -> None:
        calls.append(codex_bin)

    monkeypatch.setattr(codex_window_keeper, "_run_codex_ping", fake_run)
    return calls


def test_maybe_ping_fires_when_conditions_met(
    monkeypatch: pytest.MonkeyPatch, isolated_state: Path
) -> None:
    calls = _arm_successful_ping(monkeypatch)
    now = time.time()
    # Expired window (loader-cleared resets_at), no prior ping on disk.
    codex_window_keeper.maybe_ping(mock=False)

    assert calls == ["/fake/codex"]
    saved_reset_at, saved_ping_at = codex_window_keeper._load_ping_state()
    assert saved_reset_at is None
    assert saved_ping_at == pytest.approx(now)
    assert len(_SyncThread.instances) == 1
    assert _SyncThread.instances[0].started is True


def test_maybe_ping_fires_for_timestamped_expired_window(
    monkeypatch: pytest.MonkeyPatch, isolated_state: Path
) -> None:
    now = time.time()
    reset_at = now + EXPIRED
    calls = _arm_successful_ping(
        monkeypatch,
        limits=_limits(five_hour_pct=0.0, five_hour_resets_at=reset_at),
    )
    codex_window_keeper.maybe_ping(mock=False)

    assert calls == ["/fake/codex"]
    saved_reset_at, saved_ping_at = codex_window_keeper._load_ping_state()
    assert saved_reset_at == reset_at
    assert saved_ping_at == pytest.approx(now)


def test_maybe_ping_mock_is_noop(
    monkeypatch: pytest.MonkeyPatch, isolated_state: Path
) -> None:
    calls = _arm_successful_ping(monkeypatch)
    monkeypatch.setattr(
        codex_window_keeper,
        "load_rate_limits",
        lambda: pytest.fail("mock keeper must not load rate limits"),
    )
    codex_window_keeper.maybe_ping(mock=True)

    assert calls == []
    assert isolated_state.exists() is False
    assert _SyncThread.instances == []


def test_maybe_ping_disabled_is_noop(
    monkeypatch: pytest.MonkeyPatch, isolated_state: Path
) -> None:
    # Opt-in switch is OFF — must not read/write state, must not spawn a thread.
    calls = _arm_successful_ping(monkeypatch, enabled=False)
    monkeypatch.setattr(
        codex_window_keeper,
        "load_rate_limits",
        lambda: pytest.fail("disabled keeper must not load rate limits"),
    )
    monkeypatch.setattr(
        codex_window_keeper,
        "_load_ping_state",
        lambda: pytest.fail("disabled keeper read its state file"),
    )
    codex_window_keeper.maybe_ping(mock=False)

    assert calls == []
    assert isolated_state.exists() is False
    assert _SyncThread.instances == []


def test_maybe_ping_skips_when_window_still_running(
    monkeypatch: pytest.MonkeyPatch, isolated_state: Path
) -> None:
    now = time.time()
    calls = _arm_successful_ping(
        monkeypatch,
        limits=_limits(five_hour_pct=50.0, five_hour_resets_at=now + 3600),
    )
    codex_window_keeper.maybe_ping(mock=False)

    assert calls == []
    assert isolated_state.exists() is False
    assert _SyncThread.instances == []


def test_maybe_ping_skips_unrestricted_plan(
    monkeypatch: pytest.MonkeyPatch, isolated_state: Path
) -> None:
    calls = _arm_successful_ping(
        monkeypatch,
        limits=_limits(
            five_hour_pct=None,
            five_hour_resets_at=None,
            five_hour_window_minutes=None,
        ),
    )
    codex_window_keeper.maybe_ping(mock=False)

    assert calls == []
    assert isolated_state.exists() is False
    assert _SyncThread.instances == []


def test_maybe_ping_skips_when_rate_limits_missing(
    monkeypatch: pytest.MonkeyPatch, isolated_state: Path
) -> None:
    calls = _arm_successful_ping(monkeypatch)
    monkeypatch.setattr(codex_window_keeper, "load_rate_limits", lambda: None)
    codex_window_keeper.maybe_ping(mock=False)

    assert calls == []
    assert isolated_state.exists() is False
    assert _SyncThread.instances == []


def test_maybe_ping_deduplicates_same_boundary(
    monkeypatch: pytest.MonkeyPatch, isolated_state: Path
) -> None:
    now = time.time()
    reset_at = now + EXPIRED
    calls = _arm_successful_ping(
        monkeypatch,
        limits=_limits(five_hour_pct=0.0, five_hour_resets_at=reset_at),
    )
    codex_window_keeper._save_ping_state(reset_at, now - 60)
    codex_window_keeper.maybe_ping(mock=False)

    assert calls == []
    # State file untouched beyond the seed we wrote.
    assert codex_window_keeper._load_ping_state() == (reset_at, now - 60)
    assert _SyncThread.instances == []


def test_maybe_ping_cleared_reset_deduplicates_via_cooldown(
    monkeypatch: pytest.MonkeyPatch, isolated_state: Path
) -> None:
    now = time.time()
    calls = _arm_successful_ping(monkeypatch)
    codex_window_keeper._save_ping_state(None, now - 60)
    codex_window_keeper.maybe_ping(mock=False)

    assert calls == []
    assert codex_window_keeper._load_ping_state() == (None, now - 60)
    assert _SyncThread.instances == []


def test_maybe_ping_new_boundary_ignores_dispatch_time_drift(
    monkeypatch: pytest.MonkeyPatch, isolated_state: Path
) -> None:
    now = time.time()
    new_reset_at = now + EXPIRED
    previous_reset_at = new_reset_at - 5 * 3600
    calls = _arm_successful_ping(
        monkeypatch,
        limits=_limits(five_hour_pct=0.0, five_hour_resets_at=new_reset_at),
    )
    # Even if the previous ping was dispatched late, deduplication is tied to
    # its true boundary, so this newly expired boundary must still fire.
    codex_window_keeper._save_ping_state(previous_reset_at, now - 60)

    codex_window_keeper.maybe_ping(mock=False)

    assert calls == ["/fake/codex"]
    saved_reset_at, saved_ping_at = codex_window_keeper._load_ping_state()
    assert saved_reset_at == new_reset_at
    assert saved_ping_at == pytest.approx(now)
    assert len(_SyncThread.instances) == 1


def test_maybe_ping_old_reset_only_state_allows_same_boundary(
    monkeypatch: pytest.MonkeyPatch, isolated_state: Path
) -> None:
    now = time.time()
    reset_at = now + EXPIRED
    calls = _arm_successful_ping(
        monkeypatch,
        limits=_limits(five_hour_pct=0.0, five_hour_resets_at=reset_at),
    )
    isolated_state.write_text(
        json.dumps({"last_pinged_reset_at": reset_at}), encoding="utf-8"
    )

    codex_window_keeper.maybe_ping(mock=False)

    assert calls == ["/fake/codex"]
    saved_reset_at, saved_ping_at = codex_window_keeper._load_ping_state()
    assert saved_reset_at == reset_at
    assert saved_ping_at == pytest.approx(now)


def test_maybe_ping_inflight_guard_prevents_double_spawn(
    monkeypatch: pytest.MonkeyPatch, isolated_state: Path
) -> None:
    calls = _arm_successful_ping(monkeypatch)
    # Simulate a ping already running.
    monkeypatch.setattr(codex_window_keeper, "_ping_in_flight", True)
    codex_window_keeper.maybe_ping(mock=False)

    assert calls == []
    # Must not have stamped a new ping or spawned another worker.
    assert codex_window_keeper._load_ping_state() == (None, None)
    assert _SyncThread.instances == []


def test_maybe_ping_does_not_crash_when_codex_missing(
    monkeypatch: pytest.MonkeyPatch, isolated_state: Path
) -> None:
    calls = _arm_successful_ping(monkeypatch)
    monkeypatch.setattr(codex_window_keeper, "_resolve_codex_bin", lambda: None)
    now = time.time()
    # Should return cleanly, not raise — app must never crash on this path.
    codex_window_keeper.maybe_ping(mock=False)
    # The worker ran (and released the in-flight flag) but fired no subprocess.
    assert calls == []
    assert len(_SyncThread.instances) == 1
    assert _SyncThread.instances[0].started is True
    saved_reset_at, saved_ping_at = codex_window_keeper._load_ping_state()
    assert saved_reset_at is None
    assert saved_ping_at == pytest.approx(now)
    assert codex_window_keeper._ping_in_flight is False


def test_run_codex_ping_uses_verified_noninteractive_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        captured.update(kwargs)
        return subprocess.CompletedProcess(command, 0, "ok", "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    codex_window_keeper._run_codex_ping("/fake/codex")

    assert captured["command"] == [
        "/fake/codex",
        "exec",
        "-m",
        "gpt-5.6-luna",
        "--skip-git-repo-check",
        "ok",
    ]
    assert captured["stdin"] is subprocess.DEVNULL
    assert captured["capture_output"] is True
    assert captured["encoding"] == "utf-8"
    assert captured["timeout"] == codex_window_keeper.PING_TIMEOUT_SECONDS

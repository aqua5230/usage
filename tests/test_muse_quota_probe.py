# SPDX-License-Identifier: AGPL-3.0-only
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from loaders import muse_loader
from loaders import muse_quota_probe as probe


def quota(checked_at: float = 1000) -> probe.MuseQuotaResult:
    return {
        "checked_at": checked_at,
        "window": {"used_percent": 25, "resets_at": 10000},
        "weekly": {"used_percent": 75, "resets_at": 20000},
    }


def event() -> dict[str, Any]:
    return {
        "payload_type": "run.usage",
        "payload": {
            "allowance": {
                "window": {"used_percent": 25, "resets_at_ms": 10000000},
                "weekly": {"used_percent": 75, "resets_at_ms": 20000000},
            }
        },
    }


def test_parse_jsonl_skips_noise_and_converts_milliseconds() -> None:
    stdout = "\n".join(["garbage", "[]", "{}", json.dumps(event())])
    assert probe.parse_muse_allowance(stdout, 1000) == quota()


@pytest.mark.parametrize("bad", [None, [], {}, {"checked_at": 1000}, {**quota(), "weekly": None}])
def test_read_invalid_cache_keeps_shared_file(bad: object) -> None:
    probe.CACHE_PATH.write_text(json.dumps(bad))
    assert probe.read_cache() is None
    assert json.loads(probe.CACHE_PATH.read_text()) == bad


def test_read_missing_corrupt_and_good_cache() -> None:
    assert probe.read_cache() is None
    probe.CACHE_PATH.write_bytes(b"\xff")
    assert probe.read_cache() is None
    assert probe.CACHE_PATH.read_bytes() == b"\xff"
    probe.CACHE_PATH.write_text("{")
    assert probe.read_cache() is None
    assert probe.CACHE_PATH.read_text() == "{"
    probe.CACHE_PATH.write_text(json.dumps(quota()))
    assert probe.read_cache() == quota()


@pytest.mark.parametrize("value", [True, None, "25", -1, float("nan"), float("inf"), 10**400])
def test_invalid_percent_rejected(value: object) -> None:
    raw = event()
    raw["payload"]["allowance"]["window"]["used_percent"] = value
    assert probe.parse_muse_allowance(json.dumps(raw), 1000) is None


@pytest.mark.parametrize("value", [100, 104, 105, 250])
def test_exhausted_window_past_100_is_kept(value: int) -> None:
    raw = event()
    raw["payload"]["allowance"]["window"]["used_percent"] = value
    result = probe.parse_muse_allowance(json.dumps(raw), 1000)
    assert result is not None and result["window"]["used_percent"] == value


# Captured from Muse Code 1.4.11 on 2026-10-21 while the 5-hour window was used up.
EXHAUSTED = json.dumps(
    {
        "payload_type": "run.terminal.failed",
        "payload": {
            "reason": "API error 429 [request_id=x]: Subscription quota exhausted. "
            "Your usage window resets at 2026-10-21T08:28:56Z. (rate_limit_error)"
        },
    }
)
EXHAUSTED_QUOTA = {**quota(), "window": {"used_percent": 100.0, "resets_at": 1792571336.0}}


def test_exhausted_429_keeps_weekly_and_snapshot_age() -> None:
    now = 1792571336 - 3600
    assert probe.parse_exhausted_window(EXHAUSTED, quota(), now) == EXHAUSTED_QUOTA
    assert probe.parse_exhausted_window(EXHAUSTED, None, now) is None
    assert probe.parse_exhausted_window(json.dumps(event()), quota(), now) is None


WEEKLY_RESET = 1792972800.0  # 2026-10-26T00:00:00Z, seen in a 429 on 2026-10-22.
WEEKLY_EXHAUSTED = EXHAUSTED.replace("2026-10-21T08:28:56Z", "2026-10-26T00:00:00Z")


@pytest.mark.parametrize(
    "window_reset,expected_window",
    [
        (1_000, {"used_percent": 0.0, "resets_at": 2_000}),  # Lapsed: nothing ran since.
        (2_000 + 3600, {"used_percent": 25, "resets_at": 2_000 + 3600}),  # Still open.
        (WEEKLY_RESET, {"used_percent": 0.0, "resets_at": 2_000}),  # v0.34.5 misread.
    ],
)
def test_weekly_429_fills_weekly_and_refreshes_age(
    window_reset: float, expected_window: dict[str, float]
) -> None:
    now = 2_000.0
    cached = quota()
    cached["window"]["resets_at"] = window_reset
    assert probe.parse_exhausted_window(WEEKLY_EXHAUSTED, cached, now) == {
        "checked_at": now,
        "window": expected_window,
        "weekly": {"used_percent": 100.0, "resets_at": WEEKLY_RESET},
    }


def test_exhausted_probe_updates_session_window(monkeypatch: pytest.MonkeyPatch) -> None:
    probe.CACHE_PATH.write_text(json.dumps(quota()))
    process = Mock(returncode=1)
    process.poll.return_value = 1
    process.communicate.return_value = (EXHAUSTED, "")
    monkeypatch.setattr(subprocess, "Popen", Mock(return_value=process))
    probe._probe_worker("/fake/muse")
    assert probe.read_cache() == EXHAUSTED_QUOTA
    assert probe._retry_after == 0.0


def test_missing_weekly_is_rejected() -> None:
    raw = event()
    del raw["payload"]["allowance"]["weekly"]
    assert probe.parse_muse_allowance(json.dumps(raw), 1000) is None


@pytest.mark.parametrize(
    "installed,cached,latest,now,starts",
    [
        (False, None, 1001, 2801, False),
        (True, None, None, 2801, False),
        (True, None, 1001, 2801, True),
        (True, 1000, 1001, 2800, False),  # Exactly 30 minutes stays fresh.
        (True, 1000, 1001, 2801, True),
        (True, 1000, 1000, 2801, False),
        (True, 1000, 999, 2801, False),
        (True, 1000, None, 2801, False),
    ],
)
def test_probe_gates(
    monkeypatch: pytest.MonkeyPatch,
    installed: bool,
    cached: int | None,
    latest: int | None,
    now: int,
    starts: bool,
) -> None:
    if cached is not None:
        probe.CACHE_PATH.write_text(json.dumps(quota(cached)))
    monkeypatch.setattr(probe, "find_muse", lambda: "/fake/muse" if installed else None)
    monkeypatch.setattr(probe, "latest_session_mtime", lambda: latest)
    monkeypatch.setattr(time, "time", lambda: now)
    thread = Mock()
    monkeypatch.setattr(threading, "Thread", thread)
    result = probe.load_quota()
    assert thread.called is starts
    assert result == (quota(cached) if installed and cached is not None else None)
    if starts:
        assert thread.call_args.kwargs["daemon"] is True
        thread.return_value.start.assert_called_once()


def test_latest_session_ignores_disappeared_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    session = tmp_path / "session.jsonl"
    session.touch()
    os.utime(session, (5000, 5000))
    monkeypatch.setattr(muse_loader, "session_paths", lambda: (session, tmp_path / "missing"))
    assert probe.latest_session_mtime() == 5000


def test_probe_hides_windows_console(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(probe, "hidden_console_kwargs", lambda: {"creationflags": 0x08000000})
    process = Mock(returncode=0)
    process.poll.return_value = 0
    process.communicate.return_value = (json.dumps(event()), "")
    popen = Mock(return_value=process)
    monkeypatch.setattr(subprocess, "Popen", popen)
    probe._probe_worker("/fake/muse")
    assert popen.call_args.kwargs["creationflags"] == 0x08000000


@pytest.mark.parametrize("failure", ["timeout", "exit", "invalid", "write"])
def test_failure_cools_down_for_30_minutes(monkeypatch: pytest.MonkeyPatch, failure: str) -> None:
    monkeypatch.setattr(probe, "find_muse", lambda: "/fake/muse")
    monkeypatch.setattr(probe, "latest_session_mtime", lambda: 1001)
    clock = [100.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    process = Mock(returncode=1 if failure == "exit" else 0)
    process.poll.return_value = process.returncode
    process.communicate.return_value = ("{}" if failure == "invalid" else json.dumps(event()), "")
    if failure == "timeout":
        process.communicate.side_effect = [subprocess.TimeoutExpired("fake", 120), ("", "")]
    if failure == "write":
        monkeypatch.setattr(probe, "_write_cache", Mock(side_effect=OSError("disk full")))
    monkeypatch.setattr(subprocess, "Popen", Mock(return_value=process))
    probe._probe_worker("/fake/muse")
    assert probe._retry_after == 1900
    thread = Mock()
    monkeypatch.setattr(threading, "Thread", thread)
    clock[0] = 1899.999
    probe.load_quota()
    thread.assert_not_called()
    clock[0] = 1900
    probe.load_quota()
    thread.return_value.start.assert_called_once()


def test_hidden_card_reads_snapshot_without_probing(monkeypatch: pytest.MonkeyPatch) -> None:
    probe.CACHE_PATH.write_text(json.dumps(quota(0)))
    monkeypatch.setattr(probe, "find_muse", lambda: "/fake/muse")
    monkeypatch.setattr(probe, "latest_session_mtime", lambda: 1001)
    thread = Mock()
    monkeypatch.setattr(threading, "Thread", thread)

    assert probe.load_quota_snapshot(allow_probe=False) == (probe.read_cache(), 1001)
    thread.assert_not_called()
    probe.load_quota_snapshot()
    thread.return_value.start.assert_called_once()


def test_single_background_probe_returns_old_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    probe.CACHE_PATH.write_text(json.dumps(quota(0)))
    monkeypatch.setattr(probe, "find_muse", lambda: "/fake/muse")
    monkeypatch.setattr(probe, "latest_session_mtime", lambda: 1)
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    calls: list[dict[str, Any]] = []

    def popen(command: list[str], **kwargs: Any) -> Mock:
        calls.append({"command": command, **kwargs})
        process = Mock(returncode=0)
        process.poll.return_value = 0

        def communicate(*, timeout: int) -> tuple[str, str]:
            calls[-1]["timeout"] = timeout
            assert probe._probe_process is process
            entered.set()
            assert release.wait(5)
            return json.dumps(event()), ""

        process.communicate.side_effect = communicate
        return process

    monkeypatch.setattr(subprocess, "Popen", popen)
    worker = probe._probe_worker

    def tracked_worker(executable: str) -> None:
        try:
            worker(executable)
        finally:
            finished.set()

    monkeypatch.setattr(probe, "_probe_worker", tracked_worker)
    try:
        assert probe.load_quota() == quota(0)
        assert entered.wait(5)
        for _ in range(10):
            assert probe.load_quota() == quota(0)
        assert len(calls) == 1
        assert probe._probe_running
    finally:
        release.set()
        assert finished.wait(5)
    assert not probe._probe_running
    assert probe.read_cache() != quota(0)
    assert probe.load_quota() == probe.read_cache()
    call = calls[0]
    assert call["command"] == [
        "/fake/muse",
        "exec",
        "--model",
        probe.MUSE_MODEL,
        "--reasoning-effort",
        "low",
        "--trust-workspace",
        "--disable-web-tools",
        "--no-session-log",
        "--json",
        "Reply with OK only.",
    ]
    assert call["stdin"] == subprocess.DEVNULL
    assert call["cwd"] == probe.PROBE_DIR
    assert call["timeout"] == 120
    assert call["encoding"] == "utf-8"
    assert list(probe.CACHE_PATH.parent.glob("*.tmp")) == []


def test_atomic_cache_replace_preserves_old_until_complete(monkeypatch: pytest.MonkeyPatch) -> None:
    old, new = quota(1000), quota(3000)
    probe.CACHE_PATH.write_text(json.dumps(old))
    replace = os.replace

    def checked_replace(source: str, destination: Path) -> None:
        assert Path(source).parent == destination.parent
        assert probe.read_cache() == old
        assert json.loads(Path(source).read_text()) == new
        replace(source, destination)

    monkeypatch.setattr(os, "replace", checked_replace)
    probe._write_cache(new)
    assert probe.read_cache() == new


def test_failed_cache_replace_keeps_shared_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    probe.CACHE_PATH.write_text(json.dumps(quota()))
    monkeypatch.setattr(os, "replace", Mock(side_effect=OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        probe._write_cache(quota(3000))
    assert probe.read_cache() == quota()
    assert list(probe.CACHE_PATH.parent.glob("*.tmp")) == []


def test_thread_start_failure_cools_down(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(probe, "find_muse", lambda: "/fake/muse")
    monkeypatch.setattr(probe, "latest_session_mtime", lambda: 1001)
    monkeypatch.setattr(time, "monotonic", lambda: 100)
    thread = Mock()
    thread.return_value.start.side_effect = RuntimeError("cannot start thread")
    monkeypatch.setattr(threading, "Thread", thread)
    assert probe.load_quota() is None
    assert not probe._probe_running
    assert probe._retry_after == 1900
    probe.load_quota()
    assert thread.call_count == 1

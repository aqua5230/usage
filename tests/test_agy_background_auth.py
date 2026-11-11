# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

import json
import subprocess
import threading
import time
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from loaders import agy_quota_probe as probe
from loaders.agy_quota_probe import AgyQuotaGroup, AgyQuotaResult, AgyQuotaWindow
from menubar import agy as card
from quota import agy_window_keeper as keeper
from quota import keeper_outcome

_probe_via_cli = probe._probe_via_cli


@pytest.fixture(autouse=True)
def isolate_background(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    monkeypatch.setattr(probe, "_probe_via_cli", _probe_via_cli)
    monkeypatch.setattr(probe, "_CLI_LOG_PATH", tmp_path / "cli.log")
    monkeypatch.setattr(probe, "_cli_retry_after_monotonic", 0.0)
    monkeypatch.setattr(probe, "_rate_limit_until_monotonic", 0.0)
    monkeypatch.setattr(probe, "_group_seen_at", {})
    monkeypatch.setattr(probe, "BACKGROUND_AGY_LOCK", threading.Lock())
    monkeypatch.setattr(probe, "find_agy", lambda: "/fake/agy")
    monkeypatch.setattr(probe, "_resolve_access_token", lambda timeout: None)
    monkeypatch.setattr(keeper, "_resolve_agy_bin", lambda: "/fake/agy")
    monkeypatch.setattr(keeper, "_ping_in_flight", False)
    monkeypatch.setattr(
        subprocess, "run", lambda *args, **kwargs: pytest.fail("unexpected subprocess")
    )
    yield
    assert not probe.BACKGROUND_AGY_LOCK.locked()


def _success(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
    payload = {"command": {"data": {"groups": [{"name": "Gemini Models", "buckets": []}]}}}
    return subprocess.CompletedProcess(command, 0, json.dumps(payload).encode(), b"")


def _invoke(caller: str) -> object:
    if caller == "probe":
        return _probe_via_cli(15)
    try:
        return keeper._run_agy_ping("/fake/agy")
    except keeper._PingSkipped:
        return None


@pytest.mark.parametrize(
    "message", ["Print mode: not authenticated", "triggering interactive OAuth"]
)
@pytest.mark.parametrize("timeout", [False, True])
def test_probe_marks_only_new_signout_log(
    monkeypatch: pytest.MonkeyPatch, message: str, timeout: bool
) -> None:
    probe._CLI_LOG_PATH.write_text("old log\n", encoding="utf-8")

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        with probe._CLI_LOG_PATH.open("a", encoding="utf-8") as log:
            log.write(message + "\n")
        if timeout:
            raise subprocess.TimeoutExpired(command, 15)
        return subprocess.CompletedProcess(command, 1, b"", b"")

    monkeypatch.setattr(subprocess, "run", run)
    assert _probe_via_cli(15) is None
    assert probe.CLI_SIGNED_OUT_PATH.exists()


def test_old_signout_log_does_not_mark_an_unrelated_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe._CLI_LOG_PATH.write_text("Print mode: not authenticated\n", encoding="utf-8")
    monkeypatch.setattr(
        subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess([], 1, b"", b"")
    )
    assert _probe_via_cli(15) is None
    assert not probe.CLI_SIGNED_OUT_PATH.exists()


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_probe_marks_authentication_required(monkeypatch: pytest.MonkeyPatch, stream: str) -> None:
    result = subprocess.CompletedProcess(["/fake/agy"], 1, b"", b"")
    setattr(result, stream, b"Authentication required")
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: result)
    assert _probe_via_cli(15) is None
    assert probe.CLI_SIGNED_OUT_PATH.exists()


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_probe_marks_authentication_required_in_timeout_output(
    monkeypatch: pytest.MonkeyPatch, stream: str
) -> None:
    error = subprocess.TimeoutExpired(["/fake/agy"], 15)
    setattr(error, stream, b"Authentication required")

    def run(*args: object, **kwargs: object) -> None:
        raise error

    monkeypatch.setattr(subprocess, "run", run)
    assert _probe_via_cli(15) is None
    assert probe.CLI_SIGNED_OUT_PATH.exists()


@pytest.mark.parametrize("message", ["Authentication required", "authentication failed"])
@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_keeper_marks_signout(monkeypatch: pytest.MonkeyPatch, message: str, stream: str) -> None:
    result = subprocess.CompletedProcess(["/fake/agy"], 1, "", "")
    setattr(result, stream, message)
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: result)
    keeper._ping_worker(0)
    assert probe.CLI_SIGNED_OUT_PATH.exists()
    assert keeper_outcome.read_state(keeper.AGY_WINDOW_KEEPER_STATE_PATH)["last_result"] == "failed"


@pytest.mark.parametrize("caller", ["probe", "keeper"])
def test_signed_out_without_token_never_launches(caller: str) -> None:
    probe.CLI_SIGNED_OUT_PATH.touch()
    assert _invoke(caller) is None
    assert probe.CLI_SIGNED_OUT_PATH.exists()
    assert probe._cli_retry_after_monotonic == 0


def test_keeper_signed_out_skip_leaves_dispatch_state_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe.CLI_SIGNED_OUT_PATH.touch()
    monkeypatch.setattr(keeper, "_agy_window_keeper_enabled", lambda: True)
    monkeypatch.setattr(keeper, "_debug_log", lambda message: logs.append(message))
    logs: list[str] = []
    quota = _quota(datetime.now(UTC), None)
    projection = card.project_quota(quota, "en")
    keeper.maybe_ping(card.AgyRefreshResult(projection, False), mock=False)
    assert not keeper.AGY_WINDOW_KEEPER_STATE_PATH.exists()
    assert logs == ["Antigravity ping skipped: CLI is signed out"]


@pytest.mark.parametrize("caller", ["probe", "keeper"])
def test_signin_removes_marker_resets_cooldown_and_launches(
    monkeypatch: pytest.MonkeyPatch, caller: str
) -> None:
    probe.CLI_SIGNED_OUT_PATH.touch()
    monkeypatch.setattr(probe, "_cli_retry_after_monotonic", time.monotonic() + 1800)
    monkeypatch.setattr(probe, "_resolve_access_token", lambda timeout: "fake-access-token")
    calls: list[list[str]] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append(command)
        assert not probe.CLI_SIGNED_OUT_PATH.exists()
        assert probe._cli_retry_after_monotonic == 0
        return _success(command)

    monkeypatch.setattr(subprocess, "run", run)
    assert _invoke(caller) is not None
    assert len(calls) == 1
    assert not probe.CLI_SIGNED_OUT_PATH.exists()
    assert probe._cli_retry_after_monotonic == 0


@pytest.mark.parametrize("first", ["probe", "keeper"])
@pytest.mark.parametrize("second", ["probe", "keeper"])
def test_shared_lock_skips_second_concurrent_run(
    monkeypatch: pytest.MonkeyPatch, first: str, second: str
) -> None:
    entered, release = threading.Event(), threading.Event()
    calls: list[list[str]] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append(command)
        entered.set()
        assert release.wait(5)
        return _success(command)

    monkeypatch.setattr(subprocess, "run", run)
    results: list[object] = []
    thread = threading.Thread(target=lambda: results.append(_invoke(first)))
    thread.start()
    try:
        assert entered.wait(5)
        assert _invoke(second) is None
        assert len(calls) == 1
        assert probe._cli_retry_after_monotonic == 0
    finally:
        release.set()
        thread.join(5)
    assert not thread.is_alive()
    assert results[0] is not None


def test_keeper_worker_skip_preserves_outcome_and_allows_retry() -> None:
    path = keeper.AGY_WINDOW_KEEPER_STATE_PATH
    previous = {"last_result": "ok", "last_ping_at": 123, "retry_used": False}
    keeper_outcome.update_state(path, previous)
    probe.BACKGROUND_AGY_LOCK.acquire()
    try:
        keeper._ping_worker(123)
    finally:
        probe.BACKGROUND_AGY_LOCK.release()
    assert keeper_outcome.read_state(path) == previous | {"last_ping_at": None}
    assert not keeper._ping_in_flight


def _quota(at: datetime, weekly: AgyQuotaWindow | None) -> AgyQuotaResult:
    return AgyQuotaResult(
        [AgyQuotaGroup("GEMINI MODELS", [], weekly, AgyQuotaWindow(100, None, None))],
        at.isoformat(),
    )


@pytest.mark.parametrize("skipped", [False, True])
def test_weekly_survives_failed_or_skipped_cli_and_stays_stale(
    monkeypatch: pytest.MonkeyPatch, skipped: bool
) -> None:
    now = datetime.now(UTC)
    original_at = now - timedelta(minutes=6)
    probe._write_cache(_quota(original_at, AgyQuotaWindow(42, "2h 0m", 120)))
    if skipped:
        probe.CLI_SIGNED_OUT_PATH.touch()
    else:
        monkeypatch.setattr(
            subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess([], 1, b"", b"")
        )
    # A failed marker check skips the CLI; the fallback still resolves the token.
    tokens = iter([None, "fake-access-token"] if skipped else ["fake-access-token"])
    monkeypatch.setattr(probe, "_resolve_access_token", lambda timeout: next(tokens))

    def post(url: str, *args: object) -> object:
        if url == probe._QUOTA_URL:
            return {"groups": [{"name": "Claude and GPT models", "buckets": []}]}
        assert url == probe._MODELS_URL
        return {
            "models": {
                "gemini-flash": {
                    "quotaInfo": {
                        "remainingFraction": 1,
                        "resetTime": (now + timedelta(hours=4)).isoformat(),
                    }
                }
            }
        }

    monkeypatch.setattr(probe, "_post_json", post)

    result = probe.load_quota()

    assert result is not None
    assert result.groups[0].weekly == AgyQuotaWindow(42, "1h 54m", 114)
    assert result.groups[0].weekly_fetched_at == original_at.isoformat()
    assert probe._read_cache() == result
    projection = card.project_quota(result, "en", now=now.timestamp())
    assert projection is not None
    assert projection.weekly.percent == 58
    assert projection.weekly.reset_text != "--"
    assert projection.stale == {"ageText": "about 6 minutes ago"}
    assert (
        probe._carry_missing_weekly(_quota(now + timedelta(minutes=6), None), result)
        .groups[0]
        .weekly_fetched_at
        == original_at.isoformat()
    )


@pytest.mark.parametrize("elapsed", [120, 121])
def test_weekly_dropped_at_cached_reset(elapsed: int) -> None:
    now = datetime.now(UTC)
    cached = _quota(now, AgyQuotaWindow(42, "2h 0m", 120))
    result = probe._carry_missing_weekly(_quota(now + timedelta(minutes=elapsed), None), cached)
    assert result.groups[0].weekly is None
    assert result.groups[0].weekly_fetched_at is None


def test_expired_carried_weekly_dropped_even_from_fresh_cache() -> None:
    now = datetime.now(UTC)
    cached = _quota(now - timedelta(minutes=2), AgyQuotaWindow(42, "1m", 1))
    cached = replace(
        cached,
        groups=[
            replace(cached.groups[0], weekly_fetched_at=(now - timedelta(hours=1)).isoformat())
        ],
    )
    probe._write_cache(cached)
    result = probe.load_quota()
    assert result is not None
    assert result.groups[0].weekly is None
    assert result.groups[0].weekly_fetched_at is None


def test_missing_weekly_never_crosses_groups_or_overrides_fresh_window() -> None:
    now = datetime.now(UTC)
    cached = _quota(now, AgyQuotaWindow(42, "2h 0m", 120))
    fresh = _quota(now + timedelta(minutes=6), AgyQuotaWindow(20, "1h 54m", 114))
    assert probe._carry_missing_weekly(fresh, cached) == fresh
    other = replace(
        fresh, groups=[replace(fresh.groups[0], name="CLAUDE AND GPT MODELS", weekly=None)]
    )
    assert probe._carry_missing_weekly(other, cached) == other


def test_fresh_cli_replaces_carried_weekly_and_clears_staleness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    original = _quota(now - timedelta(minutes=30), AgyQuotaWindow(42, "2h 0m", 120))
    carried = probe._carry_missing_weekly(_quota(now - timedelta(minutes=6), None), original)
    probe._write_cache(carried)
    monkeypatch.setattr(subprocess, "run", _success)
    result = probe.load_quota()
    assert result is not None
    assert result.groups[0].weekly_fetched_at is None
    projection = card.project_quota(result, "en")
    assert projection is not None
    assert projection.stale is None

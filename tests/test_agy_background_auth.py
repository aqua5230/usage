# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

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
    probe._TOKEN_PATH.write_text(
        json.dumps({"token": {"access_token": "old-fake-token", "expiry": "2099-01-01T00:00:00Z"}})
    )
    probe.mark_cli_signed_out(probe._credential_fingerprint())
    monkeypatch.setattr(probe, "_cli_retry_after_monotonic", time.monotonic() + 1800)
    probe._TOKEN_PATH.write_text(
        json.dumps({"token": {"access_token": "new-fake-token", "expiry": "2099-01-01T00:00:00Z"}})
    )
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
    # The credential gate skips the CLI; the fallback still resolves the token.
    monkeypatch.setattr(probe, "_resolve_access_token", lambda timeout: "fake-access-token")

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


@pytest.mark.parametrize("caller", ["probe", "keeper"])
def test_unchanged_stale_credential_keeps_gate_and_cooldown(
    monkeypatch: pytest.MonkeyPatch, caller: str
) -> None:
    credential = {
        "token": {
            "access_token": "expired-fake-token",
            "refresh_token": "revoked-fake-refresh",
            "expiry": "2000-01-01T00:00:00Z",
        }
    }
    probe._TOKEN_PATH.write_text(json.dumps(credential))
    reads = []
    read_token_file = probe._read_token_file

    def read() -> object:
        reads.append(True)
        return read_token_file()

    monkeypatch.setattr(probe, "_read_token_file", read)
    monkeypatch.setattr(
        probe, "_resolve_access_token", lambda _: pytest.fail("gate must not resolve tokens")
    )
    monkeypatch.setattr(probe, "_refresh_token", lambda *_: pytest.fail("gate must not refresh"))
    probe.mark_cli_signed_out(probe._credential_fingerprint())
    marker = json.loads(probe.CLI_SIGNED_OUT_PATH.read_text())
    assert set(marker) == {"fingerprint", "marked_at"}
    assert len(marker["fingerprint"]) == 64
    assert "fake-token" not in probe.CLI_SIGNED_OUT_PATH.read_text()
    clock = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(probe, "_cli_retry_after_monotonic", 1800.0)
    reads.clear()
    for i in range(10):
        clock[0] = i * 180.0
        assert _invoke(caller) is None
    # The keeper also captures the pre-run digest immediately after taking the lock.
    assert len(reads) == (20 if caller == "keeper" else 10)
    assert probe._cli_retry_after_monotonic == 1800.0
    assert json.loads(probe.CLI_SIGNED_OUT_PATH.read_text()) == marker


def test_changed_credential_failed_launch_rewrites_digest_and_keeps_cooldown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe._TOKEN_PATH.write_text(
        json.dumps({"token": {"access_token": "old-fake-token", "expiry": "2099-01-01T00:00:00Z"}})
    )
    probe.mark_cli_signed_out(probe._credential_fingerprint())
    old_digest = json.loads(probe.CLI_SIGNED_OUT_PATH.read_text())["fingerprint"]
    probe._TOKEN_PATH.write_text(
        json.dumps({"token": {"access_token": "new-fake-token", "expiry": "2099-01-01T00:00:00Z"}})
    )
    clock = [100.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(probe, "_cli_retry_after_monotonic", 1800.0)
    launches = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        launches.append(clock[0])
        assert not probe.CLI_SIGNED_OUT_PATH.exists()
        assert probe._cli_retry_after_monotonic == 0.0
        return subprocess.CompletedProcess(command, 1, b"Authentication required", b"")

    monkeypatch.setattr(subprocess, "run", run)
    assert _probe_via_cli(15) is None
    assert probe._cli_retry_after_monotonic == 1900.0
    new_digest = json.loads(probe.CLI_SIGNED_OUT_PATH.read_text())["fingerprint"]
    assert new_digest == probe._credential_fingerprint()
    assert new_digest != old_digest
    for i in range(10):
        clock[0] = 280 + i * 180.0
        assert _probe_via_cli(15) is None
    assert launches == [100.0]
    assert probe._cli_retry_after_monotonic == 1900.0


@pytest.mark.parametrize(
    ("caller", "failure"),
    [
        ("probe", "stdout"),
        ("probe", "stderr"),
        ("probe", "timeout_stdout"),
        ("probe", "timeout_stderr"),
        ("probe", "log"),
        ("probe", "timeout_log"),
        ("keeper", "stdout"),
        ("keeper", "stderr"),
    ],
)
@pytest.mark.parametrize("changed", [False, True])
def test_failed_run_marks_only_unchanged_credential_and_retries_after_cooldown(
    monkeypatch: pytest.MonkeyPatch, caller: str, failure: str, changed: bool
) -> None:
    probe._TOKEN_PATH.write_text(
        json.dumps({"token": {"access_token": "old-fake-token", "expiry": "2099-01-01T00:00:00Z"}})
    )
    before = probe._credential_fingerprint()
    clock = [100.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    launches: list[float] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        launches.append(clock[0])
        if len(launches) > 1:
            return _success(command)
        if changed:
            probe._TOKEN_PATH.write_text(
                json.dumps(
                    {"token": {"access_token": "new-fake-token", "expiry": "2099-01-01T00:00:00Z"}}
                )
            )
        if "log" in failure:
            probe._CLI_LOG_PATH.write_text("triggering interactive OAuth\n", encoding="utf-8")
        stream = "stderr" if "stderr" in failure else "stdout"
        if failure.startswith("timeout"):
            error = subprocess.TimeoutExpired(command, 15)
            if "log" not in failure:
                setattr(error, stream, b"Authentication required")
            raise error
        result = subprocess.CompletedProcess(command, 1, b"", b"")
        if failure != "log":
            setattr(result, stream, b"Authentication required")
        return result

    monkeypatch.setattr(subprocess, "run", run)
    _invoke(caller)
    assert launches == [100.0]
    assert probe.CLI_SIGNED_OUT_PATH.exists() is not changed
    if not changed:
        marker = json.loads(probe.CLI_SIGNED_OUT_PATH.read_text())
        assert marker["fingerprint"] == before == probe._credential_fingerprint()
    if caller == "probe":
        assert probe._cli_retry_after_monotonic == 1900.0
        clock[0] = 1899.0
        assert _invoke(caller) is None
        assert launches == [100.0]
        assert probe._cli_retry_after_monotonic == 1900.0
    clock[0] = 1900.0
    assert (_invoke(caller) is not None) is changed
    assert launches == ([100.0, 1900.0] if changed else [100.0])
    assert probe.CLI_SIGNED_OUT_PATH.exists() is not changed
    if changed:
        assert probe._cli_retry_after_monotonic == 0.0


@pytest.mark.parametrize("content", ["", "{broken", "[]", '{"fingerprint": null}', "\udcff"])
def test_legacy_marker_waits_for_a_credential(content: str) -> None:
    probe.CLI_SIGNED_OUT_PATH.write_bytes(content.encode("utf-8", errors="surrogateescape"))
    assert not probe.agy_cli_signed_in(15)
    probe._TOKEN_PATH.write_text(
        json.dumps({"token": {"access_token": "new-fake-token", "expiry": "2099-01-01T00:00:00Z"}})
    )
    probe._cli_retry_after_monotonic = 1800.0
    assert probe.agy_cli_signed_in(15)
    assert not probe.CLI_SIGNED_OUT_PATH.exists()
    assert probe._cli_retry_after_monotonic == 1800.0


def test_disappearing_credential_does_not_open_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(probe, "_read_token_file", lambda: {"token": {"access_token": "fake"}})
    probe.mark_cli_signed_out(probe._credential_fingerprint())
    monkeypatch.setattr(probe, "_read_token_file", lambda: None)
    assert not probe.agy_cli_signed_in(15)
    assert probe.CLI_SIGNED_OUT_PATH.exists()


def test_f2_transient_keychain_reads_reopen_unchanged_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    credential = {
        "token": {
            "access_token": "unchanged-fake-token",
            "refresh_token": "fake-refresh",
            "expiry": "2030-01-01T00:00:00+00:00",
        }
    }
    monkeypatch.setattr(probe, "sys", SimpleNamespace(platform="darwin"))
    answers: Iterator[object] = iter(())
    monkeypatch.setattr(probe, "_read_macos_credential", lambda: next(answers))
    clock = [0.0]
    monkeypatch.setattr(
        probe, "time", SimpleNamespace(monotonic=lambda: clock[0], time=lambda: clock[0])
    )
    launches: list[float] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        launches.append(clock[0])
        return subprocess.CompletedProcess(command, 1, b"Authentication required", b"")

    monkeypatch.setattr(subprocess, "run", run)
    for at in (0, 180, 360, 540, 1799, 1800, 1980, 3599, 3600):
        clock[0] = at
        # Gate reads A; the reads before and after a failed run are unavailable.
        answers = iter(
            [credential, None, None] if probe.CLI_SIGNED_OUT_PATH.exists() else [None, None]
        )
        assert _probe_via_cli(15) is None
        if at % 1800 == 0:
            assert json.loads(probe.CLI_SIGNED_OUT_PATH.read_text()) == {
                "fingerprint": None,
                "marked_at": at,
            }
        else:
            assert not probe.CLI_SIGNED_OUT_PATH.exists()
        assert probe._cli_retry_after_monotonic == (at // 1800 + 1) * 1800
    assert launches == [0, 1800, 3600]
    assert probe._cli_retry_after_monotonic == 5400


def _write_fallback_api_mocks(monkeypatch: pytest.MonkeyPatch, *, succeed: bool = True) -> None:
    monkeypatch.setattr(probe, "_resolve_access_token", lambda timeout: "valid-token")
    summary = {"groups": [{"displayName": "Claude and GPT models", "buckets": []}]}
    models = {
        "models": {
            "gemini-flash": {
                "quotaInfo": {
                    "remainingFraction": 0.8,
                    "resetTime": (datetime.now(UTC) + timedelta(hours=3)).isoformat(),
                }
            }
        }
    }
    monkeypatch.setattr(
        probe,
        "_post_json",
        (lambda url, *args: summary if url == probe._QUOTA_URL else models)
        if succeed
        else (lambda *args: None),
    )


def test_fallback_api_success_clears_stale_signed_out_marker_after_recheck_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [10_000.0]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    probe._TOKEN_PATH.write_text(
        json.dumps({"token": {"access_token": "tok", "expiry": "2099-01-01T00:00:00Z"}})
    )
    probe.mark_cli_signed_out(probe._credential_fingerprint())
    monkeypatch.setattr(probe, "_cli_retry_after_monotonic", 12_345.0)
    _write_fallback_api_mocks(monkeypatch, succeed=True)

    clock[0] = 10_000.0 + probe.CLI_SIGNED_OUT_RECHECK_SECONDS - 1
    assert probe.probe_quota() is not None
    assert probe.CLI_SIGNED_OUT_PATH.exists()
    assert probe._cli_retry_after_monotonic == 12_345.0

    clock[0] = 10_000.0 + probe.CLI_SIGNED_OUT_RECHECK_SECONDS
    assert probe.probe_quota() is not None
    assert not probe.CLI_SIGNED_OUT_PATH.exists()
    assert probe._cli_retry_after_monotonic == 12_345.0


@pytest.mark.parametrize("failure", ["no_token", "post_failed"])
def test_fallback_api_failure_keeps_stale_signed_out_marker(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    clock = [10_000.0]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    probe._TOKEN_PATH.write_text(
        json.dumps({"token": {"access_token": "tok", "expiry": "2099-01-01T00:00:00Z"}})
    )
    probe.mark_cli_signed_out(probe._credential_fingerprint())
    if failure == "no_token":
        monkeypatch.setattr(probe, "_resolve_access_token", lambda timeout: None)
    else:
        _write_fallback_api_mocks(monkeypatch, succeed=False)

    clock[0] = 10_000.0 + probe.CLI_SIGNED_OUT_RECHECK_SECONDS + 3600
    assert probe.probe_quota() is None
    assert probe.CLI_SIGNED_OUT_PATH.exists()


@pytest.mark.parametrize(
    "payload",
    [
        b'{"fingerprint": "abc"}',
        b'{"fingerprint": "abc", "marked_at": null}',
        b'{"fingerprint": "abc", "marked_at": "1000"}',
        b'{"fingerprint": "abc", "marked_at": true}',
        b"{not-json",
    ],
)
def test_fallback_api_success_keeps_marker_without_numeric_marked_at(
    monkeypatch: pytest.MonkeyPatch, payload: bytes
) -> None:
    monkeypatch.setattr(time, "time", lambda: 100_000.0)
    probe.CLI_SIGNED_OUT_PATH.write_bytes(payload)
    _write_fallback_api_mocks(monkeypatch, succeed=True)

    assert probe.probe_quota() is not None
    assert probe.CLI_SIGNED_OUT_PATH.exists()


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
@pytest.mark.parametrize(
    "message",
    [b"Authentication required", b"triggering interactive OAuth", "Authentication required"],
)
def test_keeper_timeout_with_signout_output_marks_signed_out(
    monkeypatch: pytest.MonkeyPatch, stream: str, message: bytes | str
) -> None:
    probe._TOKEN_PATH.write_text(
        json.dumps({"token": {"access_token": "tok", "expiry": "2099-01-01T00:00:00Z"}})
    )
    error = subprocess.TimeoutExpired(["/fake/agy", "-p", "ok"], keeper.PING_TIMEOUT_SECONDS)
    setattr(error, stream, message)

    def run(*args: object, **kwargs: object) -> None:
        raise error

    monkeypatch.setattr(subprocess, "run", run)
    keeper._ping_worker(1.0)
    state = keeper_outcome.read_state(keeper.AGY_WINDOW_KEEPER_STATE_PATH)
    assert state["last_error_kind"] == "timeout"
    assert probe.CLI_SIGNED_OUT_PATH.exists()
    assert probe.agy_cli_signed_in(keeper.PING_TIMEOUT_SECONDS) is False


def test_keeper_timeout_without_signout_output_keeps_gate_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe._TOKEN_PATH.write_text(
        json.dumps({"token": {"access_token": "tok", "expiry": "2099-01-01T00:00:00Z"}})
    )

    def run(command: list[str], **kwargs: object) -> None:
        raise subprocess.TimeoutExpired(command, keeper.PING_TIMEOUT_SECONDS)

    monkeypatch.setattr(subprocess, "run", run)
    keeper._ping_worker(1.0)
    state = keeper_outcome.read_state(keeper.AGY_WINDOW_KEEPER_STATE_PATH)
    assert state["last_error_kind"] == "timeout"
    assert not probe.CLI_SIGNED_OUT_PATH.exists()
    assert probe.agy_cli_signed_in(keeper.PING_TIMEOUT_SECONDS) is True


class _JsonSpy:
    """Record JSON texts parsed by agy_cli_signed_in while delegating other json attributes."""

    def __init__(self) -> None:
        self.seen: list[str] = []

    def loads(self, text: str, *args: Any, **kwargs: Any) -> Any:
        self.seen.append(text)
        return json.loads(text, *args, **kwargs)

    def __getattr__(self, name: str) -> object:
        return getattr(json, name)


def test_mark_cli_signed_out_atomic_concurrent_read_never_opens_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fingerprint = "f" * 64
    monkeypatch.setattr(probe, "_credential_fingerprint", lambda: fingerprint)
    spy = _JsonSpy()
    monkeypatch.setattr(probe, "json", spy)
    probe.mark_cli_signed_out(fingerprint)
    assert probe.agy_cli_signed_in(180) is False

    stop = threading.Event()
    errors: list[BaseException] = []

    def writer() -> None:
        try:
            while not stop.is_set():
                probe.mark_cli_signed_out(fingerprint)
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    thread = threading.Thread(target=writer)
    thread.start()
    reads = 0
    try:
        deadline = time.monotonic() + 0.3
        while time.monotonic() < deadline or reads < 50:
            spy.seen.clear()
            reads += 1
            assert probe.agy_cli_signed_in(180) is False
            assert spy.seen and all(text.endswith("}") for text in spy.seen)
    finally:
        stop.set()
        thread.join(timeout=5)
    assert not errors
    assert probe.CLI_SIGNED_OUT_PATH.exists()


def test_mark_cli_signed_out_cleans_temp_file_on_replace_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fingerprint = "f" * 64
    monkeypatch.setattr(probe, "_credential_fingerprint", lambda: fingerprint)

    def fail_replace(src: str, dst: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", fail_replace)
    probe.mark_cli_signed_out(fingerprint)
    assert not probe.CLI_SIGNED_OUT_PATH.exists()
    leftovers = list(probe.CLI_SIGNED_OUT_PATH.parent.glob("*.tmp"))
    assert leftovers == []

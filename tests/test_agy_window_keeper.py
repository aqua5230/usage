# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any, cast

import pytest

import agy_window_keeper
import menubar_agy
from agy_quota_probe import AgyQuotaWindow
from menubar_state import AgyStaleState, QuotaRowState


class _SyncThread:
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
        self.instances.append(self)

    def start(self) -> None:
        self.started = True
        if self.target is not None:
            self.target(*self.args)


@pytest.fixture
def isolated_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    state_path = tmp_path / "agy_window_keeper.json"
    monkeypatch.setattr(
        agy_window_keeper, "AGY_WINDOW_KEEPER_STATE_PATH", state_path
    )
    monkeypatch.setattr(agy_window_keeper, "_ping_in_flight", False)
    _SyncThread.instances.clear()
    monkeypatch.setattr(threading, "Thread", _SyncThread)
    return state_path


def _gate(**overrides: object) -> bool:
    values: dict[str, object] = {
        "now": 20_000.0,
        "enabled": True,
        "last_ping_at": None,
        "remaining_percent": 100.0,
        "resets_in_minutes": None,
        "stale": None,
        "fallback_projection": False,
        "mock": False,
    }
    values.update(overrides)
    return agy_window_keeper.should_ping(
        now=cast(float, values["now"]),
        enabled=cast(bool, values["enabled"]),
        last_ping_at=cast(float | None, values["last_ping_at"]),
        remaining_percent=cast(float | None, values["remaining_percent"]),
        resets_in_minutes=cast(int | None, values["resets_in_minutes"]),
        stale=values["stale"],
        fallback_projection=cast(bool, values["fallback_projection"]),
        mock=cast(bool, values["mock"]),
    )


def test_should_ping_disabled() -> None:
    assert _gate(enabled=False) is False


def test_should_ping_rejects_stale_probe() -> None:
    assert _gate(stale={"ageText": "old"}) is False


def test_should_ping_rejects_fallback_projection() -> None:
    assert _gate(fallback_projection=True) is False


def test_should_ping_rejects_mock_mode() -> None:
    assert _gate(mock=True) is False


def test_should_ping_rejects_missing_window() -> None:
    assert _gate(remaining_percent=None) is False


def test_should_ping_rejects_running_window() -> None:
    assert _gate(remaining_percent=99.9) is False


def test_should_ping_rejects_full_window_with_countdown() -> None:
    assert _gate(resets_in_minutes=300) is False


def test_should_ping_rejects_cooldown() -> None:
    assert _gate(last_ping_at=19_999.0) is False


def test_should_ping_allows_no_prior_ping() -> None:
    assert _gate() is True


def test_should_ping_allows_after_cooldown() -> None:
    assert _gate(
        last_ping_at=20_000.0 - agy_window_keeper.PING_COOLDOWN_SECONDS
    ) is True


def test_load_last_ping_missing_file(isolated_state: Path) -> None:
    assert agy_window_keeper._load_last_ping() is None


def test_save_and_load_last_ping_roundtrip(isolated_state: Path) -> None:
    agy_window_keeper._save_last_ping(12345.5)
    assert agy_window_keeper._load_last_ping() == 12345.5
    assert json.loads(isolated_state.read_text(encoding="utf-8")) == {
        "last_ping_at": 12345.5
    }


def test_load_last_ping_tolerates_corrupt_json(isolated_state: Path) -> None:
    isolated_state.write_text("not json", encoding="utf-8")
    assert agy_window_keeper._load_last_ping() is None


@pytest.mark.parametrize("value", [True, "soon", None, []])
def test_load_last_ping_rejects_invalid_values(
    isolated_state: Path, value: object
) -> None:
    isolated_state.write_text(
        json.dumps({"last_ping_at": value}), encoding="utf-8"
    )
    assert agy_window_keeper._load_last_ping() is None


def _refresh_result(
    *,
    remaining: float = 100.0,
    resets_in_minutes: int | None = None,
    stale: AgyStaleState | None = None,
) -> menubar_agy.AgyRefreshResult:
    row = QuotaRowState(
        title="Session",
        percent=100.0 - remaining,
        percent_text="",
        reset_text="",
        color=(1.0, 1.0, 1.0),
    )
    projection = menubar_agy.AgyQuotaProjection(
        group_name="GEMINI MODELS",
        session=row,
        weekly=row,
        stale=stale,
        five_hour=AgyQuotaWindow(remaining, None, resets_in_minutes),
    )
    return menubar_agy.AgyRefreshResult(projection=projection, hide_agy=False)


def _arm_ping(monkeypatch: pytest.MonkeyPatch, *, enabled: bool = True) -> list[str]:
    calls: list[str] = []
    monkeypatch.setattr(
        agy_window_keeper, "_agy_window_keeper_enabled", lambda: enabled
    )
    monkeypatch.setattr(agy_window_keeper, "_resolve_agy_bin", lambda: "/fake/agy")
    monkeypatch.setattr(agy_window_keeper, "_run_agy_ping", calls.append)
    return calls


def test_maybe_ping_fires_and_stamps_dispatch(
    monkeypatch: pytest.MonkeyPatch, isolated_state: Path
) -> None:
    calls = _arm_ping(monkeypatch)

    agy_window_keeper.maybe_ping(_refresh_result(), mock=False)

    assert calls == ["/fake/agy"]
    assert agy_window_keeper._load_last_ping() is not None
    assert len(_SyncThread.instances) == 1
    assert _SyncThread.instances[0].daemon is True


def test_maybe_ping_disabled_has_no_side_effects(
    monkeypatch: pytest.MonkeyPatch, isolated_state: Path
) -> None:
    calls = _arm_ping(monkeypatch, enabled=False)

    agy_window_keeper.maybe_ping(_refresh_result(), mock=False)

    assert calls == []
    assert isolated_state.exists() is False
    assert _SyncThread.instances == []


def test_maybe_ping_mock_has_no_side_effects(
    monkeypatch: pytest.MonkeyPatch, isolated_state: Path
) -> None:
    monkeypatch.setattr(
        agy_window_keeper,
        "_agy_window_keeper_enabled",
        lambda: pytest.fail("preferences must not be read in mock mode"),
    )

    agy_window_keeper.maybe_ping(_refresh_result(), mock=True)

    assert isolated_state.exists() is False
    assert _SyncThread.instances == []


def test_maybe_ping_fallback_has_no_side_effects(
    monkeypatch: pytest.MonkeyPatch, isolated_state: Path
) -> None:
    calls = _arm_ping(monkeypatch)
    result = menubar_agy.AgyRefreshResult(projection=None, hide_agy=True)

    agy_window_keeper.maybe_ping(result, mock=False)

    assert calls == []
    assert isolated_state.exists() is False


def test_maybe_ping_inflight_guard_prevents_double_spawn(
    monkeypatch: pytest.MonkeyPatch, isolated_state: Path
) -> None:
    calls = _arm_ping(monkeypatch)
    monkeypatch.setattr(agy_window_keeper, "_ping_in_flight", True)

    agy_window_keeper.maybe_ping(_refresh_result(), mock=False)

    assert calls == []
    assert isolated_state.exists() is False
    assert _SyncThread.instances == []


def test_worker_releases_guard_when_agy_is_missing(
    monkeypatch: pytest.MonkeyPatch, isolated_state: Path
) -> None:
    _arm_ping(monkeypatch)
    monkeypatch.setattr(agy_window_keeper, "_resolve_agy_bin", lambda: None)

    agy_window_keeper.maybe_ping(_refresh_result(), mock=False)

    assert agy_window_keeper._ping_in_flight is False


def test_resolve_agy_bin_uses_local_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _: None)
    monkeypatch.setattr(os.path, "expanduser", lambda _: "/fake/agy")
    monkeypatch.setattr(os.path, "isfile", lambda _: True)
    monkeypatch.setattr(os, "access", lambda *_: True)

    assert agy_window_keeper._resolve_agy_bin() == "/fake/agy"


def test_run_agy_ping_uses_verified_noninteractive_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        captured.update(kwargs)
        return subprocess.CompletedProcess(command, 0, "ok", "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    agy_window_keeper._run_agy_ping("/fake/agy")

    assert captured["command"] == [
        "/fake/agy",
        "-p",
        "ok",
        "--model",
        "Gemini 3.5 Flash (Low)",
    ]
    assert captured["stdin"] is subprocess.DEVNULL
    assert captured["capture_output"] is True
    assert captured["encoding"] == "utf-8"
    assert captured["timeout"] == agy_window_keeper.PING_TIMEOUT_SECONDS

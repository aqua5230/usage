from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from quota import keeper_outcome as outcome
from quota import window_keeper


@pytest.mark.parametrize(
    ("result", "kind", "detail"),
    [
        (subprocess.CompletedProcess([], 0, "ok", ""), "", ""),
        (FileNotFoundError(), "not_found", ""),
        (subprocess.TimeoutExpired("fake", 180), "timeout", ""),
        (RuntimeError("secret"), "error", "RuntimeError"),
        (subprocess.CompletedProcess([], 2, "out", " first\n last \n "), "exit", "exit 2: last"),
        (subprocess.CompletedProcess([], 1, " first\n out \n", " \n"), "exit", "exit 1: out"),
        (subprocess.CompletedProcess([], 1, " \n", "\n"), "exit", "exit 1:"),
        (subprocess.CompletedProcess([], 3, "", "x" * 200), "exit", ("exit 3: " + "x" * 200)[:120]),
    ],
)
def test_classify(result: Any, kind: str, detail: str) -> None:
    fields = outcome.classify(result)
    assert fields["last_result"] == ("failed" if kind else "ok")
    assert fields["last_error_kind"] == kind
    assert fields["last_error_detail"] == detail
    if not kind:
        assert fields["notified_error"] == ""


def failed(**changes: Any) -> dict[str, Any]:
    state = {
        "last_result": "failed",
        "last_error_kind": "exit",
        "last_error_detail": "exit 1: login",
        "last_result_at": 1000,
        "last_pinged_reset_at": 800,
        "retry_used": False,
        "final_failure": False,
        "warning": False,
    }
    return state | changes


@pytest.mark.parametrize(
    ("changes", "now", "boundary", "idle", "expected"),
    [
        ({}, 1600, 800, True, True),
        ({}, 1599, 800, True, False),
        ({"retry_used": True}, 1600, 800, True, False),
        ({"last_error_kind": "not_found"}, 1600, 800, True, False),
        ({}, 1600, 900, True, False),
        ({}, 1600, 800, False, False),
        ({"last_result": "ok"}, 1600, 800, True, False),
        ({"last_result_at": True}, 1600, 800, True, False),
        ({"last_result_at": "old"}, 1600, 800, True, False),
        ({"last_result_at": float("nan")}, 1600, 800, True, False),
    ],
)
def test_retry(
    changes: dict[str, Any], now: float, boundary: float, idle: bool, expected: bool
) -> None:
    assert outcome.should_retry(failed(**changes), now, boundary, idle) is expected


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (failed(), False),
        (failed(retry_used=True), False),
        (failed(last_error_kind="not_found"), False),
        (failed(final_failure=True), True),
        (failed(final_failure=1), False),
        (failed(last_result="ok", final_failure=True), False),
        ({}, False),
    ],
)
def test_final_failure(state: dict[str, Any], expected: bool) -> None:
    assert outcome.final_failure(state) is expected


def test_notification_dedup_across_windows_and_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "state.json"
    monkeypatch.setattr(
        outcome, "keeper_states", lambda: [("Claude", path, outcome.read_state(path))]
    )
    sent: list[tuple[str, str]] = []

    def send(title: str, body: str) -> None:
        sent.append((title, body))

    outcome.update_state(path, failed(final_failure=True, warning=True, retry_used=True))
    outcome.notify_failures("en", True, False, send)
    assert len(sent) == 1
    # A new five-hour cycle keeps the notification record.
    outcome.update_state(path, {"last_pinged_reset_at": 20000, "retry_used": False})
    outcome.update_state(
        path, failed(final_failure=True, warning=True, retry_used=True, last_pinged_reset_at=20000)
    )
    outcome.notify_failures("en", True, False, send)
    assert len(sent) == 1
    outcome.update_state(path, {"last_error_detail": "different"})
    outcome.notify_failures("en", True, False, send)
    assert len(sent) == 2
    outcome.record_result(path, outcome.classify(subprocess.CompletedProcess([], 0)))
    assert outcome.read_state(path)["notified_error"] == ""
    outcome.update_state(path, failed(final_failure=True, warning=True, retry_used=True))
    outcome.notify_failures("en", False, False, send)
    assert outcome.read_state(path)["notified_error"] == "exit:exit 1: login"
    outcome.notify_failures("en", True, False, send)
    assert len(sent) == 2
    outcome.update_state(path, {"last_error_detail": "mock", "notified_error": ""})
    outcome.notify_failures("en", True, True, send)
    assert outcome.read_state(path)["notified_error"] == ""


@pytest.mark.parametrize(
    "module_name", ["window_keeper", "codex_window_keeper", "agy_window_keeper"]
)
def test_worker_records_failures_and_success(
    module_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from importlib import import_module

    module = import_module(f"quota.{module_name}")
    tool = {"window_keeper": "claude", "codex_window_keeper": "codex", "agy_window_keeper": "agy"}[
        module_name
    ]
    path = getattr(
        module,
        {
            "claude": "WINDOW_KEEPER_STATE_PATH",
            "codex": "CODEX_WINDOW_KEEPER_STATE_PATH",
            "agy": "AGY_WINDOW_KEEPER_STATE_PATH",
        }[tool],
    )
    monkeypatch.setattr(module, f"_resolve_{tool}_bin", lambda: "/fake")

    def run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], 2, "", "login")

    monkeypatch.setattr(subprocess, "run", run)
    module._ping_worker(0)
    assert outcome.read_state(path)["last_result"] == "failed"
    assert outcome.read_state(path)["last_error_detail"] == "exit 2: login"
    monkeypatch.setattr(module, f"_resolve_{tool}_bin", lambda: None)
    module._ping_worker(0)
    assert outcome.read_state(path)["last_error_kind"] == "not_found"
    monkeypatch.setattr(module, f"_resolve_{tool}_bin", lambda: "/fake")
    monkeypatch.setattr(
        subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess([], 0)
    )
    module._ping_worker(0)
    assert outcome.read_state(path)["last_result"] == "ok"
    assert outcome.read_state(path)["notified_error"] == ""


def test_dispatch_preserves_failure_and_retries_once(monkeypatch: pytest.MonkeyPatch) -> None:
    path = window_keeper.WINDOW_KEEPER_STATE_PATH
    outcome.update_state(
        path, failed(final_failure=True, warning=True, retry_used=True, last_ping_at=1000)
    )
    monkeypatch.setattr(window_keeper, "_window_keeper_enabled", lambda: True)
    monkeypatch.setattr(time, "time", lambda: 30000)

    class PendingThread:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def start(self) -> None:
            pass

    monkeypatch.setattr(threading, "Thread", PendingThread)
    monkeypatch.setattr(window_keeper, "_ping_in_flight", False)
    window_keeper.maybe_ping(800, 0, "hook", False)
    state = outcome.read_state(path)
    assert state["last_result"] == "failed"
    assert state["retry_used"] is False
    assert state["last_ping_at"] == 30000
    outcome.update_state(path, {"last_result_at": 30000})
    monkeypatch.setattr(window_keeper, "_ping_in_flight", False)
    monkeypatch.setattr(time, "time", lambda: 30600)
    window_keeper.maybe_ping(800, 0, "hook", False)
    assert outcome.read_state(path)["retry_used"] is True
    assert outcome.read_state(path)["last_ping_at"] == 30600
    monkeypatch.setattr(window_keeper, "_ping_in_flight", False)
    monkeypatch.setattr(time, "time", lambda: 31200)
    window_keeper.maybe_ping(800, 0, "hook", False)
    assert outcome.read_state(path)["last_ping_at"] == 30600


def test_old_state_and_preserved_extra_fields(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text('{"last_ping_at": 123, "extra": "keep"}', encoding="utf-8")
    assert not outcome.should_notify(outcome.read_state(path))
    window_keeper._save_ping_state(100, 200, path)
    assert outcome.read_state(path) == {
        "last_ping_at": 200,
        "last_pinged_reset_at": 100,
        "extra": "keep",
    }


@pytest.mark.parametrize("raw", ["[]", "null", "broken"])
def test_invalid_state(tmp_path: Path, raw: str) -> None:
    path = tmp_path / "state.json"
    path.write_text(raw, encoding="utf-8")
    assert outcome.read_state(path) == {}


@pytest.mark.parametrize("tool", ["codex", "agy"])
def test_other_keepers_retry_once_without_active_window(
    tool: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from importlib import import_module
    from types import SimpleNamespace

    module = import_module(f"quota.{tool}_window_keeper")
    path = getattr(module, f"{tool.upper()}_WINDOW_KEEPER_STATE_PATH")
    outcome.update_state(path, failed(last_pinged_reset_at=None, last_ping_at=1000))
    monkeypatch.setattr(module, "_ping_in_flight", False)
    monkeypatch.setattr(time, "time", lambda: 1600)

    class PendingThread:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def start(self) -> None:
            pass

    monkeypatch.setattr(threading, "Thread", PendingThread)
    if tool == "codex":
        monkeypatch.setattr(module, "_window_keeper_enabled", lambda: True)
        limits = SimpleNamespace(
            five_hour_resets_at=None, five_hour_pct=0, five_hour_window_minutes=300
        )
        monkeypatch.setattr(module, "load_rate_limits", lambda: limits)

        def dispatch() -> None:
            module.maybe_ping(False)

        def activate() -> None:
            limits.five_hour_resets_at = 3000
    else:
        monkeypatch.setattr(module, "_agy_window_keeper_enabled", lambda: True)
        window = SimpleNamespace(remaining_percent=100)
        result = SimpleNamespace(projection=SimpleNamespace(five_hour=window, stale=None))

        def dispatch() -> None:
            module.maybe_ping(result, False)

        def activate() -> None:
            window.remaining_percent = 99

    activate()
    dispatch()
    assert outcome.read_state(path)["retry_used"] is False
    if tool == "codex":
        limits.five_hour_resets_at = None
    else:
        window.remaining_percent = 100
    dispatch()
    state = outcome.read_state(path)
    assert state["retry_used"] is True
    assert state["last_ping_at"] == 1600
    assert state["last_result"] == "failed"
    monkeypatch.setattr(module, "_ping_in_flight", False)
    monkeypatch.setattr(time, "time", lambda: 2200)
    dispatch()
    assert outcome.read_state(path)["last_ping_at"] == 1600


def test_locked_read_modify_write(tmp_path: Path) -> None:
    from concurrent.futures import ThreadPoolExecutor

    path = tmp_path / "state.json"
    outcome.update_state(path, {"counter": 0, "extra": "keep"})

    def increment(index: int) -> None:
        outcome.update_state(path, lambda state: {"counter": state["counter"] + 1})

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(increment, range(40)))
    assert outcome.read_state(path) == {"counter": 40, "extra": "keep"}


def test_retry_notification_waits_for_result() -> None:
    state = failed(final_failure=True, warning=True, retry_used=True, last_ping_at=1600)
    assert not outcome.should_notify(state)
    state["last_result_at"] = 1600
    assert outcome.should_notify(state)
    state.update(outcome.classify(subprocess.CompletedProcess([], 0)))
    assert not outcome.should_notify(state)


@pytest.mark.parametrize("value", [False, None, 1, "true", True])
def test_warning_requires_boolean_true(value: Any) -> None:
    assert outcome.warning({"warning": value}) is (value is True)
    assert not outcome.warning({})


@pytest.mark.parametrize("retry_used", [False, True])
@pytest.mark.parametrize("kind", ["exit", "not_found", ""])
@pytest.mark.parametrize("previous_warning", [False, True])
def test_record_result_flags(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    retry_used: bool,
    kind: str,
    previous_warning: bool,
) -> None:
    path = tmp_path / "state.json"
    outcome.update_state(
        path, {"retry_used": retry_used, "warning": previous_warning, "extra": "keep"}
    )
    monkeypatch.setattr(time, "time", lambda: 1234)
    fields = {
        "last_result": "failed" if kind else "ok",
        "last_error_kind": kind,
        "last_error_detail": "detail" if kind else "",
    }
    original = fields.copy()
    outcome.record_result(path, fields)
    state = outcome.read_state(path)
    final = bool(kind) and (retry_used or kind == "not_found")
    assert state == {
        "retry_used": retry_used,
        "warning": final or (bool(kind) and previous_warning),
        "extra": "keep",
        **fields,
        "last_result_at": 1234,
        "final_failure": final,
    }
    assert fields == original


def test_legacy_failure_has_no_warning_or_notification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "old.json"
    path.write_text(
        '{"last_result": "failed", "retry_used": true, "last_error_kind": "not_found"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        outcome, "keeper_states", lambda: [("Claude", path, outcome.read_state(path))]
    )
    state = outcome.read_state(path)
    assert not outcome.final_failure(state)
    assert not outcome.warning(state)
    assert not outcome.should_notify(state)
    assert outcome.failure_tooltip("en") == ""
    outcome.record_result(path, outcome.classify(FileNotFoundError()))
    assert outcome.final_failure(outcome.read_state(path))
    assert outcome.warning(outcome.read_state(path))
    assert outcome.should_notify(outcome.read_state(path))


@pytest.mark.parametrize("tool", ["claude", "codex", "agy"])
@pytest.mark.parametrize("not_found", [False, True])
def test_warning_across_windows(
    monkeypatch: pytest.MonkeyPatch, tool: str, not_found: bool
) -> None:
    from importlib import import_module
    from types import SimpleNamespace

    module = import_module(f"quota.{'' if tool == 'claude' else tool + '_'}window_keeper")
    constant = f"{'' if tool == 'claude' else tool.upper() + '_'}WINDOW_KEEPER_STATE_PATH"
    path = getattr(module, constant)
    monkeypatch.setattr(module, "_ping_in_flight", False)
    monkeypatch.setattr(module, f"_resolve_{tool}_bin", lambda: None if not_found else "/fake")
    monkeypatch.setattr(
        module,
        "_agy_window_keeper_enabled" if tool == "agy" else "_window_keeper_enabled",
        lambda: True,
    )
    limits = SimpleNamespace(
        five_hour_resets_at=None, five_hour_pct=0, five_hour_window_minutes=300
    )
    if tool == "codex":
        monkeypatch.setattr(module, "load_rate_limits", lambda: limits)
    projection = SimpleNamespace(five_hour=SimpleNamespace(remaining_percent=100), stale=None)
    clock = [1000.0]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    result = [subprocess.CompletedProcess([], 2, "", "login")]
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: result[0])

    class PendingThread:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def start(self) -> None:
            pass

    monkeypatch.setattr(threading, "Thread", PendingThread)
    monkeypatch.setattr(outcome, "keeper_states", lambda: [(tool, path, outcome.read_state(path))])
    sent: list[tuple[str, str]] = []

    def notify() -> None:
        outcome.notify_failures("en", True, False, lambda title, body: sent.append((title, body)))

    def dispatch(now: float, retry: bool) -> None:
        clock[0] = now
        if tool == "claude":
            module.maybe_ping(800, 0, "hook", False)
        elif tool == "codex":
            module.maybe_ping(False)
        else:
            module.maybe_ping(SimpleNamespace(projection=projection), False)
        state = outcome.read_state(path)
        assert state["last_ping_at"] == now
        assert state["retry_used"] is retry

    def finish() -> None:
        clock[0] += 1
        module._ping_worker(clock[0] - 1)
        assert outcome.read_state(path)["last_result_at"] == clock[0]

    dispatch(1000, False)
    finish()
    if not_found:
        assert outcome.final_failure(outcome.read_state(path))
        assert outcome.warning(outcome.read_state(path))
        assert outcome.failure_tooltip("en")
        notify()
        notify()
        assert len(sent) == 1
        assert not outcome.should_retry(outcome.read_state(path), 1601, None, True)
        return

    assert not outcome.final_failure(outcome.read_state(path))
    assert not outcome.warning(outcome.read_state(path))
    assert outcome.failure_tooltip("en") == ""
    notify()
    assert sent == []
    dispatch(1601, True)
    notify()
    assert sent == []
    finish()
    assert outcome.final_failure(outcome.read_state(path))
    assert outcome.warning(outcome.read_state(path))
    assert outcome.failure_tooltip("en")
    notify()
    notify()
    assert len(sent) == 1

    previous = outcome.read_state(path)
    dispatch(30000, False)
    state = outcome.read_state(path)
    for key in ("final_failure", "warning", "last_result", "last_error_kind", "last_error_detail"):
        assert state[key] == previous[key]
    assert outcome.failure_tooltip("en")
    assert not outcome.should_notify(state)
    finish()
    state = outcome.read_state(path)
    assert not outcome.final_failure(state)
    assert outcome.warning(state)
    assert outcome.failure_tooltip("en")
    # A different pending error must also wait until the final attempt to notify.
    outcome.update_state(path, {"last_error_detail": "different"})
    notify()
    assert len(sent) == 1
    dispatch(30601, True)
    notify()
    assert len(sent) == 1
    result[0] = subprocess.CompletedProcess([], 0, "ok", "")
    finish()
    state = outcome.read_state(path)
    assert state["last_result"] == "ok"
    assert not outcome.final_failure(state)
    assert not outcome.warning(state)
    assert state["notified_error"] == ""
    assert outcome.failure_tooltip("en") == ""
    notify()
    assert len(sent) == 1

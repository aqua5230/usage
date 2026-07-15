# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import importlib
import sys
from typing import Any

import main
from tui import AppViewState
from usage_client import PollOutcome, PollState, UsageSnapshot


def _parse_args(monkeypatch: Any, *args: str) -> Any:
    monkeypatch.setattr("sys.argv", ["usage", *args])
    return main.parse_args()


def _snapshot(percent: int = 42) -> UsageSnapshot:
    return UsageSnapshot(
        current_percent=percent,
        current_reset_at=1_000.0,
        weekly_percent=percent + 1,
        weekly_reset_at=2_000.0,
        current_status="ok",
        polled_at=123.0,
    )


def test_parse_args_defaults(monkeypatch: Any) -> None:
    args = _parse_args(monkeypatch)

    assert args.mock is False
    assert args.interval == 60
    assert args.tui is False
    assert args.setup is False
    assert args.unsetup is False
    assert args.force_group is None


def test_parse_args_clamps_interval_to_minimum(monkeypatch: Any) -> None:
    args = _parse_args(monkeypatch, "--interval", "10")

    assert args.interval == 30


def test_parse_args_keeps_larger_interval(monkeypatch: Any) -> None:
    args = _parse_args(monkeypatch, "--interval", "120")

    assert args.interval == 120


def test_parse_args_mock_tui_and_force_group(monkeypatch: Any) -> None:
    args = _parse_args(monkeypatch, "--mock", "--tui", "--force-group", "2")

    assert args.mock is True
    assert args.tui is True
    assert args.force_group == 2


def test_parse_args_setup(monkeypatch: Any) -> None:
    args = _parse_args(monkeypatch, "--setup")

    assert args.setup is True


def test_apply_outcome_success_updates_snapshot_and_clears_fatal_message() -> None:
    state = AppViewState(fatal_message="boom")
    snapshot = _snapshot()
    outcome = PollOutcome(state=PollState.SUCCESS, snapshot=snapshot)

    main._apply_outcome(state, outcome)

    assert state.poll_state == PollState.SUCCESS
    assert state.snapshot == snapshot
    assert state.fatal_message is None


def test_apply_outcome_updates_message() -> None:
    state = AppViewState(message="old")
    outcome = PollOutcome(state=PollState.LOADING, message="new")

    main._apply_outcome(state, outcome)

    assert state.message == "new"


def test_apply_outcome_without_snapshot_keeps_existing_snapshot() -> None:
    existing = _snapshot(10)
    state = AppViewState(snapshot=existing)
    outcome = PollOutcome(state=PollState.LOADING)

    main._apply_outcome(state, outcome)

    assert state.snapshot == existing


def test_apply_outcome_non_success_keeps_fatal_message() -> None:
    state = AppViewState(fatal_message="still fatal")
    outcome = PollOutcome(state=PollState.TOKEN_ERROR)

    main._apply_outcome(state, outcome)

    assert state.poll_state == PollState.TOKEN_ERROR
    assert state.fatal_message == "still fatal"


def _patch_main_for_win32(monkeypatch: Any, calls: list[dict[str, Any]]) -> None:
    async def fake_run_tui(**kwargs: Any) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(
        main,
        "parse_args",
        lambda: type("Args", (), {
            "doctor": False,
            "setup": False,
            "unsetup": False,
            "tui": False,
            "mock": False,
            "interval": 60,
            "force_group": None,
        })(),
    )
    monkeypatch.setattr(main, "_self_heal", lambda: None)
    monkeypatch.setattr(main, "run_tui", fake_run_tui)
    monkeypatch.setattr(main, "_t", lambda key: "fallback")
    monkeypatch.setattr(sys, "platform", "win32")


def _raise_module_not_found(missing: str) -> Any:
    def fake_import(name: str) -> Any:
        assert name == "wintray"
        raise ModuleNotFoundError(f"No module named '{missing}'", name=missing)

    return fake_import


def test_main_win32_falls_back_to_tui_when_wintray_is_missing(
    monkeypatch: Any, capsys: Any
) -> None:
    calls: list[dict[str, Any]] = []
    _patch_main_for_win32(monkeypatch, calls)
    monkeypatch.setattr(importlib, "import_module", _raise_module_not_found("wintray"))

    main.main()

    assert calls == [{"mock": False, "interval": 60, "force_group": None}]
    assert capsys.readouterr().out == "fallback [wintray]\n"


def test_main_win32_falls_back_to_tui_when_wintray_dependency_is_missing(
    monkeypatch: Any, capsys: Any
) -> None:
    # Regression: wintray -> panels -> panels.web_panel -> objc used to escape
    # the fallback (exc.name != "wintray") and crash the windowed build.
    calls: list[dict[str, Any]] = []
    _patch_main_for_win32(monkeypatch, calls)
    monkeypatch.setattr(importlib, "import_module", _raise_module_not_found("objc"))

    main.main()

    assert calls == [{"mock": False, "interval": 60, "force_group": None}]
    assert capsys.readouterr().out == "fallback [objc]\n"

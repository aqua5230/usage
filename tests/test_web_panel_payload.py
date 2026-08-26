# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

import prefs
from loaders.agy_quota_probe import AgyQuotaGroup, AgyQuotaResult, AgyQuotaWindow
from menubar import agy as menubar_agy
from menubar import app as menubar
from panels.web_panel import UsageScriptBridge, _state_payload


def test_state_payload_includes_agy_card_data() -> None:
    quota = AgyQuotaResult(
        groups=[
            AgyQuotaGroup(
                name="GEMINI MODELS",
                models=["gemini"],
                five_hour=AgyQuotaWindow(
                    remaining_percent=75,
                    resets_in="1h",
                    resets_in_minutes=60,
                ),
                weekly=AgyQuotaWindow(
                    remaining_percent=50,
                    resets_in="1d",
                    resets_in_minutes=1440,
                ),
            )
        ],
        fetched_at="2026-01-01T00:00:00+00:00",
    )
    projection = menubar_agy.project_quota(quota, "en", now=1_767_225_600.0)
    assert projection is not None
    state = menubar._empty_state("en")
    state.agy_session = projection.session
    state.agy_weekly = projection.weekly
    state.agy_group_name = projection.group_name
    state.agy_stale = projection.stale
    state.hide_agy = False

    payload = _state_payload(state)

    assert payload["hideAgy"] is False
    assert payload["hideGrok"] is True
    assert payload["cardOrder"] == ["claude", "codex", "agy", "grok"]
    assert payload["projectsYesterday"] == []
    footer = cast(dict[str, object], payload["footer"])
    assert footer["yesterday"] == "Yesterday: $0.00 (0 tokens)"
    assert payload["agy"] == {
        "session": {
            "percent": 25.0,
            "percentText": "25% used",
            "resetText": "Resets in 1h 0m",
            "warning": False,
            "available": True,
            "title": "Session",
        },
        "weekly": {
            "percent": 50.0,
            "percentText": "50% used",
            "resetText": "Resets in 1d 0h",
            "warning": False,
            "available": True,
            "title": "Weekly",
        },
        "groupName": "GEMINI MODELS",
        "stale": None,
    }
    grok_payload = cast(dict[str, object], payload["grok"])
    grok_weekly = cast(dict[str, object], grok_payload["weekly"])
    assert grok_weekly["available"] is False


def test_bridge_saves_valid_card_order_and_ignores_invalid_input(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    preferences_file = tmp_path / "usage-preferences.json"
    monkeypatch.setattr(prefs, "PREFERENCES_FILE", preferences_file)
    bridge = UsageScriptBridge.alloc().init()

    bridge.userContentController_didReceiveScriptMessage_(
        None,
        SimpleNamespace(
            body=lambda: '{"action":"set_card_order","order":["agy","claude","codex"]}'
        ),
    )

    assert prefs._load_preferences()["quota_card_order"] == ["agy", "claude", "codex", "grok"]

    bridge.userContentController_didReceiveScriptMessage_(
        None,
        SimpleNamespace(
            body=lambda: '{"action":"set_card_order","order":["agy","claude","claude"]}'
        ),
    )

    assert prefs._load_preferences()["quota_card_order"] == ["agy", "claude", "codex", "grok"]


def test_bridge_saves_valid_panel_flavor_and_ignores_invalid_input(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    preferences_file = tmp_path / "usage-preferences.json"
    monkeypatch.setattr(prefs, "PREFERENCES_FILE", preferences_file)
    bridge = UsageScriptBridge.alloc().init()

    bridge.userContentController_didReceiveScriptMessage_(
        None,
        SimpleNamespace(
            body=lambda: '{"action":"set_panel_flavor","flavor":"macchiato"}'
        ),
    )
    assert prefs._load_preferences()["panel_flavor"] == "macchiato"

    bridge.userContentController_didReceiveScriptMessage_(
        None,
        SimpleNamespace(body=lambda: '{"action":"set_panel_flavor","flavor":"latte "}'),
    )
    assert prefs._load_preferences()["panel_flavor"] == "macchiato"


def test_bridge_forwards_measured_content_height() -> None:
    calls: list[tuple[object, object]] = []
    web_view = object()
    delegate = SimpleNamespace(
        panelContentHeight_forView_=lambda height, view: calls.append((height, view))
    )
    bridge = UsageScriptBridge.alloc().init()
    bridge.delegate = delegate
    bridge.web_view = web_view

    bridge.userContentController_didReceiveScriptMessage_(
        None,
        SimpleNamespace(body=lambda: '{"action":"content_height","height":612.5}'),
    )

    assert calls == [(612.5, web_view)]


def test_bridge_forwards_window_drag() -> None:
    calls: list[object] = []
    web_view = object()
    delegate = SimpleNamespace(panelBeginWindowDrag_=lambda view: calls.append(view))
    bridge = UsageScriptBridge.alloc().init()
    bridge.delegate = delegate
    bridge.web_view = web_view

    bridge.userContentController_didReceiveScriptMessage_(
        None,
        SimpleNamespace(body=lambda: '{"action":"begin_window_drag"}'),
    )

    assert calls == [web_view]

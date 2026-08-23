# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import json
from pathlib import Path

import pytest
from rich.panel import Panel

from tui import app as tui
from usage_client import PollState, UsageSnapshot


def _minimal_bundle() -> dict[str, dict[str, str]]:
    return {
        "en": {
            "current_label": "5h",
            "group_active": "Active",
            "group_heavy": "Heavy",
            "group_idle": "Idle",
            "group_normal": "Normal",
            "loading_phrases": "Loading",
            "resets_in_days": "{days}d {hours}h",
            "resets_in_hours": "{hours}h {minutes}m",
            "resets_in_minutes": "{minutes}m {seconds}s",
            "resets_in_placeholder": "--",
            "status_api_offline": "Offline",
            "status_rate_limited": "Rate limited",
            "status_token_unavailable": "Token unavailable",
            "usage_title": "usage",
            "weekly_label": "7d",
        }
    }


def test_load_i18n_bundle_reads_monkeypatched_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bundle_path = tmp_path / "i18n.json"
    bundle_path.write_text(json.dumps(_minimal_bundle()), encoding="utf-8")
    monkeypatch.setattr(tui, "I18N_PATH", bundle_path)
    tui._load_i18n_bundle.cache_clear()

    try:
        bundle = tui._load_i18n_bundle()
    finally:
        tui._load_i18n_bundle.cache_clear()

    assert isinstance(bundle, dict)
    assert bundle["en"]["usage_title"] == "usage"


def test_app_view_state_default_language_reads_usage_lang_ja(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("USAGE_LANG", "ja")

    state = tui.AppViewState()

    assert state.language == "ja"


def test_app_view_state_default_language_reads_usage_lang_zh_cn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("USAGE_LANG", "zh-CN")

    state = tui.AppViewState()

    assert state.language == "zh-CN"


def test_render_screen_smoke_with_usage_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tui, "_load_i18n_bundle", _minimal_bundle)
    snapshot = UsageSnapshot(
        current_percent=42,
        current_reset_at=2_000_000_000.0,
        weekly_percent=63,
        weekly_reset_at=2_000_086_400.0,
        current_status="ok",
        polled_at=1_234.0,
    )
    state = tui.AppViewState(
        language="en",
        poll_state=PollState.SUCCESS,
        snapshot=snapshot,
        rate_group=1,
    )

    rendered = tui.render_screen(state, frame_index=0)

    assert isinstance(rendered, Panel)


def test_render_screen_smoke_without_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tui, "_load_i18n_bundle", _minimal_bundle)
    state = tui.AppViewState(language="en", poll_state=PollState.LOADING, snapshot=None)

    rendered = tui.render_screen(state, frame_index=5)

    assert isinstance(rendered, Panel)

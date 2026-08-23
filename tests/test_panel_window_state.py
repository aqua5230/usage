# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>

from __future__ import annotations

import sys
from types import MappingProxyType, SimpleNamespace
from typing import cast

import pytest

from panels.panel_window_state import (
    PANEL_CONTENT_HEIGHTS_DEFAULTS_KEY,
    PANEL_WINDOW_ORIGIN_DEFAULTS_KEY,
    PANEL_WINDOW_TOP_LEFT_DEFAULTS_KEY,
    clamp_origin_to_visible_frames,
    load_panel_content_height,
    load_panel_window_origin,
    load_panel_window_top_left,
    resolve_panel_size,
    save_panel_content_height,
    save_panel_window_top_left,
)


class EmptyDefaults:
    def arrayForKey_(self, key: str) -> None:
        assert key == PANEL_WINDOW_ORIGIN_DEFAULTS_KEY
        return None


class Defaults:
    def __init__(self, value: object) -> None:
        self.value = value
        self.saved: tuple[object, str] | None = None

    def arrayForKey_(self, key: str) -> object:
        assert key == PANEL_WINDOW_TOP_LEFT_DEFAULTS_KEY
        return self.value

    def setObject_forKey_(self, value: object, key: str) -> None:
        self.saved = (value, key)


class ContentHeightDefaults:
    def __init__(self, value: object) -> None:
        self.value = value

    def objectForKey_(self, key: str) -> object:
        assert key == PANEL_CONTENT_HEIGHTS_DEFAULTS_KEY
        return self.value

    def setObject_forKey_(self, value: object, key: str) -> None:
        assert key == PANEL_CONTENT_HEIGHTS_DEFAULTS_KEY
        self.value = value


def test_clamp_origin_pulls_fully_offscreen_window_back() -> None:
    assert clamp_origin_to_visible_frames(
        (1400.0, -700.0),
        (360.0, 500.0),
        [(0.0, 0.0, 1200.0, 800.0)],
    ) == (840.0, 0.0)


def test_clamp_origin_leaves_normal_position_unchanged() -> None:
    assert clamp_origin_to_visible_frames(
        (240.0, 160.0),
        (360.0, 500.0),
        [(0.0, 0.0, 1200.0, 800.0)],
    ) == (240.0, 160.0)


def test_clamp_origin_uses_nearest_visible_frame() -> None:
    assert clamp_origin_to_visible_frames(
        (1700.0, 100.0),
        (360.0, 500.0),
        [
            (0.0, 0.0, 1200.0, 800.0),
            (1920.0, 0.0, 1200.0, 800.0),
        ],
    ) == (1920.0, 100.0)


def test_load_origin_returns_none_when_never_saved() -> None:
    assert load_panel_window_origin(EmptyDefaults()) is None


def test_save_top_left_stores_float_coordinates() -> None:
    defaults = Defaults(None)

    save_panel_window_top_left((12, 34.5), defaults)

    assert defaults.saved == ([12.0, 34.5], PANEL_WINDOW_TOP_LEFT_DEFAULTS_KEY)


def test_load_top_left_returns_float_coordinates() -> None:
    assert load_panel_window_top_left(Defaults([12, 34.5])) == (12.0, 34.5)


def test_load_top_left_rejects_wrong_length() -> None:
    assert load_panel_window_top_left(Defaults([12])) is None


def test_load_top_left_rejects_wrong_types_including_bool() -> None:
    assert load_panel_window_top_left(Defaults(["12", 34])) is None
    assert load_panel_window_top_left(Defaults([True, 34])) is None
    assert load_panel_window_top_left(Defaults([12, False])) is None


def test_load_top_left_rejects_non_finite_coordinates() -> None:
    assert load_panel_window_top_left(Defaults([float("nan"), 34])) is None
    assert load_panel_window_top_left(Defaults([12, float("inf")])) is None


def test_save_content_height_round_trips() -> None:
    defaults = ContentHeightDefaults({})

    save_panel_content_height("classic", 456, defaults)

    assert load_panel_content_height("classic", defaults) == 456.0


def test_content_heights_are_separate_per_panel() -> None:
    defaults = ContentHeightDefaults({})

    save_panel_content_height("classic", 456.0, defaults)
    save_panel_content_height("matrix", 789.0, defaults)

    assert load_panel_content_height("classic", defaults) == 456.0
    assert load_panel_content_height("matrix", defaults) == 789.0


@pytest.mark.parametrize(
    "value",
    ["broken", {"classic": "456"}, {"classic": float("nan")},
     {"classic": float("inf")}, {"classic": -1}, {"classic": True}],
)
def test_content_height_rejects_invalid_values_and_save_recovers(value: object) -> None:
    defaults = ContentHeightDefaults(value)

    assert load_panel_content_height("classic", defaults) is None
    save_panel_content_height("classic", 456.0, defaults)

    assert load_panel_content_height("classic", defaults) == 456.0


def test_resolve_panel_size_uses_saved_height_or_estimate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from menubar import state as menubar_state

    panel = SimpleNamespace(id="classic")
    state = object()
    defaults = ContentHeightDefaults({"classic": 456.0})
    monkeypatch.setattr(menubar_state, "popover_dimensions", lambda state, panel: (320.0, 500.0))

    assert resolve_panel_size(state, panel, defaults) == (320.0, 456.0)
    assert resolve_panel_size(state, panel, ContentHeightDefaults({})) == (320.0, 500.0)


def test_resolve_panel_size_reads_objc_mapping_measurement() -> None:
    from menubar import state as menubar_state

    state = menubar_state._empty_state()
    state.hide_agy = False
    panel = SimpleNamespace(
        id="classic",
        preferred_size=lambda: (364.0, 1004.0),
        claude_card_height=192.0,
        codex_card_height=192.0,
        codex_row_height=0.0,
        agy_card_height=192.0,
        status_wrap_extra_height=30.0,
        service_alert_height=32.0,
    )
    defaults = ContentHeightDefaults(MappingProxyType({"classic": 974.0}))

    assert menubar_state.popover_dimensions(state, panel) == (364.0, 1004.0)
    assert resolve_panel_size(state, panel, defaults) == (364.0, 974.0)


def test_resolve_panel_size_estimates_without_content_height_reports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from menubar import state as menubar_state

    state = object()
    panel = SimpleNamespace(id="classic", _content_height_reports_available=False)
    defaults = ContentHeightDefaults(MappingProxyType({"classic": 974.0}))
    monkeypatch.setattr(menubar_state, "popover_dimensions", lambda state, panel: (364.0, 1004.0))

    assert resolve_panel_size(state, panel, defaults) == (364.0, 1004.0)


@pytest.mark.skipif(sys.platform != "darwin", reason="menubar imports PyObjC")
def test_top_left_anchor_is_stable_when_content_height_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from menubar import app as menubar

    top_left = (240.0, 800.0)
    first_height = 400.0
    second_height = 560.0
    first_origin = (top_left[0], top_left[1] - first_height)
    second_origin = (top_left[0], top_left[1] - second_height)
    saved: list[tuple[float, float]] = []
    monkeypatch.setattr(menubar, "save_panel_window_top_left", saved.append)
    delegate = cast(
        menubar.AppDelegate,
        SimpleNamespace(
            popover=SimpleNamespace(
                frame=lambda: SimpleNamespace(
                    origin=SimpleNamespace(x=top_left[0], y=first_origin[1]),
                    size=SimpleNamespace(height=first_height),
                )
            ),
        ),
    )

    menubar.AppDelegate._save_panel_window_top_left(delegate)
    delegate.popover.frame = lambda: SimpleNamespace(
        origin=SimpleNamespace(x=top_left[0], y=second_origin[1]),
        size=SimpleNamespace(height=second_height),
    )
    menubar.AppDelegate._save_panel_window_top_left(delegate)

    assert saved == [top_left, top_left]
    assert first_origin != second_origin
    assert first_origin[1] + first_height == top_left[1]
    assert second_origin[1] + second_height == top_left[1]

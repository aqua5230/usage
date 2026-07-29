# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>

from __future__ import annotations

from panel_window_state import (
    PANEL_WINDOW_ORIGIN_DEFAULTS_KEY,
    clamp_origin_to_visible_frames,
    load_panel_window_origin,
)


class EmptyDefaults:
    def arrayForKey_(self, key: str) -> None:
        assert key == PANEL_WINDOW_ORIGIN_DEFAULTS_KEY
        return None


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

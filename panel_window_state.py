# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import math
import sys
from collections.abc import Mapping, Sequence
from typing import Any

if sys.platform == "darwin":
    from Foundation import NSUserDefaults
else:
    NSUserDefaults = None

PANEL_WINDOW_ORIGIN_DEFAULTS_KEY = "usage.panelWindowOrigin"
PANEL_WINDOW_TOP_LEFT_DEFAULTS_KEY = "usage.panelWindowTopLeft"
PANEL_CONTENT_HEIGHTS_DEFAULTS_KEY = "usage.panelContentHeights"

Origin = tuple[float, float]
Size = tuple[float, float]
VisibleFrame = tuple[float, float, float, float]


def clamp_origin_to_visible_frames(
    origin: Origin,
    size: Size,
    visible_frames: Sequence[VisibleFrame],
) -> Origin:
    if not visible_frames:
        return origin

    width = max(0.0, float(size[0]))
    height = max(0.0, float(size[1]))
    candidates: list[Origin] = []
    for frame_x, frame_y, frame_width, frame_height in visible_frames:
        maximum_x = float(frame_x) + max(0.0, float(frame_width) - width)
        maximum_y = float(frame_y) + max(0.0, float(frame_height) - height)
        candidate_x = min(max(float(origin[0]), float(frame_x)), maximum_x)
        candidate_y = min(max(float(origin[1]), float(frame_y)), maximum_y)
        candidates.append((candidate_x, candidate_y))

    return min(
        candidates,
        key=lambda candidate: (candidate[0] - origin[0]) ** 2
        + (candidate[1] - origin[1]) ** 2,
    )


def load_panel_window_origin(defaults: Any | None = None) -> Origin | None:
    store = defaults
    if store is None:
        assert NSUserDefaults is not None
        store = NSUserDefaults.standardUserDefaults()
    value = store.arrayForKey_(PANEL_WINDOW_ORIGIN_DEFAULTS_KEY)
    if not isinstance(value, Sequence) or isinstance(value, str | bytes) or len(value) != 2:
        return None
    x, y = value
    if (
        isinstance(x, bool)
        or isinstance(y, bool)
        or not isinstance(x, int | float)
        or not isinstance(y, int | float)
        or not math.isfinite(float(x))
        or not math.isfinite(float(y))
    ):
        return None
    return (float(x), float(y))


def save_panel_window_top_left(
    top_left: Origin,
    defaults: Any | None = None,
) -> None:
    store = defaults
    if store is None:
        assert NSUserDefaults is not None
        store = NSUserDefaults.standardUserDefaults()
    store.setObject_forKey_(
        [float(top_left[0]), float(top_left[1])],
        PANEL_WINDOW_TOP_LEFT_DEFAULTS_KEY,
    )


def load_panel_window_top_left(defaults: Any | None = None) -> Origin | None:
    store = defaults
    if store is None:
        assert NSUserDefaults is not None
        store = NSUserDefaults.standardUserDefaults()
    value = store.arrayForKey_(PANEL_WINDOW_TOP_LEFT_DEFAULTS_KEY)
    if not isinstance(value, Sequence) or isinstance(value, str | bytes) or len(value) != 2:
        return None
    x, y = value
    if (
        isinstance(x, bool)
        or isinstance(y, bool)
        or not isinstance(x, int | float)
        or not isinstance(y, int | float)
        or not math.isfinite(float(x))
        or not math.isfinite(float(y))
    ):
        return None
    return (float(x), float(y))


def save_panel_content_height(
    panel_id: str,
    height: float,
    defaults: Any | None = None,
) -> None:
    store = defaults
    if store is None:
        assert NSUserDefaults is not None
        store = NSUserDefaults.standardUserDefaults()
    value = store.objectForKey_(PANEL_CONTENT_HEIGHTS_DEFAULTS_KEY)
    heights = dict(value) if isinstance(value, Mapping) else {}
    heights[panel_id] = float(height)
    store.setObject_forKey_(heights, PANEL_CONTENT_HEIGHTS_DEFAULTS_KEY)


def load_panel_content_height(
    panel_id: str,
    defaults: Any | None = None,
) -> float | None:
    store = defaults
    if store is None:
        assert NSUserDefaults is not None
        store = NSUserDefaults.standardUserDefaults()
    heights = store.objectForKey_(PANEL_CONTENT_HEIGHTS_DEFAULTS_KEY)
    if not isinstance(heights, Mapping):
        return None
    value = heights.get(panel_id)
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(float(value))
        or value <= 0
    ):
        return None
    return float(value)


def resolve_panel_size(
    state: Any,
    panel: Any | None,
    defaults: Any | None = None,
) -> Size:
    from menubar import state as menubar_state

    width, height = menubar_state.popover_dimensions(state, panel)
    measurement_available = getattr(panel, "_content_height_reports_available", True)
    if measurement_available and panel is not None and (
        saved_height := load_panel_content_height(panel.id, defaults)
    ):
        height = saved_height
    return (width, height)

# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>

from __future__ import annotations

import math
from typing import cast

MIN_PANEL_SCALE = 0.6


def fit_scale(natural_height: object, maximum: object) -> float:
    """Ratio that fits natural_height into maximum, never below MIN_PANEL_SCALE."""
    if (
        isinstance(natural_height, bool)
        or isinstance(maximum, bool)
        or not isinstance(natural_height, int | float)
        or not isinstance(maximum, int | float)
    ):
        return 1.0
    natural = float(natural_height)
    available = float(maximum)
    if not math.isfinite(natural) or natural <= 0 or not math.isfinite(available) or available <= 0:
        return 1.0
    if natural <= available:
        return 1.0
    return max(MIN_PANEL_SCALE, available / natural)


def fit_panel_size(
    natural_width: object, natural_height: object, maximum: object
) -> tuple[float, float, float]:
    """Return (width, height, scale) fitted into maximum, height never exceeding it."""
    scale = fit_scale(natural_height, maximum)
    if (
        isinstance(natural_width, bool)
        or not isinstance(natural_width, int | float)
        or not math.isfinite(natural_width)
        or natural_width <= 0
    ):
        width = natural_width
    else:
        width = natural_width * scale
    height = cast(float, natural_height) * scale
    if (
        not isinstance(maximum, bool)
        and isinstance(maximum, int | float)
        and math.isfinite(maximum)
        and maximum > 0
    ):
        height = min(height, maximum)
    return cast(float, width), height, scale

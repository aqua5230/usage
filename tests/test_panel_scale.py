from __future__ import annotations

import math

import pytest

from panels.panel_scale import MIN_PANEL_SCALE, fit_panel_size, fit_scale


@pytest.mark.parametrize(
    ("natural_height", "maximum", "expected"),
    [
        (900.0, 921.0, 1.0),
        (1183.0, 921.0, pytest.approx(921.0 / 1183.0)),
        (4000.0, 921.0, MIN_PANEL_SCALE),
        (None, 921.0, 1.0),
        (1183.0, None, 1.0),
        (math.nan, 921.0, 1.0),
        (1183.0, math.nan, 1.0),
        (0, 921.0, 1.0),
        (-1, 921.0, 1.0),
        (1183.0, 0, 1.0),
        (1183.0, -1, 1.0),
        (True, 921.0, 1.0),
        (1183.0, True, 1.0),
    ],
)
def test_fit_scale(natural_height: object, maximum: object, expected: float) -> None:
    assert fit_scale(natural_height, maximum) == expected


@pytest.mark.parametrize(
    (
        "natural_width",
        "natural_height",
        "maximum",
        "expected_width",
        "expected_height",
        "expected_scale",
    ),
    [
        (380.0, 900.0, 921.0, 380.0, 900.0, 1.0),
        (
            380.0,
            1183.0,
            921.0,
            pytest.approx(380.0 * 921.0 / 1183.0),
            921.0,
            pytest.approx(921.0 / 1183.0),
        ),
        (380.0, 4000.0, 921.0, 228.0, 921.0, MIN_PANEL_SCALE),
        (380.0, 900.0, 0, 380.0, 900.0, 1.0),
        (380.0, 900.0, -1, 380.0, 900.0, 1.0),
        (380.0, 900.0, math.nan, 380.0, 900.0, 1.0),
        (math.nan, 900.0, 921.0, math.nan, 900.0, 1.0),
    ],
)
def test_fit_panel_size(
    natural_width: object,
    natural_height: object,
    maximum: object,
    expected_width: float,
    expected_height: float,
    expected_scale: float,
) -> None:
    width, height, scale = fit_panel_size(natural_width, natural_height, maximum)
    if isinstance(expected_width, float) and math.isnan(expected_width):
        assert math.isnan(width)
    else:
        assert width == expected_width
    assert height == expected_height
    assert scale == expected_scale

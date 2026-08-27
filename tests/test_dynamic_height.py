from __future__ import annotations

import math
from pathlib import Path

import pytest

from panels.dynamic_height import (
    CONTENT_HEIGHT_SCRIPT,
    clamp_content_height,
    inject_content_height_script,
)

PANEL_ASSETS = Path(__file__).parents[1] / "assets" / "panels"


def test_script_wraps_state_application_and_measures_without_height_constraints() -> None:
    html = inject_content_height_script(
        "<body><main class=\"wrap\"></main><script>"
        "window.usageApplyState = function() {};</script></body>"
    )

    assert html.index("usageApplyStateWithDynamicHeight") > html.index(
        "window.usageApplyState = function()"
    )
    assert 'element.style.height = "auto"' in CONTENT_HEIGHT_SCRIPT
    assert 'element.style.minHeight = "0"' in CONTENT_HEIGHT_SCRIPT
    assert "wrap.getBoundingClientRect()" in CONTENT_HEIGHT_SCRIPT
    assert 'action: "content_height"' in CONTENT_HEIGHT_SCRIPT
    assert "requestAnimationFrame" in CONTENT_HEIGHT_SCRIPT
    assert "MutationObserver" in CONTENT_HEIGHT_SCRIPT
    assert "ResizeObserver" in CONTENT_HEIGHT_SCRIPT
    assert "document.fonts.ready.then(requestContentHeight)" in CONTENT_HEIGHT_SCRIPT
    assert "height !== lastPostedHeight" in CONTENT_HEIGHT_SCRIPT
    assert "requestContentHeight();" in CONTENT_HEIGHT_SCRIPT
    assert "window.usageInvalidateContentHeight" in CONTENT_HEIGHT_SCRIPT
    assert "lastPostedHeight = null;" in CONTENT_HEIGHT_SCRIPT
    assert 'root.style.zoom = "normal"' in CONTENT_HEIGHT_SCRIPT
    assert "window.usageApplyPanelZoom" in CONTENT_HEIGHT_SCRIPT
    # Panels draw their edges with padding on whichever layer wraps .wrap, and
    # the viewport-based panels nest an extra padded .viewport in between, so
    # the whole ancestor chain has to be released and measured — assuming a
    # fixed html/body/.wrap depth loses that layer's spacing.
    assert "parentElement" in CONTENT_HEIGHT_SCRIPT
    assert "paddingTop" in CONTENT_HEIGHT_SCRIPT
    assert "paddingBottom" in CONTENT_HEIGHT_SCRIPT
    assert 'querySelectorAll("[data-usage-height-floor]")' in CONTENT_HEIGHT_SCRIPT
    assert 'floor.element.style.minHeight = floor.height + "px"' in CONTENT_HEIGHT_SCRIPT


def test_world_cup_declares_its_pitch_height_floor() -> None:
    html = (PANEL_ASSETS / "world_cup.html").read_text(encoding="utf-8")

    assert '<div style="flex:1" data-usage-height-floor></div>' in html


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (100, 240.0),
        (550.5, 550.5),
        (1200, 1200.0),
        (5000, 4000.0),
        (True, None),
        ("550", None),
        (math.inf, None),
    ],
)
def test_clamp_content_height(value: object, expected: float | None) -> None:
    assert clamp_content_height(value) == expected

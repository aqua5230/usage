# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

from panels.base import Panel
from panels.web_panel import HTMLPanel

# claude_card_height mirrors codex_card_height: the two cards share the same
# structure (header + two quota rows) and measure equal in headless renders.
PANELS: tuple[Panel, ...] = (
    HTMLPanel(
        "classic",
        "panel_default_name",
        "classic.html",
        height=1004.0,
        claude_card_height=192.0,
        codex_card_height=192.0,
        agy_card_height=192.0,
    ),
    HTMLPanel(
        "matrix",
        "panel_matrix",
        "matrix.html",
        height=1070.0,
        claude_card_height=200.0,
        codex_card_height=200.0,
        agy_card_height=200.0,
    ),
    HTMLPanel(
        "win95",
        "panel_win95",
        "win95.html",
        height=1079.0,
        claude_card_height=210.0,
        codex_card_height=209.0,
        agy_card_height=209.0,
    ),
    HTMLPanel(
        "newspaper",
        "panel_newspaper",
        "newspaper.html",
        height=1073.0,
        claude_card_height=205.0,
        codex_card_height=203.0,
        agy_card_height=203.0,
    ),
    HTMLPanel(
        "cloud_observation",
        "panel_cloud_observation",
        "cloud_observation.html",
        height=1023.0,
        claude_card_height=211.0,
        codex_card_height=211.0,
        agy_card_height=211.0,
    ),
    HTMLPanel(
        "aquarium",
        "panel_aquarium",
        "aquarium.html",
        height=1023.0,
        claude_card_height=211.0,
        codex_card_height=211.0,
        agy_card_height=211.0,
    ),
    HTMLPanel(
        "prism_arcade",
        "panel_prism_arcade",
        "prism_arcade.html",
        height=1023.0,
        claude_card_height=211.0,
        codex_card_height=211.0,
        agy_card_height=211.0,
    ),
    HTMLPanel(
        "black_hole",
        "panel_black_hole",
        "black_hole.html",
        height=1023.0,
        claude_card_height=211.0,
        codex_card_height=211.0,
        agy_card_height=211.0,
    ),
    HTMLPanel(
        "lepidoptera",
        "panel_lepidoptera",
        "lepidoptera.html",
        height=1070.0,
        claude_card_height=208.0,
        codex_card_height=208.0,
        agy_card_height=208.0,
    ),
    HTMLPanel(
        "world_cup",
        "panel_world_cup",
        "world_cup.html",
        claude_card_height=0.0,
        codex_card_height=0.0,
    ),
    HTMLPanel(
        "talent_market",
        "panel_talent_market",
        "talent_market.html",
        height=812.0,
        claude_card_height=0.0,
        codex_card_height=0.0,
    ),
)


def all_panels() -> tuple[Panel, ...]:
    return PANELS


def panel_ids() -> tuple[str, ...]:
    return tuple(panel.id for panel in PANELS)


def get_panel(panel_id: str) -> Panel:
    for panel in PANELS:
        if panel.id == panel_id:
            return panel
    return PANELS[0]

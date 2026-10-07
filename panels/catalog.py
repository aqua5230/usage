# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PanelSpec:
    id: str
    i18n_key: str
    html_filename: str
    claude_card_height: float
    codex_card_height: float
    height: float = 812.0
    agy_card_height: float = 0.0
    grok_card_height: float = 0.0
    status_wrap_extra_height: float = 0.0
    service_alert_height: float = 0.0


PANEL_SPECS: tuple[PanelSpec, ...] = (
    # claude_card_height mirrors codex_card_height: the two cards share the same
    # structure (header + two quota rows) and measure equal in headless renders.
    PanelSpec(
        "classic",
        "panel_default_name",
        "classic.html",
        height=1132.0,
        claude_card_height=192.0,
        codex_card_height=192.0,
        agy_card_height=192.0,
        grok_card_height=128.0,
        status_wrap_extra_height=30.0,
        service_alert_height=32.0,
    ),
    PanelSpec(
        "matrix",
        "panel_matrix",
        "matrix.html",
        height=1174.0,
        claude_card_height=200.0,
        codex_card_height=200.0,
        agy_card_height=200.0,
        grok_card_height=128.0,
        status_wrap_extra_height=32.0,
        service_alert_height=32.0,
    ),
    PanelSpec(
        "win95",
        "panel_win95",
        "win95.html",
        height=1183.0,
        claude_card_height=210.0,
        codex_card_height=209.0,
        agy_card_height=209.0,
        grok_card_height=128.0,
        status_wrap_extra_height=32.0,
        service_alert_height=32.0,
    ),
    PanelSpec(
        "newspaper",
        "panel_newspaper",
        "newspaper.html",
        height=1179.0,
        claude_card_height=205.0,
        codex_card_height=203.0,
        agy_card_height=203.0,
        grok_card_height=128.0,
        status_wrap_extra_height=30.0,
        service_alert_height=32.0,
    ),
    PanelSpec(
        "cloud_observation",
        "panel_cloud_observation",
        "cloud_observation.html",
        height=1134.0,
        claude_card_height=211.0,
        codex_card_height=211.0,
        agy_card_height=211.0,
        grok_card_height=128.0,
        service_alert_height=32.0,
    ),
    PanelSpec(
        "aquarium",
        "panel_aquarium",
        "aquarium.html",
        height=1134.0,
        claude_card_height=211.0,
        codex_card_height=211.0,
        agy_card_height=211.0,
        grok_card_height=128.0,
        service_alert_height=32.0,
    ),
    PanelSpec(
        "prism_arcade",
        "panel_prism_arcade",
        "prism_arcade.html",
        height=1134.0,
        claude_card_height=211.0,
        codex_card_height=211.0,
        agy_card_height=211.0,
        grok_card_height=128.0,
        service_alert_height=32.0,
    ),
    # Reuse classic's measured values because the DOM structure is identical;
    # remeasure if a future render shows clipping.
    PanelSpec(
        "stained_glass",
        "panel_stained_glass",
        "stained_glass.html",
        height=1132.0,
        claude_card_height=192.0,
        codex_card_height=192.0,
        agy_card_height=192.0,
        grok_card_height=128.0,
        status_wrap_extra_height=30.0,
        service_alert_height=32.0,
    ),
    # Reuse classic's measured values because migration keeps its DOM structure;
    # remeasure if a future render shows clipping.
    PanelSpec(
        "migration",
        "panel_migration",
        "migration.html",
        height=1132.0,
        claude_card_height=192.0,
        codex_card_height=192.0,
        agy_card_height=192.0,
        grok_card_height=128.0,
        status_wrap_extra_height=30.0,
        service_alert_height=32.0,
    ),
    # Use classic's measured values as initial estimates for the same DOM;
    # dynamic_height.py measures sketchbook's actual rendered height.
    PanelSpec(
        "sketchbook",
        "panel_sketchbook",
        "sketchbook.html",
        height=1132.0,
        claude_card_height=192.0,
        codex_card_height=192.0,
        agy_card_height=192.0,
        grok_card_height=128.0,
        status_wrap_extra_height=30.0,
        service_alert_height=32.0,
    ),
    # Use classic's measured values as initial estimates for the same DOM;
    # dynamic_height.py measures heart_monitor's actual rendered height.
    PanelSpec(
        "heart_monitor",
        "panel_heart_monitor",
        "heart_monitor.html",
        height=1132.0,
        claude_card_height=192.0,
        codex_card_height=192.0,
        agy_card_height=192.0,
        grok_card_height=128.0,
        status_wrap_extra_height=30.0,
        service_alert_height=32.0,
    ),
    # Reuse classic's measured values because the DOM structure is identical;
    # remeasure if a future render shows clipping.
    PanelSpec(
        "origami",
        "panel_origami",
        "origami.html",
        height=1132.0,
        claude_card_height=192.0,
        codex_card_height=192.0,
        agy_card_height=192.0,
        grok_card_height=128.0,
        status_wrap_extra_height=30.0,
        service_alert_height=32.0,
    ),
    PanelSpec(
        "black_hole",
        "panel_black_hole",
        "black_hole.html",
        height=1134.0,
        claude_card_height=211.0,
        codex_card_height=211.0,
        agy_card_height=211.0,
        grok_card_height=128.0,
        service_alert_height=32.0,
    ),
    PanelSpec(
        "lepidoptera",
        "panel_lepidoptera",
        "lepidoptera.html",
        height=1174.0,
        claude_card_height=208.0,
        codex_card_height=208.0,
        agy_card_height=208.0,
        grok_card_height=128.0,
        status_wrap_extra_height=32.0,
        service_alert_height=32.0,
    ),
    PanelSpec(
        "world_cup",
        "panel_world_cup",
        "world_cup.html",
        claude_card_height=0.0,
        codex_card_height=0.0,
        service_alert_height=32.0,
    ),
    # 1166 = the previous 1038px estimate + 128px for the Grok card.
    # This is estimated, not measured; verify clipping visually after packaging.
    PanelSpec(
        "catppuccin",
        "panel_catppuccin",
        "catppuccin.html",
        height=1166.0,
        claude_card_height=192.0,
        codex_card_height=192.0,
        agy_card_height=192.0,
        grok_card_height=128.0,
        status_wrap_extra_height=30.0,
        service_alert_height=32.0,
    ),
)

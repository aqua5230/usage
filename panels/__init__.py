from __future__ import annotations

from panels.base import Panel
from panels.web_panel import HTMLPanel

PANELS: tuple[Panel, ...] = (
    HTMLPanel("classic", "panel_default_name", "classic.html"),
    HTMLPanel("matrix", "panel_matrix", "matrix.html"),
    HTMLPanel("win95", "panel_win95", "win95.html"),
    HTMLPanel("newspaper", "panel_newspaper", "newspaper.html"),
    HTMLPanel("cloud_observation", "panel_cloud_observation", "cloud_observation.html"),
    HTMLPanel("aquarium", "panel_aquarium", "aquarium.html"),
    HTMLPanel("prism_arcade", "panel_prism_arcade", "prism_arcade.html"),
    HTMLPanel("black_hole", "panel_black_hole", "black_hole.html"),
    HTMLPanel("world_cup", "panel_world_cup", "world_cup.html"),
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

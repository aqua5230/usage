from __future__ import annotations

from panels.base import Panel
from panels.web_panel import HTMLPanel

PANELS: tuple[Panel, ...] = (
    HTMLPanel("classic", "預設", "classic.html"),
    HTMLPanel("matrix", "駭客任務", "matrix.html"),
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

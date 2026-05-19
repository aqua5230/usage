from __future__ import annotations

from panels.base import Panel
from panels.classic import ClassicPanel
from panels.matrix import MatrixPanel
from panels.taiwan import TaiwanPanel

PANELS: tuple[Panel, ...] = (ClassicPanel(), TaiwanPanel, MatrixPanel())
DEFAULT_PANEL_ID = "classic"


def all_panels() -> tuple[Panel, ...]:
    return PANELS


def panel_ids() -> tuple[str, ...]:
    return tuple(panel.id for panel in PANELS)


def get_panel(panel_id: str) -> Panel:
    for panel in PANELS:
        if panel.id == panel_id:
            return panel
    return PANELS[0]


def panel_id_exists(panel_id: str) -> bool:
    return any(panel.id == panel_id for panel in PANELS)

from __future__ import annotations

from pathlib import Path

import panels
from panels.base import (
    ACTIVE_PANEL_DEFAULTS_KEY,
    load_active_panel_id,
    save_active_panel_id,
)


class FakeDefaults:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.synchronized = False

    def stringForKey_(self, key: str) -> str | None:
        return self.values.get(key)

    def setObject_forKey_(self, value: str, key: str) -> None:
        self.values[key] = value

    def synchronize(self) -> None:
        self.synchronized = True


def test_registered_panel_ids_are_unique() -> None:
    ids = panels.panel_ids()

    assert ids == (
        "classic",
        "matrix",
        "win95",
        "newspaper",
        "cloud_observation",
        "aquarium",
        "prism_arcade",
        "black_hole",
        "world_cup",
    )
    assert len(ids) == len(set(ids))


def test_registered_panel_display_names() -> None:
    names = [panel.display_name for panel in panels.all_panels()]

    assert names == [
        "預設",
        "駭客任務",
        "視窗 95",
        "復古報紙",
        "雲圖觀測",
        "午夜水族箱",
        "稜鏡街機",
        "黑洞視界",
        "世界盃 2026",
    ]


def test_classic_panel_preferred_size() -> None:
    panel = panels.get_panel("classic")

    assert panel.preferred_size() == (364.0, 812.0)


def test_win95_panel_preferred_size() -> None:
    panel = panels.get_panel("win95")

    assert panel.preferred_size() == (364.0, 768.0)


def test_html_panels_place_analyze_and_cli_in_project_header() -> None:
    panel_dir = Path(__file__).resolve().parent.parent / "assets" / "panels"

    for panel_path in sorted(panel_dir.glob("*.html")):
        html = panel_path.read_text(encoding="utf-8")
        project_index = html.index('data-action="toggle-project-range"')
        footer_index = html.index('<section class="footer"')
        analyze_index = html.index('data-action="analyze"')
        cli_index = html.index('data-action="toggle-cli"')

        assert project_index < analyze_index < footer_index, panel_path.name
        assert project_index < cli_index < footer_index, panel_path.name
        assert html.count('data-action="analyze"') == 1, panel_path.name
        assert html.count('<div class="cli-status" data-cli-panel hidden></div>') == 1
        assert 'class="action" data-action="analyze"' not in html


def test_missing_panel_id_falls_back_to_classic() -> None:
    panel = panels.get_panel("missing")

    assert panel.id == "classic"


def test_defaults_load_falls_back_to_classic() -> None:
    defaults = FakeDefaults()

    assert load_active_panel_id(defaults) == "classic"


def test_defaults_round_trip() -> None:
    defaults = FakeDefaults()

    save_active_panel_id("classic", defaults)

    assert defaults.values[ACTIVE_PANEL_DEFAULTS_KEY] == "classic"
    assert load_active_panel_id(defaults) == "classic"
    assert defaults.synchronized is True

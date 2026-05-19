from __future__ import annotations

import menubar
import panels
from panels.base import (
    ACTIVE_PANEL_DEFAULTS_KEY,
    CONTENT_HEIGHT,
    HEADER_HEIGHT,
    POPOVER_WIDTH,
    ThemeConfig,
    ThemedPanel,
    load_active_panel_id,
    save_active_panel_id,
)
from panels.taiwan import TAIWAN_THEME


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

    assert ids == ("classic", "taiwan", "matrix", "ecg", "minimal")
    assert len(ids) == len(set(ids))


def test_registered_panel_display_names() -> None:
    names = [panel.display_name for panel in panels.all_panels()]

    assert names == ["預設", "台灣用量監控", "駭客任務", "ECG", "Minimal"]


def test_classic_panel_preferred_size() -> None:
    panel = panels.get_panel("classic")

    assert panel.preferred_size() == (364.0, 574.0)


def test_taiwan_panel_preferred_size() -> None:
    panel = panels.get_panel("taiwan")

    assert panel.preferred_size() == (364.0, 672.0)


def test_missing_panel_id_falls_back_to_classic() -> None:
    panel = panels.get_panel("missing")

    assert panel.id == "classic"


def test_defaults_load_falls_back_to_classic() -> None:
    defaults = FakeDefaults()

    assert load_active_panel_id(defaults) == "classic"


def test_defaults_round_trip() -> None:
    defaults = FakeDefaults()

    save_active_panel_id("taiwan", defaults)

    assert defaults.values[ACTIVE_PANEL_DEFAULTS_KEY] == "taiwan"
    assert load_active_panel_id(defaults) == "taiwan"
    assert defaults.synchronized is True


def test_taiwan_theme_config_values() -> None:
    assert TAIWAN_THEME.id == "taiwan"
    assert TAIWAN_THEME.icon_asset == "taiwan.png"
    assert TAIWAN_THEME.header_title == "台灣用量監控"
    assert TAIWAN_THEME.bg_top == (0.55, 0.05, 0.08)
    assert TAIWAN_THEME.card_bg == (0.30, 0.0, 0.02, 0.6)


def test_themed_panel_without_header_keeps_classic_height() -> None:
    config = ThemeConfig(
        id="plain",
        display_name="Plain",
        icon_asset="taiwan.png",
        header_title="",
        bg_top=(0.0, 0.0, 0.0),
        bg_bottom=(0.0, 0.0, 0.0),
        card_bg=(0.0, 0.0, 0.0, 0.5),
        text_color=(1.0, 1.0, 1.0),
        muted_text_color=(1.0, 1.0, 1.0),
        primary_button_fg=(1.0, 0.0, 0.0),
        primary_button_bg=(1.0, 1.0, 1.0),
        secondary_button_fg=(1.0, 1.0, 1.0),
    )

    assert ThemedPanel(config).preferred_size() == (POPOVER_WIDTH, CONTENT_HEIGHT)


def test_themed_panel_with_header_adds_header_height() -> None:
    assert ThemedPanel(TAIWAN_THEME).preferred_size() == (
        POPOVER_WIDTH,
        CONTENT_HEIGHT + HEADER_HEIGHT,
    )


def test_popover_size_uses_active_panel_height_and_install_button() -> None:
    state = menubar._empty_state()
    state.show_install_button = True

    size = menubar._popover_size(state, panels.get_panel("taiwan"))

    assert size.width == 364.0
    assert size.height == 714.0

# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from Foundation import NSBundle, NSUserDefaults

if TYPE_CHECKING:
    from menubar import PopoverState

ACTIVE_PANEL_DEFAULTS_KEY = "usage.activePanelId"


class Panel(Protocol):
    id: str
    i18n_key: str
    claude_card_height: float
    codex_card_height: float
    agy_card_height: float

    def build_view(self, delegate: Any) -> Any: ...
    def apply_state(self, view: Any, state: PopoverState) -> None: ...
    def preferred_size(self) -> tuple[float, float]: ...


def load_active_panel_id(defaults: Any | None = None) -> str:
    store = defaults if defaults is not None else NSUserDefaults.standardUserDefaults()
    value = store.stringForKey_(ACTIVE_PANEL_DEFAULTS_KEY)
    return str(value) if value else "classic"


def save_active_panel_id(panel_id: str, defaults: Any | None = None) -> None:
    store = defaults if defaults is not None else NSUserDefaults.standardUserDefaults()
    store.setObject_forKey_(panel_id, ACTIVE_PANEL_DEFAULTS_KEY)
    if hasattr(store, "synchronize"):
        store.synchronize()


def resolve_resource(name: str) -> str:
    bundle = NSBundle.mainBundle()
    if bundle is not None:
        stem, _, ext = name.rpartition(".")
        path = bundle.pathForResource_ofType_(stem, ext)
        if path:
            return str(path)
    return str(Path(__file__).resolve().parent.parent / "assets" / name)

# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

from functools import cache
from typing import TYPE_CHECKING

from panels.catalog import PANEL_SPECS

if TYPE_CHECKING:
    from panels.base import Panel


@cache
def all_panels() -> tuple[Panel, ...]:
    # web_panel requires PyObjC at import time (objc/AppKit/WebKit), which only
    # exists on macOS. Import it lazily so importing the panels package (e.g.
    # wintray -> panels.payload on Windows) never pulls it in.
    from panels.web_panel import HTMLPanel

    return tuple(
        HTMLPanel(
            panel_id=spec.id,
            i18n_key=spec.i18n_key,
            html_filename=spec.html_filename,
            height=spec.height,
            claude_card_height=spec.claude_card_height,
            codex_card_height=spec.codex_card_height,
            agy_card_height=spec.agy_card_height,
            grok_card_height=spec.grok_card_height,
            status_wrap_extra_height=spec.status_wrap_extra_height,
            service_alert_height=spec.service_alert_height,
        )
        for spec in PANEL_SPECS
    )


def panel_ids() -> tuple[str, ...]:
    return tuple(panel.id for panel in all_panels())


def get_panel(panel_id: str) -> Panel:
    for panel in all_panels():
        if panel.id == panel_id:
            return panel
    return all_panels()[0]

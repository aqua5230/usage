# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>

"""Preferences specific to the Windows tray."""

from __future__ import annotations

from typing import Literal

from prefs import _load_preferences, _save_preferences

type TrayProvider = Literal["claude", "codex"]


def load_tray_provider() -> TrayProvider:
    return "codex" if _load_preferences().get("tray_provider") == "codex" else "claude"


def save_tray_provider(provider: object) -> bool:
    if not isinstance(provider, str) or provider not in ("claude", "codex"):
        return False
    preferences = _load_preferences()
    preferences["tray_provider"] = provider
    _save_preferences(preferences)
    return True

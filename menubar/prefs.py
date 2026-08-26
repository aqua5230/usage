# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

from collections.abc import Mapping

from prefs import _load_preferences, _save_preferences

DEFAULT_QUOTA_CARD_ORDER = ("claude", "codex", "agy", "grok")
DEFAULT_PANEL_FLAVOR = "mocha"
PANEL_FLAVORS = ("latte", "frappe", "macchiato", "mocha")


def _resolved_preferences(prefs: Mapping[str, object] | None = None) -> Mapping[str, object]:
    return _load_preferences() if prefs is None else prefs


def _auto_update_check_enabled(prefs: Mapping[str, object] | None = None) -> bool:
    data = _resolved_preferences(prefs)
    return data.get("auto_update_check") is not False


def _hide_claude_enabled(prefs: Mapping[str, object] | None = None) -> bool:
    data = _resolved_preferences(prefs)
    return data.get("hide_claude_section") is True


def _hide_codex_enabled(prefs: Mapping[str, object] | None = None) -> bool:
    data = _resolved_preferences(prefs)
    return data.get("hide_codex_section") is True


def _hide_agy_enabled(prefs: Mapping[str, object] | None = None) -> bool:
    data = _resolved_preferences(prefs)
    return data.get("hide_agy_section") is True


def _panel_flavor(prefs: Mapping[str, object] | None = None) -> str:
    data = _resolved_preferences(prefs)
    flavor = _valid_panel_flavor(data.get("panel_flavor"))
    return DEFAULT_PANEL_FLAVOR if flavor is None else flavor


def _save_panel_flavor(flavor: object) -> bool:
    valid_flavor = _valid_panel_flavor(flavor)
    if valid_flavor is None:
        return False
    prefs = _load_preferences()
    prefs["panel_flavor"] = valid_flavor
    _save_preferences(prefs)
    return True


def _valid_panel_flavor(value: object) -> str | None:
    if not isinstance(value, str) or value not in PANEL_FLAVORS:
        return None
    return value


def _quota_card_order(prefs: Mapping[str, object] | None = None) -> tuple[str, ...]:
    data = _resolved_preferences(prefs)
    order = _valid_quota_card_order(data.get("quota_card_order"))
    return DEFAULT_QUOTA_CARD_ORDER if order is None else order


def _save_quota_card_order(order: object) -> bool:
    valid_order = _valid_quota_card_order(order)
    if valid_order is None:
        return False
    prefs = _load_preferences()
    prefs["quota_card_order"] = list(valid_order)
    _save_preferences(prefs)
    return True


def _valid_quota_card_order(value: object) -> tuple[str, ...] | None:
    if not isinstance(value, list) or any(not isinstance(card, str) for card in value):
        return None
    order = tuple(value)
    if len(order) != len(set(order)) or not set(order) <= set(DEFAULT_QUOTA_CARD_ORDER):
        return None
    # A saved order shorter than the current default means a source was added
    # since it was written (e.g. a 4th quota card) — append the newcomers
    # instead of discarding the user's whole preference.
    missing = (card for card in DEFAULT_QUOTA_CARD_ORDER if card not in order)
    return order + tuple(missing)


def _quota_notifications_enabled(prefs: Mapping[str, object] | None = None) -> bool:
    data = _resolved_preferences(prefs)
    return data.get("quota_notifications") is not False


def _window_keeper_enabled(prefs: Mapping[str, object] | None = None) -> bool:
    # Defaults OFF (opt-in) — opposite polarity from quota_notifications, which
    # is why this is `is True` rather than `is not False`.
    data = _resolved_preferences(prefs)
    return data.get("window_keeper") is True or data.get("agy_window_keeper") is True


def _agy_window_keeper_enabled(prefs: Mapping[str, object] | None = None) -> bool:
    return _window_keeper_enabled(prefs)


def _quota_notification_thresholds(prefs: Mapping[str, object] | None = None) -> list[float]:
    data = _resolved_preferences(prefs)
    raw = data.get("quota_notification_thresholds")
    if not isinstance(raw, list):
        return [90.0]
    thresholds: list[float] = []
    for value in raw:
        if isinstance(value, int | float) and 0 < float(value) <= 100:
            thresholds.append(float(value))
    return thresholds or [90.0]

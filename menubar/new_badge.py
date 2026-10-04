# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import json
import logging
import time
from typing import Any, TypeGuard

import prefs
from i18n import _t
from prefs import _load_preferences, _save_preferences

logger = logging.getLogger(__name__)
_LIFETIME = 14 * 24 * 60 * 60


def _preferences() -> dict[str, Any] | None:
    data = _load_preferences()
    # The shared loader returns {} for both empty and unreadable files.
    # Preserve unreadable files rather than replacing unrelated preferences.
    if not data and prefs.PREFERENCES_FILE.exists():
        try:
            raw = json.loads(prefs.PREFERENCES_FILE.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                logger.warning("New badge preferences must be a JSON object; preserving file")
                return None
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            logger.warning("Cannot read new badge preferences; preserving file", exc_info=True)
            return None
    return data


def _save(data: dict[str, Any]) -> None:
    try:
        _save_preferences(data)
    except OSError:
        logger.warning("Cannot save new badge preferences", exc_info=True)


def _valid_first_shown(value: object, now: float) -> TypeGuard[int]:
    return type(value) is int and 0 <= value <= now


def should_show_badge(feature_id: str, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    data = _preferences()
    if data is None:
        return True
    badges = data.get("new_feature_badges")
    if not isinstance(badges, dict):
        badges = {}
        data["new_feature_badges"] = badges
    record = badges.get(feature_id)
    if isinstance(record, dict):
        if record.get("dismissed") is True:
            return False
        first_shown = record.get("first_shown")
        if record.get("dismissed") is False and _valid_first_shown(first_shown, now):
            return bool(now - first_shown < _LIFETIME)
    badges[feature_id] = {"first_shown": int(now), "dismissed": False}
    _save(data)
    return True


def dismiss_badge(feature_id: str) -> None:
    data = _preferences()
    if data is None:
        return
    badges = data.get("new_feature_badges")
    if not isinstance(badges, dict):
        badges = {}
        data["new_feature_badges"] = badges
    record = badges.get(feature_id)
    now = time.time()
    first_shown = record.get("first_shown") if isinstance(record, dict) else None
    badges[feature_id] = {
        "first_shown": first_shown if _valid_first_shown(first_shown, now) else int(now),
        "dismissed": True,
    }
    _save(data)


def apply_badge(item: Any, language: str, feature_id: str) -> None:
    if not hasattr(item, "setBadge_"):
        return
    try:
        from AppKit import NSMenuItemBadge
    except ImportError:
        return
    if should_show_badge(feature_id):
        badge = NSMenuItemBadge.alloc().initWithString_(_t(language, "menu_badge_new"))
        item.setBadge_(badge)

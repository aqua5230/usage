# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import os
import sys
from collections.abc import Mapping


def _normalize_lang(code: str | None) -> str:
    if not code:
        return "en"
    normalized = code.split(".")[0].strip().lower().replace("_", "-")

    if normalized in {"zh-tw", "zh-hk", "zh-hant"} or normalized.startswith(
        ("zh-tw-", "zh-hant")
    ):
        return "zh-TW"
    if normalized in {"zh-cn", "zh-sg", "zh-hans", "zh"} or normalized.startswith(
        ("zh-cn-", "zh-hans")
    ):
        return "zh-CN"
    if normalized.startswith("en"):
        return "en"
    if normalized.startswith("ja"):
        return "ja"
    if normalized.startswith("ko"):
        return "ko"
    return "en"


def _detect_macos_lang() -> str:
    try:
        from Foundation import NSLocale

        preferred = NSLocale.preferredLanguages()
        if preferred:
            return _normalize_lang(str(preferred[0]))
        locale = NSLocale.currentLocale()
        identifier_attr = getattr(locale, "localeIdentifier", None)
        identifier = identifier_attr() if callable(identifier_attr) else identifier_attr
        return _normalize_lang(str(identifier) if identifier is not None else None)
    except Exception:
        return "en"


def _detect_windows_lang() -> str:
    try:
        import ctypes
        import locale

        windll = getattr(ctypes, "windll", None)
        if windll is None:
            return "en"
        lang_id = int(windll.kernel32.GetUserDefaultUILanguage())
        return _normalize_lang(locale.windows_locale.get(lang_id))
    except Exception:
        return "en"


def detect_lang(env: Mapping[str, str] | None = None) -> str:
    source = os.environ if env is None else env
    for key in ("USAGE_LANG", "TT_LANG", "LANG"):
        value = source.get(key, "").strip()
        if value:
            return _normalize_lang(value)
    if env is None:
        if sys.platform == "win32":
            return _detect_windows_lang()
        return _detect_macos_lang()
    return "en"

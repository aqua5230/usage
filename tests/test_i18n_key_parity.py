# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Key-parity test for ``i18n.json``.

The project rule is that every user-visible string lives in ``i18n.json``
under all five language sections (``zh-TW``, ``zh-CN``, ``en``, ``ja``,
``ko``). ``_t`` degrades gracefully for a missing key (English fallback,
then the raw key), so a forgotten translation never crashes — it just
silently ships English. This test makes that omission fail loudly in CI
instead.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

EXPECTED_LANGS = {"zh-TW", "zh-CN", "en", "ja", "ko"}
I18N_PATH = Path(__file__).resolve().parent.parent / "i18n.json"
_PLACEHOLDER = re.compile(r"\{[^}]*\}")


def _bundle() -> dict[str, dict[str, str]]:
    data: dict[str, dict[str, str]] = json.loads(I18N_PATH.read_text(encoding="utf-8"))
    return data


def test_all_expected_languages_present() -> None:
    assert set(_bundle().keys()) == EXPECTED_LANGS


def test_every_language_has_the_same_keys() -> None:
    bundle = _bundle()
    reference = set(bundle["en"])
    mismatches = {
        lang: {
            "missing": sorted(reference - set(keys)),
            "extra": sorted(set(keys) - reference),
        }
        for lang, keys in bundle.items()
        if set(keys) != reference
    }
    assert not mismatches, f"i18n key mismatch vs en: {mismatches}"


def test_no_translation_is_blank() -> None:
    """A present-but-empty value passes key parity yet ships a blank label."""
    bundle = _bundle()
    blanks = {
        lang: sorted(key for key, value in strings.items() if not value.strip())
        for lang, strings in bundle.items()
        if any(not value.strip() for value in strings.values())
    }
    assert not blanks, f"i18n blank translations: {blanks}"


def test_placeholders_match_english() -> None:
    """A dropped or renamed ``{placeholder}`` makes ``.format`` raise at runtime."""
    bundle = _bundle()
    english = bundle["en"]
    mismatches = {
        f"{lang}.{key}": {
            "en": sorted(_PLACEHOLDER.findall(english[key])),
            lang: sorted(_PLACEHOLDER.findall(value)),
        }
        for lang, strings in bundle.items()
        for key, value in strings.items()
        if sorted(_PLACEHOLDER.findall(value)) != sorted(_PLACEHOLDER.findall(english[key]))
    }
    assert not mismatches, f"i18n placeholder mismatch vs en: {mismatches}"

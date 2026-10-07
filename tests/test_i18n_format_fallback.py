# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""``_t`` must never crash when a locale's template has a bad placeholder.

Key parity is enforced elsewhere (``test_i18n_key_parity``), but a translator
can still ship a string whose ``{placeholder}`` doesn't match the kwargs the
call site passes. That ``.format()`` would raise; ``_t`` degrades instead —
English template first, then the raw key.
"""

from __future__ import annotations

import pytest

from usage_common import i18n


def test_t_falls_back_to_english_on_malformed_localized_placeholder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_bundle = {
        "en": {"greet": "Hello {name}"},
        "zh-TW": {"greet": "你好 {wrong}"},  # placeholder won't match name=
    }
    monkeypatch.setattr(i18n, "_load_i18n_bundle", lambda: fake_bundle)

    assert i18n._t("zh-TW", "greet", name="Ada") == "Hello Ada"


def test_t_falls_back_to_english_on_type_mismatched_format_spec(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A numeric format spec applied to a non-number raises TypeError, not the
    # KeyError/ValueError family — the fallback must cover it too.
    fake_bundle = {
        "en": {"price": "Cost {x}"},
        "zh-TW": {"price": "價格 {x:.2f}"},
    }
    monkeypatch.setattr(i18n, "_load_i18n_bundle", lambda: fake_bundle)

    assert i18n._t("zh-TW", "price", x=None) == "Cost None"


def test_t_falls_back_to_key_when_every_template_is_malformed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_bundle = {
        "en": {"greet": "Hi {missing}"},
        "zh-TW": {"greet": "嗨 {wrong}"},
    }
    monkeypatch.setattr(i18n, "_load_i18n_bundle", lambda: fake_bundle)

    assert i18n._t("zh-TW", "greet", name="Ada") == "greet"

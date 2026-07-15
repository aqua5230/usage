# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import ctypes
import sys
from types import SimpleNamespace

import pytest

from usage_lang import _detect_windows_lang, detect_lang


def _fake_windll(monkeypatch: pytest.MonkeyPatch, lang_id: int) -> None:
    windll = SimpleNamespace(
        kernel32=SimpleNamespace(GetUserDefaultUILanguage=lambda: lang_id)
    )
    monkeypatch.setattr(ctypes, "windll", windll, raising=False)


def test_detect_lang_defaults_to_en_without_environment() -> None:
    assert detect_lang({}) == "en"


def test_detect_lang_reads_lang_zh_tw_locale() -> None:
    assert detect_lang({"LANG": "zh_TW.UTF-8"}) == "zh-TW"


def test_detect_lang_reads_zh_hant_locale() -> None:
    assert detect_lang({"LANG": "zh-Hant-TW"}) == "zh-TW"


def test_detect_lang_reads_zh_hk_locale_as_traditional() -> None:
    assert detect_lang({"LANG": "zh_HK.UTF-8"}) == "zh-TW"


def test_detect_lang_reads_tt_lang_ja() -> None:
    assert detect_lang({"TT_LANG": "ja"}) == "ja"


def test_detect_lang_reads_usage_lang_ko() -> None:
    assert detect_lang({"USAGE_LANG": "ko"}) == "ko"


def test_detect_lang_prefers_usage_lang_over_tt_lang() -> None:
    assert detect_lang({"USAGE_LANG": "ko", "TT_LANG": "ja"}) == "ko"


def test_detect_lang_prefers_usage_lang_over_tt_lang_and_lang() -> None:
    env = {"USAGE_LANG": "ja", "TT_LANG": "ko", "LANG": "zh_TW.UTF-8"}
    assert detect_lang(env) == "ja"


def test_detect_lang_unknown_code_falls_back_to_en() -> None:
    assert detect_lang({"LANG": "de_DE.UTF-8"}) == "en"


@pytest.mark.parametrize(
    ("lang_id", "expected"),
    [
        (1028, "zh-TW"),  # zh_TW
        (2052, "zh-CN"),  # zh_CN
        (1041, "ja"),  # ja_JP
        (1042, "ko"),  # ko_KR
        (1033, "en"),  # en_US
    ],
)
def test_detect_windows_lang_maps_ui_language_ids(
    monkeypatch: pytest.MonkeyPatch, lang_id: int, expected: str
) -> None:
    _fake_windll(monkeypatch, lang_id)

    assert _detect_windows_lang() == expected


def test_detect_windows_lang_unknown_id_falls_back_to_en(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_windll(monkeypatch, 0x7FFF)

    assert _detect_windows_lang() == "en"


def test_detect_windows_lang_without_windll_falls_back_to_en(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ctypes, "windll", None, raising=False)

    assert _detect_windows_lang() == "en"


def test_detect_lang_uses_windows_ui_language_without_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in ("USAGE_LANG", "TT_LANG", "LANG"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    _fake_windll(monkeypatch, 1028)

    assert detect_lang() == "zh-TW"


def test_detect_lang_env_var_beats_windows_ui_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("USAGE_LANG", "ja")
    monkeypatch.setattr(sys, "platform", "win32")
    _fake_windll(monkeypatch, 1028)

    assert detect_lang() == "ja"

# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

from collections import defaultdict
from types import SimpleNamespace

import pytest

from ui import tables


@pytest.mark.parametrize(
    ("theme", "colorfgbg", "expected"),
    [
        ("light", "0;0", True),
        ("dark", "0;15", False),
        ("", "15;10", True),
        ("", "invalid", False),
        ("", "", False),
    ],
)
def test_is_light_theme_reads_theme_and_colorfgbg(
    monkeypatch: pytest.MonkeyPatch,
    theme: str,
    colorfgbg: str,
    expected: bool,
) -> None:
    if theme:
        monkeypatch.setenv("TT_THEME", theme)
    else:
        monkeypatch.delenv("TT_THEME", raising=False)
    if colorfgbg:
        monkeypatch.setenv("COLORFGBG", colorfgbg)
    else:
        monkeypatch.delenv("COLORFGBG", raising=False)

    assert tables._is_light_theme() is expected


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("claude-opus-4-7", "Opus 4.7"),
        ("claude-sonnet-5", "Sonnet 5"),
        ("provider/model-name-that-is-long", "model-name-that-"),
        ("plain-model-name-that-is-long", "plain-model-name"),
    ],
)
def test_model_short_uses_known_names_and_truncates(model: str, expected: str) -> None:
    assert tables._model_short(model) == expected


@pytest.mark.parametrize(
    ("tokens", "expected"),
    [
        (999, "999"),
        (1_000, "1.0K"),
        (1_500_000, "1.5M"),
        (1_234_567_890, "1.23B"),
    ],
)
def test_fmt_tokens_scales_large_values(tokens: int, expected: str) -> None:
    assert tables._fmt_tokens(tokens) == expected


@pytest.mark.parametrize(
    ("cost", "expected"),
    [
        (None, "--"),
        (0.0, "$0"),
        (0.1234, "$0.123"),
        (1.234, "$1.23"),
        (100.4, "$100"),
    ],
)
def test_fmt_cost_uses_expected_precision(cost: float | None, expected: str) -> None:
    assert tables._fmt_cost(cost) == expected


@pytest.mark.parametrize(
    ("minutes", "expected"),
    [
        (59.9, "59min"),
        (125.5, "2h05m"),
    ],
)
def test_fmt_duration_formats_minutes_and_hours(minutes: float, expected: str) -> None:
    assert tables._fmt_duration(minutes) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("usage", 5),
        ("用量usage", 9),
    ],
)
def test_display_width_counts_non_ascii_as_double_width(text: str, expected: int) -> None:
    assert tables._display_width(text) == expected


@pytest.mark.parametrize(
    ("ratio", "expected"),
    [
        (0.5, "bold"),
        (0.51, f"bold {tables._S.warn}"),
        (0.81, f"bold {tables._S.bad}"),
    ],
)
def test_token_heat_style_uses_warning_and_bad_thresholds(
    ratio: float,
    expected: str,
) -> None:
    assert tables._token_heat_style(ratio) == expected


@pytest.mark.parametrize(
    ("pct", "expected"),
    [
        (50.0, tables._S.bar_low),
        (50.1, tables._S.bar_mid),
        (80.1, tables._S.bar_high),
    ],
)
def test_pct_style_uses_bar_thresholds(pct: float, expected: str) -> None:
    assert tables._pct_style(pct) == expected


@pytest.mark.parametrize(
    ("agent_ids", "expected"),
    [
        (["claude-code", "codex"], True),
        (["claude-code", "", None], False),
    ],
)
def test_is_multi_agent_counts_distinct_non_empty_agent_ids(
    agent_ids: list[str | None],
    expected: bool,
) -> None:
    stats = [SimpleNamespace(agent_id=agent_id) for agent_id in agent_ids]

    assert tables._is_multi_agent(stats) is expected


def test_group_by_agent_returns_lists_keyed_by_agent_id() -> None:
    claude_first = SimpleNamespace(agent_id="claude-code")
    codex = SimpleNamespace(agent_id="codex")
    claude_second = SimpleNamespace(agent_id="claude-code")

    grouped = tables._group_by_agent([claude_first, codex, claude_second])

    assert grouped == defaultdict(
        list,
        {
            "claude-code": [claude_first, claude_second],
            "codex": [codex],
        },
    )

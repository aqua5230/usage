# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

import adapters.registry as registry
from adapters import agy
from adapters.types import AgentInfo
from loaders import agy_loader
from usage_common import pricing
from usage_common.i18n import t


@pytest.fixture
def sessions_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    directory = tmp_path / "conversations"
    monkeypatch.setattr(agy_loader, "AGY_SESSIONS_DIR", directory)
    return directory


def test_detect_uses_antigravity_sessions_directory(sessions_dir: Path) -> None:
    assert agy.detect() is None

    sessions_dir.mkdir()

    assert agy.detect() == AgentInfo(
        id="antigravity",
        name=t("agy_name"),
        data_dir=str(sessions_dir),
        installed=True,
    )


def test_load_entries_maps_usage_without_precomputing_cost(
    monkeypatch: pytest.MonkeyPatch,
    sessions_dir: Path,
) -> None:
    source_entries = [
        agy_loader.AgyUsageEntry(
            timestamp=datetime(2026, 7, 12, tzinfo=UTC),
            model="gemini-3-flash-a",
            input_tokens=120,
            output_tokens=30,
            cache_read_tokens=90,
            thinking_tokens=40,
            dedup_key="request-1",
            session_id="session-1",
            project="my-project",
        ),
        agy_loader.AgyUsageEntry(
            timestamp=datetime(2026, 7, 12, 1, tzinfo=UTC),
            model="gemini-default",
            input_tokens=10,
            output_tokens=2,
            cache_read_tokens=0,
            thinking_tokens=0,
            dedup_key="request-2",
            session_id="session-2",
            project="",
        ),
    ]
    calls: dict[str, int] = {}

    def fake_load_entries_with_stats(hours_back: int = 0) -> agy_loader.AgyLoadResult:
        calls["hours_back"] = hours_back
        return agy_loader.AgyLoadResult(source_entries, skipped_missing_dedup_key=0)

    monkeypatch.setattr(agy_loader, "load_entries_with_stats", fake_load_entries_with_stats)

    entries = agy.load_entries(hours_back=24)

    assert calls == {"hours_back": 24}
    assert [(entry.model, entry.output_tokens) for entry in entries] == [
        ("gemini-3-flash-preview", 70),
        ("gemini-default", 2),
    ]
    assert entries[0].total_tokens == 280
    assert entries[0].message_id == "request-1"
    assert entries[0].request_id == ""
    assert entries[0].cache_creation_tokens == 0
    assert entries[0].cost_usd is None
    assert entries[0].project == "my-project"
    assert entries[0].agent_id == "antigravity"
    assert entries[1].project == "Antigravity"


def test_normalize_model_covers_tokscale_aliases() -> None:
    assert [
        agy._normalize_model(model)
        for model in [
            "gemini-3-flash-a",
            "gemini-3-flash-c",
            "gemini-3-flash",
            "gemini-3.1-pro-high",
            "gemini-3.1-pro-low",
            "gemini-3-pro-high",
            "gemini-3-pro-low",
            "gemini-3.5-flash-low",
            "gemini-3.5-flash-custom",
        ]
    ] == [
        "gemini-3-flash-preview",
        "gemini-3-flash-preview",
        "gemini-3-flash-preview",
        "gemini-3.1-pro",
        "gemini-3.1-pro",
        "gemini-3-pro",
        "gemini-3-pro",
        "gemini-3.5-flash",
        "gemini-3.5-flash-custom",
    ]


def test_normalize_model_strips_agy_suffixes() -> None:
    expected = {
        "gemini-3.8-flash-n": "gemini-3.8-flash",
        "gemini-3.8-flash-tiered": "gemini-3.8-flash",
        "gemini-4-argon": "gemini-4-argon",
        "gemini-4-argon-s": "gemini-4-argon",
        "gemini-4-argon-trial": "gemini-4-argon",
        "gemini-4-hydrogen": "gemini-4-hydrogen",
        "gemini-4-hydrogen-xhigh": "gemini-4-hydrogen",
        "claude-sonnet-5-5-medium": "claude-sonnet-5-5",
        "claude-sonnet-5-5-low": "claude-sonnet-5-5",
        "claude-opus-5-5-high": "claude-opus-5-5",
        "gpt-oss-120b-medium": "gpt-oss-120b",
    }

    assert {model: agy._normalize_model(model) for model in expected} == expected


def test_normalize_model_only_strips_single_known_trailing_segment() -> None:
    assert agy._normalize_model("gemini-4-argon-s-high") == "gemini-4-argon-s"
    assert agy._normalize_model("gemini-4-low-argon") == "gemini-4-low-argon"
    assert agy._normalize_model("gemini-4-argon-preview") == "gemini-4-argon-preview"
    assert agy._normalize_model("-low") == "-low"
    assert agy._normalize_model("") == ""


def test_agy_models_resolve_against_litellm_pricing_table() -> None:
    litellm_table: pricing.PricingTable = {
        "gemini-3.8-flash": {"input_cost_per_token": 1e-6},
        "gemini/gemini-4-argon": {"input_cost_per_token": 2e-6},
        "gemini/gemini-4-carbon": {"input_cost_per_token": 3e-6},
        "claude-sonnet-5-5": {"input_cost_per_token": 2e-6},
        "claude-opus-5-5": {"input_cost_per_token": 4e-6},
    }
    expected_keys: dict[str, str | None] = {
        "gemini-3.8-flash-n": "gemini-3.8-flash",
        "gemini-3.8-flash-tiered": "gemini-3.8-flash",
        "gemini-4-argon": "gemini/gemini-4-argon",
        "gemini-4-argon-s": "gemini/gemini-4-argon",
        "gemini-4-argon-trial": "gemini/gemini-4-argon",
        "gemini-4-hydrogen": None,
        "gemini-4-hydrogen-xhigh": None,
        "claude-sonnet-5-5-medium": "claude-sonnet-5-5",
        "claude-sonnet-5-5-low": "claude-sonnet-5-5",
        "claude-opus-5-5-high": "claude-opus-5-5",
        "gpt-oss-120b-medium": None,
    }

    resolved = {
        raw: pricing._resolve_model_key(agy._normalize_model(raw), litellm_table)
        for raw in expected_keys
    }
    assert resolved == expected_keys

    expanded_table: pricing.PricingTable = {
        **litellm_table,
        "gemini/gemini-4-hydrogen": {"input_cost_per_token": 5e-6},
        "gpt-oss-120b": {"input_cost_per_token": 0.5e-6},
    }
    assert (
        pricing._resolve_model_key(agy._normalize_model("gemini-4-hydrogen-xhigh"), expanded_table)
        == "gemini/gemini-4-hydrogen"
    )
    assert (
        pricing._resolve_model_key(agy._normalize_model("gpt-oss-120b-medium"), expanded_table)
        == "gpt-oss-120b"
    )


def test_registry_includes_antigravity(monkeypatch: pytest.MonkeyPatch) -> None:
    info = AgentInfo("antigravity", "Antigravity", "~/.gemini", True)
    monkeypatch.setattr("adapters.registry.claude.detect", lambda: None)
    monkeypatch.setattr("adapters.registry.codex.detect", lambda: None)
    monkeypatch.setattr("adapters.registry.agy.detect", lambda: info)
    monkeypatch.setattr("adapters.registry.grok.detect", lambda: None)

    assert registry.detect_agents() == [info]


def test_thinking_tokens_are_included_in_output_cost(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "pricing_cache.json"
    legacy_path = tmp_path / "legacy_pricing_cache.json"
    monkeypatch.setattr(pricing, "CACHE_PATH", cache_path)
    monkeypatch.setattr(pricing, "DEFAULT_CACHE_PATH", cache_path)
    monkeypatch.setattr(pricing, "LEGACY_CACHE_PATH", legacy_path)
    monkeypatch.setattr(pricing, "DEFAULT_LEGACY_CACHE_PATH", legacy_path)
    monkeypatch.setattr(
        pricing,
        "get_pricing",
        lambda: {
            "gemini/gemini-4-argon": {
                "input_cost_per_token": 1e-6,
                "output_cost_per_token": 1e-5,
            }
        },
    )
    monkeypatch.setattr(pricing, "warm_up_pricing", lambda *args, **kwargs: None)
    pricing._set_pricing_cache_for_test(None)
    pricing._reset_pricing_warm_up_for_test()
    try:
        raw = agy_loader.AgyUsageEntry(
            timestamp=datetime(2026, 11, 13, tzinfo=UTC),
            model="gemini-4-argon-s",
            input_tokens=100,
            output_tokens=30,
            cache_read_tokens=0,
            thinking_tokens=5000,
            dedup_key="request-thinking",
            session_id="session-thinking",
            project="my-project",
        )
        usage_entry = agy._to_usage_entry(raw)

        assert usage_entry.output_tokens == 5030
        assert usage_entry.total_tokens == 5130
        assert pricing.calculate_cost(usage_entry) == pytest.approx(100 * 1e-6 + 5030 * 1e-5)
    finally:
        pricing._set_pricing_cache_for_test(None)
        pricing._reset_pricing_warm_up_for_test()

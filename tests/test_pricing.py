from __future__ import annotations

import json
import os
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import pytest

import pricing
from history_loader import UsageEntry


def _entry(
    *,
    model: str = "claude-sonnet",
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
    cost_usd: float | None = None,
) -> UsageEntry:
    return UsageEntry(
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        session_id="session",
        message_id="message",
        request_id="request",
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_tokens=cache_creation_tokens,
        cache_read_tokens=cache_read_tokens,
        cost_usd=cost_usd,
        project="project",
    )


def test_calculate_cost_returns_existing_cost() -> None:
    assert pricing.calculate_cost(_entry(cost_usd=1.23)) == 1.23


def test_calculate_cost_returns_zero_for_unknown_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pricing, "get_pricing", lambda: {"known": {"input_cost_per_token": 1.0}})

    assert pricing.calculate_cost(_entry(model="missing", input_tokens=100)) == 0.0


def test_calculate_cost_sums_all_token_types(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        pricing,
        "get_pricing",
        lambda: {
            "claude-sonnet": {
                "input_cost_per_token": 1.0,
                "output_cost_per_token": 2.0,
                "cache_creation_input_token_cost": 3.0,
                "cache_read_input_token_cost": 4.0,
            }
        },
    )

    assert (
        pricing.calculate_cost(
            _entry(
                model="claude-sonnet",
                input_tokens=1,
                output_tokens=2,
                cache_creation_tokens=3,
                cache_read_tokens=4,
            )
        )
        == 30.0
    )


def test_resolve_model_key_exact_match() -> None:
    assert pricing._resolve_model_key("model-a", {"model-a": {}}) == "model-a"


def test_resolve_model_key_substring_match_both_directions() -> None:
    pricing_table: pricing.PricingTable = {
        "claude-sonnet-4-6": {},
        "claude-opus": {},
    }

    assert pricing._resolve_model_key("sonnet-4", pricing_table) == "claude-sonnet-4-6"
    assert (
        pricing._resolve_model_key("anthropic/claude-opus-latest", pricing_table) == "claude-opus"
    )


def test_resolve_model_key_not_found() -> None:
    assert pricing._resolve_model_key("missing", {"known": {}}) is None


def test_normalize_pricing_rejects_non_dict_and_empty_dict() -> None:
    assert pricing._normalize_pricing(["not", "a", "dict"]) is None
    assert pricing._normalize_pricing({}) is None


def test_normalize_pricing_filters_invalid_models_and_values() -> None:
    assert pricing._normalize_pricing(
        {
            "not-a-dict": "bad",
            "empty-after-filtering": {"input_cost_per_token": "bad"},
            "valid": {
                "input_cost_per_token": 1,
                "output_cost_per_token": 2.5,
                "cache_creation_input_token_cost": None,
                "cache_read_input_token_cost": "bad",
            },
        }
    ) == {
        "valid": {
            "input_cost_per_token": 1.0,
            "output_cost_per_token": 2.5,
        }
    }


def test_fallback_pricing_contains_expected_models() -> None:
    fallback = pricing._fallback_pricing()

    assert "claude-opus-4-7" in fallback
    assert "claude-sonnet-4-6" in fallback
    assert "claude-haiku-4-5-20251001" in fallback


def test_read_cache_missing_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(pricing, "CACHE_PATH", tmp_path / "pricing_cache.json")

    assert pricing._read_cache() is None


def test_read_cache_expired(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cache_path = tmp_path / "pricing_cache.json"
    cache_path.write_text(json.dumps({"model": {"input_cost_per_token": 1.0}}), encoding="utf-8")
    expired = time.time() - ((pricing.CACHE_TTL_DAYS * 86400) + 1)
    os.utime(cache_path, (expired, expired))
    monkeypatch.setattr(pricing, "CACHE_PATH", cache_path)

    assert pricing._read_cache() is None


def test_read_cache_bad_json(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cache_path = tmp_path / "pricing_cache.json"
    cache_path.write_text("{bad json", encoding="utf-8")
    monkeypatch.setattr(pricing, "CACHE_PATH", cache_path)

    assert pricing._read_cache() is None


def test_read_cache_valid(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cache_path = tmp_path / "pricing_cache.json"
    cache_path.write_text(json.dumps({"model": {"input_cost_per_token": 1.0}}), encoding="utf-8")
    monkeypatch.setattr(pricing, "CACHE_PATH", cache_path)

    assert pricing._read_cache() == {"model": {"input_cost_per_token": 1.0}}


def test_load_pricing_falls_back_when_fetch_fails_without_real_network(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "pricing_cache.json"
    monkeypatch.setattr(pricing, "CACHE_PATH", cache_path)

    def fake_urlopen(request: object, timeout: int) -> object:
        _ = request, timeout
        raise OSError("offline")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    assert pricing._load_pricing() == pricing._fallback_pricing()


def test_write_cache_writes_json_atomically(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "pricing_cache.json"
    monkeypatch.setattr(pricing, "CACHE_PATH", cache_path)

    pricing._write_cache({"model": {"input_cost_per_token": 1.0}})

    assert json.loads(cache_path.read_text(encoding="utf-8")) == {
        "model": {"input_cost_per_token": 1.0}
    }
    assert list(tmp_path.glob("*.tmp")) == []

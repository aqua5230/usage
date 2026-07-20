# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.request
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

import pricing
from adapters.types import UsageEntry as AnalyzerUsageEntry
from history_loader import UsageEntry


@pytest.fixture(autouse=True)
def reset_pricing_state() -> Iterator[None]:
    pricing._set_pricing_cache_for_test(None)
    pricing._reset_pricing_warm_up_for_test()
    yield
    pricing._set_pricing_cache_for_test(None)
    pricing._reset_pricing_warm_up_for_test()


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


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
    monkeypatch.setattr(pricing, "warm_up_pricing", lambda on_ready=None, **kwargs: None)

    assert pricing.calculate_cost(_entry(model="missing", input_tokens=100)) == 0.0


def test_calculate_cost_triggers_pricing_refresh_for_unknown_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warm_up_calls = 0

    def fake_warm_up_pricing(on_ready: object = None, **kwargs: object) -> None:
        nonlocal warm_up_calls
        _ = on_ready, kwargs
        warm_up_calls += 1

    monkeypatch.setattr(pricing, "get_pricing", lambda: {"known": {"input_cost_per_token": 1.0}})
    monkeypatch.setattr(pricing, "warm_up_pricing", fake_warm_up_pricing)
    monkeypatch.setattr("pricing.time.monotonic", lambda: 1.0)

    assert pricing.calculate_cost(_entry(model="missing", input_tokens=100)) == 0.0
    assert warm_up_calls == 1


def test_unknown_model_pricing_refresh_is_debounced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warm_up_calls = 0
    now = 1_000.0

    def fake_warm_up_pricing(on_ready: object = None, **kwargs: object) -> None:
        nonlocal warm_up_calls
        _ = on_ready, kwargs
        warm_up_calls += 1

    monkeypatch.setattr(pricing, "get_pricing", lambda: {"known": {"input_cost_per_token": 1.0}})
    monkeypatch.setattr(pricing, "warm_up_pricing", fake_warm_up_pricing)
    monkeypatch.setattr("pricing.time.monotonic", lambda: now)

    assert pricing.calculate_cost(_entry(model="missing", input_tokens=100)) == 0.0
    assert pricing.calculate_cost(_entry(model="missing", input_tokens=100)) == 0.0
    now += pricing.FALLBACK_RETRY_SECONDS + 1
    assert pricing.calculate_cost(_entry(model="missing", input_tokens=100)) == 0.0
    assert warm_up_calls == 2


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


def test_calculate_cost_accepts_analyzer_usage_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        pricing,
        "get_pricing",
        lambda: {
            "claude-opus-4-7": {
                "input_cost_per_token": 15e-6,
                "output_cost_per_token": 75e-6,
            }
        },
    )
    entry = AnalyzerUsageEntry(
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        session_id="session",
        message_id="message",
        request_id="request",
        model="claude-opus-4-7",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cache_creation_tokens=0,
        cache_read_tokens=0,
        cost_usd=None,
        project="project",
        agent_id="claude-code",
    )

    assert pricing.calculate_cost(entry) == 90.0
    assert entry.cost_usd is None


def test_calculate_cost_recomputes_none_cost_when_pricing_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pricing_tables = [
        {
            "gpt-5": {
                "input_cost_per_token": 1.0,
                "output_cost_per_token": 2.0,
            }
        },
        {
            "gpt-5": {
                "input_cost_per_token": 3.0,
                "output_cost_per_token": 4.0,
            }
        },
    ]
    monkeypatch.setattr(pricing, "get_pricing", lambda: pricing_tables.pop(0))
    entry = _entry(model="gpt-5", input_tokens=1, output_tokens=1, cost_usd=None)

    assert pricing.calculate_cost(entry) == 3.0
    assert entry.cost_usd is None
    assert pricing.calculate_cost(entry) == 7.0
    assert entry.cost_usd is None


def test_resolve_model_key_exact_match() -> None:
    assert pricing._resolve_model_key("model-a", {"model-a": {}}) == "model-a"


def test_resolve_model_key_strips_provider_prefix_before_exact_match() -> None:
    pricing_table: pricing.PricingTable = {
        "gpt-5": {},
    }

    assert pricing._resolve_model_key("openai/gpt-5", pricing_table) == "gpt-5"


def test_resolve_model_key_strips_date_suffix_before_exact_match() -> None:
    pricing_table: pricing.PricingTable = {
        "gpt-4o": {},
    }

    assert pricing._resolve_model_key("gpt-4o-2024-05-13", pricing_table) == "gpt-4o"
    assert pricing._resolve_model_key("gpt-4o-20240513", pricing_table) == "gpt-4o"


def test_resolve_model_key_uses_strict_prefix_match_deterministically() -> None:
    pricing_table: pricing.PricingTable = {
        "gpt-5-mini": {},
        "gpt-5-pro": {},
    }

    assert pricing._resolve_model_key("openai/gpt-5", pricing_table) == "gpt-5-pro"


def test_resolve_model_key_does_not_match_partial_token_prefix() -> None:
    pricing_table: pricing.PricingTable = {
        "gpt-4o-mini": {},
    }

    assert pricing._resolve_model_key("gpt-4", pricing_table) is None


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
    assert "claude-sonnet-5" in fallback
    assert "claude-haiku-4-5-20251001" in fallback
    assert fallback["claude-opus-4-6"] == {
        "input_cost_per_token": 15e-6,
        "output_cost_per_token": 75e-6,
        "cache_creation_input_token_cost": 18.75e-6,
        "cache_read_input_token_cost": 1.5e-6,
    }
    assert fallback["claude-opus-4-7"] == {
        "input_cost_per_token": 15e-6,
        "output_cost_per_token": 75e-6,
        "cache_creation_input_token_cost": 18.75e-6,
        "cache_read_input_token_cost": 1.5e-6,
    }
    assert fallback["claude-sonnet-5"] == {
        "input_cost_per_token": 2e-6,
        "output_cost_per_token": 10e-6,
        "cache_creation_input_token_cost": 2.5e-6,
        "cache_read_input_token_cost": 0.2e-6,
    }


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


def test_read_cache_allows_expired_when_stale_allowed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cache_path = tmp_path / "pricing_cache.json"
    cache_path.write_text(json.dumps({"model": {"input_cost_per_token": 1.0}}), encoding="utf-8")
    expired = time.time() - ((pricing.CACHE_TTL_DAYS * 86400) + 1)
    os.utime(cache_path, (expired, expired))
    monkeypatch.setattr(pricing, "CACHE_PATH", cache_path)

    assert pricing._read_cache(allow_stale=True) == {"model": {"input_cost_per_token": 1.0}}


def test_read_cache_bad_json(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cache_path = tmp_path / "pricing_cache.json"
    cache_path.write_text("{bad json", encoding="utf-8")
    monkeypatch.setattr(pricing, "CACHE_PATH", cache_path)

    assert pricing._read_cache() is None


def test_read_cache_logs_bad_json_in_debug_mode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    cache_path = tmp_path / "pricing_cache.json"
    cache_path.write_text("{bad json", encoding="utf-8")
    monkeypatch.setattr(pricing, "CACHE_PATH", cache_path)
    monkeypatch.setenv("USAGE_DEBUG", "1")

    with caplog.at_level(logging.WARNING):
        assert pricing._read_cache() is None

    assert f"failed to decode pricing cache {cache_path}" in caplog.text


def test_read_cache_logs_bad_utf8_in_debug_mode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    cache_path = tmp_path / "pricing_cache.json"
    cache_path.write_bytes(b"\xff")
    monkeypatch.setattr(pricing, "CACHE_PATH", cache_path)
    monkeypatch.setenv("USAGE_DEBUG", "1")

    with caplog.at_level(logging.WARNING):
        assert pricing._read_cache() is None

    assert f"failed to decode pricing cache {cache_path}" in caplog.text


def test_read_cache_valid(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cache_path = tmp_path / "pricing_cache.json"
    cache_path.write_text(json.dumps({"model": {"input_cost_per_token": 1.0}}), encoding="utf-8")
    monkeypatch.setattr(pricing, "CACHE_PATH", cache_path)

    assert pricing._read_cache() == {"model": {"input_cost_per_token": 1.0}}


def test_read_cache_uses_legacy_claude_path_when_new_cache_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    legacy_cache = tmp_path / ".claude" / "pricing_cache.json"
    legacy_cache.parent.mkdir()
    legacy_cache.write_text(
        json.dumps({"legacy-model": {"input_cost_per_token": 1.0}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(pricing, "CACHE_PATH", tmp_path / ".usage" / "pricing_cache.json")
    monkeypatch.setattr(pricing, "LEGACY_CACHE_PATH", legacy_cache)

    assert pricing._read_cache() == {"legacy-model": {"input_cost_per_token": 1.0}}


def test_load_pricing_falls_back_without_fetching(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "pricing_cache.json"
    monkeypatch.setattr(pricing, "CACHE_PATH", cache_path)
    fetch_calls = 0

    def fake_fetch_pricing() -> pricing.PricingTable | None:
        nonlocal fetch_calls
        fetch_calls += 1
        return None

    monkeypatch.setattr(pricing, "_fetch_pricing", fake_fetch_pricing)

    assert pricing._load_pricing() == pricing._fallback_pricing()
    assert fetch_calls == 0


def test_fetch_pricing_returns_none_for_bad_utf8_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", lambda request, timeout: FakeResponse(b"\xff"))

    assert pricing._fetch_pricing() is None


def test_load_pricing_uses_fresh_cache_without_fetching(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cached = {"cached-model": {"input_cost_per_token": 1.0}}
    fetch_calls = 0

    def fake_fetch_pricing() -> pricing.PricingTable | None:
        nonlocal fetch_calls
        fetch_calls += 1
        return None

    monkeypatch.setattr(pricing, "_read_cache", lambda *, allow_stale=False: cached)
    monkeypatch.setattr(pricing, "_fetch_pricing", fake_fetch_pricing)

    assert pricing._load_pricing_with_source() == (cached, "cache")
    assert fetch_calls == 0


def test_warm_up_pricing_fetches_writes_updates_cache_and_notifies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetched = {"fetched-model": {"input_cost_per_token": 2.0}}
    writes: list[pricing.PricingTable] = []
    ready = threading.Event()

    monkeypatch.setattr(pricing, "_read_cache", lambda *, allow_stale=False: None)
    monkeypatch.setattr(pricing, "_fetch_pricing", lambda: fetched)
    monkeypatch.setattr(pricing, "_write_cache", writes.append)
    monkeypatch.setattr("pricing.time.monotonic", lambda: 1_000.0)

    pricing.warm_up_pricing(ready.set)

    assert ready.wait(timeout=1)
    assert writes == [fetched]
    assert pricing._get_pricing_cache_for_test() == (fetched, "fetched", 1_000.0)


def test_warm_up_pricing_skips_fetch_for_fresh_disk_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cached = {"cached-model": {"input_cost_per_token": 1.0}}
    fetch_calls = 0

    def fake_fetch_pricing() -> pricing.PricingTable | None:
        nonlocal fetch_calls
        fetch_calls += 1
        return None

    monkeypatch.setattr(
        pricing,
        "_load_pricing_with_source",
        lambda: (cached, "cache"),
    )
    monkeypatch.setattr(pricing, "_fetch_pricing", fake_fetch_pricing)
    monkeypatch.setattr("pricing.time.monotonic", lambda: 1_000.0)

    pricing._warm_up_pricing_worker(None, False)

    assert fetch_calls == 0


def test_warm_up_pricing_fetches_when_disk_cache_is_expired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cached = {"cached-model": {"input_cost_per_token": 1.0}}
    fetched = {"fetched-model": {"input_cost_per_token": 2.0}}
    fetch_calls = 0

    def fake_fetch_pricing() -> pricing.PricingTable | None:
        nonlocal fetch_calls
        fetch_calls += 1
        return fetched

    pricing._set_pricing_cache_for_test(
        (cached, "cache", 1_000.0 - pricing.CACHE_TTL_DAYS * 86400 - 1),
    )
    monkeypatch.setattr(pricing, "_fetch_pricing", fake_fetch_pricing)
    monkeypatch.setattr(pricing, "_write_cache", lambda table: None)
    monkeypatch.setattr("pricing.time.monotonic", lambda: 1_000.0)

    pricing._warm_up_pricing_worker(None, False)

    assert fetch_calls == 1


def test_load_pricing_uses_stale_cache_without_fetching(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stale = {"stale-model": {"input_cost_per_token": 3.0}}
    fetch_calls = 0

    def fake_read_cache(*, allow_stale: bool = False) -> pricing.PricingTable | None:
        return stale if allow_stale else None

    def fake_fetch_pricing() -> pricing.PricingTable | None:
        nonlocal fetch_calls
        fetch_calls += 1
        return None

    monkeypatch.setattr(pricing, "_read_cache", fake_read_cache)
    monkeypatch.setattr(pricing, "_fetch_pricing", fake_fetch_pricing)
    monkeypatch.setattr(
        pricing,
        "_fallback_pricing",
        lambda: {"fallback-model": {"input_cost_per_token": 4.0}},
    )

    assert pricing._load_pricing_with_source() == (stale, "stale")
    assert fetch_calls == 0


def test_load_pricing_uses_fallback_when_cache_and_fetch_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fallback = {"fallback-model": {"input_cost_per_token": 4.0}}

    monkeypatch.setattr(pricing, "_read_cache", lambda *, allow_stale=False: None)
    monkeypatch.setattr(pricing, "_fetch_pricing", lambda: None)
    monkeypatch.setattr(pricing, "_fallback_pricing", lambda: fallback)

    assert pricing._load_pricing_with_source() == (fallback, "fallback")


def test_get_pricing_reuses_fallback_within_retry_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 1_000.0
    warm_up_calls = 0
    fallback = {"fallback-model": {"input_cost_per_token": 1.0}}

    def fake_warm_up_pricing(on_ready: object = None) -> None:
        nonlocal warm_up_calls
        _ = on_ready
        warm_up_calls += 1

    pricing._set_pricing_cache_for_test(None)
    monkeypatch.setattr(pricing, "_read_cache", lambda *, allow_stale=False: None)
    monkeypatch.setattr(pricing, "warm_up_pricing", fake_warm_up_pricing)
    monkeypatch.setattr(pricing, "_fallback_pricing", lambda: fallback)
    monkeypatch.setattr("pricing.time.monotonic", lambda: now)
    monkeypatch.setattr(pricing, "FALLBACK_RETRY_SECONDS", 600)

    assert pricing.get_pricing() == fallback
    now += 599
    assert pricing.get_pricing() == fallback
    assert warm_up_calls == 1
    assert pricing._get_pricing_cache_for_test() == (fallback, "fallback", 1_000.0)


def test_get_pricing_without_cache_returns_fallback_without_fetching(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fallback = {"fallback-model": {"input_cost_per_token": 1.0}}
    fetch_calls = 0
    warm_up_calls = 0

    def fake_fetch_pricing() -> pricing.PricingTable | None:
        nonlocal fetch_calls
        fetch_calls += 1
        return {"fetched-model": {"input_cost_per_token": 2.0}}

    def fake_warm_up_pricing(on_ready: object = None) -> None:
        nonlocal warm_up_calls
        _ = on_ready
        warm_up_calls += 1

    monkeypatch.setattr(pricing, "_read_cache", lambda *, allow_stale=False: None)
    monkeypatch.setattr(pricing, "_fetch_pricing", fake_fetch_pricing)
    monkeypatch.setattr(pricing, "_fallback_pricing", lambda: fallback)
    monkeypatch.setattr(pricing, "warm_up_pricing", fake_warm_up_pricing)

    assert pricing.get_pricing() == fallback
    assert fetch_calls == 0
    assert warm_up_calls == 1


def test_get_pricing_with_stale_cache_triggers_warm_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 1_000.0
    stale = {"stale-model": {"input_cost_per_token": 3.0}}
    warm_up_calls = 0

    def fake_read_cache(*, allow_stale: bool = False) -> pricing.PricingTable | None:
        return stale if allow_stale else None

    def fake_warm_up_pricing(on_ready: object = None) -> None:
        nonlocal warm_up_calls
        _ = on_ready
        warm_up_calls += 1

    monkeypatch.setattr(pricing, "_read_cache", fake_read_cache)
    monkeypatch.setattr(pricing, "warm_up_pricing", fake_warm_up_pricing)
    monkeypatch.setattr("pricing.time.monotonic", lambda: now)

    assert pricing.get_pricing() == stale
    assert warm_up_calls == 1
    assert pricing._get_pricing_cache_for_test() == (stale, "stale", 1_000.0)


def test_warm_up_pricing_deduplicates_concurrent_and_reentrant_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetched = {"fetched-model": {"input_cost_per_token": 2.0}}
    fetch_started = threading.Event()
    release_fetch = threading.Event()
    ready = threading.Event()
    fetch_calls = 0
    ready_calls = 0

    def fake_fetch_pricing() -> pricing.PricingTable | None:
        nonlocal fetch_calls
        fetch_calls += 1
        fetch_started.set()
        assert release_fetch.wait(timeout=1)
        return fetched

    def on_ready() -> None:
        nonlocal ready_calls
        ready_calls += 1
        pricing.warm_up_pricing()
        ready.set()

    monkeypatch.setattr(pricing, "_fetch_pricing", fake_fetch_pricing)
    monkeypatch.setattr(pricing, "_write_cache", lambda table: None)
    monkeypatch.setattr(pricing, "_read_cache", lambda *, allow_stale=False: None)

    pricing.warm_up_pricing(on_ready)
    assert fetch_started.wait(timeout=1)

    for _ in range(5):
        pricing.warm_up_pricing()

    release_fetch.set()

    assert ready.wait(timeout=1)
    assert fetch_calls == 1
    assert ready_calls == 1
    cached = pricing._get_pricing_cache_for_test()
    assert cached is not None
    assert cached[0] == fetched


def test_get_pricing_triggers_warm_up_after_fallback_retry_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 1_000.0
    fallback = {"fallback-model": {"input_cost_per_token": 1.0}}
    warm_up_calls = 0

    def fake_warm_up_pricing(on_ready: object = None) -> None:
        nonlocal warm_up_calls
        _ = on_ready
        warm_up_calls += 1

    pricing._set_pricing_cache_for_test(None)
    monkeypatch.setattr(pricing, "_read_cache", lambda *, allow_stale=False: None)
    monkeypatch.setattr(pricing, "warm_up_pricing", fake_warm_up_pricing)
    monkeypatch.setattr(pricing, "_fallback_pricing", lambda: fallback)
    monkeypatch.setattr("pricing.time.monotonic", lambda: now)
    monkeypatch.setattr(pricing, "FALLBACK_RETRY_SECONDS", 600)

    assert pricing.get_pricing() == fallback
    now += 601
    assert pricing.get_pricing() == fallback
    assert warm_up_calls == 2
    assert pricing._get_pricing_cache_for_test() == (fallback, "fallback", 1_000.0)


def test_get_pricing_retries_fallback_after_monotonic_ttl_when_wall_clock_moves_backward(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monotonic_now = 1_000.0
    wall_clock_now = 5_000.0
    fallback = {"fallback-model": {"input_cost_per_token": 1.0}}
    warm_up_calls = 0

    def fake_warm_up_pricing(on_ready: object = None) -> None:
        nonlocal warm_up_calls
        _ = on_ready
        warm_up_calls += 1

    pricing._set_pricing_cache_for_test(None)
    monkeypatch.setattr(pricing, "_read_cache", lambda *, allow_stale=False: None)
    monkeypatch.setattr(pricing, "warm_up_pricing", fake_warm_up_pricing)
    monkeypatch.setattr(pricing, "_fallback_pricing", lambda: fallback)
    monkeypatch.setattr("pricing.time.monotonic", lambda: monotonic_now)
    monkeypatch.setattr("pricing.time.time", lambda: wall_clock_now)
    monkeypatch.setattr(pricing, "FALLBACK_RETRY_SECONDS", 600)

    assert pricing.get_pricing() == fallback
    monotonic_now += 601
    wall_clock_now -= 4_000
    assert pricing.get_pricing() == fallback
    assert warm_up_calls == 2
    assert pricing._get_pricing_cache_for_test() == (fallback, "fallback", 1_000.0)


def test_get_pricing_keeps_fetched_result_after_retry_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 1_000.0
    fetched = {"fetched-model": {"input_cost_per_token": 2.0}}
    load_calls = 0

    def fake_load_pricing_with_source() -> tuple[pricing.PricingTable, pricing.PricingSource]:
        nonlocal load_calls
        load_calls += 1
        return fetched, "fetched"

    pricing._set_pricing_cache_for_test(None)
    monkeypatch.setattr(pricing, "_read_cache", lambda: None)
    monkeypatch.setattr(pricing, "_load_pricing_with_source", fake_load_pricing_with_source)
    monkeypatch.setattr(pricing, "_write_cache", lambda table: None)
    monkeypatch.setattr("pricing.time.monotonic", lambda: now)
    monkeypatch.setattr(pricing, "FALLBACK_RETRY_SECONDS", 600)

    assert pricing.get_pricing() == fetched
    now += 601
    assert pricing.get_pricing() == fetched
    assert load_calls == 1
    assert pricing._get_pricing_cache_for_test() == (fetched, "fetched", 1_000.0)


def test_get_pricing_keeps_cache_result_after_retry_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 1_000.0
    cached = {"cached-model": {"input_cost_per_token": 3.0}}
    fetch_calls = 0

    def fake_fetch_pricing() -> pricing.PricingTable | None:
        nonlocal fetch_calls
        fetch_calls += 1
        return None

    pricing._set_pricing_cache_for_test(None)
    monkeypatch.setattr(pricing, "_read_cache", lambda: cached)
    monkeypatch.setattr(pricing, "_fetch_pricing", fake_fetch_pricing)
    monkeypatch.setattr("pricing.time.monotonic", lambda: now)
    monkeypatch.setattr(pricing, "FALLBACK_RETRY_SECONDS", 600)

    assert pricing.get_pricing() == cached
    now += 601
    assert pricing.get_pricing() == cached
    assert fetch_calls == 0
    assert pricing._get_pricing_cache_for_test() == (cached, "cache", 1_000.0)


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


def test_is_model_priced_returns_true_for_known_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """is_model_priced returns True for models in pricing table."""
    pricing_table = {
        "claude-opus-4-8": {"input_cost_per_token": 15e-6},
        "gpt-4": {"input_cost_per_token": 30e-6},
    }
    pricing._set_pricing_cache_for_test((pricing_table, "cache", 0.0))

    assert pricing.is_model_priced("claude-opus-4-8") is True
    assert pricing.is_model_priced("gpt-4") is True


def test_is_model_priced_returns_false_for_unknown_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """is_model_priced returns False for models not in pricing table."""
    pricing_table = {
        "claude-opus-4-8": {"input_cost_per_token": 15e-6},
    }
    pricing._set_pricing_cache_for_test((pricing_table, "cache", 0.0))
    monkeypatch.setattr(pricing, "warm_up_pricing", lambda on_ready=None, **kwargs: None)

    assert pricing.is_model_priced("glm-5.2") is False
    assert pricing.is_model_priced("unknown-model") is False


def test_missing_model_resolution_is_memoized_per_pricing_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pricing_table = {
        "claude-opus-4-8": {"input_cost_per_token": 15e-6},
    }
    resolve_calls = 0

    original_resolve_model_key = pricing._resolve_model_key

    def counted_resolve_model_key(model: str, table: pricing.PricingTable) -> str | None:
        nonlocal resolve_calls
        resolve_calls += 1
        return original_resolve_model_key(model, table)

    pricing._set_pricing_cache_for_test((pricing_table, "cache", 0.0))
    monkeypatch.setattr(pricing, "_resolve_model_key", counted_resolve_model_key)
    monkeypatch.setattr(pricing, "warm_up_pricing", lambda on_ready=None, **kwargs: None)

    missing_entry = _entry(model="glm-5.2", input_tokens=100)

    assert pricing.calculate_cost(missing_entry) == 0.0
    assert pricing.calculate_cost(missing_entry) == 0.0
    assert pricing.is_model_priced("glm-5.2") is False
    assert pricing.is_model_priced("glm-5.2") is False
    assert resolve_calls == 1


def test_missing_model_resolution_rechecks_after_pricing_object_replaced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pricing_table = {
        "claude-opus-4-8": {"input_cost_per_token": 15e-6},
    }
    replacement_pricing_table = {
        "glm-5.2": {"input_cost_per_token": 1.0},
    }
    resolve_calls = 0

    original_resolve_model_key = pricing._resolve_model_key

    def counted_resolve_model_key(model: str, table: pricing.PricingTable) -> str | None:
        nonlocal resolve_calls
        resolve_calls += 1
        return original_resolve_model_key(model, table)

    monkeypatch.setattr(pricing, "_resolve_model_key", counted_resolve_model_key)
    monkeypatch.setattr(pricing, "warm_up_pricing", lambda on_ready=None, **kwargs: None)

    pricing._set_pricing_cache_for_test((pricing_table, "cache", 0.0))
    assert pricing.calculate_cost(_entry(model="glm-5.2", input_tokens=100)) == 0.0
    assert pricing.is_model_priced("glm-5.2") is False
    assert resolve_calls == 1

    pricing._set_pricing_cache_for_test((replacement_pricing_table, "cache", 0.0))
    assert pricing.is_model_priced("glm-5.2") is True
    assert pricing.calculate_cost(_entry(model="glm-5.2", input_tokens=2)) == 2.0
    assert resolve_calls == 2

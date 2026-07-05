# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import tempfile
import threading
import time
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, Protocol

logger = logging.getLogger(__name__)

LITELLM_PRICING_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
)
DEFAULT_CACHE_PATH = Path(os.path.expanduser("~/.usage/pricing_cache.json"))
DEFAULT_LEGACY_CACHE_PATH = Path(os.path.expanduser("~/.claude/pricing_cache.json"))
CACHE_PATH = DEFAULT_CACHE_PATH
LEGACY_CACHE_PATH = DEFAULT_LEGACY_CACHE_PATH
CACHE_TTL_DAYS = 7
FALLBACK_RETRY_SECONDS = 600
MISSING_MODEL_REFRESH_SECONDS = FALLBACK_RETRY_SECONDS
USER_AGENT = "usage/0.9"
PROVIDER_PREFIXES = (
    "openai/",
    "anthropic/",
    "bedrock/",
    "azure/",
    "vertex_ai/",
    "vertex/",
    "google/",
)
DATE_SUFFIX_RE = re.compile(r"-(?:\d{8}|\d{4}-\d{2}-\d{2})$")

PricingTable = dict[str, dict[str, float]]
PricingSource = Literal["cache", "stale", "fetched", "fallback"]

_pricing_cache: tuple[PricingTable, PricingSource, float] | None = None
_pricing_cache_lock = threading.Lock()
_pricing_warm_up_in_progress = False
_pricing_miss_refresh_at: float | None = None
_pricing_miss_refresh_lock = threading.Lock()
_model_key_cache_lock = threading.Lock()
_model_key_cache: dict[int, tuple[PricingTable, dict[str, str | None]]] = {}


class _CostEntry(Protocol):
    model: str
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    cost_usd: float | None


def calculate_cost(entry: _CostEntry) -> float:
    if entry.cost_usd is not None:
        return entry.cost_usd

    pricing = get_pricing()
    model_key = _resolve_model_key_cached(entry.model, pricing)
    if model_key is None:
        _request_pricing_refresh_for_missing_model()
        return 0.0

    model_pricing = pricing[model_key]
    input_cost = model_pricing.get("input_cost_per_token", 0.0)
    output_cost = model_pricing.get("output_cost_per_token", 0.0)
    cache_creation_cost = model_pricing.get(
        "cache_creation_input_token_cost",
        input_cost * 1.25,
    )
    cache_read_cost = model_pricing.get("cache_read_input_token_cost", input_cost * 0.1)

    cost = (
        entry.input_tokens * input_cost
        + entry.output_tokens * output_cost
        + entry.cache_creation_tokens * cache_creation_cost
        + entry.cache_read_tokens * cache_read_cost
    )
    return cost


def is_model_priced(model: str) -> bool:
    """Check if a model has pricing information available."""
    pricing = get_pricing()
    model_key = _resolve_model_key_cached(model, pricing)
    if model_key is None:
        _request_pricing_refresh_for_missing_model()
        return False
    return True


def _resolve_model_key_cached(model: str, pricing: PricingTable) -> str | None:
    with _model_key_cache_lock:
        per_table_cache = _model_key_cache.get(id(pricing))
        if per_table_cache is None or per_table_cache[0] is not pricing:
            model_cache: dict[str, str | None] = {}
            _model_key_cache[id(pricing)] = (pricing, model_cache)
        else:
            model_cache = per_table_cache[1]

        if model in model_cache:
            return model_cache[model]

        resolved = _resolve_model_key(model, pricing)
        model_cache[model] = resolved
        return resolved


def get_pricing() -> PricingTable:
    global _pricing_cache
    now = time.monotonic()
    with _pricing_cache_lock:
        cached_entry = _pricing_cache
    if cached_entry is not None:
        pricing, source, cached_at = cached_entry
        if _memory_cache_is_fresh(source, cached_at, now):
            return pricing
        warm_up_pricing()
        return pricing

    pricing, source = _load_pricing_with_source()
    with _pricing_cache_lock:
        _pricing_cache = (pricing, source, now)
    if source in {"stale", "fallback"}:
        warm_up_pricing()
    return pricing


def _memory_cache_is_fresh(source: PricingSource, cached_at: float, now: float) -> bool:
    if source == "fallback":
        return (now - cached_at) <= FALLBACK_RETRY_SECONDS
    if source == "stale":
        return False
    return (now - cached_at) <= CACHE_TTL_DAYS * 86400


def warm_up_pricing(on_ready: Callable[[], None] | None = None) -> None:
    global _pricing_warm_up_in_progress
    with _pricing_cache_lock:
        if _pricing_warm_up_in_progress:
            return
        _pricing_warm_up_in_progress = True

    thread = threading.Thread(target=_warm_up_pricing_worker, args=(on_ready,), daemon=True)
    thread.start()


def _warm_up_pricing_worker(on_ready: Callable[[], None] | None) -> None:
    global _pricing_cache, _pricing_warm_up_in_progress
    try:
        with _pricing_cache_lock:
            baseline = _pricing_cache
        if baseline is None:
            baseline_pricing, baseline_source = _load_pricing_with_source()
            baseline = (baseline_pricing, baseline_source, time.monotonic())

        fetched = _fetch_pricing()
        if not fetched:
            return

        _write_cache(fetched)
        now = time.monotonic()
        with _pricing_cache_lock:
            previous = _pricing_cache or baseline
            pricing, source, _ = previous
            should_notify = source in {"stale", "fallback"} or pricing != fetched
            _pricing_cache = (fetched, "fetched", now)

        if should_notify and on_ready is not None:
            on_ready()
    except Exception:
        if os.environ.get("USAGE_DEBUG") == "1":
            logger.warning("failed to warm up pricing", exc_info=True)
    finally:
        with _pricing_cache_lock:
            _pricing_warm_up_in_progress = False


def _set_pricing_cache_for_test(
    value: tuple[PricingTable, PricingSource, float] | None,
) -> None:
    global _pricing_cache
    with _pricing_cache_lock:
        _pricing_cache = value


def _get_pricing_cache_for_test() -> tuple[PricingTable, PricingSource, float] | None:
    with _pricing_cache_lock:
        return _pricing_cache


def _reset_pricing_warm_up_for_test() -> None:
    global _pricing_warm_up_in_progress, _pricing_miss_refresh_at
    with _pricing_cache_lock:
        _pricing_warm_up_in_progress = False
    with _pricing_miss_refresh_lock:
        _pricing_miss_refresh_at = None


def _load_pricing() -> PricingTable:
    pricing, _ = _load_pricing_with_source()
    return pricing


def _load_pricing_with_source() -> tuple[PricingTable, PricingSource]:
    cached = _read_cache()
    if cached:
        return cached, "cache"

    stale_cached = _read_cache(allow_stale=True)
    if stale_cached:
        return stale_cached, "stale"

    return _fallback_pricing(), "fallback"


def _read_cache(*, allow_stale: bool = False) -> PricingTable | None:
    use_legacy = CACHE_PATH == DEFAULT_CACHE_PATH or LEGACY_CACHE_PATH != DEFAULT_LEGACY_CACHE_PATH
    path = CACHE_PATH if CACHE_PATH.exists() or not use_legacy else LEGACY_CACHE_PATH
    cache_mtime: float | None = None
    with contextlib.suppress(OSError):
        cache_mtime = path.stat().st_mtime
    if cache_mtime is None:
        return None
    if not allow_stale and (time.time() - cache_mtime) > CACHE_TTL_DAYS * 86400:
        return None

    with contextlib.suppress(OSError), path.open(encoding="utf-8") as file:
        try:
            return _normalize_pricing(json.load(file))
        except (UnicodeDecodeError, json.JSONDecodeError):
            if os.environ.get("USAGE_DEBUG") == "1":
                logger.warning("failed to decode pricing cache %s", path, exc_info=True)
            return None
    return None


def _fetch_pricing() -> PricingTable | None:
    request = urllib.request.Request(LITELLM_PRICING_URL, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TimeoutError):
        if os.environ.get("USAGE_DEBUG") == "1":
            logger.warning("failed to fetch pricing from %s", LITELLM_PRICING_URL, exc_info=True)
        return None
    return _normalize_pricing(payload)


def _write_cache(pricing: PricingTable) -> None:
    tmp_path: str | None = None
    try:
        with contextlib.suppress(OSError):
            CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=CACHE_PATH.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(pricing, file, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp_path, CACHE_PATH)
        tmp_path = None
    except OSError as exc:
        logger.warning("failed to write pricing cache: %s", exc)
        return
    finally:
        if tmp_path and os.path.exists(tmp_path):
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)


def _normalize_pricing(payload: Any) -> PricingTable | None:
    if not isinstance(payload, dict):
        return None

    pricing: PricingTable = {}
    for model, raw_info in payload.items():
        if not isinstance(model, str) or not isinstance(raw_info, dict):
            continue

        info: dict[str, float] = {}
        for key in (
            "input_cost_per_token",
            "output_cost_per_token",
            "cache_creation_input_token_cost",
            "cache_read_input_token_cost",
        ):
            value = raw_info.get(key)
            if isinstance(value, int | float):
                info[key] = float(value)

        if info:
            pricing[model] = info

    return pricing or None


def _resolve_model_key(model: str, pricing: PricingTable) -> str | None:
    if model in pricing:
        return model

    normalized = _normalize_model_name(model)
    if normalized in pricing:
        return normalized

    prefix_matches = [
        key
        for key in pricing
        if key.startswith(normalized)
        and (len(key) == len(normalized) or key[len(normalized)] == "-")
    ]
    if prefix_matches:
        return sorted(prefix_matches, key=lambda key: (len(key), key))[0]

    logger.debug("pricing: no match for model=%s", model)
    return None


def _normalize_model_name(model: str) -> str:
    normalized = model.strip().lower()
    for prefix in PROVIDER_PREFIXES:
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
            break
    return DATE_SUFFIX_RE.sub("", normalized)


def _fallback_pricing() -> PricingTable:
    return {
        "claude-opus-4-6": {
            "input_cost_per_token": 15e-6,
            "output_cost_per_token": 75e-6,
            "cache_creation_input_token_cost": 18.75e-6,
            "cache_read_input_token_cost": 1.5e-6,
        },
        "claude-opus-4-7": {
            "input_cost_per_token": 15e-6,
            "output_cost_per_token": 75e-6,
            "cache_creation_input_token_cost": 18.75e-6,
            "cache_read_input_token_cost": 1.5e-6,
        },
        "claude-sonnet-4-6": {
            "input_cost_per_token": 3e-6,
            "output_cost_per_token": 15e-6,
            "cache_creation_input_token_cost": 3.75e-6,
            "cache_read_input_token_cost": 0.3e-6,
        },
        "claude-sonnet-5": {
            "input_cost_per_token": 2e-6,
            "output_cost_per_token": 10e-6,
            "cache_creation_input_token_cost": 2.5e-6,
            "cache_read_input_token_cost": 0.2e-6,
        },
        "claude-haiku-4-5-20251001": {
            "input_cost_per_token": 0.8e-6,
            "output_cost_per_token": 4e-6,
            "cache_creation_input_token_cost": 1e-6,
            "cache_read_input_token_cost": 0.08e-6,
        },
    }


def _request_pricing_refresh_for_missing_model() -> None:
    global _pricing_miss_refresh_at
    now = time.monotonic()
    with _pricing_miss_refresh_lock:
        if (
            _pricing_miss_refresh_at is not None
            and (now - _pricing_miss_refresh_at) < MISSING_MODEL_REFRESH_SECONDS
        ):
            return
        _pricing_miss_refresh_at = now
    warm_up_pricing()

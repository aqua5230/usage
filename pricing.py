from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any

from history_loader import UsageEntry

logger = logging.getLogger(__name__)

LITELLM_PRICING_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
)
CACHE_PATH = Path(os.path.expanduser("~/.claude/pricing_cache.json"))
CACHE_TTL_DAYS = 7
USER_AGENT = "usage/0.2"

PricingTable = dict[str, dict[str, float]]

_pricing_cache: PricingTable | None = None


def calculate_cost(entry: UsageEntry) -> float:
    if entry.cost_usd is not None:
        return entry.cost_usd

    pricing = get_pricing()
    model_key = _resolve_model_key(entry.model, pricing)
    if model_key is None:
        return 0.0

    model_pricing = pricing[model_key]
    input_cost = model_pricing.get("input_cost_per_token", 0.0)
    output_cost = model_pricing.get("output_cost_per_token", 0.0)
    cache_creation_cost = model_pricing.get(
        "cache_creation_input_token_cost",
        input_cost * 1.25,
    )
    cache_read_cost = model_pricing.get("cache_read_input_token_cost", input_cost * 0.1)

    return (
        entry.input_tokens * input_cost
        + entry.output_tokens * output_cost
        + entry.cache_creation_tokens * cache_creation_cost
        + entry.cache_read_tokens * cache_read_cost
    )


def get_pricing() -> PricingTable:
    global _pricing_cache
    if _pricing_cache is None:
        _pricing_cache = _load_pricing()
    return _pricing_cache


def _load_pricing() -> PricingTable:
    cached = _read_cache()
    if cached:
        return cached

    fetched = _fetch_pricing()
    if fetched:
        _write_cache(fetched)
        return fetched

    return _fallback_pricing()


def _read_cache() -> PricingTable | None:
    cache_mtime: float | None = None
    with contextlib.suppress(OSError):
        cache_mtime = CACHE_PATH.stat().st_mtime
    if cache_mtime is None:
        return None
    if (time.time() - cache_mtime) > CACHE_TTL_DAYS * 86400:
        return None

    with contextlib.suppress(OSError), CACHE_PATH.open(encoding="utf-8") as file:
        try:
            return _normalize_pricing(json.load(file))
        except json.JSONDecodeError:
            return None
    return None


def _fetch_pricing() -> PricingTable | None:
    request = urllib.request.Request(LITELLM_PRICING_URL, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, json.JSONDecodeError, TimeoutError):
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

    model_lower = model.lower()
    for key in pricing:
        key_lower = key.lower()
        if model_lower in key_lower or key_lower in model_lower:
            return key

    return None


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
        "claude-haiku-4-5-20251001": {
            "input_cost_per_token": 0.8e-6,
            "output_cost_per_token": 4e-6,
            "cache_creation_input_token_cost": 1e-6,
            "cache_read_input_token_cost": 0.08e-6,
        },
    }

#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Compare fallback prices with LiteLLM; run once before each release."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pricing  # noqa: E402

PRICE_FIELDS = (
    "input_cost_per_token",
    "output_cost_per_token",
    "cache_creation_input_token_cost",
    "cache_read_input_token_cost",
)
MAINSTREAM_CLAUDE_RE = re.compile(r"^claude-(?:opus|sonnet|haiku|fable)-(?:4|5)(?:-|$)")


@dataclass(frozen=True)
class PriceMismatch:
    model: str
    field: str
    upstream: float | None
    local: float | None


@dataclass(frozen=True)
class ComparisonResult:
    mismatches: tuple[PriceMismatch, ...]
    missing_upstream: tuple[str, ...]
    missing_fallback: tuple[str, ...]

    @property
    def has_differences(self) -> bool:
        return bool(self.mismatches or self.missing_upstream or self.missing_fallback)


def compare_pricing(
    fallback: pricing.PricingTable,
    upstream: pricing.PricingTable,
) -> ComparisonResult:
    mismatches: list[PriceMismatch] = []
    missing_upstream: list[str] = []

    for model in sorted(fallback):
        upstream_key = pricing._resolve_model_key(model, upstream)
        if upstream_key is None:
            missing_upstream.append(model)
            continue
        upstream_prices = upstream[upstream_key]
        local_prices = fallback[model]
        for field in PRICE_FIELDS:
            upstream_value = upstream_prices.get(field)
            local_value = local_prices.get(field)
            if upstream_value != local_value:
                mismatches.append(PriceMismatch(model, field, upstream_value, local_value))

    # Resolve rather than diff keys: the fallback table drops date suffixes on
    # purpose, so a raw set difference reports models that price just fine.
    missing_fallback = sorted(
        model
        for model in upstream.keys() - fallback.keys()
        if MAINSTREAM_CLAUDE_RE.match(model) and pricing._resolve_model_key(model, fallback) is None
    )
    return ComparisonResult(
        tuple(mismatches),
        tuple(missing_upstream),
        tuple(missing_fallback),
    )


def print_report(result: ComparisonResult) -> None:
    print("價格不一致：")
    if result.mismatches:
        for mismatch in result.mismatches:
            print(
                f"- {mismatch.model} {mismatch.field}: "
                f"上游={mismatch.upstream!r} 本機={mismatch.local!r}"
            )
    else:
        print("- 無")

    print("上游查無此型號：")
    for model in result.missing_upstream or ("無",):
        print(f"- {model}")

    print("上游有但 fallback 缺：")
    for model in result.missing_fallback or ("無",):
        print(f"- {model}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare the offline fallback pricing table with LiteLLM upstream."
    )
    return parser.parse_args()


def main() -> int:
    parse_args()
    upstream = pricing._fetch_pricing()
    if upstream is None:
        print("無法下載或解析 LiteLLM 上游價目表", file=sys.stderr)
        return 1

    result = compare_pricing(pricing._fallback_pricing(), upstream)
    print_report(result)
    return 1 if result.has_differences else 0


if __name__ == "__main__":
    raise SystemExit(main())

# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>

"""Normalized token usage for one discussion turn."""

from dataclasses import dataclass


@dataclass(frozen=True)
class TurnUsage:
    input_tokens: int
    output_tokens: int
    total_tokens: int

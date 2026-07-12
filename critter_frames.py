# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

PHOENIX_FRAMES = tuple(f"critters/phoenix/{index}.png" for index in range(1, 6))
DRAGON_FRAMES = tuple(f"critters/dragon/{index}.png" for index in range(1, 6))
LION_FRAMES = tuple(f"critters/lion/{index}.png" for index in range(1, 6))

IDLE_INTERVAL_SECONDS = 0.0
NORMAL_INTERVAL_SECONDS = 0.18
ACTIVE_INTERVAL_SECONDS = 0.10
HEAVY_INTERVAL_SECONDS = 0.05


def group_to_interval(group: int) -> float:
    if group <= 0:
        return IDLE_INTERVAL_SECONDS
    if group == 1:
        return NORMAL_INTERVAL_SECONDS
    if group == 2:
        return ACTIVE_INTERVAL_SECONDS
    return HEAVY_INTERVAL_SECONDS

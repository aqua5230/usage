# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import critter_frames


def test_critter_frame_paths_have_five_frames() -> None:
    assert len(critter_frames.PHOENIX_FRAMES) == 5
    assert len(critter_frames.DRAGON_FRAMES) == 5
    assert len(critter_frames.LION_FRAMES) == 5
    assert critter_frames.PHOENIX_FRAMES[0] == "critters/phoenix/1.png"
    assert critter_frames.PHOENIX_FRAMES[-1] == "critters/phoenix/5.png"
    assert critter_frames.DRAGON_FRAMES[0] == "critters/dragon/1.png"
    assert critter_frames.DRAGON_FRAMES[-1] == "critters/dragon/5.png"
    assert critter_frames.LION_FRAMES[0] == "critters/lion/1.png"
    assert critter_frames.LION_FRAMES[-1] == "critters/lion/5.png"


def test_group_to_interval_boundaries() -> None:
    assert critter_frames.group_to_interval(-1) == 0.0
    assert critter_frames.group_to_interval(0) == 0.0
    assert critter_frames.group_to_interval(1) == 0.18
    assert critter_frames.group_to_interval(2) == 0.10
    assert critter_frames.group_to_interval(3) == 0.05
    assert critter_frames.group_to_interval(99) == 0.05

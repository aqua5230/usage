# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

from rich.style import Style
from rich.text import Text

ORANGE = "#d97757"
EYE = "#1A1A1A"

Pixel = str | None
Frame = list[list[Pixel]]

TRANSPARENT: Pixel = None


FRAMES: list[Frame] = [
    [
        [
            TRANSPARENT,
            TRANSPARENT,
            ORANGE,
            ORANGE,
            ORANGE,
            ORANGE,
            ORANGE,
            TRANSPARENT,
            TRANSPARENT,
        ],
        [TRANSPARENT, ORANGE, ORANGE, ORANGE, ORANGE, ORANGE, ORANGE, ORANGE, TRANSPARENT],
        [ORANGE, ORANGE, EYE, ORANGE, ORANGE, ORANGE, EYE, ORANGE, ORANGE],
        [ORANGE, ORANGE, EYE, ORANGE, ORANGE, ORANGE, EYE, ORANGE, ORANGE],
        [ORANGE, ORANGE, ORANGE, ORANGE, ORANGE, ORANGE, ORANGE, ORANGE, ORANGE],
        [EYE, ORANGE, ORANGE, ORANGE, ORANGE, ORANGE, ORANGE, ORANGE, ORANGE],
        [
            TRANSPARENT,
            ORANGE,
            TRANSPARENT,
            ORANGE,
            TRANSPARENT,
            ORANGE,
            TRANSPARENT,
            ORANGE,
            TRANSPARENT,
        ],
        [
            TRANSPARENT,
            ORANGE,
            TRANSPARENT,
            ORANGE,
            TRANSPARENT,
            ORANGE,
            TRANSPARENT,
            ORANGE,
            TRANSPARENT,
        ],
    ],
    [
        [
            TRANSPARENT,
            TRANSPARENT,
            ORANGE,
            ORANGE,
            ORANGE,
            ORANGE,
            ORANGE,
            TRANSPARENT,
            TRANSPARENT,
        ],
        [TRANSPARENT, ORANGE, ORANGE, ORANGE, ORANGE, ORANGE, ORANGE, ORANGE, TRANSPARENT],
        [ORANGE, ORANGE, ORANGE, ORANGE, ORANGE, ORANGE, ORANGE, ORANGE, ORANGE],
        [ORANGE, ORANGE, EYE, ORANGE, ORANGE, ORANGE, EYE, ORANGE, ORANGE],
        [ORANGE, ORANGE, ORANGE, ORANGE, ORANGE, ORANGE, ORANGE, ORANGE, ORANGE],
        [EYE, ORANGE, ORANGE, ORANGE, ORANGE, ORANGE, ORANGE, ORANGE, ORANGE],
        [
            TRANSPARENT,
            ORANGE,
            TRANSPARENT,
            ORANGE,
            TRANSPARENT,
            ORANGE,
            TRANSPARENT,
            ORANGE,
            TRANSPARENT,
        ],
        [
            TRANSPARENT,
            ORANGE,
            TRANSPARENT,
            ORANGE,
            TRANSPARENT,
            ORANGE,
            TRANSPARENT,
            ORANGE,
            TRANSPARENT,
        ],
    ],
    [
        [
            TRANSPARENT,
            TRANSPARENT,
            ORANGE,
            ORANGE,
            ORANGE,
            ORANGE,
            ORANGE,
            TRANSPARENT,
            TRANSPARENT,
        ],
        [TRANSPARENT, ORANGE, ORANGE, ORANGE, ORANGE, ORANGE, ORANGE, ORANGE, TRANSPARENT],
        [ORANGE, ORANGE, EYE, ORANGE, ORANGE, ORANGE, EYE, ORANGE, ORANGE],
        [ORANGE, ORANGE, EYE, ORANGE, ORANGE, ORANGE, EYE, ORANGE, ORANGE],
        [ORANGE, ORANGE, ORANGE, ORANGE, ORANGE, ORANGE, ORANGE, ORANGE, ORANGE],
        [EYE, ORANGE, ORANGE, ORANGE, ORANGE, ORANGE, ORANGE, ORANGE, ORANGE],
        [
            TRANSPARENT,
            TRANSPARENT,
            TRANSPARENT,
            ORANGE,
            TRANSPARENT,
            ORANGE,
            TRANSPARENT,
            ORANGE,
            TRANSPARENT,
        ],
        [
            TRANSPARENT,
            ORANGE,
            TRANSPARENT,
            ORANGE,
            TRANSPARENT,
            ORANGE,
            TRANSPARENT,
            ORANGE,
            TRANSPARENT,
        ],
    ],
    [
        [
            TRANSPARENT,
            TRANSPARENT,
            ORANGE,
            ORANGE,
            ORANGE,
            ORANGE,
            ORANGE,
            TRANSPARENT,
            TRANSPARENT,
        ],
        [TRANSPARENT, ORANGE, ORANGE, ORANGE, ORANGE, ORANGE, ORANGE, ORANGE, TRANSPARENT],
        [ORANGE, ORANGE, EYE, ORANGE, ORANGE, ORANGE, EYE, ORANGE, ORANGE],
        [ORANGE, ORANGE, EYE, ORANGE, ORANGE, ORANGE, EYE, ORANGE, ORANGE],
        [ORANGE, ORANGE, ORANGE, ORANGE, ORANGE, ORANGE, ORANGE, ORANGE, ORANGE],
        [EYE, ORANGE, ORANGE, ORANGE, ORANGE, ORANGE, ORANGE, ORANGE, ORANGE],
        [
            TRANSPARENT,
            ORANGE,
            TRANSPARENT,
            ORANGE,
            TRANSPARENT,
            ORANGE,
            TRANSPARENT,
            TRANSPARENT,
            TRANSPARENT,
        ],
        [
            TRANSPARENT,
            ORANGE,
            TRANSPARENT,
            ORANGE,
            TRANSPARENT,
            ORANGE,
            TRANSPARENT,
            ORANGE,
            TRANSPARENT,
        ],
    ],
]


def render_sprite(frame_index: int) -> Text:
    frame = FRAMES[frame_index % len(FRAMES)]
    text = Text()

    for row in range(0, len(frame), 2):
        upper = frame[row]
        lower = frame[row + 1] if row + 1 < len(frame) else [None] * len(upper)

        for upper_pixel, lower_pixel in zip(upper, lower, strict=True):
            if upper_pixel is None and lower_pixel is None:
                text.append(" ")
                continue
            if upper_pixel is None:
                text.append("▄", style=Style(color=lower_pixel))
                continue
            if lower_pixel is None:
                text.append("▀", style=Style(color=upper_pixel))
                continue
            text.append("▀", style=Style(color=upper_pixel, bgcolor=lower_pixel))
        text.append("\n")

    return text

# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Two-line percentage block for the menu bar title.

An attributed string can't stack two differently sized numbers in one column,
so the pair is rendered to a template image and carried by an NSTextAttachment
like the provider icons and critters already are. Black on clear: the status
bar button tints template images for the light and dark menu bar on its own.
"""

from __future__ import annotations

from typing import Any

from AppKit import (
    NSAttributedString,
    NSColor,
    NSFont,
    NSFontAttributeName,
    NSFontWeightBold,
    NSFontWeightSemibold,
    NSForegroundColorAttributeName,
    NSImage,
    NSMakePoint,
    NSMakeRect,
    NSMakeSize,
    NSString,
    NSTextAttachment,
)

# The status bar is 22pt tall; the block has to leave room above and below.
_BLOCK_HEIGHT = 19.0
_TOP_SIZE = 12.0
_BOTTOM_SIZE = 8.5
_TOP_BASELINE = 7.5
_BOTTOM_BASELINE = -0.5
# Sits the block so its top line shares the baseline of the single-line text.
_ATTACHMENT_Y = -5.0

_IMAGE_CACHE: dict[tuple[str, str], Any] = {}
_STRING_CACHE: dict[tuple[str, str], Any] = {}


def _attributes(size: float, weight: float) -> dict[Any, Any]:
    return {
        NSFontAttributeName: NSFont.systemFontOfSize_weight_(size, weight),
        NSForegroundColorAttributeName: NSColor.blackColor(),
    }


def _stacked_image(top: str, bottom: str) -> Any:
    cached = _IMAGE_CACHE.get((top, bottom))
    if cached is not None:
        return cached
    top_attrs = _attributes(_TOP_SIZE, NSFontWeightBold)
    bottom_attrs = _attributes(_BOTTOM_SIZE, NSFontWeightSemibold)
    top_string = NSString.stringWithString_(top)
    bottom_string = NSString.stringWithString_(bottom)
    width = max(
        top_string.sizeWithAttributes_(top_attrs).width,
        bottom_string.sizeWithAttributes_(bottom_attrs).width,
    )
    image = NSImage.alloc().initWithSize_(NSMakeSize(width, _BLOCK_HEIGHT))
    image.lockFocus()
    top_string.drawAtPoint_withAttributes_(NSMakePoint(0.0, _TOP_BASELINE), top_attrs)
    bottom_string.drawAtPoint_withAttributes_(
        NSMakePoint(0.0, _BOTTOM_BASELINE), bottom_attrs
    )
    image.unlockFocus()
    image.setTemplate_(True)
    _IMAGE_CACHE[(top, bottom)] = image
    return image


def stacked_percent_string(top: str, bottom: str) -> Any:
    """Attributed string carrying `top` over `bottom` as one attachment."""
    cached = _STRING_CACHE.get((top, bottom))
    if cached is not None:
        return cached
    image = _stacked_image(top, bottom)
    attachment = NSTextAttachment.alloc().init()
    attachment.setImage_(image)
    attachment.setBounds_(
        NSMakeRect(0, _ATTACHMENT_Y, image.size().width, _BLOCK_HEIGHT)
    )
    attributed = NSAttributedString.attributedStringWithAttachment_(attachment)
    _STRING_CACHE[(top, bottom)] = attributed
    return attributed

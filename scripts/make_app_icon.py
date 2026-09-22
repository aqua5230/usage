#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Generate brand PNGs from assets/brand/*.svg with AppKit (macOS only).

Run: .venv/bin/python scripts/make_app_icon.py
Then run: bash scripts/build_icns.sh
Then run: python3 scripts/make_ico.py
"""

from __future__ import annotations

from pathlib import Path

from AppKit import (
    NSBitmapImageRep,
    NSCompositingOperationSourceOver,
    NSGraphicsContext,
    NSImage,
    NSMakeRect,
    NSPNGFileType,
)
from Foundation import NSData

ROOT = Path(__file__).resolve().parent.parent
BRAND = ROOT / "assets" / "brand"
PAPER = "#F1EDE4"


def render(svg: str, output: Path, width: int, height: int) -> None:
    data = svg.encode()
    image = NSImage.alloc().initWithData_(NSData.dataWithBytes_length_(data, len(data)))
    rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(  # noqa: E501
        None, width, height, 8, 4, True, False, "NSDeviceRGBColorSpace", 0, 0
    )
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.setCurrentContext_(NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep))
    image.drawInRect_fromRect_operation_fraction_(
        NSMakeRect(0, 0, width, height),
        NSMakeRect(0, 0, 0, 0),
        NSCompositingOperationSourceOver,
        1.0,
    )
    NSGraphicsContext.restoreGraphicsState()
    rep.representationUsingType_properties_(NSPNGFileType, {}).writeToFile_atomically_(
        str(output), True
    )


def main() -> None:
    app_icon = (BRAND / "usage-app-icon.svg").read_text()
    mark = (BRAND / "usage-mark.svg").read_text().split(">", 1)[1].rsplit("</svg>", 1)[0]
    wordmark = (BRAND / "usage-wordmark.svg").read_text().split(">", 1)[1].rsplit("</svg>", 1)[0]
    outputs = [
        (ROOT / "assets" / "usage_icon.png", app_icon, 1024, 1024),
        (ROOT / "assets" / "usage_icon_windows.png", app_icon, 1024, 1024),
        (
            ROOT / "docs" / "readme-logo.png",
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">'
            f'<circle cx="256" cy="256" r="256" fill="{PAPER}"/>'
            f'<g transform="translate(64 64) scale(6)">{mark}</g></svg>',
            512,
            512,
        ),
        (
            ROOT / "docs" / "favicon-32.png",
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
            f'<rect width="32" height="32" rx="7" fill="{PAPER}"/>'
            f'<g transform="translate(1 1) scale(0.46875)">{mark}</g></svg>',
            32,
            32,
        ),
        (
            ROOT / "docs" / "apple-touch-icon.png",
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 180 180">'
            f'<rect width="180" height="180" fill="{PAPER}"/>'
            f'<g transform="translate(22 22) scale(2.125)">{mark}</g></svg>',
            180,
            180,
        ),
        (
            ROOT / "docs" / "logo.png",
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1774 887">'
            f'<rect width="1774" height="887" fill="{PAPER}"/>'
            f'<g transform="translate(216 243.5) scale(6.25)">{mark}</g>'
            f'<g transform="translate(672 285.1) scale(3.6)">{wordmark}</g></svg>',
            1774,
            887,
        ),
    ]
    for output, svg, width, height in outputs:
        render(svg, output, width, height)
        print(f"wrote {output.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

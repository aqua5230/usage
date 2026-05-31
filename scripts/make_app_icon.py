#!/usr/bin/env python3
"""Generate the usage app icon (placeholder art).

Draws a macOS-style rounded square (Apple icon grid: 824x824 content inside a
1024 canvas, corner radius 185) with a teal gradient and a flat white paw,
matching the 🐾 menu-bar identity. Writes assets/usage_icon.png.

Run: python3 scripts/make_app_icon.py
Then scripts/build_icns.sh turns the PNG into assets/usage.icns.

This is intentionally simple placeholder art — swap assets/usage_icon.png for
the real icon later and re-run scripts/build_icns.sh; no code change needed.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

CANVAS = 1024
MARGIN = 100  # Apple icon grid: 824x824 content centred in 1024
RADIUS = 185
TOP_COLOR = (43, 212, 192)  # teal
BOTTOM_COLOR = (14, 124, 111)  # deep teal

ASSETS = Path(__file__).resolve().parent.parent / "assets"


def _vertical_gradient(
    size: int, top: tuple[int, int, int], bottom: tuple[int, int, int]
) -> Image.Image:
    grad = Image.new("RGB", (1, size))
    for y in range(size):
        t = y / (size - 1)
        grad.putpixel(
            (0, y),
            tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3)),
        )
    return grad.resize((size, size))


def _rounded_mask(size: int, margin: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle(
        (margin, margin, size - margin, size - margin),
        radius=radius,
        fill=255,
    )
    return mask


def _draw_paw(draw: ImageDraw.ImageDraw, cx: int, cy: int) -> None:
    white = (255, 255, 255, 255)
    # Main pad: a wide rounded shape low-centre.
    draw.ellipse((cx - 150, cy + 20, cx + 150, cy + 230), fill=white)
    # Four toe beans arching above the pad.
    toes = [
        (cx - 175, cy - 90, 90, 130),  # outer left
        (cx - 70, cy - 150, 95, 140),  # inner left
        (cx + 35, cy - 150, 95, 140),  # inner right
        (cx + 140, cy - 90, 90, 130),  # outer right
    ]
    for tx, ty, w, h in toes:
        draw.ellipse((tx, ty, tx + w, ty + h), fill=white)


def main() -> None:
    base = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    gradient = _vertical_gradient(CANVAS, TOP_COLOR, BOTTOM_COLOR).convert("RGBA")
    mask = _rounded_mask(CANVAS, MARGIN, RADIUS)
    base.paste(gradient, (0, 0), mask)

    paw_layer = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    _draw_paw(ImageDraw.Draw(paw_layer), CANVAS // 2, CANVAS // 2 - 20)
    base = Image.alpha_composite(base, paw_layer)

    ASSETS.mkdir(exist_ok=True)
    out = ASSETS / "usage_icon.png"
    base.save(out)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()

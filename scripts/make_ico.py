#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Build assets/usage.ico from assets/usage_icon_windows.png.

Swap the PNG and re-run to update the Windows app icon — no code change
needed elsewhere; scripts/build_windows.ps1 already points PyInstaller at
assets/usage.ico.

Run: python3 scripts/make_ico.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

ASSETS = Path(__file__).resolve().parent.parent / "assets"
SRC = ASSETS / "usage_icon_windows.png"
OUT = ASSETS / "usage.ico"
SIZES = [16, 24, 32, 48, 64, 128, 256]


def main() -> None:
    image = Image.open(SRC).convert("RGBA")
    image.save(OUT, format="ICO", sizes=[(size, size) for size in SIZES])
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()

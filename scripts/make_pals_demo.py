#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Build the landing page's Plush Pals demo.
Use a temporary file from `git show <tag>:docs/panels/felt.html` to pin it to the latest release.
Rerun after each release so the site never shows unreleased pals.
"""

import argparse
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "docs"
CLOCK = (
    "<script>if (parent.__fake) { const f = parent.__fake, R = Date; const t = new R();"
    " t.setMonth(f.month - 1, f.day); t.setHours(f.hour, 30, 0, 0);"
    " const off = t - R.now(); window.Date = class extends R {"
    " constructor(...a) { a.length ? super(...a) : super(R.now() + off); } }; }</script>"
)
ZOOM_ONLY = (
    '<style id="zoom-only">.wrap>section.card~section.card,.wrap>section.footer'
    "{display:none!important}html,body{overflow:hidden}</style>"
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", nargs="?", type=Path, default=DOCS / "panels" / "felt.html")
    source = parser.parse_args().source
    page = source.read_bytes()
    for anchor in (b"<head>", b"</head>"):
        count = page.count(anchor)
        if count != 1:
            parser.error(f"{source}: expected exactly one {anchor.decode()}, found {count}")

    page = page.replace(b"<head>", b"<head>" + CLOCK.encode())
    page = page.replace(b"</head>", ZOOM_ONLY.encode() + b"</head>")
    output = DOCS / "pals" / "felt-demo.html"
    output.parent.mkdir(exist_ok=True)
    output.write_bytes(page)


if __name__ == "__main__":
    main()

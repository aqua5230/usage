# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

# mypy: disable-error-code="import-untyped,import-not-found"
"""Share a hidden pal's collectible card.

The felt panel draws the card as a PNG and posts it here with where the user
wants it: the clipboard (alone or before opening a post page), Downloads, or
the system share menu. AppKit is imported inside share_pal_card so the message
checks stay testable on every platform.
"""

from __future__ import annotations

import base64
import binascii
import logging
import re
import tempfile
import urllib.parse
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

REPO_URL = "https://github.com/aqua5230/usage"
# Post pages only take text and a link, so the picture travels on the
# clipboard and the user pastes it with ⌘V.
INTENTS = {
    "threads": "https://www.threads.com/intent/post",
    "x": "https://x.com/intent/post",
}
TARGETS = frozenset({*INTENTS, "copy", "save", "more"})
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_MAX_PNG_BYTES = 8 * 1024 * 1024
_NAME = re.compile(r"[a-z]{1,20}")


def intent_url(target: str, text: str) -> str:
    return f"{INTENTS[target]}?{urllib.parse.urlencode({'text': text[:280], 'url': REPO_URL})}"


def decode_png(data: object) -> bytes | None:
    if not isinstance(data, str) or len(data) > _MAX_PNG_BYTES * 4 // 3 + 4:
        return None
    try:
        png = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        return None
    return png if png.startswith(_PNG_MAGIC) else None


def free_path(folder: Path, stem: str) -> Path:
    path = folder / f"{stem}.png"
    n = 2
    while path.exists():
        path = folder / f"{stem} ({n}).png"
        n += 1
    return path


def parse(message: dict[str, Any]) -> tuple[str, str, bytes, str] | None:
    target, name, text = message.get("target"), message.get("name"), message.get("text")
    if not isinstance(target, str) or target not in TARGETS:
        return None
    if not isinstance(name, str) or not _NAME.fullmatch(name) or not isinstance(text, str):
        return None
    png = decode_png(message.get("png"))
    return None if png is None else (target, name, png, text)


def _anchor(message: dict[str, Any]) -> tuple[float, float, float, float]:
    anchor = message.get("anchor")
    raw = [anchor.get(k) for k in ("x", "y", "w", "h")] if isinstance(anchor, dict) else []
    values = [float(v) for v in raw if isinstance(v, int | float)]
    if len(values) == 4:
        return values[0], values[1], values[2], values[3]
    return 0.0, 0.0, 1.0, 1.0


def share_pal_card(web_view: Any, message: dict[str, Any]) -> None:
    parsed = parse(message)
    if parsed is None:
        logger.warning("ignored a malformed share_pal_card message")
        return
    target, name, png, text = parsed
    from AppKit import (
        NSImage,
        NSMakeRect,
        NSMaxYEdge,
        NSPasteboard,
        NSPasteboardTypePNG,
        NSPasteboardTypeTIFF,
        NSSharingServicePicker,
        NSWorkspace,
    )
    from Foundation import NSURL, NSData

    if target == "save":
        path = free_path(Path.home() / "Downloads", f"usage-{name}")
        path.write_bytes(png)
        NSWorkspace.sharedWorkspace().activateFileViewerSelectingURLs_(
            [NSURL.fileURLWithPath_(str(path))]
        )
        return
    if target == "more":
        # A file URL, not an NSImage: AirDrop and Telegram take files.
        path = Path(tempfile.gettempdir()) / f"usage-{name}.png"
        path.write_bytes(png)
        picker = NSSharingServicePicker.alloc().initWithItems_([NSURL.fileURLWithPath_(str(path))])
        # WKWebView is flipped, so the button's bottom edge is MaxY.
        picker.showRelativeToRect_ofView_preferredEdge_(
            NSMakeRect(*_anchor(message)), web_view, NSMaxYEdge
        )
        return
    data = NSData.dataWithBytes_length_(png, len(png))
    board = NSPasteboard.generalPasteboard()
    board.declareTypes_owner_([NSPasteboardTypePNG, NSPasteboardTypeTIFF], None)
    board.setData_forType_(data, NSPasteboardTypePNG)
    # Some apps paste images only as TIFF.
    board.setData_forType_(
        NSImage.alloc().initWithData_(data).TIFFRepresentation(), NSPasteboardTypeTIFF
    )
    if target in INTENTS:
        NSWorkspace.sharedWorkspace().openURL_(NSURL.URLWithString_(intent_url(target, text)))

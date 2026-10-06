# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

import re

_HEADING_RE = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]+(.*?)[ \t]*#*[ \t]*$")
_BULLET_RE = re.compile(r"^([ \t]*)[-*][ \t]+(.*)$")
_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_STRONG_RE = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_LEAD_BULLET_RE = re.compile(r"^([ \t]*[-*][ \t]+)\*\*(.+?)\*\*(.*)$")
_FIRST_SENTENCE_RE = re.compile(r"\s*(.+?(?:。|\.(?=\s|$)))")


def _format_inline_markdown(text: str) -> str:
    text = _LINK_RE.sub(r"\1", text)
    text = _STRONG_RE.sub(lambda match: match.group(1) or match.group(2), text)
    return _INLINE_CODE_RE.sub(r"\1", text)


def format_release_notes(body: str, limit: int) -> str:
    """Convert GitHub Release Markdown into compact plain text for an alert."""
    if not isinstance(body, str) or limit <= 0:
        return ""

    lines: list[str] = []
    for line in body.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        heading = _HEADING_RE.match(line)
        if heading:
            if lines and lines[-1]:
                lines.append("")
            lines.append(_format_inline_markdown(heading.group(1)))
            lines.append("")
            continue

        line = _format_inline_markdown(line)
        lines.append(_BULLET_RE.sub(r"\1• \2", line))

    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    if len(text) <= limit:
        return text
    if limit == 1:
        return "…"

    boundary = max(text.rfind(" ", 0, limit), text.rfind("\n", 0, limit))
    if boundary < 0:
        return "…"
    return f"{text[:boundary].rstrip()}…"


def select_release_notes(body: str, language: str) -> str:
    """Select a language section; old releases and missing translations fall back."""
    parts = re.split(
        r"^## 繁體中文$",
        body.replace("\r\n", "\n").replace("\r", "\n"),
        maxsplit=1,
        flags=re.MULTILINE,
    )
    if len(parts) == 1:
        return body
    english, chinese = (part.strip() for part in parts)
    return chinese if language in ("zh-TW", "zh-CN") and chinese else english


def headline_release_notes(body: str) -> str:
    """Shorten bullets that open with a bold sentence to that sentence.

    A category lead such as "Build:" keeps the first sentence after it. A bold
    word inside a sentence leaves the bullet whole.
    """
    lines = []
    for line in body.split("\n"):
        match = _LEAD_BULLET_RE.match(line)
        if match:
            prefix, lead, rest = match.groups()
            if lead.endswith((".", "。", "!", "！", "?", "？")):
                line = f"{prefix}**{lead}**"
            elif lead.endswith((":", "：")) and (sentence := _FIRST_SENTENCE_RE.match(rest)):
                gap = "" if lead.endswith("：") else " "
                line = f"{prefix}**{lead}**{gap}{sentence.group(1)}"
        lines.append(line)
    return "\n".join(lines)


def alert_release_notes(body: str, language: str, limit: int) -> str:
    return format_release_notes(headline_release_notes(select_release_notes(body, language)), limit)

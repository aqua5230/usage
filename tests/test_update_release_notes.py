from __future__ import annotations

from typing import cast

import pytest

from update_release_notes import format_release_notes


def test_formats_changelog_style_release_notes() -> None:
    body = """### Added
- **`usage status` prints your quota.** Read `usage status --json` for details.

### Fixed
- See the [development docs](https://example.test/docs)."""

    formatted = format_release_notes(body, 2_000)

    assert formatted == (
        "Added\n\n"
        "• usage status prints your quota. Read usage status --json for details.\n\n"
        "Fixed\n\n"
        "• See the development docs."
    )
    assert not any(marker in formatted for marker in ("#", "*", "`"))


def test_headings_keep_a_blank_line_before_and_after() -> None:
    body = "Before\n## **Changes**\nAfter"
    assert format_release_notes(body, 100) == "Before\n\nChanges\n\nAfter"


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("**Bold** and __also bold__", "Bold and also bold"),
        ("Use `usage status`", "Use usage status"),
        ("- First\n* Second", "• First\n• Second"),
        ("Read [the guide](https://example.test/guide).", "Read the guide."),
    ],
)
def test_removes_supported_inline_markdown(body: str, expected: str) -> None:
    assert format_release_notes(body, 100) == expected


def test_collapses_multiple_blank_lines() -> None:
    assert format_release_notes("One\n\n\n\nTwo", 100) == "One\n\nTwo"


def test_truncates_at_a_whitespace_boundary_with_ellipsis() -> None:
    assert format_release_notes("alpha beta gamma", 12) == "alpha beta…"


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("", ""),
        (cast(str, None), ""),
        ("Plain text without Markdown.", "Plain text without Markdown."),
    ],
)
def test_handles_empty_none_like_and_plain_text(body: str, expected: str) -> None:
    assert format_release_notes(body, 100) == expected

from __future__ import annotations

from typing import cast

import pytest

from updates.release_notes import alert_release_notes, format_release_notes, headline_release_notes


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


def test_headlines_keep_only_bold_leads() -> None:
    body = (
        "### Changed\n"
        "- **Context color now accounts for window size.** It turns yellow sooner.\n"
        "- **Build:** the app is re-signed. `codesign --verify` passes.\n"
        "- **打包：** 刪除快取後重新簽章。下載的 app 可以通過檢查。\n"
        "- **Faster** startup via `usage status`.\n"
        "- Plain bullet stays whole."
    )

    assert headline_release_notes(body) == (
        "### Changed\n"
        "- **Context color now accounts for window size.**\n"
        "- **Build:** the app is re-signed.\n"
        "- **打包：**刪除快取後重新簽章。\n"
        "- **Faster** startup via `usage status`.\n"
        "- Plain bullet stays whole."
    )


def test_alert_notes_select_language_then_headline() -> None:
    body = (
        "### Added\n- **English lead.** Detail.\n\n## 繁體中文\n\n### 新增\n- **中文標題。** 細節。"
    )

    assert alert_release_notes(body, "zh-TW", 100) == "新增\n\n• 中文標題。"
    assert alert_release_notes(body, "ja", 100) == "Added\n\n• English lead."

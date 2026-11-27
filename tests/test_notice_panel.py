from __future__ import annotations

import sys
from typing import Any

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="requires AppKit")


def _parts(controller: Any) -> tuple[list[str], list[str], dict[str, Any]]:
    views = list(controller.panel.contentView().subviews())
    labels = [view.stringValue() for view in views if view.className() == "NSTextField"]
    bodies = [view.documentView().string() for view in views if view.className() == "NSScrollView"]
    buttons = {view.title(): view for view in views if view.className() == "NSButton"}
    return labels, bodies, buttons


@pytest.mark.parametrize(
    ("clicked", "expected"),
    [("Download", 1000), ("Later", 1001), ("Skip", 1002), (None, 1001)],
)
def test_choice_codes_and_cleanup(clicked: str | None, expected: int) -> None:
    from menubar import notice_panel

    choices: list[int] = []
    # Built but never ordered front, so the test run shows no window.
    controller = notice_panel.build(
        "Title", "Body", ["Download", "Later", "Skip"], choices.append, cancel=1001
    )
    notice_panel._open_notices.add(controller)
    labels, bodies, buttons = _parts(controller)
    assert labels == ["Title"] and bodies == ["Body"]
    assert {title: button.keyEquivalent() for title, button in buttons.items()} == {
        "Download": "\r",
        "Later": "",
        "Skip": "",
    }
    # Like NSAlert, the default button sits rightmost and later buttons to its left.
    lefts = [buttons[title].frame().origin.x for title in ("Download", "Later", "Skip")]
    assert lefts == sorted(lefts, reverse=True)
    panel = controller.panel
    assert not panel.hidesOnDeactivate() and not panel.isReleasedWhenClosed()
    if clicked is None:
        panel.cancelOperation_(None)  # Escape
    else:
        buttons[clicked].performClick_(None)
    assert choices == [expected]
    assert controller not in notice_panel._open_notices


def test_close_without_cancel_reports_nothing() -> None:
    from menubar import notice_panel

    choices: list[int] = []
    controller = notice_panel.build("Title", "Body", ["OK"], choices.append)
    notice_panel._open_notices.add(controller)
    controller.panel.performClose_(None)
    assert choices == []
    assert controller not in notice_panel._open_notices

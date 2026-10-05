from __future__ import annotations

import subprocess
import sys
from typing import Any

import pytest


@pytest.mark.skipif(sys.platform != "darwin", reason="menu APIs require PyObjC")
@pytest.mark.parametrize("trust", ["untrusted", "disabled", "trusted", "unknown", "not_installed"])
def test_menu_warnings(monkeypatch: pytest.MonkeyPatch, trust: str) -> None:
    from installer import codex_hook_trust
    from menubar import menu as menu_module
    from menubar.menu import build_menu_item
    from quota import keeper_outcome, window_keeper

    class Item:
        def __init__(self) -> None:
            self.label = ""
            self.tooltip = ""

        @staticmethod
        def alloc() -> Item:
            return Item()

        def initWithTitle_action_keyEquivalent_(self, title: str, *args: Any) -> Item:
            self.label = title
            return self

        def setTarget_(self, value: Any) -> None:
            pass

        def setState_(self, value: int) -> None:
            pass

        def setTitle_(self, value: str) -> None:
            self.label = value

        def setToolTip_(self, value: str) -> None:
            self.tooltip = value

        def title(self) -> str:
            return self.label

        def toolTip(self) -> str:
            return self.tooltip

    monkeypatch.setattr(menu_module, "NSMenuItem", Item)
    monkeypatch.setattr(codex_hook_trust, "codex_terse_hook_trust", lambda: trust)
    terse = build_menu_item(
        "en", "terse_mode_menu", "", target=None, state=True, tooltip_key="terse_mode_tooltip"
    )
    assert str(terse.title()).endswith(" ⚠") is (trust in ("untrusted", "disabled"))
    if trust in ("untrusted", "disabled"):
        assert "/hooks" in str(terse.toolTip())
    keeper_outcome.record_result(
        window_keeper.WINDOW_KEEPER_STATE_PATH,
        {
            "last_result": "failed",
            "last_error_kind": "not_found",
            "last_result_at": 1000,
        },
    )

    def menu(state: bool) -> Any:
        return build_menu_item(
            "en",
            "window_keeper_menu",
            "",
            target=None,
            state=state,
            tooltip_key="window_keeper_tooltip",
        )

    assert str(menu(True).title()).endswith(" ⚠")
    assert "Claude" in str(menu(True).toolTip())
    assert not str(menu(False).title()).endswith(" ⚠")
    keeper_outcome.record_result(
        window_keeper.WINDOW_KEEPER_STATE_PATH,
        keeper_outcome.classify(subprocess.CompletedProcess([], 0)),
    )
    assert not str(menu(True).title()).endswith(" ⚠")

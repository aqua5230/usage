# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>

from __future__ import annotations

import pytest

import win_login_item


class _Key:
    def __enter__(self) -> _Key:
        return self

    def __exit__(self, *args: object) -> None:
        return None


class FakeWinreg:
    HKEY_CURRENT_USER = object()
    REG_SZ = 1
    KEY_SET_VALUE = 2

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def OpenKey(self, *args: object) -> _Key:  # noqa: N802 - winreg contract
        if win_login_item.VALUE_NAME not in self.values:
            raise FileNotFoundError
        return _Key()

    def CreateKey(self, *args: object) -> _Key:  # noqa: N802 - winreg contract
        return _Key()

    def QueryValueEx(self, key: object, name: str) -> tuple[str, int]:  # noqa: N802
        return (self.values[name], self.REG_SZ)

    def SetValueEx(  # noqa: N802 - winreg contract
        self, key: object, name: str, reserved: int, kind: int, value: str
    ) -> None:
        self.values[name] = value

    def DeleteValue(self, key: object, name: str) -> None:  # noqa: N802
        del self.values[name]


def test_win_login_item_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeWinreg()
    monkeypatch.setattr(win_login_item, "_winreg", lambda: fake)
    monkeypatch.setattr(win_login_item, "_command", lambda: '"usage.exe"')

    assert win_login_item.is_enabled() is False
    win_login_item.enable()
    assert win_login_item.is_enabled() is True
    win_login_item.disable()
    assert win_login_item.is_enabled() is False


def test_win_login_item_detects_different_command(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeWinreg()
    fake.values[win_login_item.VALUE_NAME] = '"old-usage.exe"'
    monkeypatch.setattr(win_login_item, "_winreg", lambda: fake)
    monkeypatch.setattr(win_login_item, "_command", lambda: '"usage.exe"')

    assert win_login_item.is_enabled() is False

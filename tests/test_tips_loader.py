from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

import tips_loader


def _write_commands(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_load_tip_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = tmp_path / "tips" / "commands.json"
    _write_commands(
        path,
        """
        {
          "commands": [
            {
              "id": "compact",
              "command": "/compact",
              "level": "beginner",
              "translations": {
                "zh-TW": {
                  "title": "壓縮對話節省 token",
                  "what": "這個指令做什麼",
                  "when": "什麼時候用",
                  "how": "怎麼用",
                  "note": "**保留** 與 **丟掉**",
                  "scenario": "實際情境"
                }
              }
            }
          ]
        }
        """.strip(),
    )
    monkeypatch.setattr(tips_loader, "_commands_path", lambda: path)

    tip = tips_loader.load_tip("zh-TW", today=date(2026, 5, 23))

    assert tip is not None
    assert tip.id == "compact"
    assert tip.command == "/compact"
    assert tip.title == "壓縮對話節省 token"


def test_load_tip_returns_none_when_language_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "tips" / "commands.json"
    _write_commands(
        path,
        """
        {
          "commands": [
            {
              "id": "compact",
              "command": "/compact",
              "level": "beginner",
              "translations": {
                "en": {
                  "title": "Compact",
                  "what": "what",
                  "when": "when",
                  "how": "how",
                  "note": "note",
                  "scenario": "scenario"
                }
              }
            }
          ]
        }
        """.strip(),
    )
    monkeypatch.setattr(tips_loader, "_commands_path", lambda: path)

    assert tips_loader.load_tip("zh-TW", today=date(2026, 5, 23)) is None


def test_load_tip_returns_none_when_file_missing_or_invalid(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    missing = tmp_path / "tips" / "commands.json"
    monkeypatch.setattr(tips_loader, "_commands_path", lambda: missing)
    assert tips_loader.load_tip("zh-TW", today=date(2026, 5, 23)) is None

    broken = tmp_path / "tips" / "broken.json"
    _write_commands(broken, "{not-json")
    monkeypatch.setattr(tips_loader, "_commands_path", lambda: broken)
    assert tips_loader.load_tip("zh-TW", today=date(2026, 5, 23)) is None


def test_load_tip_returns_none_when_commands_file_has_bad_utf8(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    broken = tmp_path / "tips" / "bad-utf8.json"
    broken.parent.mkdir(parents=True, exist_ok=True)
    broken.write_bytes(b"\xff\xfe not utf-8\n")
    monkeypatch.setattr(tips_loader, "_commands_path", lambda: broken)

    assert tips_loader.load_tip("zh-TW", today=date(2026, 5, 23)) is None


def test_load_tip_uses_date_rotation(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = tmp_path / "tips" / "commands.json"
    _write_commands(
        path,
        """
        {
          "commands": [
            {
              "id": "zero",
              "command": "/zero",
              "level": "beginner",
              "translations": {
                "en": {
                  "title": "Zero",
                  "what": "what",
                  "when": "when",
                  "how": "how",
                  "note": "note",
                  "scenario": "scenario"
                }
              }
            },
            {
              "id": "one",
              "command": "/one",
              "level": "advanced",
              "translations": {
                "en": {
                  "title": "One",
                  "what": "what",
                  "when": "when",
                  "how": "how",
                  "note": "note",
                  "scenario": "scenario"
                }
              }
            }
          ]
        }
        """.strip(),
    )
    monkeypatch.setattr(tips_loader, "_commands_path", lambda: path)

    first_day = date(2026, 5, 22)
    second_day = date(2026, 5, 23)

    first_tip = tips_loader.load_tip("en", today=first_day)
    second_tip = tips_loader.load_tip("en", today=second_day)

    assert first_tip is not None
    assert second_tip is not None
    assert first_tip.id == ("zero" if first_day.toordinal() % 2 == 0 else "one")
    assert second_tip.id == ("zero" if second_day.toordinal() % 2 == 0 else "one")

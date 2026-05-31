from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from importlib import import_module
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Tip:
    id: str
    command: str
    level: str
    title: str
    what: str
    when: str
    how: str
    note: str
    scenario: str


def _commands_path() -> Path:
    try:
        bundle = import_module("Foundation").NSBundle.mainBundle()
        bundle_path = bundle.resourcePath() if bundle is not None else None
        if bundle_path:
            candidate = Path(str(bundle_path)) / "tips" / "commands.json"
            if candidate.exists():
                return candidate
    except Exception:
        pass
    return Path(__file__).resolve().with_name("tips") / "commands.json"


def _load_commands() -> list[dict[str, Any]] | None:
    try:
        data = json.loads(_commands_path().read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None

    commands = data.get("commands")
    if not isinstance(commands, list) or not commands:
        return None
    return [command for command in commands if isinstance(command, dict)]


def load_tip(lang: str, today: date | None = None) -> Tip | None:
    commands = _load_commands()
    if not commands:
        return None

    selected = commands[(today or date.today()).toordinal() % len(commands)]
    translations = selected.get("translations")
    if not isinstance(translations, dict):
        return None

    localized = translations.get(lang)
    if not isinstance(localized, dict):
        return None

    fields = ["id", "command", "level"]
    text_fields = ["title", "what", "when", "how", "note", "scenario"]
    values: dict[str, str] = {}

    for field in fields:
        value = selected.get(field)
        if not isinstance(value, str) or not value:
            return None
        values[field] = value

    for field in text_fields:
        value = localized.get(field)
        if not isinstance(value, str) or not value:
            return None
        values[field] = value

    return Tip(**values)

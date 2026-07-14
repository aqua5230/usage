# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import json
import os
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any

PREFERENCES_FILE = Path(os.path.expanduser("~/.claude/usage-preferences.json"))


def _load_preferences(path: Path | None = None) -> dict[str, Any]:
    preferences_file = PREFERENCES_FILE if path is None else path
    if not preferences_file.exists():
        return {}
    try:
        data = json.loads(preferences_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_preferences(data: dict[str, Any], path: Path | None = None) -> None:
    preferences_file = PREFERENCES_FILE if path is None else path
    preferences_file.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    tmp_path: str | None = None
    try:
        fd, tmp_path = tempfile.mkstemp(dir=preferences_file.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(tmp_path, preferences_file)
        tmp_path = None
    finally:
        if tmp_path and os.path.exists(tmp_path):
            with suppress(OSError):
                os.unlink(tmp_path)

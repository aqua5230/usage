# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import contextlib
import json
import os
import shlex
import sys
from pathlib import Path
from typing import Any

from setup_hook import _atomic_write_text


def _claude_settings_path() -> Path:
    return Path(os.path.expanduser("~/.claude/settings.json"))


def _load_claude_settings() -> dict[str, Any]:
    settings_path = _claude_settings_path()
    if not settings_path.exists():
        return {}
    with settings_path.open(encoding="utf-8") as file:
        settings = json.load(file)
    if not isinstance(settings, dict):
        raise ValueError(f"{settings_path} must be a JSON object")
    return settings


def _save_claude_settings(settings: dict[str, Any]) -> None:
    settings_path = _claude_settings_path()
    trailing_newline = True
    with contextlib.suppress(OSError):
        trailing_newline = settings_path.read_bytes().endswith(b"\n")
    content = json.dumps(settings, indent=2, ensure_ascii=False)
    if trailing_newline:
        content += "\n"
    _atomic_write_text(settings_path, content)


def _statusline_command_target_exists(statusline: object) -> bool:
    if not isinstance(statusline, dict):
        return True
    command = statusline.get("command")
    if not isinstance(command, str):
        return True
    try:
        parts = shlex.split(command)
    except ValueError:
        return True
    for part in parts:
        if "statusline" not in part or not part.endswith(".py"):
            continue
        return Path(os.path.expanduser(part)).exists()
    return True


def _set_forwarder_mode_prompt_dismissed() -> None:
    import setup_hook

    settings = setup_hook._load_settings()
    usage_settings = settings.get(setup_hook.BACKUP_KEY)
    if not isinstance(usage_settings, dict):
        usage_settings = {}
        settings[setup_hook.BACKUP_KEY] = usage_settings
    usage_settings["forwarderModePromptDismissed"] = True
    setup_hook._save_settings(settings)


def _sync_agy_statusline(enable: bool) -> None:
    """Mirror the switch onto Antigravity's status line when its CLI is installed.

    Antigravity is a side effect of the one switch the panel shows, so a missing
    or unwritable ~/.gemini config must never stop Claude's own status line from
    being toggled.
    """
    if sys.platform != "darwin":
        return
    import setup_hook

    with contextlib.suppress(Exception):
        if enable:
            setup_hook._setup_agy()
        else:
            setup_hook._unsetup_agy()


def _disable_statusline_settings() -> int:
    _sync_agy_statusline(False)
    settings = _load_claude_settings()
    if "statusLine" not in settings:
        return 0
    usage_settings = settings.setdefault("usage", {})
    if not isinstance(usage_settings, dict):
        usage_settings = {}
        settings["usage"] = usage_settings
    usage_settings["previousStatusLine"] = settings["statusLine"]
    del settings["statusLine"]
    _save_claude_settings(settings)
    return 0


def _enable_statusline_settings() -> int:
    _sync_agy_statusline(True)
    settings = _load_claude_settings()
    if "statusLine" in settings:
        return 0
    raw_usage_settings = settings.get("usage")
    usage_settings = raw_usage_settings if isinstance(raw_usage_settings, dict) else None
    previous = usage_settings.get("previousStatusLine") if usage_settings is not None else None
    if previous:
        assert usage_settings is not None
        if not _statusline_command_target_exists(previous):
            del usage_settings["previousStatusLine"]
            if not usage_settings:
                del settings["usage"]
            _save_claude_settings(settings)
            import setup_hook

            return setup_hook.setup()
        settings["statusLine"] = previous
        del usage_settings["previousStatusLine"]
        if not usage_settings:
            del settings["usage"]
        _save_claude_settings(settings)
        return 0

    import setup_hook

    exit_code = setup_hook.setup()
    if exit_code != 0 and setup_hook.is_agy_setup():
        return 0
    return exit_code


def _toggle_statusline_settings() -> tuple[str, int]:
    if _statusline_enabled():
        return "uninstall", _disable_statusline_settings()
    return "install", _enable_statusline_settings()


def _statusline_enabled() -> bool:
    try:
        settings = _load_claude_settings()
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    if "statusLine" in settings:
        return True
    if sys.platform != "darwin":
        return False
    with contextlib.suppress(Exception):
        import setup_hook

        return setup_hook.is_agy_setup()
    return False

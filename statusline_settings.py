from __future__ import annotations

import contextlib
import json
import os
import shlex
import tempfile
from pathlib import Path
from typing import Any


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
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    trailing_newline = True
    with contextlib.suppress(OSError):
        trailing_newline = settings_path.read_bytes().endswith(b"\n")
    tmp_path: str | None = None
    try:
        fd, tmp_path = tempfile.mkstemp(dir=settings_path.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(settings, file, indent=2, ensure_ascii=False)
            if trailing_newline:
                file.write("\n")
        os.replace(tmp_path, settings_path)
        tmp_path = None
    finally:
        if tmp_path and os.path.exists(tmp_path):
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)


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


def _disable_statusline_settings() -> int:
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

    return setup_hook.setup()


def _toggle_statusline_settings() -> tuple[str, int]:
    if _statusline_enabled():
        return "uninstall", _disable_statusline_settings()
    return "install", _enable_statusline_settings()


def _statusline_enabled() -> bool:
    try:
        settings = _load_claude_settings()
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    return "statusLine" in settings

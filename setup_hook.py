"""把 usage 的 statusLine hook 安裝到 / 從 Claude Code 設定移除。

Claude Code 透過 ~/.claude/settings.json 的 statusLine 欄位，
在每次刷新狀態列時呼叫指定指令並餵 JSON 給 stdin。
我們把專案內的 usage_statusline.py 複製到 ~/.claude/usage-statusline.py，
然後把 statusLine 指向它，讓它把 JSON 落地到磁碟給 usage 主程式讀。

備份原 statusLine 到 settings["usage"]["previousStatusLine"]，
unsetup 時還原。
"""

from __future__ import annotations

import contextlib
import json
import os
import shlex
import shutil
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any

CLAUDE_SETTINGS = Path(os.path.expanduser("~/.claude/settings.json"))
HOOK_TARGET = Path(os.path.expanduser("~/.claude/usage-statusline.py"))
STATUS_FILE = Path(os.path.expanduser("~/.claude/usage-status.json"))
LEGACY_NAME = "usag"
LEGACY_HOOK_TARGET = Path(os.path.expanduser(f"~/.claude/{LEGACY_NAME}-statusline.py"))
LEGACY_STATUS_FILE = Path(os.path.expanduser(f"~/.claude/{LEGACY_NAME}-status.json"))
BACKUP_KEY = "usage"
LEGACY_BACKUP_KEY = LEGACY_NAME
PREV_SL_KEY = "previousStatusLine"


def _resolve_hook_source() -> Path:
    paths = [
        Path(__file__).resolve().parent / "usage_statusline.py",
        Path(sys.executable).resolve().parent.parent / "Resources" / "usage_statusline.py",
    ]
    for path in paths:
        if path.exists():
            return path
    tried = ", ".join(str(path) for path in paths)
    raise SystemExit(f"❌ 找不到 hook 原始檔，tried: {tried}")


def _statusline_command() -> str:
    # 用系統 python3，不綁 venv（hook 只用標準庫）
    python = shutil.which("python3") or "python3"
    return f"{shlex.quote(python)} {shlex.quote(str(HOOK_TARGET))}"


def _is_usage_hook(sl: object) -> bool:
    if not isinstance(sl, dict):
        return False
    cmd = sl.get("command")
    return isinstance(cmd, str) and "usage-statusline" in cmd


def _migrate_from_legacy_usage() -> None:
    changed = False

    for path in (LEGACY_HOOK_TARGET, LEGACY_STATUS_FILE):
        try:
            if path.exists():
                path.unlink()
                changed = True
        except OSError as exc:
            print(f"⚠ 無法移除舊檔 {path}: {exc}")

    settings: dict[str, Any] | None = None
    try:
        if CLAUDE_SETTINGS.exists():
            with CLAUDE_SETTINGS.open(encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                settings = data
            else:
                print(f"⚠ {CLAUDE_SETTINGS} 不是 JSON object，略過 migration")
    except (OSError, json.JSONDecodeError) as exc:
        print(f"⚠ 無法讀取舊設定做 migration: {exc}")

    if settings is not None:
        try:
            sl = settings.get("statusLine")
            cmd = sl.get("command") if isinstance(sl, dict) else None
            if (
                isinstance(cmd, str)
                and f"{LEGACY_NAME}-statusline" in cmd
                and "usage-statusline" not in cmd
            ):
                settings.pop("statusLine", None)
                changed = True
        except Exception as exc:
            print(f"⚠ 無法清理舊 statusLine: {exc}")

        try:
            legacy_backup = settings.pop(LEGACY_BACKUP_KEY, None)
            current_backup = settings.get(BACKUP_KEY)
            if isinstance(legacy_backup, dict):
                if isinstance(current_backup, dict):
                    settings[BACKUP_KEY] = {**legacy_backup, **current_backup}
                else:
                    settings[BACKUP_KEY] = legacy_backup
                changed = True
            elif legacy_backup is not None:
                changed = True
        except Exception as exc:
            print(f"⚠ 無法搬移舊備份 key: {exc}")

        if changed:
            try:
                _save_settings(settings)
            except Exception as exc:
                print(f"⚠ 無法寫回 migration 設定: {exc}")

    if changed:
        print(f"ℹ 已從 v0.1.x ({LEGACY_NAME}) 自動 migrate 到 usage")
    else:
        print("ℹ 無需 migration")


def _load_settings() -> dict[str, Any]:
    if not CLAUDE_SETTINGS.exists():
        return {}
    try:
        with CLAUDE_SETTINGS.open(encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"❌ 無法讀取 {CLAUDE_SETTINGS}: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"❌ {CLAUDE_SETTINGS} 必須是 JSON object")
    return data


def _save_settings(data: dict[str, Any]) -> None:
    CLAUDE_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: str | None = None
    try:
        fd, tmp_path = tempfile.mkstemp(dir=CLAUDE_SETTINGS.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp_path, CLAUDE_SETTINGS)
        tmp_path = None
    finally:
        if tmp_path and os.path.exists(tmp_path):
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)


def _copy_hook_script() -> None:
    hook_source = _resolve_hook_source()
    HOOK_TARGET.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(hook_source, HOOK_TARGET)
    HOOK_TARGET.chmod(HOOK_TARGET.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def setup() -> int:
    _migrate_from_legacy_usage()
    if not CLAUDE_SETTINGS.parent.exists():
        print("❌ 找不到 ~/.claude/，請先安裝並執行過 Claude Code 一次", file=sys.stderr)
        return 1

    settings = _load_settings()
    _copy_hook_script()

    existing = settings.get("statusLine")
    if existing and not _is_usage_hook(existing):
        backup = settings.get(BACKUP_KEY)
        if not isinstance(backup, dict):
            backup = {}
            settings[BACKUP_KEY] = backup
        backup[PREV_SL_KEY] = existing
        print(f"ℹ 已備份原有 statusLine 到 settings.{BACKUP_KEY}.{PREV_SL_KEY}")

    settings["statusLine"] = {"type": "command", "command": _statusline_command()}
    _save_settings(settings)

    print(f"✓ hook 已安裝：{HOOK_TARGET}")
    print(f"✓ settings 已更新：{CLAUDE_SETTINGS}")
    print("ℹ 請重新開啟 Claude Code 一次（讓它重新讀 settings 並刷新一次 statusLine）")
    return 0


def unsetup() -> int:
    settings = _load_settings()
    sl = settings.get("statusLine")

    if _is_usage_hook(sl):
        backup = settings.get(BACKUP_KEY)
        prev = backup.get(PREV_SL_KEY) if isinstance(backup, dict) else None
        if isinstance(prev, dict):
            settings["statusLine"] = prev
            print("✓ 已還原原有 statusLine")
        else:
            settings.pop("statusLine", None)
            print("✓ 已移除 usage statusLine")

        if isinstance(backup, dict):
            backup.pop(PREV_SL_KEY, None)
            if not backup:
                del settings[BACKUP_KEY]

        _save_settings(settings)
    else:
        print("ℹ statusLine 不是 usage 安裝的，settings 未動")

    if HOOK_TARGET.exists():
        HOOK_TARGET.unlink()
        print(f"✓ 已刪除 hook：{HOOK_TARGET}")

    if STATUS_FILE.exists():
        STATUS_FILE.unlink()
        print(f"✓ 已刪除狀態檔：{STATUS_FILE}")

    return 0

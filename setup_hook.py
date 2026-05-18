"""把 usag 的 statusLine hook 安裝到 / 從 Claude Code 設定移除。

Claude Code 透過 ~/.claude/settings.json 的 statusLine 欄位，
在每次刷新狀態列時呼叫指定指令並餵 JSON 給 stdin。
我們把專案內的 usag_statusline.py 複製到 ~/.claude/usag-statusline.py，
然後把 statusLine 指向它，讓它把 JSON 落地到磁碟給 usag 主程式讀。

備份原 statusLine 到 settings["usag"]["previousStatusLine"]，
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
HOOK_TARGET = Path(os.path.expanduser("~/.claude/usag-statusline.py"))
STATUS_FILE = Path(os.path.expanduser("~/.claude/usag-status.json"))
HOOK_SOURCE = Path(__file__).resolve().parent / "usag_statusline.py"

BACKUP_KEY = "usag"
PREV_SL_KEY = "previousStatusLine"


def _statusline_command() -> str:
    # 用系統 python3，不綁 venv（hook 只用標準庫）
    python = shutil.which("python3") or "python3"
    return f"{shlex.quote(python)} {shlex.quote(str(HOOK_TARGET))}"


def _is_usag_hook(sl: object) -> bool:
    if not isinstance(sl, dict):
        return False
    cmd = sl.get("command")
    return isinstance(cmd, str) and "usag-statusline" in cmd


def _load_settings() -> dict[str, Any]:
    if not CLAUDE_SETTINGS.exists():
        return {}
    try:
        with CLAUDE_SETTINGS.open(encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"❌ 無法讀取 {CLAUDE_SETTINGS}: {exc}") from exc
    return data if isinstance(data, dict) else {}


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
    if not HOOK_SOURCE.exists():
        raise SystemExit(f"❌ 找不到 hook 原始檔：{HOOK_SOURCE}")
    HOOK_TARGET.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(HOOK_SOURCE, HOOK_TARGET)
    HOOK_TARGET.chmod(HOOK_TARGET.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def setup() -> int:
    if not CLAUDE_SETTINGS.parent.exists():
        print("❌ 找不到 ~/.claude/，請先安裝並執行過 Claude Code 一次", file=sys.stderr)
        return 1

    _copy_hook_script()
    settings = _load_settings()

    existing = settings.get("statusLine")
    if existing and not _is_usag_hook(existing):
        settings.setdefault(BACKUP_KEY, {})[PREV_SL_KEY] = existing
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

    if _is_usag_hook(sl):
        prev = settings.get(BACKUP_KEY, {}).get(PREV_SL_KEY)
        if isinstance(prev, dict):
            settings["statusLine"] = prev
            print("✓ 已還原原有 statusLine")
        else:
            settings.pop("statusLine", None)
            print("✓ 已移除 usag statusLine")

        backup = settings.get(BACKUP_KEY)
        if isinstance(backup, dict):
            backup.pop(PREV_SL_KEY, None)
            if not backup:
                del settings[BACKUP_KEY]

        _save_settings(settings)
    else:
        print("ℹ statusLine 不是 usag 安裝的，settings 未動")

    if HOOK_TARGET.exists():
        HOOK_TARGET.unlink()
        print(f"✓ 已刪除 hook：{HOOK_TARGET}")

    if STATUS_FILE.exists():
        STATUS_FILE.unlink()
        print(f"✓ 已刪除狀態檔：{STATUS_FILE}")

    return 0

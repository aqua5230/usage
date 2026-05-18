#!/usr/bin/env python3
"""Claude Code statusLine hook：把 Claude Code 推來的狀態 JSON 持久化到磁碟。

Claude Code 每次刷新 statusLine 時會把當前 session 的完整 JSON
（含 rate_limits.five_hour / seven_day、context_window、cost 等）
從 stdin 傳給這個 script。我們只負責落地到 usage-status.json，
不輸出任何 statusLine 文字，避免覆蓋使用者自訂版面。

usage 主程式會反向讀這個檔，呈現給 menubar / TUI。

刻意只用標準庫，方便用系統 python3 跑。
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from typing import Any

__version__ = "1.0"

STATUS_FILE = os.path.expanduser("~/.claude/usage-status.json")


def save(data: dict[str, Any], now: datetime) -> None:
    data["_received_at"] = now.isoformat()
    data["_received_at_ts"] = now.timestamp()
    target_dir = os.path.dirname(STATUS_FILE)
    os.makedirs(target_dir, exist_ok=True)
    tmp_path: str | None = None
    try:
        fd, tmp_path = tempfile.mkstemp(dir=target_dir, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp_path, STATUS_FILE)
        tmp_path = None
    finally:
        if tmp_path and os.path.exists(tmp_path):
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)


def main() -> None:
    try:
        raw = sys.stdin.read()
    except Exception:
        return
    if not raw.strip():
        return
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return
    if not isinstance(data, dict):
        return
    save(data, datetime.now(timezone.utc))


if __name__ == "__main__":
    main()

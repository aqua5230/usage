#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""usage UserPromptSubmit hook — re-inject a terse-mode reminder on each user message.

Claude Code runs this every time the user submits a prompt and pipes the session
JSON on stdin. ``usage_terse_mode.py`` only fires once at SessionStart; over a long
conversation the terse style drifts back to verbose. This hook appends a one-line
bracketed nudge — not a request the model must answer — so terseness holds across
turns. Code, commands, paths, and error messages are explicitly left byte-exact.

Stdlib-only and 3.9-safe — same constraint as ``usage_statusline.py`` and
``usage_terse_mode.py``: it may run under macOS's bundled ``/usr/bin/python3``
(3.9), so no third-party imports, no ``datetime.UTC``, no runtime ``X | Y``
types. The reminder wording lives in the same sidecar written by ``setup_hook``
(``~/.claude/usage-terse-prompt.json``, the ``reminder`` field per language); if
that file or field is missing, this script falls back to embedded defaults. Any
failure exits 0 with no output.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

__version__ = "1.0"

PROMPT_SIDECAR = Path(os.path.expanduser("~/.claude/usage-terse-prompt.json"))

_DEFAULT_REMINDER: dict[str, str] = {
    "zh-TW": (
        "[精簡模式仍生效：這則回覆保持精簡；程式碼、指令、路徑、錯誤訊息照舊一字不改；"
        "安全警示與不可逆操作確認仍要講完整。]"
    ),
    "en": (
        "[Terse mode is still on: keep this reply brief; code, commands, paths, and "
        "error messages stay byte-exact; security warnings and irreversible-action "
        "confirmations must still be written out in full.]"
    ),
    "zh-CN": (
        "[精简模式仍生效：这则回复保持精简；代码、指令、路径、错误信息照旧一字不改；"
        "安全警示与不可逆操作确认仍要讲完整。]"
    ),
    "ja": (
        "[簡潔モードは引き続き有効：この返信は簡潔に；コード、コマンド、パス、エラー"
        "メッセージは一字そのまま；セキュリティ警告と不可逆操作の確認は引き続き完全に"
        "記述すること。]"
    ),
    "ko": (
        "[간결 모드 계속 적용 중: 이 답변은 짧게; 코드, 명령어, 경로, 오류 메시지는 한 "
        "글자 그대로; 보안 경고와 되돌릴 수 없는 작업 확인은 여전히 완전히 적을 것.]"
    ),
}


def _detect_lang() -> str:
    for key in ("USAGE_LANG", "TT_LANG", "LANG"):
        value = os.environ.get(key, "").strip()
        if value:
            return _normalize_lang(value)
    return "en"


def _normalize_lang(code: str) -> str:
    normalized = code.split(".")[0].strip().lower().replace("_", "-")
    if normalized in {"zh-tw", "zh-hk", "zh-hant"} or normalized.startswith(("zh-tw-", "zh-hant")):
        return "zh-TW"
    if normalized in {"zh-cn", "zh-sg", "zh-hans", "zh"} or normalized.startswith(
        ("zh-cn-", "zh-hans")
    ):
        return "zh-CN"
    if normalized.startswith("ja"):
        return "ja"
    if normalized.startswith("ko"):
        return "ko"
    return "en"


def _load_reminder(lang: str) -> str:
    try:
        raw = json.loads(PROMPT_SIDECAR.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raw = None
    if isinstance(raw, dict):
        table = raw.get(lang)
        if isinstance(table, dict):
            reminder = table.get("reminder")
            if isinstance(reminder, str) and reminder:
                return reminder
        table = raw.get("en")
        if isinstance(table, dict):
            reminder = table.get("reminder")
            if isinstance(reminder, str) and reminder:
                return reminder
    return _DEFAULT_REMINDER.get(lang, _DEFAULT_REMINDER["en"])


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except (OSError, ValueError, TypeError):
        return 0
    if not isinstance(payload, dict):
        return 0
    output: dict[str, Any] = {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": _load_reminder(_detect_lang()),
        }
    }
    print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

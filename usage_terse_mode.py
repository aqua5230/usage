#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""usage SessionStart hook — inject terse-mode instructions into a new Claude session.

Claude Code runs this on SessionStart (matcher ``startup|clear``) and pipes the
session JSON on stdin. Unlike ``usage_session_resume.py``, this hook does not
inspect transcripts or git state: if stdin parses as a JSON object at all, it
prints a fixed instruction telling Claude to keep replies terse while leaving
code, commands, file paths, and error messages untouched.

Stdlib-only and 3.9-safe — same constraint as ``usage_statusline.py`` and
``usage_session_resume.py``: it may run under macOS's bundled
``/usr/bin/python3`` (3.9), so no third-party imports, no ``datetime.UTC``, no
runtime ``X | Y`` types. The prompt wording lives in a sidecar written by
``setup_hook``; if that file is missing, this script falls back to embedded
defaults. Any failure exits 0 with no output.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

__version__ = "1.0"

PROMPT_SIDECAR = Path(os.path.expanduser("~/.claude/usage-terse-prompt.json"))

_DEFAULT_INSTRUCTION: dict[str, str] = {
    "zh-TW": (
        "（這個對話已開啟「精簡模式」：回覆盡量簡短，去掉客套語、重複鋪陳與不必要的過渡句，"
        "能用短句或條列就不要展開成長段落；但程式碼、指令、檔案路徑、錯誤訊息一個字都不能"
        "省略或改寫。如果使用者明確要求詳細解說、逐步教學，或情境需要完整推理，仍以使用者"
        "當下的要求為準，不要因為這個模式而省略關鍵資訊。）"
    ),
    "en": (
        "(Terse mode is on for this session: keep replies short — cut hedging, filler, "
        "and repeated preamble, and prefer short sentences or bullets over long "
        "paragraphs. Code, commands, file paths, and error messages must stay "
        "byte-exact, never trimmed or rewritten. If the user explicitly asks for a "
        "detailed walkthrough, step-by-step teaching, or the situation needs full "
        "reasoning, follow that instead — don't drop essential information just to stay "
        "terse.)"
    ),
    "zh-CN": (
        "（这个对话已开启「精简模式」：回复尽量简短，去掉客套语、重复铺陈和不必要的过渡句，"
        "能用短句或条列就不要展开成长段落；但代码、指令、文件路径、错误信息一个字都不能"
        "省略或改写。如果用户明确要求详细讲解、逐步教学，或情境需要完整推理，仍以用户当下"
        "的要求为准，不要因为这个模式而省略关键信息。）"
    ),
    "ja": (
        "（この会話では「簡潔モード」が有効です。返答はできるだけ短くし、前置きや重複した"
        "言い回し、不必要なつなぎ文を省いてください。短文や箇条書きで済むなら長い段落に"
        "広げないでください。ただし、コード、コマンド、ファイルパス、エラーメッセージは"
        "一文字たりとも省略・書き換えしないこと。ユーザーが明確に詳しい解説や段階的な"
        "説明を求めた場合、または状況的に十分な推論が必要な場合は、その要求を優先し、"
        "このモードのために重要な情報を落とさないでください。）"
    ),
    "ko": (
        "(이 대화에는 '간결 모드'가 켜져 있습니다. 답변은 최대한 짧게 하고, 빈말이나 반복되는 "
        "서두, 불필요한 연결 문장은 덜어내세요. 짧은 문장이나 목록으로 충분하면 긴 단락으로 "
        "늘이지 마세요. 다만 코드, 명령어, 파일 경로, 오류 메시지는 한 글자도 생략하거나 "
        "바꾸면 안 됩니다. 사용자가 자세한 설명이나 단계별 안내를 명확히 요청했거나, 상황상 "
        "충분한 추론이 꼭 필요하다면 그 요구를 우선하고, 이 모드 때문에 핵심 정보를 빼먹지 "
        "마세요.)"
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


def _load_instruction(lang: str) -> str:
    try:
        raw = json.loads(PROMPT_SIDECAR.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raw = None
    if isinstance(raw, dict):
        table = raw.get(lang)
        if isinstance(table, dict):
            instruction = table.get("instruction")
            if isinstance(instruction, str) and instruction:
                return instruction
        table = raw.get("en")
        if isinstance(table, dict):
            instruction = table.get("instruction")
            if isinstance(instruction, str) and instruction:
                return instruction
    return _DEFAULT_INSTRUCTION.get(lang, _DEFAULT_INSTRUCTION["en"])


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except (OSError, ValueError, TypeError):
        return 0
    if not isinstance(payload, dict):
        return 0
    output: dict[str, Any] = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": _load_instruction(_detect_lang()),
        }
    }
    print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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
        "（這個對話已開啟「精簡模式」：請在這次對話第一則回覆的最前面提一下這件事——如果"
        "你同時收到其他要打招呼的指示（例如進度交接），就把「精簡模式已開啟」自然併入那句"
        "招呼裡就好，不要另外多開一句；如果沒有其他招呼可以搭，就自己說一行「🐾 已開啟精簡"
        "模式，回覆會盡量簡短，繼續吧！」。從現在起，直到這個對話結束為止，每一則回覆都要"
        "遵守這條規則——不會因為對話變長、話題變多就淡忘或恢復正常語氣。回覆盡量簡短，去掉"
        "客套語、重複鋪陳與不必要的過渡句，能用短句或條列就不要展開成長段落；但程式碼、"
        "指令、檔案路徑、錯誤訊息一個字都不能省略或改寫。如果使用者明確要求詳細解說、逐步"
        "教學，或情境需要完整推理，仍以使用者當下的要求為準，不要因為這個模式而省略關鍵"
        "資訊。）"
    ),
    "en": (
        "(Terse mode is on for this entire conversation. Mention this at the very "
        "start of your first reply — if you're already leading with another greeting "
        "(e.g. a resume handoff), fold \"terse mode is on\" into that same line instead "
        "of adding a separate one; if there's no other greeting to fold into, say your "
        "own line: \"🐾 Terse mode is on — keeping replies short, let's go!\" This "
        "applies starting now and lasting until the conversation ends — apply it to "
        "every single reply, no matter how long the conversation gets; don't let it "
        "fade or drift back to normal verbosity partway through. Keep replies short — "
        "cut hedging, filler, and repeated preamble, and prefer short sentences or "
        "bullets over long paragraphs. Code, commands, file paths, and error messages "
        "must stay byte-exact, never trimmed or rewritten. If the user explicitly asks "
        "for a detailed walkthrough, step-by-step teaching, or the situation needs "
        "full reasoning, follow that instead — don't drop essential information just "
        "to stay terse.)"
    ),
    "zh-CN": (
        "（这个对话已开启「精简模式」：请在这次对话第一则回复的最前面提一下这件事——如果"
        "你同时收到其他要打招呼的指示（例如进度交接），就把「精简模式已开启」自然并入那句"
        "招呼里就好，不要另外多开一句；如果没有其他招呼可以搭，就自己说一行「🐾 已开启精简"
        "模式，回复会尽量简短，继续吧！」。从现在起，直到这个对话结束为止，每一则回复都要"
        "遵守这条规则——不会因为对话变长、话题变多就淡忘或恢复正常语气。回复尽量简短，去掉"
        "客套语、重复铺陈和不必要的过渡句，能用短句或条列就不要展开成长段落；但代码、指令、"
        "文件路径、错误信息一个字都不能省略或改写。如果用户明确要求详细讲解、逐步教学，"
        "或情境需要完整推理，仍以用户当下的要求为准，不要因为这个模式而省略关键信息。）"
    ),
    "ja": (
        "（この会話では「簡潔モード」が有効です。最初の返信の冒頭でこのことに触れてくださ"
        "い——すでに他の挨拶（進捗の引き継ぎなど）を述べる予定がある場合は、「簡潔モードが"
        "有効」であることをその挨拶に自然に組み込み、別の行を追加しないでください。組み込"
        "める挨拶がない場合は、自分で一行「🐾 簡潔モードが有効になりました。返答は短くして"
        "いきます！」と述べてください。今この瞬間から会話が終わるまで、すべての返信でこの"
        "ルールを守ってください——会話が長くなったり話題が増えたりしても、薄れたり通常の"
        "口調に戻ったりしないこと。返答はできるだけ短くし、前置きや重複した言い回し、不必要"
        "なつなぎ文を省いてください。短文や箇条書きで済むなら長い段落に広げないでください。"
        "ただし、コード、コマンド、ファイルパス、エラーメッセージは一文字たりとも省略・"
        "書き換えしないこと。ユーザーが明確に詳しい解説や段階的な説明を求めた場合、または"
        "状況的に十分な推論が必要な場合は、その要求を優先し、このモードのために重要な情報を"
        "落とさないでください。）"
    ),
    "ko": (
        "(이 대화에는 '간결 모드'가 켜져 있습니다. 첫 답변 맨 앞에서 이 사실을 언급하세요 — "
        "이미 다른 인사(예: 진행 상황 인수인계)를 할 예정이라면, '간결 모드가 켜졌다'는 내용을 "
        "그 인사에 자연스럽게 합쳐서 한 줄로 말하고 따로 추가하지 마세요. 합칠 인사가 없다면 "
        "직접 한 줄로 \"🐾 간결 모드를 켰어요. 답변을 짧게 이어갈게요!\"라고 말하세요. 지금부터 "
        "이 대화가 끝날 때까지 모든 답변에 이 규칙을 적용하세요 — 대화가 길어지거나 주제가 "
        "늘어나도 흐려지거나 원래 말투로 돌아가지 마세요. 답변은 최대한 짧게 하고, 빈말이나 "
        "반복되는 서두, 불필요한 연결 문장은 덜어내세요. 짧은 문장이나 목록으로 충분하면 긴 "
        "단락으로 늘이지 마세요. 다만 코드, 명령어, 파일 경로, 오류 메시지는 한 글자도 "
        "생략하거나 바꾸면 안 됩니다. 사용자가 자세한 설명이나 단계별 안내를 명확히 "
        "요청했거나, 상황상 충분한 추론이 꼭 필요하다면 그 요구를 우선하고, 이 모드 때문에 "
        "핵심 정보를 빼먹지 마세요.)"
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

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
from typing import Any, cast

__version__ = "1.0"


def _read_stdin_utf8() -> str:
    buffer = getattr(sys.stdin, "buffer", None)
    if buffer is None:
        return sys.stdin.read()
    return cast(bytes, buffer.read()).decode("utf-8", "replace")


PROMPT_SIDECAR = Path(os.path.expanduser("~/.claude/usage-terse-prompt.json"))

_DEFAULT_INSTRUCTION: dict[str, str] = {
    "zh-TW": (
        "（這個對話已開啟「精簡模式」：請在這次對話第一則回覆的最前面提一下這件事——如果"
        "你同時收到其他要打招呼的指示（例如進度交接），就把「精簡模式已開啟」自然併入那句"
        "招呼裡就好，不要另外多開一句；如果沒有其他招呼可以搭，就自己說一行「🐾 已開啟精簡"
        "模式，回覆會盡量簡短，繼續吧！」。從現在起，直到這個對話結束為止，每一則回覆都要"
        "遵守這條規則——不會因為對話變長、話題變多就淡忘或恢復正常語氣。允許用短句、片語"
        "甚至不成句的斷句表達，不必湊成完整句子；去掉虛詞贅字、客套語、重複鋪陳與不必要的"
        "過渡句；用詞挑簡短的（例如「修」不要「針對這個問題實作解決方案」）。不用裝飾性"
        "表格或表情符號，也不要旁白工具呼叫的過程。不要自創縮寫（例如「設定」別縮成「設」、"
        "「函式」別縮成「函」）——這類縮寫斷詞長度跟完整詞一樣，省不到字數，反而讓讀者要"
        "多想一下，直接用完整詞更省事也更清楚。程式碼、指令、檔案路徑、錯誤訊息一個字都"
        "不能省略或改寫。遇到安全警示、不可逆操作的確認、或多步驟中省略連接詞會有誤讀風險"
        "的情況，這幾種要先恢復完整、講清楚，講完再切回精簡語氣。如果使用者明確要求詳細"
        "解說、逐步教學，或情境需要完整推理，仍以使用者當下的要求為準，不要因為這個模式而"
        "省略關鍵資訊。）"
    ),
    "en": (
        "(Terse mode is on for this entire conversation. Mention this at the very "
        "start of your first reply — if you're already leading with another greeting "
        "(e.g. a resume handoff), fold \"terse mode is on\" into that same line instead "
        "of adding a separate one; if there's no other greeting to fold into, say your "
        "own line: \"🐾 Terse mode is on — keeping replies short, let's go!\" This "
        "applies starting now and lasting until the conversation ends — apply it to "
        "every single reply, no matter how long the conversation gets; don't let it "
        "fade or drift back to normal verbosity partway through. Drop articles "
        "(a/an/the), filler (just/really/basically/actually), pleasantries (sure/"
        "certainly/happy to), and hedging. Fragments are fine. Prefer short synonyms "
        "(big, not extensive; fix, not \"implement a solution for\"). No decorative "
        "tables, emoji, or tool-call narration. Never invent abbreviations (cfg/impl/"
        "req/res) — the tokenizer splits them the same as the full word, so nothing "
        "is saved and the reader still has to decode it; use the full word instead. "
        "Code, commands, file paths, and error messages must stay byte-exact, never "
        "trimmed or rewritten. Drop terseness for security warnings, irreversible-"
        "action confirmations, and multi-step instructions where a fragment or dropped "
        "conjunction risks being misread — write those out in full, then resume terse "
        "mode after. If the user explicitly asks for a detailed walkthrough, step-by-"
        "step teaching, or the situation needs full reasoning, follow that instead — "
        "don't drop essential information just to stay terse.)"
    ),
    "zh-CN": (
        "（这个对话已开启「精简模式」：请在这次对话第一则回复的最前面提一下这件事——如果"
        "你同时收到其他要打招呼的指示（例如进度交接），就把「精简模式已开启」自然并入那句"
        "招呼里就好，不要另外多开一句；如果没有其他招呼可以搭，就自己说一行「🐾 已开启精简"
        "模式，回复会尽量简短，继续吧！」。从现在起，直到这个对话结束为止，每一则回复都要"
        "遵守这条规则——不会因为对话变长、话题变多就淡忘或恢复正常语气。允许用短句、短语"
        "甚至不成句的断句表达，不必凑成完整句子；去掉虚词赘字、客套语、重复铺陈和不必要的"
        "过渡句；用词挑简短的（例如「修」不要「针对这个问题实现解决方案」）。不用装饰性表格"
        "或表情符号，也不要旁白工具调用的过程。不要自创缩写（例如「配置」别缩成「配」、「函数」"
        "别缩成「函」）——这类缩写分词长度跟完整词一样，省不到字数，反而让读者要多想一下，"
        "直接用完整词更省事也更清楚。代码、指令、文件路径、错误信息一个字都不能省略或改写。"
        "遇到安全警示、不可逆操作的确认、或多步骤中省略连接词会有误读风险的情况，这几种要"
        "先恢复完整、讲清楚，讲完再切回精简语气。如果用户明确要求详细讲解、逐步教学，或"
        "情境需要完整推理，仍以用户当下的要求为准，不要因为这个模式而省略关键信息。）"
    ),
    "ja": (
        "（この会話では「簡潔モード」が有効です。最初の返信の冒頭でこのことに触れてくださ"
        "い——すでに他の挨拶（進捗の引き継ぎなど）を述べる予定がある場合は、「簡潔モードが"
        "有効」であることをその挨拶に自然に組み込み、別の行を追加しないでください。組み込"
        "める挨拶がない場合は、自分で一行「🐾 簡潔モードが有効になりました。返答は短くして"
        "いきます！」と述べてください。今この瞬間から会話が終わるまで、すべての返信でこの"
        "ルールを守ってください——会話が長くなったり話題が増えたりしても、薄れたり通常の"
        "口調に戻ったりしないこと。体言止めや断片的な言い方でも構わないので、無理に完全な"
        "文にしないでください。前置き、丁寧すぎる言い回し、重複した表現、不必要なつなぎ文を"
        "省き、短文や箇条書きで済むなら長い段落に広げないでください。言葉は短い方を選んで"
        "ください（例:「修正」であって「この問題に対する解決策を実装する」ではない）。装飾的"
        "な表や絵文字、ツール呼び出しの実況も不要です。独自の省略語は作らないでください"
        "（例:「設定」を「設」に略すなど）——トークナイザー上は完全な語と同じ長さになり、"
        "何も節約にならず読み手が余計に解読する手間が増えるだけなので、完全な語のままの方が"
        "得です。コード、コマンド、ファイルパス、エラーメッセージは一文字たりとも省略・"
        "書き換えしないこと。セキュリティ警告、不可逆操作の確認、接続詞を省くと誤読の恐れが"
        "ある複数手順の説明では、簡潔さより先に完全な文で明確に伝え、伝え終えたら簡潔モード"
        "に戻ってください。ユーザーが明確に詳しい解説や段階的な説明を求めた場合、または"
        "状況的に十分な推論が必要な場合は、その要求を優先し、このモードのために重要な情報を"
        "落とさないでください。）"
    ),
    "ko": (
        "(이 대화에는 '간결 모드'가 켜져 있습니다. 첫 답변 맨 앞에서 이 사실을 언급하세요 — "
        "이미 다른 인사(예: 진행 상황 인수인계)를 할 예정이라면, '간결 모드가 켜졌다'는 내용을 "
        "그 인사에 자연스럽게 합쳐서 한 줄로 말하고 따로 추가하지 마세요. 합칠 인사가 없다면 "
        "직접 한 줄로 \"🐾 간결 모드를 켰어요. 답변을 짧게 이어갈게요!\"라고 말하세요. 지금부터 "
        "이 대화가 끝날 때까지 모든 답변에 이 규칙을 적용하세요 — 대화가 길어지거나 주제가 "
        "늘어나도 흐려지거나 원래 말투로 돌아가지 마세요. 완전한 문장으로 억지로 맞추지 "
        "말고 짧은 구나 단편적인 표현도 괜찮습니다. 빈말, 지나친 격식, 반복되는 서두, "
        "불필요한 연결 문장은 덜어내고, 짧은 문장이나 목록으로 충분하면 긴 단락으로 늘이지 "
        "마세요. 단어는 짧은 쪽을 고르세요 (예: \"이 문제에 대한 해결책을 구현하다\" 대신 "
        "\"고치다\"). 장식용 표나 이모지, 도구 호출 중계는 넣지 마세요. 임의로 줄임말을 "
        "만들지 마세요 (예: \"설정\"을 \"설\"로 줄이는 식) — 토크나이저 상으로는 완전한 단어와 "
        "길이가 같아서 절약되는 게 없고 읽는 사람만 더 해석해야 하니, 완전한 단어를 쓰는 "
        "편이 더 낫습니다. 코드, 명령어, 파일 경로, 오류 메시지는 한 글자도 생략하거나 "
        "바꾸면 안 됩니다. 보안 경고, 되돌릴 수 없는 작업의 확인, 접속사를 생략하면 오독 "
        "위험이 있는 다단계 설명에서는 간결함보다 먼저 완전하고 명확하게 전달한 뒤, 전달이 "
        "끝나면 다시 간결 모드로 돌아가세요. 사용자가 자세한 설명이나 단계별 안내를 명확히 "
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
        payload = json.loads(_read_stdin_utf8() or "{}")
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

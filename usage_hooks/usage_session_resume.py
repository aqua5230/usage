#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""usage SessionStart hook — inject "where you left off" into a new Claude Code session.

This is the session resume feature. Claude Code runs this on SessionStart (matcher
``startup|clear|resume``) and pipes the session JSON on stdin. For startup/clear,
it locates the project's *previous* session log, gathers the *evidence* of that
session — recent user requests, verified progress, pending todos, and the latest
usable summary or reply — and hands it to Claude via
``hookSpecificOutput.additionalContext`` with an instruction to *reason over* it rather
than transcribe it. The model that reads this is Claude itself, so the intelligence of
the handoff lives in Claude's reply, not in this script's string-formatting.

**Stdlib-only and 3.9-safe** — same constraint as ``usage_statusline.py``: it may run
under macOS's bundled ``/usr/bin/python3`` (3.9), so no third-party imports, no
``datetime.UTC``, no runtime ``X | Y`` types. The session-log parse is self-contained here
(no app imports), so the hook stays loadable under the bundled interpreter.

For resume, it may show a cache-expiry warning through ``systemMessage`` only.

When there's no fresh progress to hand over (brand-new project, the previous session
did nothing extractable, or it's older than the cutoff) the hook still checks in with
a short greeting rather than going silent.

The installer copies the ``report_rw_`` templates from ``i18n.json`` to a sidecar.
Missing templates fall back to embedded wording for the detected language.
The script never raises into the session — any failure exits 0 with no output.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, NamedTuple, TypedDict, cast

__version__ = "1.17"


class _HiddenConsoleKwargs(TypedDict, total=False):
    creationflags: int


def hidden_console_kwargs() -> _HiddenConsoleKwargs:
    if sys.platform == "win32":
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    return {}


def _configure_windows_utf8_output() -> None:
    """Make SessionStart JSON UTF-8 when Claude Code reads a Windows pipe."""
    if os.name != "nt":
        return
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, OSError, ValueError):
            # Test runners and embedders may replace the TextIOWrapper streams.
            cast(Any, stream).reconfigure(encoding="utf-8")


def _read_stdin_utf8() -> str:
    buffer = getattr(sys.stdin, "buffer", None)
    if buffer is None:
        return sys.stdin.read()
    return cast(bytes, buffer.read()).decode("utf-8", "replace")


PROMPT_SIDECAR = Path(os.path.expanduser("~/.claude/usage-resume-prompt.json"))
DIAGNOSIS_SNAPSHOT = Path(os.path.expanduser("~/.claude/usage-diagnosis.json"))
DIAGNOSIS_STATE = Path(os.path.expanduser("~/.claude/usage-diagnosis-state.json"))

# Only a heredoc that feeds git's commit message — `-F -` / `--file -` or `-m "$(cat`.
# Anchoring on these keeps an unrelated heredoc in the same command (e.g. a python
# `<<PYEOF` script whose first line is `import ...`) from being mistaken for a title.
_COMMIT_HEREDOC = re.compile(
    r"""(?:-F\s*-?|--file[=\s]\s*-?|\$\(\s*cat)\s*<<-?\s*['"]?\w+['"]?\s*\n(.+?)\n""", re.S
)
_COMMIT_INLINE = re.compile(r"""-m\s+["']([^"'\n]{4,90})""")
_MAX_AGE_DAYS = 30
_MAX_COMMITS = 3
_MAX_DONE_ITEMS = 5
_MAX_TODOS = 5
_MAX_FILES = 5
_MAX_UNCOMMITTED_FILES = 3
_MAX_REQUESTS = 3
_MAX_REQUEST_CHARS = 280
# Claude Code caps its recap at 400 characters (2.1.236); this only guards odd input.
_MAX_SUMMARY_CHARS = 400
_MAX_LAST_REPLY_CHARS = 200
_MIN_SUBSTANTIVE_CHARS = 7
_IMAGE_MARKER = re.compile(r"\[Image(?:\s+#[0-9]+)?\]", re.I)
# User turns Claude Code writes on the user's behalf: background-task notices, `!` shell
# runs, and local command output. Matched exactly so a user's own `<Task>` prompt survives.
_SYSTEM_TURN_PREFIXES = (
    "<task-notification>",
    "<bash-input>",
    "<bash-stdout>",
    "<bash-stderr>",
    "<local-command-stdout>",
)
_SLASH_COMMAND_PREFIXES = ("<command-name>", "<command-message>")
_SLASH_COMMAND_NAME = re.compile(r"<command-name>(.*?)</command-name>")
_SLASH_COMMAND_ARGS = re.compile(r"<command-args>(.*?)</command-args>")
_BASH_INPUT = re.compile(r"<bash-input>(.*?)</bash-input>", re.S)
_BASH_OUTPUT = re.compile(r"<bash-(stdout|stderr)>(.*?)</bash-\1>", re.S)
# gh returned "unknown flag:" for PR #373 and "GraphQL:" for denied auto-merges
# and merge conflicts. Git can write ordinary progress to stderr; match errors instead.
_BASH_FAILURE = re.compile(
    r"^\s*(?:error:|fatal:|unknown flag:|GraphQL:|gh:|failed to |remote:\s*(?:error:|fatal:))"
    r"|\[(?:rejected|remote rejected|remote failure)\]"
    r"|\b(?:permission denied|command not found|(?:merge|push|tag) failed)\b"
    r"|\bexit (?:code|status)\s+[1-9][0-9]*\b",
    re.I | re.M,
)
# Protect separators inside quotes and escaped characters. The remaining shell syntax
# is kept out of closeout detection when it requires interpreting the shell.
_SHELL_SYNTAX = re.compile(
    r"""\\[\s\S]|'[^']*'|"(?:\\[\s\S]|[^"\\])*"|&&|\|[|&]|<<|[;&|()<>{}`#\n'"]"""
)
_SHELL_CONTROL_WORDS = {
    "if",
    "then",
    "elif",
    "else",
    "fi",
    "for",
    "while",
    "until",
    "case",
    "esac",
    "do",
    "done",
}
_TAG_LIST_FLAGS = {
    "--list",
    "--delete",
    "--verify",
    "--contains",
    "--no-contains",
    "--merged",
    "--no-merged",
    "--points-at",
    "--format",
    "--column",
    "--sort",
    "--ignore-case",
    "--help",
}
_TAG_NAME = re.compile(r"""[^\s~^:?*\[\\$`<>"';&|(){}]+""")
# Fenced blocks go; inline code keeps its text ("the old `usage.app`" keeps the app name).
_REPLY_CODE = re.compile(r"```[\s\S]*?(?:```|\Z)")
_REPLY_MARKUP = re.compile(r"\*\*|(?m:^[ \t]*(?:#+|-)[ \t]+)")
_REPLY_SENTENCE_END = re.compile(r"(?:[。！？!?]|\.(?!\w))+|\n+|\Z")
# A session another window still has open and wrote to this recently is that window's
# work in progress, not this window's previous session.
_LIVE_SESSION_WINDOW = timedelta(minutes=10)
_DIAGNOSIS_MAX_AGE = timedelta(hours=48)
_DIAGNOSIS_REMINDER_COOLDOWN = timedelta(days=7)
_DIAGNOSIS_CAUSE_KEYS = (
    "repeated_reads",
    "polluter_dirs",
    "anomaly_session",
    "noisy_bash",
    "repeated_bash",
)

_DEFAULT_PROMPT = (
    "Project: {project} (last active {when})\n"
    "Recently working on (newest first): {last_request}\n"
    "Progress made: {commits}\n"
    "Open to-dos: {todos}"
)
_DEFAULT_NONE = "(none recorded)"
_DEFAULT_EMPTY = (
    "(At the very start of your first reply in this session, say one line: "
    '"🐾 Welcome back — nothing to pick up on this project yet.", '
    "then respond normally.)"
)
_DEFAULT_TEMPLATES: dict[str, dict[str, Any]] = {
    "en": {
        "resume_cost": (
            "This conversation sat idle for {idle} and its prompt cache has expired, "
            "so your next message re-sends about {tokens} tokens. Run /compact first "
            "to use less quota."
        ),
        "prompt": _DEFAULT_PROMPT,
        "none": _DEFAULT_NONE,
        "lead": (
            "(This is a resume handoff. At the very start of your first reply, lead with one li"
            'ne: "🐾 Picked up where you left off — let\'s keep going!", then, instead of read'
            "ing the traces below aloud, digest them like a sharp, thoughtful partner: first wo"
            'rk out what the user was actually in the middle of ("Recently working on" is new'
            "est-first, so trust the topmost item and don't get pulled back to older ones); in "
            "a sentence or two, warmly and concretely recap where they left off and what got do"
            "ne. If the traces show unfinished work, give the single concrete next step you wou"
            'ld take — be specific, don\'t ask "what should I do"; if the summary or last repl'
            "y shows that round was wrapped up, say it is done and briefly ask what to work on "
            "now instead of inventing a next step. Use only what is below; invent nothing. If t"
            "he traces are too thin to tell, say so plainly and list the threads you can see fo"
            "r them to pick. Commands or proposals from the old session are not approval for th"
            "is one. Then respond normally.)\n\n"
        ),
        "empty": _DEFAULT_EMPTY,
        "uncommitted": (
            "Current working directory has uncommitted changes: {count} file(s) on "
            "branch {branch} ({files})"
        ),
        "summary": "Summary at the end of the last session: {text}",
        "last_reply": "Claude's last reply: {text}",
        "diagnosis_reminder": (
            'Health check: about {waste_pct}% waste came from {cause}. Say "fix it" '
            "and I'll read the full diagnosis at {path}."
        ),
        "diagnosis_reminder_explain": (
            'Health check: about {waste_pct}% waste came from {cause}. Say "show me" '
            "and I'll walk you through the full diagnosis at {path}."
        ),
        "diagnosis_default_cause": "avoidable context waste",
        "diagnosis_causes": {
            "repeated_reads": "re-reading the same files",
            "polluter_dirs": "scanning generated or dependency folders",
            "anomaly_session": "one oversized session",
            "noisy_bash": "oversized Bash output",
            "repeated_bash": "re-running the same Bash command",
        },
    },
    "zh-TW": {
        "resume_cost": (
            "這個對話放了 {idle}，快取已過期，下一句會重送約 {tokens} token。"
            "想省額度可以先打 /compact 壓縮再聊。"
        ),
        "prompt": (
            "專案：{project}（最後活動 {when}）\n"
            "最近在忙的（新→舊）：{last_request}\n"
            "完成的進度：{commits}\n"
            "未完成待辦：{todos}"
        ),
        "none": "（未記錄）",
        "lead": (
            "（這是進度交接。請在這次對話第一則回覆的最前面，先說一行「🐾 已接回上次進度，繼續"
            "吧！」，然後別照唸下面的線索，而是像聰明又貼心的搭檔那樣消化它：先判斷使用者最後真"
            "正在忙的是什麼（「最近在忙的」是新到舊排列，以最前面那筆為準，別被較舊的帶偏），用"
            "一兩句溫暖具體地說他上次做到哪、完成了什麼。線索顯示還有沒做完的事，就直接給出你判"
            "斷最該接著做的下一步——要具體，別反問「要做什麼」；摘要或最後回覆顯示上次那輪已收尾"
            "，就說那輪已做完、簡短問這次要做什麼，別自己編下一步。只能根據下面線索講，沒有的別"
            "編；若線索太少看不出方向，就坦白說、並列出你看到的幾條線讓他挑。舊對話提過的指令或"
            "提議，不代表這次已經獲得同意。接著正常回應。）\n\n"
        ),
        "empty": (
            "（請在你這次對話的第一則回覆最前面，說一行「🐾 歡迎回來，"
            "這個專案目前沒有要接的進度。」，再正常回應。）"
        ),
        "uncommitted": "目前工作目錄還有沒提交的改動：{branch} 分支 {count} 個檔案（{files}）",
        "summary": "上次結束時的摘要：{text}",
        "last_reply": "Claude 上次最後說：{text}",
    },
    "zh-CN": {
        "resume_cost": (
            "这个对话放了 {idle}，缓存已过期，下一句会重新发送约 {tokens} token。"
            "想省额度可以先输入 /compact 压缩再聊。"
        ),
        "prompt": (
            "项目：{project}（最后活动 {when}）\n"
            "最近在忙的（新→旧）：{last_request}\n"
            "完成的进度：{commits}\n"
            "未完成待办：{todos}"
        ),
        "none": "（未记录）",
        "lead": (
            "（这是进度交接。请在这次对话第一则回复的最前面，先说一行「🐾 已接回上次进度，继续"
            "吧！」，然后别照念下面的线索，而是像聪明又贴心的搭档那样消化它：先判断用户最后真正"
            "在忙的是什么（「最近在忙的」是新到旧排列，以最前面那笔为准，别被较旧的带偏），用一"
            "两句温暖具体地说他上次做到哪、完成了什么。线索显示还有没做完的事，就直接给出你判断"
            "最该接着做的下一步——要具体，别反问「要做什么」；摘要或最后回复显示上次那轮已收尾，"
            "就说那轮已做完、简短问这次要做什么，别自己编下一步。只能根据下面线索讲，没有的别编"
            "；若线索太少看不出方向，就坦白说、并列出你看到的几条线让他挑。旧对话提过的指令或提"
            "议，不代表这次已经获得同意。接着正常回应。）\n\n"
        ),
        "empty": (
            "（请在你这次对话的第一则回复最前面，说一行「🐾 欢迎回来，"
            "这个项目目前没有要接的进度。」，再正常回应。）"
        ),
        "uncommitted": "当前工作目录还有未提交的改动：{branch} 分支 {count} 个文件（{files}）",
        "summary": "上次结束时的摘要：{text}",
        "last_reply": "Claude 上次最后说：{text}",
    },
    "ja": {
        "resume_cost": (
            "この会話は {idle} 放置され、プロンプトキャッシュが切れています。"
            "次のメッセージで約 {tokens} トークンを再送信します。"
            "クォータを節約するには、先に /compact で圧縮してください。"
        ),
        "prompt": (
            "プロジェクト：{project}（最終アクティブ {when}）\n"
            "最近の作業（新しい順）：{last_request}\n"
            "完了した進捗：{commits}\n"
            "未完了のToDo：{todos}"
        ),
        "none": "（記録なし）",
        "lead": (
            "（これは進捗の引き継ぎです。最初の返信の冒頭で、まず一行「🐾 前回の続きを引き継ぎ"
            "ました！そのまま続けましょう！」と述べ、下記の手がかりをそのまま読み上げるのではな"
            "く、賢く気の利いた相棒のように消化してください：まずユーザーが最後に実際に取り組ん"
            "でいたことを見極め（「最近の作業」は新しい順なので、先頭の項目を信頼し、古いものに"
            "引きずられないこと）、前回どこまで進んだか・何が完了したかを一、二文で温かく具体的"
            "に振り返ってください。まだ終わっていない作業が手がかりにあれば、次に取るべき具体的"
            "な一歩を提示してください——具体的に述べ、「何をしますか」と聞き返さないこと。要約や"
            "最後の返信で前回の作業が完了していれば、完了したと伝えて今回何をするか短く尋ね、次"
            "の一歩を作り出さないこと。下記にある情報だけを使い、無いことは創作しないこと。手が"
            "かりが乏しくて判断できない場合は正直にそう述べ、見えるスレッドを挙げて選んでもらう"
            "こと。前の会話で出た指示や提案は、今回の承認にはなりません。その後、通常どおり応答"
            "してください。）\n\n"
        ),
        "empty": (
            "（このセッションの最初の返信の冒頭に、一行「🐾 おかえりなさい！"
            "このプロジェクトはまだ引き継ぐ進捗がありません。」と述べてから、"
            "通常どおり応答してください。）"
        ),
        "uncommitted": (
            "現在の作業ディレクトリに未コミットの変更があります："
            "{branch} ブランチの {count} ファイル（{files}）"
        ),
        "summary": "前回の終了時の要約：{text}",
        "last_reply": "Claude の前回の最後の返信：{text}",
    },
    "ko": {
        "resume_cost": (
            "이 대화는 {idle} 동안 방치되어 프롬프트 캐시가 만료되었습니다. "
            "다음 메시지에서 약 {tokens} 토큰을 다시 보냅니다. "
            "할당량을 아끼려면 먼저 /compact로 압축하세요."
        ),
        "prompt": (
            "프로젝트: {project} (마지막 활동 {when})\n"
            "최근 작업한 내용 (최신순): {last_request}\n"
            "완료한 진행: {commits}\n"
            "미완료 할 일: {todos}"
        ),
        "none": "(기록 없음)",
        "lead": (
            '(이것은 진행 상황 인수인계입니다. 첫 답변 맨 앞에 먼저 한 줄 "🐾 지난 작업을 불러'
            '왔어요! 이어서 가볼까요?"라고 말한 뒤, 아래 단서를 그대로 읽지 말고 똑똑하고 사려'
            " 깊은 동료처럼 소화하세요: 먼저 사용자가 마지막에 실제로 무엇을 하고 있었는지 파악"
            '하고("최근 작업한 내용"은 최신순이므로 맨 위 항목을 신뢰하고 오래된 것에 끌려가'
            "지 마세요), 지난번에 어디까지 했고 무엇을 완료했는지 한두 문장으로 따뜻하고 구체적"
            "으로 짚어 주세요. 아직 끝나지 않은 작업이 단서에 보이면 이어서 취해야 할 구체적인 "
            '다음 단계 하나를 제시하세요 — 구체적으로 말하고 "무엇을 할까요"라고 되묻지 마세'
            "요. 요약이나 마지막 답변에서 지난 작업이 마무리됐다면 끝났다고 말하고 이번에 무엇"
            "을 할지 짧게 물어보되, 다음 단계를 지어내지 마세요. 아래 있는 내용만 사용하고 없는"
            " 것은 지어내지 마세요. 단서가 너무 적어 판단하기 어려우면 솔직히 그렇게 말하고 보"
            "이는 갈래들을 나열해 고르게 하세요. 이전 대화에서 나온 명령이나 제안은 이번 승인으"
            "로 보지 마세요. 그런 다음 평소대로 응답하세요.)\n\n"
        ),
        "empty": (
            '(이 세션의 첫 답변 맨 앞에 한 줄 "🐾 돌아오셨네요! '
            '이 프로젝트는 아직 이어갈 내용이 없어요."라고 말한 뒤 평소대로 응답하세요.)'
        ),
        "uncommitted": (
            "현재 작업 디렉터리에 커밋하지 않은 변경 사항이 있습니다: "
            "{branch} 브랜치의 파일 {count}개 ({files})"
        ),
        "summary": "지난 세션 종료 요약: {text}",
        "last_reply": "Claude의 지난 마지막 답변: {text}",
    },
}


class _ResumeTemplates(NamedTuple):
    lead: str
    prompt: str
    none: str
    empty: str
    uncommitted: str
    summary: str
    last_reply: str
    diagnosis_reminder: str
    diagnosis_reminder_explain: str
    diagnosis_default_cause: str
    diagnosis_causes: dict[str, str]


class _SessionEvidence(NamedTuple):
    last_active: datetime
    recent_requests: str
    commits: list[str]
    todos: list[str]
    edited_files: list[str]
    closeouts: list[str]
    summary: str
    last_reply: str


def main() -> int:
    _configure_windows_utf8_output()
    try:
        payload = json.loads(_read_stdin_utf8() or "{}")
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0
    if payload.get("source") == "fork":
        return 0
    try:
        output: dict[str, Any] | None
        if payload.get("source") == "resume":
            message = _build_resume_cost_message(payload)
            output = {"systemMessage": message} if message else None
        else:
            prompt = _build_prompt(payload)
            output = (
                {
                    "hookSpecificOutput": {
                        "hookEventName": "SessionStart",
                        "additionalContext": prompt,
                    }
                }
                if prompt
                else None
            )
    except Exception:
        return 0
    if output is None:
        return 0
    try:
        print(json.dumps(output, ensure_ascii=True))
    except Exception:
        return 0
    return 0


def _build_resume_cost_message(payload: dict[str, Any]) -> str:
    if payload.get("prompt_cache_likely_expired") is not True:
        return ""
    tokens = payload.get("context_tokens")
    idle = payload.get("seconds_since_last_response")
    if isinstance(tokens, bool) or not isinstance(tokens, int) or tokens < 50_000:
        return ""
    if isinstance(idle, bool) or not isinstance(idle, (int, float)) or idle < 0:
        return ""
    lang = _detect_lang()
    template = cast(str, _DEFAULT_TEMPLATES[lang]["resume_cost"])
    try:
        bundle = json.loads(PROMPT_SIDECAR.read_text(encoding="utf-8"))
        entry = bundle.get(lang) if isinstance(bundle, dict) else None
        candidate = entry.get("resume_cost") if isinstance(entry, dict) else None
        if isinstance(candidate, str) and candidate:
            template = candidate
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    return template.format(idle=_fmt_duration(idle), tokens=_fmt_tokens(tokens))


def _fmt_duration(seconds: float) -> str:
    if seconds >= 86400:
        days = int(seconds // 86400)
        remaining = int(seconds % 86400)
        return f"{days}d{remaining // 3600}h"
    if seconds >= 3600:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h{minutes}m"
    if seconds >= 60:
        return f"{int(seconds // 60)}min"
    return f"{int(seconds)}s"


def _fmt_tokens(value: int) -> str:
    if value >= 999_950_000:
        return f"{value / 1_000_000_000:.1f}B"
    if value >= 999_500:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.0f}k"
    return str(value)


def _build_prompt(payload: dict[str, Any]) -> str:
    transcript = payload.get("transcript_path")
    cwd = payload.get("cwd")
    if not isinstance(transcript, str) or not transcript:
        return ""
    project_dir = Path(transcript).parent
    if not project_dir.is_dir():
        return ""

    templates = _load_template(_detect_lang())
    project = _project_from_cwd(cwd) if isinstance(cwd, str) and cwd else project_dir.name
    uncommitted = _git_dirty(cwd) if isinstance(cwd, str) and cwd else None
    report = _build_report(
        project_dir,
        Path(transcript).name,
        project,
        templates,
        uncommitted,
    )
    # The resume hook always checks in: when there's no fresh progress to hand over, it
    # greets instead of going silent.
    prompt = report or templates.empty
    diagnosis_instruction = _build_diagnosis_instruction(
        diagnosis_reminder=templates.diagnosis_reminder,
        diagnosis_reminder_explain=templates.diagnosis_reminder_explain,
        diagnosis_default_cause=templates.diagnosis_default_cause,
        diagnosis_causes=templates.diagnosis_causes,
    )
    if diagnosis_instruction:
        prompt += "\n\n" + diagnosis_instruction
    return prompt


def _build_report(
    project_dir: Path,
    current_name: str,
    project: str,
    templates: _ResumeTemplates,
    uncommitted: tuple[str, int, list[str]] | None,
) -> str:
    """The "I loaded your last progress" prompt, or "" when there's nothing fresh to report."""
    parsed = None
    for candidate in _other_jsonls_by_mtime(project_dir, exclude=current_name):
        parsed = _parse_session(candidate)
        if parsed is not None:
            break
    if parsed is None:
        return ""
    if parsed.last_active < _cutoff():
        return ""
    done_items = parsed.closeouts + parsed.commits[-_MAX_COMMITS:][::-1]
    done_items = done_items[:_MAX_DONE_ITEMS] or parsed.edited_files[:_MAX_FILES]
    prompt = templates.prompt
    if not parsed.todos:
        # Recent Claude Code sessions record no TodoWrite at all, so an empty to-do
        # line would read as "nothing left" when it only means "nothing recorded".
        prompt = "\n".join(
            line for line in prompt.split("\n") if "{todos}" not in line or line.count("{") > 1
        )
    report = templates.lead + prompt.format(
        project=project,
        when=_format_time(parsed.last_active),
        last_request=parsed.recent_requests or templates.none,
        commits=" · ".join(done_items) or templates.none,
        todos=" · ".join(parsed.todos[:_MAX_TODOS]) or templates.none,
    )
    if parsed.summary:
        report += "\n" + templates.summary.format(text=parsed.summary)
    elif parsed.last_reply:
        report += "\n" + templates.last_reply.format(text=parsed.last_reply)
    if uncommitted is not None:
        branch, count, files = uncommitted
        report += "\n" + templates.uncommitted.format(
            branch=branch,
            count=count,
            files=", ".join(files),
        )
    return report


def _git_dirty(cwd: str) -> tuple[str, int, list[str]] | None:
    try:
        branch_proc = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--abbrev-ref", "HEAD"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=2,
            encoding="utf-8",
            check=False,
            stdin=subprocess.DEVNULL,
            **hidden_console_kwargs(),
        )
        if branch_proc.returncode != 0:
            return None
        branch = branch_proc.stdout.strip()
        if not branch:
            return None
        status_proc = subprocess.run(
            ["git", "-C", cwd, "-c", "core.fsmonitor=false", "status", "--porcelain"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=2,
            encoding="utf-8",
            check=False,
            stdin=subprocess.DEVNULL,
            **hidden_console_kwargs(),
        )
        if status_proc.returncode != 0:
            return None
        changed = [line for line in status_proc.stdout.splitlines() if line.strip()]
        if not changed:
            return None
        files: list[str] = []
        for line in changed:
            path = line[3:].strip() if len(line) > 3 else line.strip()
            if " -> " in path:
                path = path.rsplit(" -> ", 1)[1]
            base = os.path.basename(path.strip('"').rstrip("/"))
            if base and base not in files:
                files.append(base)
            if len(files) >= _MAX_UNCOMMITTED_FILES:
                break
        return branch, len(changed), files
    except Exception:
        return None


def _cutoff() -> datetime:
    return datetime.now().astimezone() - timedelta(days=_MAX_AGE_DAYS)


def _other_jsonls_by_mtime(project_dir: Path, exclude: str) -> list[Path]:
    """Other session logs, with this window's pre-clear session first if registered.

    Newest-first so the caller can skip a freshly-written but empty/corrupt log and
    still fall back to the previous session that actually has progress to report.
    Sessions another window still has open and is still writing are left out: with
    several windows in one project, the newest log is usually a neighbour's live work.
    A session closed a moment ago is no longer registered, so it stays a candidate.
    """
    sessions_dir = project_dir.parent.parent / "sessions"
    own_pids = _own_window_pids()
    own_ids = set()
    for pid in own_pids:
        data = _read_json_file(sessions_dir / f"{pid}.json")
        session_id = data.get("sessionId") if data is not None else None
        if isinstance(session_id, str) and session_id:
            own_ids.add(session_id)
    live_ids = _live_session_ids(sessions_dir, own_pids)
    busy_since = (datetime.now() - _LIVE_SESSION_WINDOW).timestamp()
    candidates: list[tuple[float, Path]] = []
    for jsonl in project_dir.glob("*.jsonl"):
        if jsonl.name == exclude:
            continue
        try:
            mtime = jsonl.stat().st_mtime
        except OSError:
            continue
        if mtime >= busy_since and jsonl.stem in live_ids and jsonl.stem not in own_ids:
            continue
        candidates.append((mtime, jsonl))
    candidates.sort(key=lambda item: (item[1].stem in own_ids, item[0]), reverse=True)
    return [path for _, path in candidates]


def _live_session_ids(sessions_dir: Path, own_pids: set[int]) -> set[str]:
    """Session IDs that open Claude Code windows list in ``~/.claude/sessions/<pid>.json``."""
    ids: set[str] = set()
    try:
        entries = list(sessions_dir.glob("*.json"))
    except OSError:
        return ids
    for entry in entries:
        data = _read_json_file(entry)
        if data is None:
            continue
        session_id = data.get("sessionId")
        pid = data.get("pid")
        if isinstance(pid, int) and pid in own_pids:
            continue
        if isinstance(session_id, str) and session_id and _pid_running(pid):
            ids.add(session_id)
    return ids


def _own_window_pids() -> set[int]:
    """This window's Claude Code process. After /clear its registry entry may still name
    the session just cleared, which is the one to hand over."""
    pids = {os.getppid()}
    with contextlib.suppress(ValueError):
        pids.add(int(os.environ.get("CLAUDE_PID", "")))
    return pids


def _pid_running(pid: object) -> bool:
    """False for a registry entry a crashed window left behind."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    # On Windows os.kill(pid, 0) sends CTRL_C_EVENT instead of probing, so the entry
    # is trusted as is.
    if os.name == "nt":
        return True
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _parse_session(path: Path) -> _SessionEvidence | None:
    """Gather requests, verified progress, and the freshest conclusion from a session."""
    requests: dict[str, int] = {}
    seen_requests: set[str] = set()
    request_copies: dict[str, int] = {}
    previous_request = ""
    tool_uses: list[tuple[int, dict[str, Any]]] = []
    seen_tool_ids: set[str] = set()
    successful_tool_ids: set[str] = set()
    shell_inputs: dict[str, tuple[int, list[str]]] = {}
    shell_results: dict[str, bool] = {}
    last_ts: datetime | None = None
    latest_work_ts: datetime | None = None
    unknown_work_time = False
    summary = ""
    last_reply = ""

    try:
        with path.open(encoding="utf-8") as file:
            for line_number, line in enumerate(file):
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(data, dict):
                    continue
                entry_type = data.get("type")
                if entry_type == "pr-link":
                    continue
                parent_uuid = data.get("parentUuid")
                if entry_type == "user":
                    if data.get("isCompactSummary", False) is not False:
                        continue
                    if parent_uuid is not None and not isinstance(parent_uuid, str):
                        continue
                attachment = data.get("attachment")
                if entry_type == "attachment":
                    if not isinstance(attachment, dict):
                        continue
                    if attachment.get("type") == "queued_command" and not isinstance(
                        attachment.get("prompt"), (str, list)
                    ):
                        continue
                is_summary = entry_type == "system" and data.get("subtype") == "away_summary"
                summary_content = data.get("content") if is_summary else None
                if is_summary and not (
                    isinstance(summary_content, str) and summary_content.strip()
                ):
                    continue
                timestamp = _parse_timestamp(data.get("timestamp"))
                if timestamp is not None and (last_ts is None or timestamp > last_ts):
                    last_ts = timestamp
                if data.get("isMeta") is True or data.get("isSidechain") is True:
                    continue

                if entry_type == "last-prompt":
                    last_prompt = data.get("lastPrompt")
                    if isinstance(last_prompt, str) and not last_prompt.lstrip().startswith("!"):
                        text = _clean_request(last_prompt, truncate=False)
                        if text:
                            request_copies.setdefault(text, line_number)
                    continue
                if isinstance(summary_content, str):
                    summary = ""
                    if (
                        timestamp is not None
                        and not unknown_work_time
                        and (latest_work_ts is None or timestamp > latest_work_ts)
                    ):
                        summary = _ellipsize(" ".join(summary_content.split()), _MAX_SUMMARY_CHARS)
                    continue

                work = False
                if entry_type == "assistant":
                    parts = _message_parts(data.get("message"))
                    if parts:
                        previous_request = ""
                    reply_parts: list[str] = []
                    for part in parts:
                        if part.get("type") == "tool_use":
                            tool_uses.append((line_number, part))
                            tool_id = part.get("id")
                            if isinstance(tool_id, str):
                                seen_tool_ids.add(tool_id)
                            reply_parts.clear()
                            work = True
                        elif part.get("type") == "text":
                            reply_text = part.get("text")
                            if isinstance(reply_text, str) and reply_text.strip():
                                reply_parts.append(reply_text)
                                work = True
                    if work:
                        last_reply = "\n".join(reply_parts)
                elif entry_type in ("user", "attachment"):
                    if entry_type == "user":
                        parts = _message_parts(data.get("message"))
                        for part in parts:
                            tool_id = part.get("tool_use_id")
                            if (
                                part.get("type") == "tool_result"
                                and isinstance(tool_id, str)
                                and tool_id in seen_tool_ids
                                and part.get("is_error") is not True
                            ):
                                successful_tool_ids.add(tool_id)
                        origin = data.get("origin")
                        if origin is not None and not _is_human_origin(origin):
                            continue
                    else:
                        parts = _queued_prompt_parts(attachment)

                    raw_request = _text_content(parts).strip()
                    if entry_type == "user" and raw_request.startswith("<bash-input>"):
                        work = True
                        previous_request = ""
                        uuid = data.get("uuid")
                        command = _BASH_INPUT.fullmatch(raw_request)
                        if isinstance(uuid, str) and uuid and command is not None:
                            closeout_actions = _closeout_actions(command[1])
                            if closeout_actions:
                                shell_inputs[uuid] = (line_number, closeout_actions)
                    elif entry_type == "user" and raw_request.startswith(
                        ("<bash-stdout>", "<bash-stderr>")
                    ):
                        if isinstance(parent_uuid, str) and parent_uuid in shell_inputs:
                            outputs = _BASH_OUTPUT.findall(raw_request)
                            if outputs and not _BASH_OUTPUT.sub("", raw_request).strip():
                                shell_results[parent_uuid] = shell_results.get(
                                    parent_uuid, True
                                ) and not any(_BASH_FAILURE.search(output) for _, output in outputs)
                    elif _request_body(raw_request) or any(p.get("type") == "image" for p in parts):
                        work = True
                        last_reply = ""
                        text = _clean_request(raw_request, truncate=False)
                        if text:
                            if previous_request and text.startswith(previous_request):
                                requests.pop(previous_request, None)
                            requests[text] = line_number
                            seen_requests.add(text)
                        previous_request = text

                if work:
                    # The line order and timestamps must both put the summary after work.
                    summary = ""
                    if timestamp is None:
                        unknown_work_time = True
                    elif latest_work_ts is None or timestamp > latest_work_ts:
                        latest_work_ts = timestamp
    except (OSError, UnicodeDecodeError):
        return None

    commits, todos, edited_files, actions = _collect_tools(tool_uses, successful_tool_ids)
    for uuid, (line_number, shell_actions) in shell_inputs.items():
        if shell_results.get(uuid):
            actions.extend((line_number, action) for action in shell_actions)
    actions.sort(key=lambda item: item[0])
    closeouts = list(dict.fromkeys(action for _, action in reversed(actions)))

    # Copies fill gaps at their first appearance; they cannot move or revive a real request.
    requests.update(
        (text, row) for text, row in request_copies.items() if text not in seen_requests
    )
    recent = sorted(requests, key=requests.__getitem__, reverse=True)[:_MAX_REQUESTS]
    recent_requests = " · ".join(_ellipsize(text, _MAX_REQUEST_CHARS) for text in recent)
    last_reply = "" if summary else _clean_last_reply(last_reply)
    if last_ts is None or not (
        recent_requests or commits or todos or edited_files or closeouts or summary or last_reply
    ):
        return None
    return _SessionEvidence(
        last_ts, recent_requests, commits, todos, edited_files, closeouts, summary, last_reply
    )


def _is_human_origin(origin: object) -> bool:
    return isinstance(origin, dict) and origin.get("kind") == "human"


def _queued_prompt_parts(attachment: object) -> list[dict[str, Any]]:
    if not isinstance(attachment, dict) or attachment.get("type") != "queued_command":
        return []
    human_turn = attachment.get("humanTurn")
    origin = attachment.get("origin")
    if human_turn is not None and human_turn is not True:
        return []
    if not _is_human_origin(origin) and (origin is not None or human_turn is not True):
        return []
    return _content_parts(attachment.get("prompt"))


def _message_parts(message: object) -> list[dict[str, Any]]:
    return _content_parts(message.get("content")) if isinstance(message, dict) else []


def _content_parts(content: object) -> list[dict[str, Any]]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        return [part for part in content if isinstance(part, dict)]
    return []


def _text_content(parts: list[dict[str, Any]]) -> str:
    return "\n".join(
        part["text"]
        for part in parts
        if part.get("type") == "text" and isinstance(part.get("text"), str)
    )


def _request_body(value: object) -> str:
    if not isinstance(value, str):
        return ""
    text = " ".join(value.split())
    if text.startswith((*_SYSTEM_TURN_PREFIXES, "[Request interrupted")):
        return ""
    if text.startswith(_SLASH_COMMAND_PREFIXES):
        # Keep a slash command only when it carries arguments: `/loop 5m check CI` is a request.
        name = _SLASH_COMMAND_NAME.search(text)
        args = _SLASH_COMMAND_ARGS.search(text)
        if name is None or args is None or not args.group(1).strip():
            return ""
        return f"{name.group(1).strip()} {args.group(1).strip()}"
    return text


def _clean_request(value: object, *, truncate: bool = True) -> str:
    text = _request_body(value)
    starts_with_image = text.startswith("[Image")
    text = _IMAGE_MARKER.sub("", text).strip()
    substantive_len = _substantive_len(text)
    if substantive_len == 0:
        return ""
    if substantive_len < _MIN_SUBSTANTIVE_CHARS and (
        starts_with_image or not _has_structural_signal(text)
    ):
        return ""
    return _ellipsize(text, _MAX_REQUEST_CHARS) if truncate else text


def _ellipsize(text: str, limit: int) -> str:
    return text[: limit - 1].rstrip() + "…" if len(text) > limit else text


def _clean_last_reply(value: str) -> str:
    text = _REPLY_MARKUP.sub("", _REPLY_CODE.sub(" ", value).replace("`", ""))
    text = re.sub(r"[ \t]+(?=[。！？.!?,，])", "", text)
    result = ""
    for boundary in _REPLY_SENTENCE_END.finditer(text):
        candidate = " ".join(text[: boundary.end()].split())
        if len(candidate) > _MAX_LAST_REPLY_CHARS:
            break
        result = candidate
    return result if _substantive_len(result) else ""


def _substantive_len(text: str) -> int:
    return sum(1 for char in text if char.isalnum())


def _has_structural_signal(text: str) -> bool:
    markers = ("/", "\\", ".", "_", "-", "#", ":", "`", "(", ")")
    for index, char in enumerate(text):
        if char not in markers or index == 0 or index == len(text) - 1:
            continue
        if text[index - 1].isalnum() and text[index + 1].isalnum():
            return True
    return False


def _pending_todos(items: list[Any]) -> list[str]:
    result: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("status") not in ("pending", "in_progress"):
            continue
        text = item.get("content")
        if isinstance(text, str) and text.strip():
            result.append(_clean_request(text))
    return [t for t in result if t]


def _closeout_actions(command: str) -> list[str]:
    """Read simple shell command lists without evaluating or running them."""
    chunks: list[str] = []
    start = 0
    nested: list[str] = []
    complex_chunk = False
    continuation_from = 0
    for match in _SHELL_SYNTAX.finditer(command):
        token = match[0]
        if token in ("(", "{"):
            nested.append(")" if token == "(" else "}")
            complex_chunk = True
        elif token in (")", "}"):
            if not nested or nested.pop() != token:
                return []
        elif token in ("<<", "`", "#", "'", '"'):
            # Heredocs, comments, and malformed quoting can hide apparent commands.
            return []
        elif nested:
            continue
        elif token in ("&&", ";", "\n"):
            if token == "\n" and not command[continuation_from : match.start()].strip():
                continue
            if not complex_chunk:
                chunks.append(command[start : match.start()])
            start = match.end()
            continuation_from = start
            complex_chunk = False
        elif token in ("|", "||", "|&", "&", "<", ">"):
            complex_chunk = True
            if token in ("|", "||", "|&"):
                continuation_from = match.end()
        elif token.startswith('"') and ("$(" in token or "`" in token):
            complex_chunk = True
    if nested:
        return []
    if not complex_chunk:
        chunks.append(command[start:])

    actions = []
    for chunk in chunks:
        try:
            args = shlex.split(chunk)
        except ValueError:
            return []
        if args and args[0] in _SHELL_CONTROL_WORDS:
            return []
        action = _closeout_action(args)
        if action:
            actions.append(action)
    return actions


def _closeout_action(args: list[str]) -> str:
    if args[:3] == ["gh", "pr", "merge"] and len(args) >= 4:
        flags = {arg.partition("=")[0] for arg in args[4:]}
        if re.fullmatch(r"[0-9]+", args[3]) and not flags & {"--auto", "--disable-auto", "--help"}:
            return f"merged PR #{args[3]}"
    if args[:1] != ["git"]:
        return ""
    while len(args) >= 3 and args[1] in ("-C", "-c"):
        args = [args[0], *args[3:]]
    if args[:2] == ["git", "push"]:
        for arg in args[2:]:
            if (
                arg.partition("=")[0] in {"--delete", "--dry-run", "--help"}
                or re.fullmatch(r"-[a-zA-Z]*[dn][a-zA-Z]*", arg)
                or (arg.startswith(":") and arg != ":")
            ):
                return ""
        return "pushed"
    if args[:2] == ["git", "tag"]:
        tag_args = args[2:]
        if tag_args[:1] == ["-a"]:
            tag_args = tag_args[1:]
        if not tag_args or tag_args[0].startswith("-") or not _TAG_NAME.fullmatch(tag_args[0]):
            return ""
        options = iter(tag_args[1:])
        for arg in options:
            if arg.partition("=")[0] in _TAG_LIST_FLAGS or re.match(r"^-[ldvni]", arg):
                return ""
            if arg in ("-m", "--message", "-F", "--file", "-u", "--local-user"):
                next(options, None)
        return f"tagged {tag_args[0]}"
    return ""


def _collect_tools(
    tool_uses: list[tuple[int, dict[str, Any]]],
    successful_tool_ids: set[str],
) -> tuple[list[str], list[str], list[str], list[tuple[int, str]]]:
    commits: dict[str, None] = {}
    todos: list[str] = []
    edited_files: list[str] = []
    actions: list[tuple[int, str]] = []
    for line_number, part in tool_uses:
        name = part.get("name")
        raw_input = part.get("input")
        if not isinstance(raw_input, dict):
            continue
        if name == "TodoWrite":
            items = raw_input.get("todos")
            if isinstance(items, list):
                # Latest TodoWrite wins, even when it clears the list — everything got done.
                todos[:] = _pending_todos(items)
        elif not isinstance(part.get("id"), str) or part["id"] not in successful_tool_ids:
            continue
        elif name == "Bash":
            command = raw_input.get("command")
            if isinstance(command, str):
                actions.extend((line_number, action) for action in _closeout_actions(command))
                if "git commit" in command:
                    title = _extract_commit_title(command)
                    if title:
                        commits.pop(title, None)
                        commits[title] = None
        elif name in ("Edit", "Write", "NotebookEdit"):
            fp = raw_input.get("file_path")
            if isinstance(fp, str):
                base = os.path.basename(fp)
                if base and base not in edited_files:
                    edited_files.append(base)
    return list(commits), todos, edited_files, actions


def _extract_commit_title(command: str) -> str:
    heredoc = _COMMIT_HEREDOC.search(command)
    if heredoc:
        return heredoc.group(1).strip()
    inline = _COMMIT_INLINE.search(command)
    if inline:
        return inline.group(1).strip()
    return ""


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        # Older logs may omit the offset; use local time for those timestamps.
        return parsed if parsed.tzinfo is not None else parsed.astimezone()
    except (ValueError, OverflowError, OSError):
        return None


def _build_diagnosis_instruction(
    *,
    diagnosis_reminder: str,
    diagnosis_reminder_explain: str,
    diagnosis_default_cause: str,
    diagnosis_causes: Mapping[str, str],
) -> str:
    snapshot = _read_json_file(DIAGNOSIS_SNAPSHOT)
    if not isinstance(snapshot, dict):
        return ""

    now = datetime.now(timezone.utc)
    generated_at = _parse_timestamp(snapshot.get("generated_at"))
    if generated_at is None:
        return ""
    if now - generated_at.astimezone(timezone.utc) > _DIAGNOSIS_MAX_AGE:
        return ""
    if snapshot.get("has_data") is not True:
        return ""

    raw_findings = snapshot.get("findings")
    findings = raw_findings if isinstance(raw_findings, list) else []
    waste_pct = _coerce_float(snapshot.get("waste_pct"))
    has_critical = any(
        isinstance(finding, dict) and finding.get("severity") == "critical" for finding in findings
    )
    if waste_pct < 5.0 and not has_critical:
        return ""

    fingerprint = _diagnosis_fingerprint(snapshot)
    if not fingerprint:
        return ""
    if _diagnosis_cooldown_active(fingerprint, now):
        return ""

    primary = _pick_primary_finding(findings)
    kind = primary.get("kind") if isinstance(primary, dict) else None
    cause = diagnosis_causes.get(str(kind), diagnosis_default_cause)
    # When nothing is auto-fixable, don't promise a fix: invite a walkthrough instead.
    fixable_tokens = _coerce_float(snapshot.get("fixable_waste_tokens"))
    template = diagnosis_reminder if fixable_tokens > 0 else diagnosis_reminder_explain
    reminder_line = template.format(
        waste_pct=_format_percent_number(waste_pct),
        cause=cause,
        path=str(DIAGNOSIS_SNAPSHOT),
    )
    with contextlib.suppress(OSError):
        _write_diagnosis_state(
            {
                "last_fingerprint": fingerprint,
                "last_reminded_at": _format_utc_timestamp(now),
            }
        )
    return (
        "(At the end of your first reply in this session, add exactly one line: "
        + json.dumps(reminder_line, ensure_ascii=False)
        + ")"
    )


def _read_json_file(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _coerce_float(value: object) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def _pick_primary_finding(findings: object) -> dict[str, Any]:
    if not isinstance(findings, list):
        return {}

    candidates = [finding for finding in findings if isinstance(finding, dict)]
    if not candidates:
        return {}
    candidates.sort(
        key=lambda finding: (
            -int(finding.get("estimated_waste_tokens") or 0),
            0 if finding.get("severity") == "critical" else 1,
            str(finding.get("kind") or ""),
        )
    )
    return candidates[0]


def _diagnosis_fingerprint(snapshot: Mapping[str, object]) -> str:
    value = snapshot.get("findings_fingerprint")
    if isinstance(value, str) and value:
        return value
    return ""


def _diagnosis_cooldown_active(fingerprint: str, now: datetime) -> bool:
    state = _read_json_file(DIAGNOSIS_STATE)
    if not isinstance(state, dict):
        return False
    previous = state.get("last_fingerprint")
    reminded_at = _parse_timestamp(state.get("last_reminded_at"))
    if previous != fingerprint:
        return False
    if reminded_at is None:
        return False
    return now - reminded_at.astimezone(timezone.utc) < _DIAGNOSIS_REMINDER_COOLDOWN


def _write_diagnosis_state(data: Mapping[str, object]) -> None:
    DIAGNOSIS_STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(dir=str(DIAGNOSIS_STATE.parent), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.write("\n")
        os.replace(tmp_path, DIAGNOSIS_STATE)
        tmp_path = None
    finally:
        if tmp_path and os.path.exists(tmp_path):
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)


def _format_utc_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _format_percent_number(value: float) -> str:
    rounded = round(value, 1)
    if rounded.is_integer():
        return str(int(rounded))
    return str(rounded)


def _format_time(parsed: datetime) -> str:
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone()
    return f"{parsed.month}/{parsed.day} {parsed.hour:02d}:{parsed.minute:02d}"


def _project_from_cwd(cwd: str) -> str:
    home = os.path.expanduser("~")
    rel = cwd[len(home) :] if cwd.startswith(home) else cwd
    # Windows sessions read transcripts whose cwd may use either separator
    # (e.g. POSIX-style paths). POSIX filenames may legitimately contain
    # backslashes, so only normalize them on Windows.
    if sys.platform == "win32":
        rel = rel.replace("\\", "/")
        sep = "/"
    else:
        sep = os.sep
    rel = rel.strip(sep)
    parts = rel.split(sep)
    return parts[-1] if parts and parts[-1] else (rel or "unknown")


def _windows_system_lang() -> str:
    if os.name != "nt":
        return ""
    try:
        import ctypes
        import locale as _locale

        windll = getattr(ctypes, "windll", None)
        if windll is None:
            return ""
        lang_id = int(windll.kernel32.GetUserDefaultUILanguage())
        return _locale.windows_locale.get(lang_id, "") or ""
    except Exception:
        return ""


def _detect_lang() -> str:
    # Windows 上的 LANG 多半是 Git Bash / MSYS 帶進來的，不代表使用者的系統語言。
    keys = (
        ("USAGE_LANG", "TT_LANG") if sys.platform == "win32" else ("USAGE_LANG", "TT_LANG", "LANG")
    )
    for key in keys:
        value = os.environ.get(key, "").strip()
        if value:
            return _normalize_lang(value)
    return _normalize_lang(_windows_system_lang())


def _normalize_lang(code: str) -> str:
    normalized = code.split(".")[0].split("@")[0].strip().lower().replace("_", "-")
    if normalized in {"zh-tw", "zh-hk", "zh-hant"} or normalized.startswith(
        ("zh-tw-", "zh-hk-", "zh-hant-")
    ):
        return "zh-TW"
    if normalized in {"zh-cn", "zh-sg", "zh-hans", "zh"} or normalized.startswith(
        ("zh-cn-", "zh-hans-", "zh-sg-")
    ):
        return "zh-CN"
    if normalized == "ja" or normalized.startswith("ja-"):
        return "ja"
    if normalized == "ko" or normalized.startswith("ko-"):
        return "ko"
    return "en"


def _load_template(lang: str) -> _ResumeTemplates:
    defaults = {**_DEFAULT_TEMPLATES["en"], **_DEFAULT_TEMPLATES.get(lang, {})}
    try:
        bundle = json.loads(PROMPT_SIDECAR.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        bundle = {}
    entry = (bundle.get(lang) or bundle.get("en")) if isinstance(bundle, dict) else None
    overrides = entry if isinstance(entry, dict) else {}

    def text(key: str) -> str:
        value = overrides.get(key)
        return value if isinstance(value, str) and (value or key == "lead") else str(defaults[key])

    causes = dict(defaults["diagnosis_causes"])
    raw_causes = overrides.get("diagnosis_causes")
    if isinstance(raw_causes, Mapping):
        for key in _DIAGNOSIS_CAUSE_KEYS:
            value = raw_causes.get(key)
            if isinstance(value, str) and value:
                causes[key] = value
    return _ResumeTemplates(
        lead=text("lead"),
        prompt=text("prompt"),
        none=text("none"),
        empty=text("empty"),
        uncommitted=text("uncommitted"),
        summary=text("summary"),
        last_reply=text("last_reply"),
        diagnosis_reminder=text("diagnosis_reminder"),
        diagnosis_reminder_explain=text("diagnosis_reminder_explain"),
        diagnosis_default_cause=text("diagnosis_default_cause"),
        diagnosis_causes=causes,
    )


if __name__ == "__main__":
    sys.exit(main())

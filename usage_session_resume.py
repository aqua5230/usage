#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""usage SessionStart hook — inject "where you left off" into a new Claude Code session.

This is the session resume feature. Claude Code runs this on SessionStart (matcher
``startup|clear``) and pipes the session JSON on stdin; the script locates the project's
*previous* session log, gathers the *evidence* of that session — the most recent user
requests (newest first, so a session that drifted topics is still read correctly), the
commits made, the files edited, and any pending todos — and hands it to Claude via
``hookSpecificOutput.additionalContext`` with an instruction to *reason over* it rather
than transcribe it. The model that reads this is Claude itself, so the intelligence of
the handoff lives in Claude's reply, not in this script's string-formatting.

**Stdlib-only and 3.9-safe** — same constraint as ``usage_statusline.py``: it may run
under macOS's bundled ``/usr/bin/python3`` (3.9), so no third-party imports, no
``datetime.UTC``, no runtime ``X | Y`` types. The session-log parse is self-contained here
(no app imports), so the hook stays loadable under the bundled interpreter.

When there's no fresh progress to hand over (brand-new project, the previous session
did nothing extractable, or it's older than the cutoff) the hook still checks in with
a short greeting rather than going silent.

The prompt wording stays single-sourced: ``setup_hook`` writes ``report_rw_prompt`` /
``report_rw_none`` / ``report_rw_inject_lead`` / ``report_rw_empty`` from ``i18n.json`` to
a sidecar that this script reads. If the sidecar is missing it falls back to embedded
templates for the detected language. The script never raises into the session — any
failure exits 0 with no output.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast

__version__ = "1.6"


def _configure_windows_utf8_output() -> None:
    """Make SessionStart JSON UTF-8 when Claude Code reads a Windows pipe."""
    if os.name != "nt":
        return
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, OSError, ValueError):
            # Test runners and embedders may replace the TextIOWrapper streams.
            cast(Any, stream).reconfigure(encoding="utf-8")


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
_MAX_TODOS = 5
_MAX_FILES = 5
_MAX_UNCOMMITTED_FILES = 3
_MAX_REQUESTS = 3
_MAX_REQUEST_CHARS = 280
_MIN_SUBSTANTIVE_CHARS = 7
_IMAGE_MARKER = re.compile(r"\[Image(?:\s+#[0-9]+)?\]", re.I)
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
        "prompt": _DEFAULT_PROMPT,
        "none": _DEFAULT_NONE,
        "lead": (
            "(This is a resume handoff. At the very start of your first reply, lead "
            'with one line: "🐾 Picked up where you left off — let\'s keep going!", '
            "then, instead of reading the traces below aloud, digest them like a sharp, "
            "thoughtful partner: first work out what the user was actually in the middle of "
            '("Recently working on" is newest-first, so trust the topmost item and don\'t get '
            "pulled back to older ones); in a sentence or two, warmly and concretely recap "
            "where they left off and what got done; then give the single concrete next step "
            'you would take — be specific, don\'t ask "what should I do". Use only what is '
            "below; invent nothing. If the traces are too thin to tell, say so plainly and "
            "list the threads you can see for them to pick. Then respond normally.)\n\n"
        ),
        "empty": _DEFAULT_EMPTY,
        "uncommitted": (
            "Left uncommitted last time: {count} changed file(s) on branch {branch} ({files})"
        ),
        "diagnosis_reminder": (
            'Health check: about {waste_pct}% waste from {cause}. Say "fix it" '
            "and I'll read the full diagnosis at {path}."
        ),
        "diagnosis_reminder_explain": (
            'Health check: about {waste_pct}% waste from {cause}. Say "show me" '
            "and I'll walk you through the full diagnosis at {path}."
        ),
        "diagnosis_default_cause": "avoidable context waste",
        "diagnosis_causes": {
            "repeated_reads": "re-reading the same files",
            "polluter_dirs": "scanning generated folders",
            "anomaly_session": "one oversized session",
            "noisy_bash": "oversized Bash output",
            "repeated_bash": "re-running the same Bash command",
        },
    },
    "zh-TW": {
        "prompt": (
            "專案：{project}（最後活動 {when}）\n"
            "最近在忙的（新→舊）：{last_request}\n"
            "完成的進度：{commits}\n"
            "未完成待辦：{todos}"
        ),
        "none": "（未記錄）",
        "lead": (
            "（這是進度交接。請在這次對話第一則回覆的最前面，先說一行"
            "「🐾 已接回上次進度，繼續吧！」，然後別照唸下面的線索，"
            "而是像聰明又貼心的搭檔那樣消化它：先判斷使用者最後真正在忙的是什麼"
            "（「最近在忙的」是新到舊排列，以最前面那筆為準，別被較舊的帶偏），"
            "用一兩句溫暖具體地說他上次做到哪、完成了什麼，再直接給出你判斷最該"
            "接著做的下一步——要具體，別反問「要做什麼」。只能根據下面線索講，"
            "沒有的別編；若線索太少看不出方向，就坦白說、並列出你看到的幾條線讓他挑。"
            "接著正常回應。）\n\n"
        ),
        "empty": (
            "（請在你這次對話的第一則回覆最前面，說一行「🐾 歡迎回來，"
            "這個專案目前沒有要接的進度。」，再正常回應。）"
        ),
        "uncommitted": (
            "上次離開時還留著：{branch} 分支有 {count} 個檔案改了還沒提交（{files}）"
        ),
    },
    "zh-CN": {
        "prompt": (
            "项目：{project}（最后活动 {when}）\n"
            "最近在忙的（新→旧）：{last_request}\n"
            "完成的进度：{commits}\n"
            "未完成待办：{todos}"
        ),
        "none": "（未记录）",
        "lead": (
            "（这是进度交接。请在这次对话第一则回复的最前面，先说一行"
            "「🐾 已接回上次进度，继续吧！」，然后别照念下面的线索，"
            "而是像聪明又贴心的搭档那样消化它：先判断用户最后真正在忙的是什么"
            "（「最近在忙的」是新到旧排列，以最前面那笔为准，别被较旧的带偏），"
            "用一两句温暖具体地说他上次做到哪、完成了什么，再直接给出你判断最该"
            "接着做的下一步——要具体，别反问「要做什么」。只能根据下面线索讲，"
            "没有的别编；若线索太少看不出方向，就坦白说、并列出你看到的几条线让他挑。"
            "接着正常回应。）\n\n"
        ),
        "empty": (
            "（请在你这次对话的第一则回复最前面，说一行「🐾 欢迎回来，"
            "这个项目目前没有要接的进度。」，再正常回应。）"
        ),
        "uncommitted": (
            "上次离开时还留着：{branch} 分支有 {count} 个文件改了还没提交（{files}）"
        ),
    },
    "ja": {
        "prompt": (
            "プロジェクト：{project}（最終アクティブ {when}）\n"
            "最近の作業（新しい順）：{last_request}\n"
            "完了した進捗：{commits}\n"
            "未完了のToDo：{todos}"
        ),
        "none": "（記録なし）",
        "lead": (
            "（これは進捗の引き継ぎです。最初の返信の冒頭で、まず一行"
            "「🐾 前回の続き、引き継ぎ済みです！そのままどうぞ！」と述べ、"
            "下記の手がかりをそのまま読み上げるのではなく、賢く気の利いた相棒のように"
            "消化してください：まずユーザーが最後に実際に取り組んでいたことを見極め"
            "（「最近の作業」は新しい順なので、先頭の項目を信頼し、古いものに引きずられない"
            "こと）、前回どこまで進んだか・何が完了したかを一、二文で温かく具体的に振り返り、"
            "次に取るべき具体的な一歩を提示してください——具体的に述べ、「何をしますか」と"
            "聞き返さないこと。下記にある情報だけを使い、無いことは創作しないこと。手がかりが"
            "乏しくて判断できない場合は正直にそう述べ、見えるスレッドを挙げて選んでもらうこと。"
            "その後、通常どおり応答してください。）\n\n"
        ),
        "empty": (
            "（このセッションの最初の返信の冒頭に、一行「🐾 おかえりなさい！"
            "このプロジェクトはまだこれからですね。」と述べてから、通常どおり応答してください。）"
        ),
        "uncommitted": (
            "前回の終了時に未コミット：{branch} ブランチに変更済み未コミットのファイルが "
            "{count} 件（{files}）"
        ),
    },
    "ko": {
        "prompt": (
            "프로젝트: {project} (마지막 활동 {when})\n"
            "최근 작업한 내용 (최신순): {last_request}\n"
            "완료한 진행: {commits}\n"
            "미완료 할 일: {todos}"
        ),
        "none": "(기록 없음)",
        "lead": (
            "(이것은 진행 상황 인수인계입니다. 첫 답변 맨 앞에 먼저 한 줄 "
            '"🐾 지난 작업을 불러왔어요! 이어서 가볼까요?"라고 '
            "말한 뒤, 아래 단서를 그대로 읽지 말고 똑똑하고 사려 깊은 동료처럼 소화하세요: "
            "먼저 사용자가 마지막에 실제로 무엇을 하고 있었는지 파악하고(\"최근 작업한 내용\"은 "
            "최신순이므로 맨 위 항목을 신뢰하고 오래된 것에 끌려가지 마세요), 지난번에 어디까지 "
            "했고 무엇을 완료했는지 한두 문장으로 따뜻하고 구체적으로 짚어 준 뒤, 이어서 취해야 "
            '할 구체적인 다음 단계 하나를 제시하세요 — 구체적으로 말하고 "무엇을 할까요"라고 '
            "되묻지 마세요. 아래 있는 내용만 사용하고 없는 것은 지어내지 마세요. 단서가 너무 "
            "적어 판단하기 어려우면 솔직히 그렇게 말하고 보이는 갈래들을 나열해 고르게 하세요. "
            "그런 다음 평소대로 응답하세요.)\n\n"
        ),
        "empty": (
            '(이 세션의 첫 답변 맨 앞에 한 줄 "🐾 돌아오셨네요! '
            '이 프로젝트는 아직 이어갈 내용이 없어요."라고 말한 뒤 평소대로 응답하세요.)'
        ),
        "uncommitted": (
            "지난번 종료 시 미커밋: {branch} 브랜치에 변경된 미커밋 파일 {count}개 ({files})"
        ),
    },
}


def main() -> int:
    _configure_windows_utf8_output()
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except (json.JSONDecodeError, ValueError):
        return 0
    if not isinstance(payload, dict):
        return 0
    try:
        prompt = _build_prompt(payload)
    except Exception:
        return 0
    if not prompt:
        return 0
    output = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": prompt,
        }
    }
    print(json.dumps(output, ensure_ascii=False))
    return 0


def _build_prompt(payload: dict[str, Any]) -> str:
    transcript = payload.get("transcript_path")
    cwd = payload.get("cwd")
    if not isinstance(transcript, str) or not transcript:
        return ""
    project_dir = Path(transcript).parent
    if not project_dir.is_dir():
        return ""

    (
        lead,
        template,
        none_label,
        empty,
        uncommitted_template,
        diagnosis_reminder,
        diagnosis_reminder_explain,
        diagnosis_default_cause,
        diagnosis_causes,
    ) = _load_template(_detect_lang())
    project = _project_from_cwd(cwd) if isinstance(cwd, str) and cwd else project_dir.name
    uncommitted = _git_dirty(cwd) if isinstance(cwd, str) and cwd else None
    report = _build_report(
        project_dir,
        Path(transcript).name,
        project,
        lead,
        template,
        none_label,
        uncommitted_template,
        uncommitted,
    )
    # The resume hook always checks in: when there's no fresh progress to hand over, it
    # greets instead of going silent.
    prompt = report or empty
    diagnosis_instruction = _build_diagnosis_instruction(
        diagnosis_reminder=diagnosis_reminder,
        diagnosis_reminder_explain=diagnosis_reminder_explain,
        diagnosis_default_cause=diagnosis_default_cause,
        diagnosis_causes=diagnosis_causes,
    )
    if diagnosis_instruction:
        prompt += "\n\n" + diagnosis_instruction
    return prompt


def _build_report(
    project_dir: Path,
    current_name: str,
    project: str,
    lead: str,
    template: str,
    none_label: str,
    uncommitted_template: str,
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
    last_active, last_request, commits, todos, edited_files = parsed
    if last_active < _cutoff():
        return ""
    request_text = last_request or none_label
    done_items = commits[:_MAX_COMMITS] or edited_files[:_MAX_FILES]
    commits_text = " · ".join(done_items) or none_label
    todos_text = " · ".join(todos[:_MAX_TODOS]) or none_label
    report = lead + template.format(
        project=project,
        when=_format_time(last_active),
        last_request=request_text,
        commits=commits_text,
        todos=todos_text,
    )
    if uncommitted is not None:
        branch, count, files = uncommitted
        report += "\n" + uncommitted_template.format(
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
        )
        if branch_proc.returncode != 0:
            return None
        branch = branch_proc.stdout.strip()
        if not branch:
            return None
        status_proc = subprocess.run(
            ["git", "-C", cwd, "status", "--porcelain"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=2,
            encoding="utf-8",
            check=False,
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
            base = os.path.basename(path.strip('"'))
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
    """Other session logs in the project, newest first.

    Newest-first so the caller can skip a freshly-written but empty/corrupt log and
    still fall back to the previous session that actually has progress to report.
    """
    candidates: list[tuple[float, Path]] = []
    for jsonl in project_dir.glob("*.jsonl"):
        if jsonl.name == exclude:
            continue
        try:
            mtime = jsonl.stat().st_mtime
        except OSError:
            continue
        candidates.append((mtime, jsonl))
    candidates.sort(key=lambda item: item[0], reverse=True)
    return [path for _, path in candidates]


def _parse_session(path: Path) -> tuple[datetime, str, list[str], list[str], list[str]] | None:
    """Return (last_active, recent_requests, commits, todos, edited_files) for the previous session.

    ``recent_requests`` is the last few substantive user requests joined newest-first: a
    session often drifts (you start on task A and end deep in task B), so what you were
    *last* working on — not the opening request — is where you want to resume. Trailing
    reactions, screenshot markers, and interruption notes are filtered out by
    ``_clean_request``, so "most recent" stays meaningful. ``todos`` are the pending items
    from the latest TodoWrite, if the session used one. ``edited_files`` are the basenames
    of files touched by Edit / Write / NotebookEdit, deduplicated and in first-seen order.
    """
    requests: list[str] = []
    seen_requests: set[str] = set()
    commits: list[str] = []
    todos: list[str] = []
    edited_files: list[str] = []
    last_ts: datetime | None = None

    try:
        with path.open(encoding="utf-8") as file:
            for raw_line in file:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(data, dict):
                    continue

                timestamp = _parse_timestamp(data.get("timestamp"))
                if timestamp is not None and (last_ts is None or timestamp > last_ts):
                    last_ts = timestamp

                if data.get("isMeta") is True:
                    continue

                entry_type = data.get("type")
                if entry_type == "last-prompt":
                    text = _clean_request(data.get("lastPrompt"))
                    if text and text not in seen_requests:
                        requests.append(text)
                        seen_requests.add(text)
                    continue
                if entry_type == "user":
                    text = _user_request_text(data.get("message"))
                    if text and text not in seen_requests:
                        requests.append(text)
                        seen_requests.add(text)
                    continue
                if entry_type != "assistant":
                    continue
                message = data.get("message")
                if not isinstance(message, dict):
                    continue
                content = message.get("content")
                if not isinstance(content, list):
                    continue
                _collect_tools(content, commits, todos, edited_files)
    except OSError:
        return None

    if last_ts is None or not (requests or commits or todos or edited_files):
        return None
    # Newest-first, capped: the most recent request leads so Claude resumes the latest
    # thread, with a little prior context to spot a topic drift.
    last_request = " · ".join(reversed(requests[-_MAX_REQUESTS:]))
    return last_ts, last_request, commits, todos, edited_files


def _user_request_text(message: object) -> str:
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return _clean_request(content)
    if isinstance(content, list):
        parts = [
            part.get("text")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        ]
        return _clean_request(" ".join(p for p in parts if isinstance(p, str) and p.strip()))
    return ""


def _clean_request(value: object) -> str:
    if not isinstance(value, str):
        return ""
    text = " ".join(value.split())
    # Skip the interruption marker Claude Code writes as a user turn — it is noise,
    # not a request.
    if not text or text.startswith("[Request interrupted"):
        return ""
    starts_with_image = text.startswith("[Image")
    text = _IMAGE_MARKER.sub("", text).strip()
    if not text:
        return ""
    substantive_len = _substantive_len(text)
    if substantive_len == 0:
        return ""
    if starts_with_image and substantive_len < _MIN_SUBSTANTIVE_CHARS:
        return ""
    if substantive_len < _MIN_SUBSTANTIVE_CHARS and not _has_structural_signal(text):
        return ""
    if len(text) > _MAX_REQUEST_CHARS:
        text = text[: _MAX_REQUEST_CHARS - 1].rstrip() + "…"
    return text


def _substantive_len(text: str) -> int:
    return sum(1 for char in text if char.isalnum())


def _has_structural_signal(text: str) -> bool:
    return any(marker in text for marker in ("/", "\\", ".", "_", "-", "#", ":", "`", "(", ")"))


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


def _collect_tools(
    content: list[Any],
    commits: list[str],
    todos: list[str],
    edited_files: list[str],
) -> None:
    for part in content:
        if not isinstance(part, dict) or part.get("type") != "tool_use":
            continue
        name = part.get("name")
        raw_input = part.get("input")
        if not isinstance(raw_input, dict):
            continue
        if name == "TodoWrite":
            items = raw_input.get("todos")
            if isinstance(items, list):
                pending = _pending_todos(items)
                if pending:
                    todos[:] = pending  # latest TodoWrite wins — it is the current state
        elif name == "Bash":
            command = raw_input.get("command")
            if isinstance(command, str) and "git commit" in command:
                title = _extract_commit_title(command)
                if title and title not in commits:
                    commits.append(title)
        elif name in {"Edit", "Write", "NotebookEdit"}:
            fp = raw_input.get("file_path")
            if isinstance(fp, str):
                base = os.path.basename(fp)
                if base and base not in edited_files:
                    edited_files.append(base)


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
    except ValueError:
        return None
    # A naive timestamp (no offset) can't be compared against the aware _cutoff();
    # assume local time so the comparison stays type-safe.
    return parsed if parsed.tzinfo is not None else parsed.astimezone()


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
        isinstance(finding, dict) and finding.get("severity") == "critical"
        for finding in findings
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
    rel = cwd[len(home):] if cwd.startswith(home) else cwd
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


def _load_template(lang: str) -> tuple[
    str,
    str,
    str,
    str,
    str,
    str,
    str,
    str,
    dict[str, str],
]:
    """Return (lead, prompt, none, empty, uncommitted). ``lead`` is a short instruction prepended to
    the injected context so Claude's first reply visibly acknowledges it loaded the
    progress — the only way a SessionStart hook can surface itself to the user.
    ``empty`` is the standalone greeting shown when there's no fresh progress to report."""
    fallback = _template_from_entry(_DEFAULT_TEMPLATES.get(lang) or _DEFAULT_TEMPLATES["en"])
    try:
        bundle = json.loads(PROMPT_SIDECAR.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return fallback
    if not isinstance(bundle, dict):
        return fallback
    entry = bundle.get(lang) or bundle.get("en")
    if not isinstance(entry, dict):
        return fallback
    return _template_from_entry(entry, fallback)


def _template_from_entry(
    entry: Mapping[str, object],
    fallback: tuple[str, str, str, str, str, str, str, str, dict[str, str]] | None = None,
) -> tuple[str, str, str, str, str, str, str, str, dict[str, str]]:
    if fallback is None:
        fallback = (
            "",
            _DEFAULT_PROMPT,
            _DEFAULT_NONE,
            _DEFAULT_EMPTY,
            _DEFAULT_TEMPLATES["en"]["uncommitted"],
            _DEFAULT_TEMPLATES["en"]["diagnosis_reminder"],
            _DEFAULT_TEMPLATES["en"]["diagnosis_reminder_explain"],
            _DEFAULT_TEMPLATES["en"]["diagnosis_default_cause"],
            _DEFAULT_TEMPLATES["en"]["diagnosis_causes"],
        )
    lead = entry.get("lead")
    prompt = entry.get("prompt")
    none_label = entry.get("none")
    empty = entry.get("empty")
    uncommitted = entry.get("uncommitted")
    diagnosis_reminder = entry.get("diagnosis_reminder")
    diagnosis_reminder_explain = entry.get("diagnosis_reminder_explain")
    diagnosis_default_cause = entry.get("diagnosis_default_cause")
    raw_causes = entry.get("diagnosis_causes")
    causes = dict(fallback[8])
    if isinstance(raw_causes, Mapping):
        for key in _DIAGNOSIS_CAUSE_KEYS:
            value = raw_causes.get(key)
            if isinstance(value, str) and value:
                causes[key] = value
    return (
        lead if isinstance(lead, str) else fallback[0],
        prompt if isinstance(prompt, str) and prompt else fallback[1],
        none_label if isinstance(none_label, str) and none_label else fallback[2],
        empty if isinstance(empty, str) and empty else fallback[3],
        uncommitted if isinstance(uncommitted, str) and uncommitted else fallback[4],
        (
            diagnosis_reminder
            if isinstance(diagnosis_reminder, str) and diagnosis_reminder
            else fallback[5]
        ),
        (
            diagnosis_reminder_explain
            if isinstance(diagnosis_reminder_explain, str) and diagnosis_reminder_explain
            else fallback[6]
        ),
        (
            diagnosis_default_cause
            if isinstance(diagnosis_default_cause, str) and diagnosis_default_cause
            else fallback[7]
        ),
        causes,
    )


if __name__ == "__main__":
    sys.exit(main())

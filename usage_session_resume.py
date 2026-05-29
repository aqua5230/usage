#!/usr/bin/env python3
"""usage SessionStart hook — inject "where you left off" into a new Claude Code session.

This is ceiling C of the resume feature. Claude Code runs this on SessionStart (matcher
``startup|clear``) and pipes the session JSON on stdin; the script locates the project's
*previous* session log, pulls the files changed and commits made last time, and emits a
ready-to-act resume prompt via ``hookSpecificOutput.additionalContext``.

**Stdlib-only and 3.9-safe** — same constraint as ``usage_statusline.py``: it may run
under macOS's bundled ``/usr/bin/python3`` (3.9), so no third-party imports, no
``datetime.UTC``, no runtime ``X | Y`` types. It cannot import ``resume_loader`` (3.10
slots, package imports), so the one-project parse is reimplemented here.

The prompt wording stays single-sourced: ``setup_hook`` writes ``rw_prompt`` / ``rw_none``
from ``i18n.json`` to a sidecar that this script reads. If the sidecar is missing it falls
back to the embedded English default. The script never raises into the session — any
failure exits 0 with no output.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

__version__ = "1.0"

PROMPT_SIDECAR = Path(os.path.expanduser("~/.claude/usage-resume-prompt.json"))

_EDIT_TOOLS = {"Edit", "Write"}
# Mirror resume_loader's commit-title extraction so report and hook agree.
_COMMIT_HEREDOC = re.compile(r"""cat\s*<<\s*['"]?\w+['"]?\s*\n(.+?)\n""", re.S)
_COMMIT_INLINE = re.compile(r"""-m\s+["']([^"'\n]{4,90})""")
_MAX_AGE_DAYS = 30
_MAX_FILES = 6
_MAX_COMMITS = 3

_DEFAULT_PROMPT = (
    'Last time I was working on the "{project}" project (last active {when}).\n'
    "Files I changed: {files}\nCommits: {commits}\n\n"
    "Please help me recall where I left off and suggest concrete next steps."
)
_DEFAULT_NONE = "(none recorded)"


def main() -> int:
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
    latest = _latest_other_jsonl(project_dir, exclude=Path(transcript).name)
    if latest is None:
        return ""
    parsed = _parse_session(latest)
    if parsed is None:
        return ""
    last_active, changed, commits = parsed
    if last_active < _cutoff():
        return ""

    lead, template, none_label = _load_template(_detect_lang())
    project = _project_from_cwd(cwd) if isinstance(cwd, str) and cwd else project_dir.name
    files_text = " · ".join(changed[:_MAX_FILES]) or none_label
    commits_text = " · ".join(commits[:_MAX_COMMITS]) or none_label
    return lead + template.format(
        project=project, when=_format_time(last_active), files=files_text, commits=commits_text
    )


def _cutoff() -> datetime:
    return datetime.now().astimezone() - timedelta(days=_MAX_AGE_DAYS)


def _latest_other_jsonl(project_dir: Path, exclude: str) -> Path | None:
    latest: Path | None = None
    latest_mtime = -1.0
    for jsonl in project_dir.glob("*.jsonl"):
        if jsonl.name == exclude:
            continue
        try:
            mtime = jsonl.stat().st_mtime
        except OSError:
            continue
        if mtime > latest_mtime:
            latest_mtime = mtime
            latest = jsonl
    return latest


def _parse_session(path: Path) -> tuple[datetime, list[str], list[str]] | None:
    changed: list[str] = []
    seen_files: set[str] = set()
    commits: list[str] = []
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

                if data.get("type") != "assistant":
                    continue
                message = data.get("message")
                if not isinstance(message, dict):
                    continue
                content = message.get("content")
                if not isinstance(content, list):
                    continue
                _collect_tools(content, changed, seen_files, commits)
    except OSError:
        return None

    if last_ts is None or (not changed and not commits):
        return None
    return last_ts, changed, commits


def _collect_tools(
    content: list[Any], changed: list[str], seen_files: set[str], commits: list[str]
) -> None:
    for part in content:
        if not isinstance(part, dict) or part.get("type") != "tool_use":
            continue
        name = part.get("name")
        raw_input = part.get("input")
        if not isinstance(raw_input, dict):
            continue
        if name in _EDIT_TOOLS:
            file_path = raw_input.get("file_path")
            if isinstance(file_path, str) and file_path:
                base_name = file_path.rsplit("/", 1)[-1]
                if base_name not in seen_files:
                    seen_files.add(base_name)
                    changed.append(base_name)
        elif name == "Bash":
            command = raw_input.get("command")
            if isinstance(command, str) and "git commit" in command:
                title = _extract_commit_title(command)
                if title and title not in commits:
                    commits.append(title)


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
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _format_time(parsed: datetime) -> str:
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone()
    return f"{parsed.month}/{parsed.day} {parsed.hour:02d}:{parsed.minute:02d}"


def _project_from_cwd(cwd: str) -> str:
    home = os.path.expanduser("~")
    rel = cwd[len(home):].strip(os.sep) if cwd.startswith(home) else cwd.strip(os.sep)
    parts = rel.split(os.sep)
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


def _load_template(lang: str) -> tuple[str, str, str]:
    """Return (lead, prompt, none). ``lead`` is a short instruction prepended to the
    injected context so Claude's first reply visibly acknowledges it loaded the
    progress — the only way a SessionStart hook can surface itself to the user."""
    try:
        bundle = json.loads(PROMPT_SIDECAR.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return "", _DEFAULT_PROMPT, _DEFAULT_NONE
    if not isinstance(bundle, dict):
        return "", _DEFAULT_PROMPT, _DEFAULT_NONE
    entry = bundle.get(lang) or bundle.get("en")
    if not isinstance(entry, dict):
        return "", _DEFAULT_PROMPT, _DEFAULT_NONE
    lead = entry.get("lead")
    prompt = entry.get("prompt")
    none_label = entry.get("none")
    return (
        lead if isinstance(lead, str) else "",
        prompt if isinstance(prompt, str) and prompt else _DEFAULT_PROMPT,
        none_label if isinstance(none_label, str) and none_label else _DEFAULT_NONE,
    )


if __name__ == "__main__":
    sys.exit(main())

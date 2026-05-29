"""Read each project's "where you left off" from Claude Code session logs.

Pure local, zero AI, zero network — every field is a fact Claude or the user
already wrote (Edit/Write file paths and git commit titles). This is "ceiling A"
of the resume feature; the :class:`ProjectResume` fact-pack is kept as a standalone
structure so a future AI-summary layer ("ceiling B") can build on it without a rewrite.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from adapters import claude

_EDIT_TOOLS = {"Edit", "Write"}
# git commit -m "$(cat <<'EOF'\n<title>\n...\nEOF\n)"  — heredoc title is the first line.
# The `cat <<` anchor avoids matching unrelated heredocs (e.g. `python3 - <<'PY'`).
_COMMIT_HEREDOC = re.compile(r"""cat\s*<<\s*['"]?\w+['"]?\s*\n(.+?)\n""", re.S)
# git commit -m "<title>"  — plain inline message.
_COMMIT_INLINE = re.compile(r"""-m\s+["']([^"'\n]{4,90})""")


@dataclass(slots=True)
class ProjectResume:
    """One project's "what did I do last time" fact-pack.

    Every field is read straight from the session log — no inference. ``changed_files``
    and ``commit_titles`` keep first-seen order; UI layers decide how many to show.
    """

    project: str
    last_active: datetime
    changed_files: list[str]
    commit_titles: list[str]
    session_id: str = ""
    cwd: str = ""


def load_recent_work(days_back: int = 30, max_projects: int = 8) -> list[ProjectResume]:
    """Return one ``ProjectResume`` per project, newest activity first.

    For each project directory only its most recently modified ``*.jsonl`` is parsed
    (the latest conversation), so this never scans the whole history. Sessions with no
    edits and no commits are skipped — they carry no "where you left off" signal.
    """
    cutoff = datetime.now().astimezone() - timedelta(days=days_back)
    results: list[ProjectResume] = []
    for base_dir in claude.get_claude_dirs():
        base = Path(base_dir)
        if not base.is_dir():
            continue
        for project_dir in base.iterdir():
            if not project_dir.is_dir():
                continue
            latest = _latest_jsonl(project_dir)
            if latest is None:
                continue
            resume = _parse_session(latest, base)
            if resume is None or resume.last_active < cutoff:
                continue
            results.append(resume)
    results.sort(key=lambda r: r.last_active, reverse=True)
    top = results[:max_projects]
    _disambiguate(top)
    return top


def _disambiguate(items: list[ProjectResume]) -> None:
    """Same basename across paths (e.g. Developer/usage vs an archived copy) is
    ambiguous, so suffix the parent dir to tell them apart. Mutates in place."""
    counts = Counter(r.project for r in items)
    for r in items:
        if counts[r.project] > 1 and r.cwd:
            parent = Path(r.cwd).parent.name
            if parent:
                r.project = f"{r.project} ({parent})"


def recent_work_items(days_back: int = 30, max_projects: int = 8) -> list[dict[str, object]]:
    """``load_recent_work`` flattened to report-friendly dicts (UI formats the time)."""
    return [
        {
            "project": resume.project,
            "last_active": resume.last_active.isoformat(),
            "changed_files": resume.changed_files,
            "commit_titles": resume.commit_titles,
        }
        for resume in load_recent_work(days_back, max_projects)
    ]


def _latest_jsonl(project_dir: Path) -> Path | None:
    latest: Path | None = None
    latest_mtime = -1.0
    for jsonl in project_dir.glob("*.jsonl"):
        try:
            mtime = jsonl.stat().st_mtime
        except OSError:
            continue
        if mtime > latest_mtime:
            latest_mtime = mtime
            latest = jsonl
    return latest


def _parse_session(path: Path, base: Path) -> ProjectResume | None:
    changed: list[str] = []
    seen_files: set[str] = set()
    commits: list[str] = []
    last_ts: datetime | None = None
    session_id = ""
    cwd = ""

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
                sid = data.get("sessionId")
                if isinstance(sid, str) and sid:
                    session_id = sid
                if not cwd:
                    raw_cwd = data.get("cwd")
                    if isinstance(raw_cwd, str) and raw_cwd:
                        cwd = raw_cwd

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
    # Real cwd from the log is lossless; the encoded dir name (dashes for every
    # separator) mangles hyphenated and non-ASCII project names, so prefer cwd.
    project = claude.project_from_cwd(cwd) if cwd else claude.extract_project_from_dir(path, base)
    return ProjectResume(
        project=project,
        last_active=last_ts,
        changed_files=changed,
        commit_titles=commits,
        session_id=session_id,
        cwd=cwd,
    )


def _collect_tools(
    content: list[object],
    changed: list[str],
    seen_files: set[str],
    commits: list[str],
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

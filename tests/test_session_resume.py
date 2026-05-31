from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import usage_session_resume as mod


def _write_session(
    path: Path,
    *,
    when: datetime,
    request: str = "",
    commits: list[str] | None = None,
    todos: list[str] | None = None,
    edited_files: list[str] | None = None,
) -> None:
    lines: list[dict[str, object]] = []
    if request:
        lines.append(
            {"type": "user", "timestamp": when.isoformat(), "message": {"content": request}}
        )
    content: list[dict[str, object]] = []
    for title in commits or []:
        command = f'git commit -m "{title}"'
        content.append({"type": "tool_use", "name": "Bash", "input": {"command": command}})
    if todos:
        content.append(
            {
                "type": "tool_use",
                "name": "TodoWrite",
                "input": {"todos": [{"content": t, "status": "pending"} for t in todos]},
            }
        )
    for fp in edited_files or []:
        content.append({"type": "tool_use", "name": "Edit", "input": {"file_path": fp}})
    lines.append(
        {"type": "assistant", "timestamp": when.isoformat(), "message": {"content": content}}
    )
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")


def _project_dir(tmp_path: Path) -> Path:
    project = tmp_path / "projects" / "-Users-me-Developer-myproj"
    project.mkdir(parents=True)
    return project


def _sidecar(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sidecar = tmp_path / "usage-resume-prompt.json"
    sidecar.write_text(
        json.dumps(
            {
                "en": {
                    "prompt": "proj={project} when={when} req={last_request} "
                    "commits={commits} todos={todos}",
                    "none": "(none)",
                    "lead": "LEAD:: ",
                    "empty": "GREETING::",
                },
                "zh-TW": {
                    "prompt": "專案={project} 請求={last_request}",
                    "none": "（無）",
                    "lead": "前情:: ",
                    "empty": "管家報到::",
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "PROMPT_SIDECAR", sidecar)


def test_build_prompt_reads_previous_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("USAGE_LANG", raising=False)
    monkeypatch.delenv("TT_LANG", raising=False)
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    _sidecar(tmp_path, monkeypatch)
    project = _project_dir(tmp_path)
    now = datetime.now().astimezone()
    _write_session(
        project / "prev.jsonl",
        when=now - timedelta(hours=2),
        request="add a dark mode toggle to the settings panel",
        commits=["fix: the thing"],
    )
    current = project / "current.jsonl"
    current.write_text("", encoding="utf-8")

    prompt = mod._build_prompt(
        {"transcript_path": str(current), "cwd": "/Users/me/Developer/myproj"}
    )

    assert prompt.startswith("LEAD:: ")  # injected lead so Claude visibly acknowledges
    assert "proj=myproj" in prompt
    assert "add a dark mode toggle to the settings panel" in prompt  # the last request
    assert "fix: the thing" in prompt


def test_build_prompt_includes_pending_todos(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    _sidecar(tmp_path, monkeypatch)
    project = _project_dir(tmp_path)
    _write_session(
        project / "prev.jsonl",
        when=datetime.now().astimezone() - timedelta(hours=1),
        request="ship the release",
        todos=["write changelog", "tag the version"],
    )
    current = project / "current.jsonl"
    current.write_text("", encoding="utf-8")

    prompt = mod._build_prompt(
        {"transcript_path": str(current), "cwd": "/Users/me/Developer/myproj"}
    )

    assert "write changelog" in prompt and "tag the version" in prompt


def test_build_prompt_reads_last_prompt_entry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    _sidecar(tmp_path, monkeypatch)
    project = _project_dir(tmp_path)
    when = datetime.now().astimezone() - timedelta(hours=1)
    # A `last-prompt` entry is the cleanest record of what the user asked.
    (project / "prev.jsonl").write_text(
        "\n".join(
            json.dumps(line)
            for line in [
                {
                    "type": "last-prompt",
                    "timestamp": when.isoformat(),
                    "lastPrompt": "refactor the parser",
                },
                {"type": "assistant", "timestamp": when.isoformat(), "message": {"content": []}},
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    current = project / "current.jsonl"
    current.write_text("", encoding="utf-8")

    prompt = mod._build_prompt(
        {"transcript_path": str(current), "cwd": "/Users/me/Developer/myproj"}
    )

    assert "refactor the parser" in prompt


def test_build_prompt_uses_first_substantive_task_not_trailing_reaction(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    _sidecar(tmp_path, monkeypatch)
    project = _project_dir(tmp_path)
    when = datetime.now().astimezone() - timedelta(hours=1)
    (project / "prev.jsonl").write_text(
        "\n".join(
            json.dumps(line)
            for line in [
                {
                    "type": "user",
                    "timestamp": when.isoformat(),
                    "message": {"content": "Fix the SessionStart hook reliability regression"},
                },
                {
                    "type": "user",
                    "timestamp": when.isoformat(),
                    "message": {"content": "[Image #2]"},
                },
                {
                    "type": "last-prompt",
                    "timestamp": when.isoformat(),
                    "lastPrompt": "[Image #2] huh",
                },
                {"type": "assistant", "timestamp": when.isoformat(), "message": {"content": []}},
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    current = project / "current.jsonl"
    current.write_text("", encoding="utf-8")

    prompt = mod._build_prompt(
        {"transcript_path": str(current), "cwd": "/Users/me/Developer/myproj"}
    )

    assert "Fix the SessionStart hook reliability regression" in prompt
    assert "[Image" not in prompt
    assert "huh" not in prompt


def test_build_prompt_greets_when_only_current_transcript(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    _sidecar(tmp_path, monkeypatch)
    project = _project_dir(tmp_path)
    current = project / "current.jsonl"
    # Only the current transcript exists → no "previous" session, so the butler just greets.
    _write_session(current, when=datetime.now().astimezone(), request="do a thing")

    prompt = mod._build_prompt(
        {"transcript_path": str(current), "cwd": "/Users/me/Developer/myproj"}
    )

    assert prompt == "GREETING::"


def test_build_prompt_greets_when_previous_is_stale(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    _sidecar(tmp_path, monkeypatch)
    project = _project_dir(tmp_path)
    _write_session(
        project / "prev.jsonl",
        when=datetime.now().astimezone() - timedelta(days=mod._MAX_AGE_DAYS + 1),
        request="something old",
    )
    current = project / "current.jsonl"
    current.write_text("", encoding="utf-8")

    prompt = mod._build_prompt(
        {"transcript_path": str(current), "cwd": "/Users/me/Developer/myproj"}
    )

    assert prompt == "GREETING::"


def test_build_prompt_greets_when_no_signal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    _sidecar(tmp_path, monkeypatch)
    project = _project_dir(tmp_path)
    # No user request, no commits, no todos → nothing to report, so the butler just greets.
    _write_session(
        project / "prev.jsonl",
        when=datetime.now().astimezone() - timedelta(hours=1),
    )
    current = project / "current.jsonl"
    current.write_text("", encoding="utf-8")

    prompt = mod._build_prompt(
        {"transcript_path": str(current), "cwd": "/Users/me/Developer/myproj"}
    )

    assert prompt == "GREETING::"


def test_build_prompt_falls_back_to_default_when_sidecar_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    monkeypatch.setattr(mod, "PROMPT_SIDECAR", tmp_path / "does-not-exist.json")
    project = _project_dir(tmp_path)
    _write_session(
        project / "prev.jsonl",
        when=datetime.now().astimezone() - timedelta(hours=1),
        request="implement feature x",
        commits=["feat: x"],
    )
    current = project / "current.jsonl"
    current.write_text("", encoding="utf-8")

    prompt = mod._build_prompt(
        {"transcript_path": str(current), "cwd": "/Users/me/Developer/myproj"}
    )

    assert "Recently working on" in prompt  # embedded default wording
    assert "implement feature x" in prompt
    assert "myproj" in prompt


def test_build_prompt_falls_back_to_detected_language_when_sidecar_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("USAGE_LANG", "zh-TW")
    monkeypatch.setattr(mod, "PROMPT_SIDECAR", tmp_path / "does-not-exist.json")
    project = _project_dir(tmp_path)
    _write_session(
        project / "prev.jsonl",
        when=datetime.now().astimezone() - timedelta(hours=1),
        request="修好專案管家 SessionStart 缺檔問題",
    )
    current = project / "current.jsonl"
    current.write_text("", encoding="utf-8")

    prompt = mod._build_prompt(
        {"transcript_path": str(current), "cwd": "/Users/me/Developer/myproj"}
    )

    assert "🐾 已接回上次進度，繼續吧！" in prompt
    assert "修好專案管家 SessionStart 缺檔問題" in prompt


def test_build_prompt_uses_detected_language(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("USAGE_LANG", "zh-TW")
    _sidecar(tmp_path, monkeypatch)
    project = _project_dir(tmp_path)
    _write_session(
        project / "prev.jsonl",
        when=datetime.now().astimezone() - timedelta(hours=1),
        request="加一個深色模式",
    )
    current = project / "current.jsonl"
    current.write_text("", encoding="utf-8")

    prompt = mod._build_prompt(
        {"transcript_path": str(current), "cwd": "/Users/me/Developer/myproj"}
    )

    assert prompt.startswith("前情:: ")
    assert "專案=myproj" in prompt
    assert "加一個深色模式" in prompt


def test_main_emits_additional_context(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    _sidecar(tmp_path, monkeypatch)
    project = _project_dir(tmp_path)
    _write_session(
        project / "prev.jsonl",
        when=datetime.now().astimezone() - timedelta(hours=1),
        request="wire up the new endpoint",
        commits=["fix: y"],
    )
    current = project / "current.jsonl"
    current.write_text("", encoding="utf-8")
    payload = json.dumps({"transcript_path": str(current), "cwd": "/Users/me/Developer/myproj"})
    monkeypatch.setattr("sys.stdin", _FakeStdin(payload))

    assert mod.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert out["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "wire up the new endpoint" in out["hookSpecificOutput"]["additionalContext"]


def test_main_emits_greeting_when_no_progress(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    _sidecar(tmp_path, monkeypatch)
    project = _project_dir(tmp_path)
    # Brand-new project: only the current transcript, nothing previous to report.
    current = project / "current.jsonl"
    current.write_text("", encoding="utf-8")
    payload = json.dumps({"transcript_path": str(current), "cwd": "/Users/me/Developer/myproj"})
    monkeypatch.setattr("sys.stdin", _FakeStdin(payload))

    assert mod.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert out["hookSpecificOutput"]["additionalContext"] == "GREETING::"


def test_extract_commit_title_handles_heredoc_forms() -> None:
    # `git commit -F - <<'EOF'` has no `cat` prefix — the most common form, previously missed.
    assert (
        mod._extract_commit_title("git commit -F - <<'EOF'\nfeat: add butler\nbody\nEOF")
        == "feat: add butler"
    )
    # `-m "$(cat <<'EOF' ...)"` still works (heredoc body wins over the inline `$(cat` noise).
    assert (
        mod._extract_commit_title("git commit -m \"$(cat <<'EOF'\nfix: a thing\nEOF\n)\"")
        == "fix: a thing"
    )
    # Plain inline `-m` still works.
    assert mod._extract_commit_title('git commit -m "chore: bump version"') == "chore: bump version"
    # Message typed in the editor (no -m, no heredoc) is genuinely unrecoverable from the command.
    assert mod._extract_commit_title("git commit --amend") == ""
    # A python script that merely MENTIONS git commit must not have its own `<<PYEOF`
    # heredoc body (e.g. `import ...`) mistaken for a commit title. Regression guard.
    assert (
        mod._extract_commit_title(
            "python3 <<'PYEOF'\nimport json, tempfile, os\n# exercise git commit parsing\nPYEOF"
        )
        == ""
    )


def test_main_with_empty_stdin_is_silent(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", _FakeStdin(""))
    assert mod.main() == 0
    assert capsys.readouterr().out == ""


def test_build_prompt_skips_corrupt_latest_and_uses_previous(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The freshest log is empty; the butler must fall back to the older valid session
    # instead of going silent.
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    _sidecar(tmp_path, monkeypatch)
    project = _project_dir(tmp_path)
    now = datetime.now().astimezone()
    valid = project / "older_valid.jsonl"
    _write_session(
        valid,
        when=now - timedelta(hours=3),
        request="resume the real task",
        commits=["feat: real work"],
    )
    empty = project / "newer_empty.jsonl"
    empty.write_text("", encoding="utf-8")
    current = project / "current.jsonl"
    current.write_text("", encoding="utf-8")
    os.utime(valid, (now.timestamp() - 3600, now.timestamp() - 3600))  # older mtime

    prompt = mod._build_prompt(
        {"transcript_path": str(current), "cwd": "/Users/me/Developer/myproj"}
    )

    assert "resume the real task" in prompt
    assert "feat: real work" in prompt


def test_build_prompt_handles_naive_timestamp(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # A transcript whose timestamps carry no UTC offset must not crash the cutoff check.
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    _sidecar(tmp_path, monkeypatch)
    project = _project_dir(tmp_path)
    naive = (datetime.now() - timedelta(hours=1)).replace(microsecond=0)
    assert naive.tzinfo is None
    lines = [
        {"type": "user", "timestamp": naive.isoformat(), "message": {"content": "fix the clock"}},
        {"type": "assistant", "timestamp": naive.isoformat(), "message": {"content": []}},
    ]
    prev = project / "prev.jsonl"
    prev.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")
    current = project / "current.jsonl"
    current.write_text("", encoding="utf-8")

    prompt = mod._build_prompt(
        {"transcript_path": str(current), "cwd": "/Users/me/Developer/myproj"}
    )

    assert "fix the clock" in prompt


class _FakeStdin:
    def __init__(self, data: str) -> None:
        self._data = data

    def read(self) -> str:
        return self._data


def test_done_falls_back_to_edited_files_when_no_commits(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When a session has Edit/Write but no git commit, the done field shows basenames."""
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    _sidecar(tmp_path, monkeypatch)
    project = _project_dir(tmp_path)
    _write_session(
        project / "prev.jsonl",
        when=datetime.now().astimezone() - timedelta(hours=1),
        request="refactor the parser",
        edited_files=[
            "/Users/me/Developer/myproj/src/parser.py",
            "/Users/me/Developer/myproj/tests/test_parser.py",
            "/Users/me/Developer/myproj/src/parser.py",  # duplicate — should be deduped
        ],
    )
    current = project / "current.jsonl"
    current.write_text("", encoding="utf-8")

    prompt = mod._build_prompt(
        {"transcript_path": str(current), "cwd": "/Users/me/Developer/myproj"}
    )

    assert "parser.py" in prompt
    assert "test_parser.py" in prompt
    # basename dedup: "parser.py" should appear only once
    commits_field = prompt.split("commits=")[1].split(" todos=")[0]
    done_items = [s.strip() for s in commits_field.split(" · ")]
    assert done_items.count("parser.py") == 1


def test_done_prefers_commits_over_edited_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When a session has both git commits and Edit/Write, only commits appear in done."""
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    _sidecar(tmp_path, monkeypatch)
    project = _project_dir(tmp_path)
    _write_session(
        project / "prev.jsonl",
        when=datetime.now().astimezone() - timedelta(hours=1),
        request="add dark mode",
        commits=["feat: add dark mode toggle"],
        edited_files=["/Users/me/Developer/myproj/src/theme.py"],
    )
    current = project / "current.jsonl"
    current.write_text("", encoding="utf-8")

    prompt = mod._build_prompt(
        {"transcript_path": str(current), "cwd": "/Users/me/Developer/myproj"}
    )

    assert "feat: add dark mode toggle" in prompt
    assert "theme.py" not in prompt


def test_build_prompt_surfaces_recent_requests_newest_first(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A session that drifts topics: the most recent request leads, the opening one trails."""
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    _sidecar(tmp_path, monkeypatch)
    project = _project_dir(tmp_path)
    when = datetime.now().astimezone() - timedelta(hours=1)
    lines = [
        {
            "type": "user",
            "timestamp": when.isoformat(),
            "message": {"content": "fix the codex parser bug"},
        },
        {
            "type": "user",
            "timestamp": when.isoformat(),
            "message": {"content": "now redesign the project butler handoff"},
        },
        {"type": "assistant", "timestamp": when.isoformat(), "message": {"content": []}},
    ]
    (project / "prev.jsonl").write_text(
        "\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8"
    )
    current = project / "current.jsonl"
    current.write_text("", encoding="utf-8")

    prompt = mod._build_prompt(
        {"transcript_path": str(current), "cwd": "/Users/me/Developer/myproj"}
    )

    # Both surface, but the latest thread leads so Claude resumes where work actually ended.
    assert "now redesign the project butler handoff" in prompt
    assert "fix the codex parser bug" in prompt
    assert prompt.index("redesign the project butler handoff") < prompt.index(
        "fix the codex parser bug"
    )

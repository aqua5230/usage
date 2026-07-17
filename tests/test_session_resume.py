# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import io
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

import usage_session_resume as mod


def test_windows_output_reconfigures_both_streams(monkeypatch: pytest.MonkeyPatch) -> None:
    class Stream:
        def __init__(self) -> None:
            self.encodings: list[str] = []

        def reconfigure(self, *, encoding: str) -> None:
            self.encodings.append(encoding)

    stdout = Stream()
    stderr = Stream()
    monkeypatch.setattr(mod, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)

    mod._configure_windows_utf8_output()

    assert stdout.encodings == ["utf-8"]
    assert stderr.encodings == ["utf-8"]


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
                    "uncommitted": "dirty branch={branch} count={count} files={files}",
                    "diagnosis_reminder": (
                        'Health check: about {waste_pct}% waste came from {cause}. '
                        'If you say "修", the full diagnosis is at {path}.'
                    ),
                    "diagnosis_reminder_explain": (
                        'Health check: about {waste_pct}% waste came from {cause}. '
                        'If you say "看", I will walk you through {path}.'
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
                    "prompt": "專案={project} 請求={last_request}",
                    "none": "（無）",
                    "lead": "前情:: ",
                    "empty": "管家報到::",
                    "uncommitted": "未提交 branch={branch} count={count} files={files}",
                    "diagnosis_reminder": (
                        "健檢提醒：最近約 {waste_pct}% 浪費在{cause}。跟我說「修」，"
                        "完整診斷在 {path}。"
                    ),
                    "diagnosis_default_cause": "可避免的上下文浪費",
                    "diagnosis_causes": {
                        "repeated_reads": "重複讀同一批檔案",
                        "polluter_dirs": "掃進了產物/依賴資料夾",
                        "anomaly_session": "單一工作階段異常膨脹",
                        "noisy_bash": "Bash 輸出過大",
                        "repeated_bash": "重複跑同一個 Bash 指令",
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "PROMPT_SIDECAR", sidecar)


def _diagnosis_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    snapshot = tmp_path / "usage-diagnosis.json"
    state = tmp_path / "usage-diagnosis-state.json"
    monkeypatch.setattr(mod, "DIAGNOSIS_SNAPSHOT", snapshot)
    monkeypatch.setattr(mod, "DIAGNOSIS_STATE", state)
    return snapshot, state


def _write_diagnosis_snapshot(
    path: Path,
    *,
    generated_at: datetime,
    has_data: bool = True,
    waste_pct: float = 12.5,
    fingerprint: str = "fp-1",
    severity: str = "info",
    kind: str = "polluter_dirs",
    estimated_waste_tokens: int = 100,
    fixable_waste_tokens: int = 100,
) -> None:
    path.write_text(
        json.dumps(
            {
                "generated_at": generated_at.astimezone().isoformat().replace("+00:00", "Z"),
                "has_data": has_data,
                "waste_pct": waste_pct,
                "fixable_waste_tokens": fixable_waste_tokens,
                "findings_fingerprint": fingerprint,
                "findings": [
                    {
                        "severity": severity,
                        "kind": kind,
                        "estimated_waste_tokens": estimated_waste_tokens,
                        "items": [{"label": "node_modules"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def _write_diagnosis_state(path: Path, *, fingerprint: str, reminded_at: datetime) -> None:
    path.write_text(
        json.dumps(
            {
                "last_fingerprint": fingerprint,
                "last_reminded_at": reminded_at.astimezone().isoformat().replace("+00:00", "Z"),
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.parametrize("value", [".", "..."])
def test_clean_request_rejects_punctuation_only(value: str) -> None:
    assert mod._clean_request(value) == ""


def test_clean_request_keeps_structured_text() -> None:
    assert mod._clean_request("fix menubar.py") == "fix menubar.py"


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


def test_build_prompt_includes_uncommitted_git_changes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    _sidecar(tmp_path, monkeypatch)
    monkeypatch.setattr(
        mod,
        "_git_dirty",
        lambda cwd: ("feature/resume", 2, ["usage_session_resume.py", "i18n.json"]),
    )
    project = _project_dir(tmp_path)
    when = datetime.now().astimezone() - timedelta(hours=2)
    _write_session(
        project / "prev.jsonl",
        when=when,
        request="improve the resume handoff",
        commits=["feat: resume handoff"],
    )
    current = project / "current.jsonl"
    current.write_text("", encoding="utf-8")

    prompt = mod._build_prompt(
        {"transcript_path": str(current), "cwd": "/Users/me/Developer/myproj"}
    )

    assert "dirty branch=feature/resume" in prompt
    assert "count=2" in prompt
    assert "usage_session_resume.py, i18n.json" in prompt


def test_build_prompt_omits_uncommitted_line_when_git_dirty_returns_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    _sidecar(tmp_path, monkeypatch)
    monkeypatch.setattr(mod, "_git_dirty", lambda cwd: None)
    project = _project_dir(tmp_path)
    when = datetime.now().astimezone() - timedelta(hours=2)
    _write_session(
        project / "prev.jsonl",
        when=when,
        request="improve the resume handoff",
        commits=["feat: resume handoff"],
    )
    current = project / "current.jsonl"
    current.write_text("", encoding="utf-8")

    prompt = mod._build_prompt(
        {"transcript_path": str(current), "cwd": "/Users/me/Developer/myproj"}
    )

    assert prompt == (
        f"LEAD:: proj=myproj when={mod._format_time(when)} "
        "req=improve the resume handoff commits=feat: resume handoff todos=(none)"
    )
    assert "dirty branch=" not in prompt


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


def test_main_reads_utf8_bytes_when_stdin_uses_cp950(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    _sidecar(tmp_path, monkeypatch)
    project = _project_dir(tmp_path)
    current = project / "current.jsonl"
    current.write_text("", encoding="utf-8")
    payload = json.dumps(
        {"transcript_path": str(current), "cwd": r"C:\\Users\\USER\\Desktop\\GitHub專案\\usage"},
        ensure_ascii=False,
    )
    monkeypatch.setattr(
        sys, "stdin", io.TextIOWrapper(io.BytesIO(payload.encode("utf-8")), encoding="cp950")
    )

    assert mod.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert out["hookSpecificOutput"]["hookEventName"] == "SessionStart"


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


def test_build_prompt_skips_meta_entries_and_dedupes_non_adjacent_repeats(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """isMeta entries (skill/command expansions) are noise, not requests; repeats separated
    by such noise are still the same request and shouldn't eat a second handoff slot."""
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    _sidecar(tmp_path, monkeypatch)
    project = _project_dir(tmp_path)
    when = datetime.now().astimezone() - timedelta(hours=1)
    lines = [
        {
            "type": "user",
            "timestamp": when.isoformat(),
            "message": {"content": "evaluate repo X"},
        },
        {
            "type": "user",
            "isMeta": True,
            "timestamp": when.isoformat(),
            "message": {"content": "Base directory for this skill: /skills/foo ..."},
        },
        {
            "type": "user",
            "timestamp": when.isoformat(),
            "message": {"content": "evaluate repo X"},
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

    assert "Base directory for this skill" not in prompt
    assert prompt.count("evaluate repo X") == 1


def test_build_prompt_skips_diagnosis_reminder_when_waste_below_threshold(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    _sidecar(tmp_path, monkeypatch)
    snapshot, _state = _diagnosis_paths(tmp_path, monkeypatch)
    _write_diagnosis_snapshot(
        snapshot,
        generated_at=datetime.now().astimezone(),
        waste_pct=4.9,
        severity="info",
    )
    project = _project_dir(tmp_path)
    _write_session(
        project / "prev.jsonl",
        when=datetime.now().astimezone() - timedelta(hours=1),
        request="finish the parser cleanup",
    )
    current = project / "current.jsonl"
    current.write_text("", encoding="utf-8")

    prompt = mod._build_prompt(
        {"transcript_path": str(current), "cwd": "/Users/me/Developer/myproj"}
    )

    assert "Health check:" not in prompt


def test_build_prompt_skips_diagnosis_reminder_during_cooldown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    _sidecar(tmp_path, monkeypatch)
    snapshot, state = _diagnosis_paths(tmp_path, monkeypatch)
    now = datetime.now().astimezone()
    _write_diagnosis_snapshot(snapshot, generated_at=now, fingerprint="fp-same")
    _write_diagnosis_state(state, fingerprint="fp-same", reminded_at=now - timedelta(days=1))
    project = _project_dir(tmp_path)
    _write_session(
        project / "prev.jsonl",
        when=now - timedelta(hours=1),
        request="finish the parser cleanup",
    )
    current = project / "current.jsonl"
    current.write_text("", encoding="utf-8")

    prompt = mod._build_prompt(
        {"transcript_path": str(current), "cwd": "/Users/me/Developer/myproj"}
    )

    assert "Health check:" not in prompt


def test_build_prompt_injects_diagnosis_reminder_when_fingerprint_changes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    _sidecar(tmp_path, monkeypatch)
    snapshot, state = _diagnosis_paths(tmp_path, monkeypatch)
    now = datetime.now().astimezone()
    _write_diagnosis_snapshot(
        snapshot,
        generated_at=now,
        waste_pct=2.0,
        fingerprint="fp-new",
        severity="critical",
    )
    _write_diagnosis_state(state, fingerprint="fp-old", reminded_at=now - timedelta(days=1))
    project = _project_dir(tmp_path)
    _write_session(
        project / "prev.jsonl",
        when=now - timedelta(hours=1),
        request="finish the parser cleanup",
    )
    current = project / "current.jsonl"
    current.write_text("", encoding="utf-8")

    prompt = mod._build_prompt(
        {"transcript_path": str(current), "cwd": "/Users/me/Developer/myproj"}
    )

    assert "Health check: about 2% waste came from scanning generated folders." in prompt
    assert "修" in prompt


def test_build_prompt_uses_explain_reminder_when_nothing_fixable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    _sidecar(tmp_path, monkeypatch)
    snapshot, state = _diagnosis_paths(tmp_path, monkeypatch)
    now = datetime.now().astimezone()
    _write_diagnosis_snapshot(
        snapshot,
        generated_at=now,
        waste_pct=2.0,
        fingerprint="fp-new",
        severity="critical",
        fixable_waste_tokens=0,
    )
    _write_diagnosis_state(state, fingerprint="fp-old", reminded_at=now - timedelta(days=1))
    project = _project_dir(tmp_path)
    _write_session(
        project / "prev.jsonl",
        when=now - timedelta(hours=1),
        request="finish the parser cleanup",
    )
    current = project / "current.jsonl"
    current.write_text("", encoding="utf-8")

    prompt = mod._build_prompt(
        {"transcript_path": str(current), "cwd": "/Users/me/Developer/myproj"}
    )

    assert "Health check: about 2% waste came from scanning generated folders." in prompt
    assert "看" in prompt
    assert "修" not in prompt
    # The reminder line is JSON-encoded into the prompt, which escapes the
    # backslashes of a Windows snapshot path.
    assert json.dumps(str(snapshot), ensure_ascii=False)[1:-1] in prompt
    state_data = json.loads(state.read_text(encoding="utf-8"))
    assert state_data["last_fingerprint"] == "fp-new"


def test_build_prompt_skips_diagnosis_reminder_when_snapshot_is_stale(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    _sidecar(tmp_path, monkeypatch)
    snapshot, _state = _diagnosis_paths(tmp_path, monkeypatch)
    _write_diagnosis_snapshot(
        snapshot,
        generated_at=datetime.now().astimezone() - timedelta(hours=49),
    )
    project = _project_dir(tmp_path)
    _write_session(
        project / "prev.jsonl",
        when=datetime.now().astimezone() - timedelta(hours=1),
        request="finish the parser cleanup",
    )
    current = project / "current.jsonl"
    current.write_text("", encoding="utf-8")

    prompt = mod._build_prompt(
        {"transcript_path": str(current), "cwd": "/Users/me/Developer/myproj"}
    )

    assert "Health check:" not in prompt

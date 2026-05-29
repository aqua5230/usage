from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import resume_loader


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _edit(path: str) -> dict[str, object]:
    return {"name": "Edit", "input": {"file_path": path}}


def _write_tool(path: str) -> dict[str, object]:
    return {"name": "Write", "input": {"file_path": path}}


def _bash(command: str) -> dict[str, object]:
    return {"name": "Bash", "input": {"command": command}}


def _assistant_tools(ts: str, tools: list[dict[str, object]]) -> dict[str, object]:
    content = [{"type": "tool_use", **tool} for tool in tools]
    return {
        "type": "assistant",
        "timestamp": ts,
        "sessionId": "s1",
        "message": {"content": content},
    }


def _write_session(project_dir: Path, name: str, lines: list[dict[str, object]]) -> Path:
    project_dir.mkdir(parents=True, exist_ok=True)
    path = project_dir / name
    path.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")
    return path


def _patch_dirs(monkeypatch: pytest.MonkeyPatch, base: Path) -> None:
    monkeypatch.setattr("adapters.claude.get_claude_dirs", lambda: [str(base)])


def test_collects_edits_and_inline_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = tmp_path / "projects"
    tools = [
        _edit("/Users/me/myproj/app.py"),
        _write_tool("/Users/me/myproj/README.md"),
        _bash('git commit -m "feat: add thing"'),
    ]
    _write_session(base / "-Users-me-myproj", "a.jsonl", [_assistant_tools(_now_iso(), tools)])
    _patch_dirs(monkeypatch, base)

    rows = resume_loader.load_recent_work()

    assert len(rows) == 1
    assert rows[0].project == "myproj"
    assert rows[0].changed_files == ["app.py", "README.md"]
    assert rows[0].commit_titles == ["feat: add thing"]


def test_heredoc_commit_title(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    command = "git commit -m \"$(cat <<'EOF'\nfix: the bug\n\nbody line\nEOF\n)\""
    tools = [_edit("/Users/me/proj2/x.py"), _bash(command)]
    _write_session(
        tmp_path / "projects" / "-Users-me-proj2",
        "a.jsonl",
        [_assistant_tools(_now_iso(), tools)],
    )
    _patch_dirs(monkeypatch, tmp_path / "projects")

    rows = resume_loader.load_recent_work()

    assert rows[0].commit_titles == ["fix: the bug"]


def test_python_heredoc_not_mistaken_for_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Command mentions "git commit" but is really a python heredoc — must NOT be a commit.
    command = "python3 - <<'PY'\nimport re\nx = 'git commit'\nPY"
    tools = [_edit("/Users/me/proj3/y.py"), _bash(command)]
    _write_session(
        tmp_path / "projects" / "-Users-me-proj3",
        "a.jsonl",
        [_assistant_tools(_now_iso(), tools)],
    )
    _patch_dirs(monkeypatch, tmp_path / "projects")

    rows = resume_loader.load_recent_work()

    assert rows[0].commit_titles == []


def test_session_without_work_is_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chat: dict[str, object] = {
        "type": "assistant",
        "timestamp": _now_iso(),
        "sessionId": "s",
        "message": {"content": [{"type": "text", "text": "hi"}]},
    }
    _write_session(tmp_path / "projects" / "-Users-me-proj4", "a.jsonl", [chat])
    _patch_dirs(monkeypatch, tmp_path / "projects")

    assert resume_loader.load_recent_work() == []


def test_old_session_filtered_by_cutoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = (datetime.now(UTC) - timedelta(days=60)).isoformat()
    tools = [_edit("/Users/me/proj5/z.py")]
    _write_session(
        tmp_path / "projects" / "-Users-me-proj5",
        "a.jsonl",
        [_assistant_tools(old, tools)],
    )
    _patch_dirs(monkeypatch, tmp_path / "projects")

    assert resume_loader.load_recent_work(days_back=30) == []


def test_latest_jsonl_wins_within_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proj = tmp_path / "projects" / "-Users-me-proj6"
    older = _write_session(
        proj, "old.jsonl", [_assistant_tools(_now_iso(), [_edit("/Users/me/proj6/old.py")])]
    )
    newer = _write_session(
        proj, "new.jsonl", [_assistant_tools(_now_iso(), [_edit("/Users/me/proj6/new.py")])]
    )
    os.utime(older, (1, 1))
    os.utime(newer, None)
    _patch_dirs(monkeypatch, tmp_path / "projects")

    rows = resume_loader.load_recent_work()

    assert len(rows) == 1
    assert rows[0].changed_files == ["new.py"]


def test_project_name_from_cwd_beats_encoded_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The encoded dir name turns every separator into "-", so a hyphenated
    # project ("usage-promo") gets sliced to "promo". The cwd field is lossless.
    entry = _assistant_tools(_now_iso(), [_edit("/Users/me/usage-promo/refresh.py")])
    entry["cwd"] = "/Users/me/usage-promo"
    _write_session(tmp_path / "projects" / "-Users-me-usage-promo", "a.jsonl", [entry])
    _patch_dirs(monkeypatch, tmp_path / "projects")

    rows = resume_loader.load_recent_work()

    assert rows[0].project == "usage-promo"


def test_project_name_falls_back_to_dir_without_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Sessions without a cwd field still resolve a name from the dir.
    _write_session(
        tmp_path / "projects" / "-Users-me-myproj",
        "a.jsonl",
        [_assistant_tools(_now_iso(), [_edit("/Users/me/myproj/app.py")])],
    )
    _patch_dirs(monkeypatch, tmp_path / "projects")

    assert resume_loader.load_recent_work()[0].project == "myproj"


def test_same_name_projects_disambiguated_by_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Two "usage" projects under different parents must stay distinguishable.
    base = tmp_path / "projects"
    a = _assistant_tools(_now_iso(), [_edit("/Users/me/Developer/usage/a.py")])
    a["cwd"] = "/Users/me/Developer/usage"
    b = _assistant_tools(_now_iso(), [_edit("/Users/me/Desktop/usage/b.py")])
    b["cwd"] = "/Users/me/Desktop/usage"
    _write_session(base / "-Users-me-Developer-usage", "a.jsonl", [a])
    _write_session(base / "-Users-me-Desktop-usage", "b.jsonl", [b])
    _patch_dirs(monkeypatch, base)

    names = {r.project for r in resume_loader.load_recent_work()}

    assert names == {"usage (Developer)", "usage (Desktop)"}


def test_recent_work_items_shape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    proj = tmp_path / "projects" / "-Users-me-proj7"
    _write_session(
        proj, "a.jsonl", [_assistant_tools(_now_iso(), [_edit("/Users/me/proj7/a.py")])]
    )
    _patch_dirs(monkeypatch, tmp_path / "projects")

    items = resume_loader.recent_work_items()

    assert items[0]["project"] == "proj7"
    assert items[0]["changed_files"] == ["a.py"]
    assert isinstance(items[0]["last_active"], str)

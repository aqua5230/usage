# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

import project_resolver
from project_resolver import project_from_encoded_path


@pytest.fixture(autouse=True)
def _clear_project_resolver_cache() -> None:
    project_resolver.resolve_project_name.cache_clear()
    project_resolver._resolve_project_name.cache_clear()


def _completed(
    returncode: int,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["git", "-C", "/work/feature", "worktree", "list", "--porcelain"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def test_resolve_project_name_uses_first_worktree_basename(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = Mock(
        return_value=_completed(
            0,
            stdout=(
                "worktree /Users/me/src/main-project\n"
                "worktree /Users/me/src/main-project-feature\n"
            ),
        )
    )
    monkeypatch.setattr("project_resolver.subprocess.run", run)

    assert project_resolver.resolve_project_name("/work/feature") == "main-project"


def test_resolve_project_name_falls_back_for_non_git_repo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = Mock(return_value=_completed(128, stderr="fatal: not a git repository\n"))
    monkeypatch.setattr("project_resolver.subprocess.run", run)

    assert project_resolver.resolve_project_name("/work/feature") == "feature"


def test_resolve_project_name_falls_back_when_git_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = Mock(side_effect=FileNotFoundError)
    monkeypatch.setattr("project_resolver.subprocess.run", run)

    assert project_resolver.resolve_project_name("/work/feature") == "feature"


def test_resolve_project_name_falls_back_on_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = Mock(side_effect=subprocess.TimeoutExpired(cmd=["git"], timeout=3))
    monkeypatch.setattr("project_resolver.subprocess.run", run)

    assert project_resolver.resolve_project_name("/work/feature") == "feature"


@pytest.mark.parametrize("stdout", ["", "bare /work/feature\n"])
def test_resolve_project_name_falls_back_for_unexpected_output(
    monkeypatch: pytest.MonkeyPatch,
    stdout: str,
) -> None:
    run = Mock(return_value=_completed(0, stdout=stdout))
    monkeypatch.setattr("project_resolver.subprocess.run", run)

    assert project_resolver.resolve_project_name("/work/feature") == "feature"


def test_resolve_project_name_falls_back_for_empty_cwd(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = Mock(return_value=_completed(0, stdout="worktree /work/main\n"))
    monkeypatch.setattr("project_resolver.subprocess.run", run)

    assert project_resolver.resolve_project_name("") == "unknown"
    run.assert_not_called()


def test_resolve_project_name_reuses_cached_subprocess_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "feature"
    run = Mock(return_value=_completed(0, stdout="worktree /work/main-project\n"))
    monkeypatch.setattr("project_resolver.subprocess.run", run)

    assert project_resolver.resolve_project_name(path) == "main-project"
    assert project_resolver.resolve_project_name(str(path)) == "main-project"
    assert run.call_count == 1


def test_resolve_project_name_caches_path_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolve = Mock(return_value=Path("/work/feature"))
    run = Mock(return_value=_completed(0, stdout="worktree /work/main-project\n"))
    monkeypatch.setattr(Path, "resolve", resolve)
    monkeypatch.setattr("project_resolver.subprocess.run", run)

    assert project_resolver.resolve_project_name("/work/feature") == "main-project"
    assert project_resolver.resolve_project_name("/work/feature") == "main-project"

    assert resolve.call_count == 1
    assert run.call_count == 1


def test_zzz_debug_windows_decode(tmp_path: Path) -> None:
    real_project = tmp_path / "Users" / "me" / "alpha"
    real_project.mkdir(parents=True)
    encoded = str(real_project).replace(os.sep, "-")
    parts = [p for p in encoded.split("-") if p]
    root, start = project_resolver._encoded_path_root(parts)
    debug = [
        f"os.sep={os.sep!r}",
        f"tmp_path={tmp_path!r}",
        f"parts={parts!r}",
        f"root={root!r} start={start}",
    ]

    def search(index: int, current: Path) -> Path | None:
        for end in range(index + 1, len(parts) + 1):
            candidate = current / "-".join(parts[index:end])
            hit = candidate.is_dir()
            debug.append(f"try index={index} end={end} candidate={candidate!r} is_dir={hit}")
            if not hit:
                continue
            if end == len(parts):
                return candidate
            result = search(end, candidate)
            if result is not None:
                return result
        return None

    found = search(start, root)
    debug.append(f"found={found!r}")
    raise AssertionError("\n".join(debug))


def test_project_from_encoded_path_decodes_real_project(tmp_path: Path) -> None:
    projects_dir = tmp_path / "projects"
    real_project = tmp_path / "Users" / "me" / "alpha"
    real_project.mkdir(parents=True)
    encoded = str(real_project).replace(os.sep, "-")

    result = project_from_encoded_path(projects_dir / encoded / "a.jsonl", projects_dir)

    assert result == "alpha"


def test_project_from_encoded_path_resolves_existing_dash_dir(tmp_path: Path) -> None:
    projects_dir = tmp_path / "projects"
    real_project = tmp_path / "Users" / "me" / "Desktop" / "claude-tutorial-video"
    real_project.mkdir(parents=True)
    encoded = str(real_project).replace(os.sep, "-")

    result = project_from_encoded_path(projects_dir / encoded / "a.jsonl", projects_dir)

    assert result == "claude-tutorial-video"


def test_encoded_path_root_uses_windows_drive_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(os, "sep", "\\")

    root, start = project_resolver._encoded_path_root(
        ["C:", "Users", "runneradmin", "AppData", "Local", "Temp", "alpha"]
    )

    assert str(root) == "C:\\"
    assert start == 1


def test_project_from_encoded_path_fallback_preserves_dash(tmp_path: Path) -> None:
    projects_dir = tmp_path / "projects"

    result = project_from_encoded_path(
        projects_dir / "-missing-plain-project" / "a.jsonl", projects_dir
    )

    assert result == "missing-plain-project"


def test_project_from_encoded_path_outside_dir_is_unknown(tmp_path: Path) -> None:
    projects_dir = tmp_path / "projects"

    result = project_from_encoded_path(tmp_path / "outside.jsonl", projects_dir)

    assert result == "unknown"


def test_resolve_project_name_forces_utf8_git_decoding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A .app launched via LaunchServices has no LANG, so text=True would decode
    # git output as ASCII and crash on non-ASCII repo paths. Lock in utf-8.
    run = Mock(return_value=_completed(0, stdout="worktree /work/main-project\n"))
    monkeypatch.setattr("project_resolver.subprocess.run", run)

    project_resolver.resolve_project_name("/work/feature")

    _, kwargs = run.call_args
    assert kwargs.get("encoding") == "utf-8"
    assert kwargs.get("errors") == "replace"

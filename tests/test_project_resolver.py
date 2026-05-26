from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

import project_resolver


@pytest.fixture(autouse=True)
def _clear_project_resolver_cache() -> None:
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

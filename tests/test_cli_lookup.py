# SPDX-License-Identifier: AGPL-3.0-only
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from usage_common import cli_lookup


@pytest.fixture(autouse=True)
def isolated_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr("usage_common.cli_lookup.shutil.which", lambda _: None)


def executable(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    path.chmod(0o755)
    return str(path)


def test_which_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("usage_common.cli_lookup.shutil.which", lambda _: "/from/path/cli")
    monkeypatch.setattr(
        "usage_common.cli_lookup.os.path.expanduser", lambda _: pytest.fail("searched")
    )
    assert cli_lookup.resolve_cli("cli", ("~/fallback",)) == "/from/path/cli"


@pytest.mark.skipif(sys.platform == "win32", reason="Unix executable paths")
def test_fallback_order_before_managers(tmp_path: Path) -> None:
    first = executable(tmp_path / "first/cli")
    executable(tmp_path / "second/cli")
    executable(tmp_path / ".volta/bin/cli")
    assert cli_lookup.resolve_cli("cli", ("~/first/cli", "~/second/cli")) == first


@pytest.mark.skipif(sys.platform == "win32", reason="Unix version managers")
@pytest.mark.parametrize(
    "directory",
    [
        ".volta/bin",
        ".local/share/mise/shims",
        ".asdf/shims",
        ".local/share/fnm/aliases/default/bin",
        "Library/Application Support/fnm/aliases/default/bin",
        ".bun/bin",
        "Library/pnpm",
        ".npm-global/bin",
        ".nvm/versions/node/v22.3.0/bin",
    ],
)
def test_manager_location(tmp_path: Path, directory: str) -> None:
    path = executable(tmp_path / directory / "cli")
    assert cli_lookup.resolve_cli("cli", ()) == path


@pytest.mark.skipif(sys.platform == "win32", reason="Unix version managers")
def test_nvm_numeric_order_and_invalid_version(tmp_path: Path) -> None:
    root = tmp_path / ".nvm/versions/node"
    executable(root / "v9.10.0/bin/cli")
    newest = executable(root / "v22.3.0/bin/cli")
    executable(root / "v999.invalid/bin/cli")
    assert cli_lookup.resolve_cli("cli", ()) == newest


@pytest.mark.skipif(sys.platform == "win32", reason="Unix execution permissions")
def test_rejects_nonexecutable_and_directory(tmp_path: Path) -> None:
    path = Path(executable(tmp_path / ".volta/bin/cli"))
    path.chmod(0o644)
    (tmp_path / ".asdf/shims/cli").mkdir(parents=True)
    assert cli_lookup.resolve_cli("cli", (str(path),)) is None


@pytest.mark.skipif(sys.platform == "win32", reason="Unix executable fixture")
def test_windows_skips_managers(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    executable(tmp_path / ".volta/bin/cli")
    fallback = executable(tmp_path / "fallback/cli")
    monkeypatch.setattr("usage_common.cli_lookup.sys.platform", "win32")
    assert cli_lookup.resolve_cli("cli", ()) is None
    assert cli_lookup.resolve_cli("cli", (fallback,)) == fallback


@pytest.mark.skipif(sys.platform == "win32", reason="Unix PATH")
@pytest.mark.parametrize("path", [None, "", "/usr/bin", "/bin/tools:/usr/bin"])
def test_cli_env_prepends_and_preserves(path: str | None) -> None:
    base = {"KEEP": "value"}
    if path is not None:
        base["PATH"] = path
    result = cli_lookup.cli_env("/bin/tools/cli", base)
    assert result["PATH"].split(os.pathsep)[0] == "/bin/tools"
    assert result["PATH"].count("/bin/tools") == 1
    assert result["KEEP"] == "value"
    assert result is not base
    assert base == ({"KEEP": "value"} if path is None else {"KEEP": "value", "PATH": path})


@pytest.mark.skipif(sys.platform == "win32", reason="Unix PATH")
def test_cli_env_defaults_to_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("KEEP", "value")
    result = cli_lookup.cli_env("/tools/cli")
    assert result["PATH"] == "/tools:/usr/bin"
    assert result["KEEP"] == "value"
    assert os.environ["PATH"] == "/usr/bin"


@pytest.mark.skipif(sys.platform == "win32", reason="Unix PATH")
def test_cli_env_leaves_path_for_bare_name() -> None:
    assert cli_lookup.cli_env("cli", {"PATH": "/usr/bin"})["PATH"] == "/usr/bin"


def test_cli_env_windows_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("usage_common.cli_lookup.sys.platform", "win32")
    base = {"PATH": "original", "KEEP": "value"}
    result = cli_lookup.cli_env("C:/tools/cli", base)
    assert result == base
    assert result is not base

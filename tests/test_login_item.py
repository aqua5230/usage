# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import inspect
import logging
import plistlib
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import get_type_hints

import pytest

from installer import login_item


def _configure_login_item_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    plist_path = tmp_path / "LaunchAgents" / "com.lollapalooza.usage.plist"
    monkeypatch.setattr(login_item, "PLIST_PATH", plist_path)
    monkeypatch.setattr(login_item, "_LOG_DIR", tmp_path / "Logs" / "usage")
    monkeypatch.setattr(login_item, "_plist_text", lambda: "plist")
    return plist_path


def _completed(
    cmd: list[str],
    returncode: int,
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(cmd, returncode, stdout="", stderr=stderr)


def test_build_plist_for_app_context() -> None:
    plist_text = login_item.build_plist(
        ["/usr/bin/open", "/Applications/usage.app"],
        None,
    )

    payload = plistlib.loads(plist_text.encode("utf-8"))

    assert payload["Label"] == login_item.LABEL
    assert payload["RunAtLoad"] is True
    assert payload["ProgramArguments"] == ["/usr/bin/open", "/Applications/usage.app"]
    assert "KeepAlive" not in payload
    assert "WorkingDirectory" not in payload
    assert payload["StandardOutPath"].endswith("/Library/Logs/usage/usage.log")
    assert payload["StandardErrorPath"].endswith("/Library/Logs/usage/usage.err.log")


def test_build_plist_for_source_context() -> None:
    plist_text = login_item.build_plist(
        ["/usr/bin/python3", "/tmp/usage/main.py"],
        "/tmp/usage",
    )

    payload = plistlib.loads(plist_text.encode("utf-8"))

    assert payload["ProgramArguments"] == ["/usr/bin/python3", "/tmp/usage/main.py"]
    assert payload["WorkingDirectory"] == "/tmp/usage"
    assert payload["KeepAlive"] == {"SuccessfulExit": False}


def test_program_context_for_app_bundle_preserves_space_in_bundle_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle_path = "/Applications/Usage Monitor.app"
    bundle = SimpleNamespace(
        bundleIdentifier=lambda: login_item.LABEL,
        bundlePath=lambda: bundle_path,
    )
    monkeypatch.setattr(login_item, "NSBundle", SimpleNamespace(mainBundle=lambda: bundle))

    program_args, working_dir = login_item._program_context()

    assert program_args == ["/usr/bin/open", bundle_path]
    assert working_dir is None


def test_program_context_for_source_tree_uses_main_py_and_project_dir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = SimpleNamespace(
        bundleIdentifier=lambda: "com.example.other-app",
        bundlePath=lambda: "/Applications/Other.app",
    )
    monkeypatch.setattr(login_item, "NSBundle", SimpleNamespace(mainBundle=lambda: bundle))
    project_dir = Path(login_item.__file__).resolve().parent.parent

    program_args, working_dir = login_item._program_context()

    assert program_args == [str(sys.executable), str(project_dir / "main.py")]
    assert working_dir == str(project_dir)


def test_is_enabled_uses_plist_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    plist_path = tmp_path / "com.lollapalooza.usage.plist"
    monkeypatch.setattr(login_item, "PLIST_PATH", plist_path)

    assert login_item.is_enabled() is False

    plist_path.write_text("plist", encoding="utf-8")

    assert login_item.is_enabled() is True


def test_disable_removes_plist(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    plist_path = tmp_path / "com.lollapalooza.usage.plist"
    plist_path.write_text("plist", encoding="utf-8")
    monkeypatch.setattr(login_item, "PLIST_PATH", plist_path)
    monkeypatch.setattr(login_item, "_launchctl_bootout", lambda: None)

    login_item.disable()

    assert plist_path.exists() is False
    assert login_item.is_enabled() is False


def test_enable_bootstrap_returncode_0_keeps_plist_and_uses_safe_subprocess(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plist_path = _configure_login_item_paths(monkeypatch, tmp_path)
    calls: list[tuple[list[str], bool, bool, str, str, bool, int]] = []

    def fake_getuid() -> int:
        return 501

    def fake_run(
        cmd: list[str],
        *,
        capture_output: bool,
        text: bool,
        encoding: str,
        errors: str,
        check: bool,
        timeout: int,
    ) -> subprocess.CompletedProcess[str]:
        calls.append((cmd, capture_output, text, encoding, errors, check, timeout))
        return _completed(cmd, 0)

    monkeypatch.setattr("installer.login_item.os.getuid", fake_getuid)
    monkeypatch.setattr("installer.login_item.subprocess.run", fake_run)

    login_item.enable()

    assert plist_path.read_text(encoding="utf-8") == "plist"
    assert calls == [
        (
            ["launchctl", "bootstrap", "gui/501", str(plist_path)],
            True,
            True,
            "utf-8",
            "replace",
            False,
            5,
        )
    ]
    assert isinstance(calls[0][0], list)


def test_enable_bootstrap_returncode_17_keeps_plist_without_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plist_path = _configure_login_item_paths(monkeypatch, tmp_path)

    def fake_run(
        cmd: list[str],
        *,
        capture_output: bool,
        text: bool,
        encoding: str,
        errors: str,
        check: bool,
        timeout: int,
    ) -> subprocess.CompletedProcess[str]:
        _ = capture_output, text, check, timeout
        return _completed(cmd, 17, "Bootstrap failed: 17: File exists")

    monkeypatch.setattr("installer.login_item.subprocess.run", fake_run)

    login_item.enable()

    assert plist_path.exists() is True


def test_enable_bootstrap_unexpected_returncode_warns_and_keeps_plist(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    plist_path = _configure_login_item_paths(monkeypatch, tmp_path)

    def fake_run(
        cmd: list[str],
        *,
        capture_output: bool,
        text: bool,
        encoding: str,
        errors: str,
        check: bool,
        timeout: int,
    ) -> subprocess.CompletedProcess[str]:
        _ = capture_output, text, check, timeout
        return _completed(cmd, 5, "permission denied")

    monkeypatch.setattr("installer.login_item.subprocess.run", fake_run)
    caplog.set_level(logging.WARNING, logger="installer.login_item")

    login_item.enable()

    assert plist_path.exists() is True
    assert "bootstrap" in caplog.text
    assert "returncode=5" in caplog.text
    assert "permission denied" in caplog.text


@pytest.mark.parametrize(
    "side_effect",
    [
        FileNotFoundError("launchctl missing"),
        subprocess.TimeoutExpired(cmd=["launchctl"], timeout=5),
    ],
)
def test_enable_bootstrap_subprocess_exception_warns_and_keeps_plist(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    side_effect: BaseException,
) -> None:
    plist_path = _configure_login_item_paths(monkeypatch, tmp_path)

    def fake_run(
        cmd: list[str],
        *,
        capture_output: bool,
        text: bool,
        encoding: str,
        errors: str,
        check: bool,
        timeout: int,
    ) -> subprocess.CompletedProcess[str]:
        _ = cmd, capture_output, text, check, timeout
        raise side_effect

    monkeypatch.setattr("installer.login_item.subprocess.run", fake_run)
    caplog.set_level(logging.WARNING, logger="installer.login_item")

    login_item.enable()

    assert plist_path.exists() is True
    assert "bootstrap" in caplog.text
    assert "failed" in caplog.text


def test_disable_bootout_returncode_0_removes_plist_and_uses_safe_subprocess(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plist_path = _configure_login_item_paths(monkeypatch, tmp_path)
    plist_path.parent.mkdir(parents=True)
    plist_path.write_text("plist", encoding="utf-8")
    calls: list[tuple[list[str], bool, bool, str, str, bool, int]] = []

    def fake_getuid() -> int:
        return 501

    def fake_run(
        cmd: list[str],
        *,
        capture_output: bool,
        text: bool,
        encoding: str,
        errors: str,
        check: bool,
        timeout: int,
    ) -> subprocess.CompletedProcess[str]:
        calls.append((cmd, capture_output, text, encoding, errors, check, timeout))
        return _completed(cmd, 0)

    monkeypatch.setattr("installer.login_item.os.getuid", fake_getuid)
    monkeypatch.setattr("installer.login_item.subprocess.run", fake_run)

    login_item.disable()

    assert plist_path.exists() is False
    assert calls == [
        (
            ["launchctl", "bootout", f"gui/501/{login_item.LABEL}"],
            True,
            True,
            "utf-8",
            "replace",
            False,
            5,
        )
    ]
    assert isinstance(calls[0][0], list)


def test_disable_bootout_returncode_113_removes_plist_without_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plist_path = _configure_login_item_paths(monkeypatch, tmp_path)
    plist_path.parent.mkdir(parents=True)
    plist_path.write_text("plist", encoding="utf-8")

    def fake_run(
        cmd: list[str],
        *,
        capture_output: bool,
        text: bool,
        encoding: str,
        errors: str,
        check: bool,
        timeout: int,
    ) -> subprocess.CompletedProcess[str]:
        _ = capture_output, text, check, timeout
        return _completed(cmd, 113, "could not find specified service")

    monkeypatch.setattr("installer.login_item.subprocess.run", fake_run)

    login_item.disable()

    assert plist_path.exists() is False


def test_disable_bootout_unexpected_returncode_warns_and_removes_plist(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    plist_path = _configure_login_item_paths(monkeypatch, tmp_path)
    plist_path.parent.mkdir(parents=True)
    plist_path.write_text("plist", encoding="utf-8")

    def fake_run(
        cmd: list[str],
        *,
        capture_output: bool,
        text: bool,
        encoding: str,
        errors: str,
        check: bool,
        timeout: int,
    ) -> subprocess.CompletedProcess[str]:
        _ = capture_output, text, check, timeout
        return _completed(cmd, 5, "bad service")

    monkeypatch.setattr("installer.login_item.subprocess.run", fake_run)
    caplog.set_level(logging.WARNING, logger="installer.login_item")

    login_item.disable()

    assert plist_path.exists() is False
    assert "bootout" in caplog.text
    assert "returncode=5" in caplog.text
    assert "bad service" in caplog.text


def test_disable_bootout_file_not_found_warns_and_removes_plist(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    plist_path = _configure_login_item_paths(monkeypatch, tmp_path)
    plist_path.parent.mkdir(parents=True)
    plist_path.write_text("plist", encoding="utf-8")

    def fake_run(
        cmd: list[str],
        *,
        capture_output: bool,
        text: bool,
        encoding: str,
        errors: str,
        check: bool,
        timeout: int,
    ) -> subprocess.CompletedProcess[str]:
        _ = cmd, capture_output, text, check, timeout
        raise FileNotFoundError("launchctl missing")

    monkeypatch.setattr("installer.login_item.subprocess.run", fake_run)
    caplog.set_level(logging.WARNING, logger="installer.login_item")

    login_item.disable()

    assert plist_path.exists() is False
    assert "bootout" in caplog.text
    assert "launchctl missing" in caplog.text


def test_enable_disable_signatures_stay_void() -> None:
    assert list(inspect.signature(login_item.enable).parameters) == []
    assert list(inspect.signature(login_item.disable).parameters) == []
    assert get_type_hints(login_item.enable)["return"] is type(None)
    assert get_type_hints(login_item.disable)["return"] is type(None)


def test_launchctl_domain_target_uses_gui_uid(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_getuid() -> int:
        return 501

    monkeypatch.setattr("installer.login_item.os.getuid", fake_getuid)

    assert login_item._launchctl_domain_target() == "gui/501"

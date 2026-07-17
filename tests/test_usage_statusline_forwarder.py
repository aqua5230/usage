# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import io
import json
import subprocess
import sys
from importlib import import_module
from types import SimpleNamespace
from typing import Any

import pytest

usage_statusline_forwarder: Any = import_module("usage_statusline_forwarder")


def test_windows_output_reconfigures_both_streams(monkeypatch: pytest.MonkeyPatch) -> None:
    class Stream:
        def __init__(self) -> None:
            self.encodings: list[str] = []

        def reconfigure(self, *, encoding: str) -> None:
            self.encodings.append(encoding)

    stdout = Stream()
    stderr = Stream()
    monkeypatch.setattr(usage_statusline_forwarder, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)

    usage_statusline_forwarder._configure_windows_utf8_output()

    assert stdout.encodings == ["utf-8"]
    assert stderr.encodings == ["utf-8"]


def test_main_fans_stdin_out_to_all_hooks(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[tuple[list[str], str, int]] = []
    hooks = [
        "/tmp/claude-statusline.py",
        "/tmp/usage-statusline-forwarder.py",
        "/tmp/usage-statusline.py",
    ]

    def fake_run(
        cmd: list[str],
        *,
        input: str,
        text: bool,
        encoding: str,
        errors: str,
        check: bool,
        capture_output: bool,
        timeout: int,
    ) -> subprocess.CompletedProcess[str]:
        assert text is True
        assert encoding == "utf-8"
        assert errors == "replace"
        assert check is False
        assert capture_output is True
        calls.append((cmd, input, timeout))
        return subprocess.CompletedProcess(cmd, 0, stdout=f"{cmd[1]}\n", stderr="")

    monkeypatch.setattr(sys, "stdin", io.StringIO('{"session_id":"abc"}'))
    monkeypatch.setattr(usage_statusline_forwarder.glob, "glob", lambda pattern: hooks)
    monkeypatch.setattr(usage_statusline_forwarder.subprocess, "run", fake_run)

    usage_statusline_forwarder.main()

    assert calls == [
        ([sys.executable, "/tmp/claude-statusline.py"], '{"session_id":"abc"}', 5),
        ([sys.executable, "/tmp/usage-statusline.py"], '{"session_id":"abc"}', 5),
    ]
    assert capsys.readouterr().out == "/tmp/claude-statusline.py\n/tmp/usage-statusline.py\n"


def test_main_reads_utf8_bytes_when_stdin_uses_cp950(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_values: list[str] = []
    payload = json.dumps(
        {"cwd": r"C:\\Users\\USER\\Desktop\\GitHub專案\\usage"}, ensure_ascii=False
    )
    stdin = io.TextIOWrapper(io.BytesIO(payload.encode("utf-8")), encoding="cp950")

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        raw_values.append(kwargs["input"])
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(
        usage_statusline_forwarder.glob, "glob", lambda pattern: ["/tmp/x-statusline.py"]
    )
    monkeypatch.setattr(usage_statusline_forwarder.subprocess, "run", fake_run)

    usage_statusline_forwarder.main()

    assert raw_values == [payload]


def test_timeout_hook_does_not_block_later_hooks(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[str] = []
    hooks = ["/tmp/aaa-slow-statusline.py", "/tmp/zzz-ok-statusline.py"]

    def fake_run(
        cmd: list[str],
        *,
        input: str,
        text: bool,
        encoding: str,
        errors: str,
        check: bool,
        capture_output: bool,
        timeout: int,
    ) -> subprocess.CompletedProcess[str]:
        _ = input, text, encoding, errors, check, capture_output
        calls.append(cmd[1])
        if cmd[1] == "/tmp/aaa-slow-statusline.py":
            raise subprocess.TimeoutExpired(cmd, timeout)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n", stderr="")

    monkeypatch.setattr(sys, "stdin", io.StringIO('{"ok":true}'))
    monkeypatch.setattr(usage_statusline_forwarder.glob, "glob", lambda pattern: hooks)
    monkeypatch.setattr(usage_statusline_forwarder.subprocess, "run", fake_run)

    usage_statusline_forwarder.main()

    assert calls == hooks
    assert capsys.readouterr().out == "ok\n"


def test_nonzero_hook_exit_keeps_forwarder_successful(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    hooks = ["/tmp/fail-statusline.py", "/tmp/ok-statusline.py"]

    def fake_run(
        cmd: list[str],
        *,
        input: str,
        text: bool,
        encoding: str,
        errors: str,
        check: bool,
        capture_output: bool,
        timeout: int,
    ) -> subprocess.CompletedProcess[str]:
        _ = input, text, encoding, errors, check, capture_output, timeout
        if cmd[1] == "/tmp/fail-statusline.py":
            return subprocess.CompletedProcess(cmd, 1, stdout="failed output\n", stderr="boom")
        return subprocess.CompletedProcess(cmd, 0, stdout="ok output\n", stderr="")

    monkeypatch.setattr(sys, "stdin", io.StringIO('{"ok":true}'))
    monkeypatch.setattr(usage_statusline_forwarder.glob, "glob", lambda pattern: hooks)
    monkeypatch.setattr(usage_statusline_forwarder.subprocess, "run", fake_run)

    usage_statusline_forwarder.main()

    assert capsys.readouterr().out == "failed output\nok output\n"


def test_unicode_decode_error_hook_does_not_block_later_hooks(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    hooks = ["/tmp/bad-statusline.py", "/tmp/ok-statusline.py"]

    def fake_run(
        cmd: list[str],
        *,
        input: str,
        text: bool,
        encoding: str,
        errors: str,
        check: bool,
        capture_output: bool,
        timeout: int,
    ) -> subprocess.CompletedProcess[str]:
        _ = input, text, encoding, errors, check, capture_output, timeout
        if cmd[1] == "/tmp/bad-statusline.py":
            raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")
        return subprocess.CompletedProcess(cmd, 0, stdout="ok output\n", stderr="")

    monkeypatch.setattr(sys, "stdin", io.StringIO('{"ok":true}'))
    monkeypatch.setattr(usage_statusline_forwarder.glob, "glob", lambda pattern: hooks)
    monkeypatch.setattr(usage_statusline_forwarder.subprocess, "run", fake_run)

    usage_statusline_forwarder.main()

    assert capsys.readouterr().out == "ok output\n"


def test_blank_stdin_does_not_run_any_hooks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO("  \n"))
    monkeypatch.setattr(
        usage_statusline_forwarder.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("subprocess.run should not be called"),
    )

    usage_statusline_forwarder.main()

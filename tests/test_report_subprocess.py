# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Report workers preserve platform semantics without loading history in the app."""

from __future__ import annotations

import ast
import builtins
import io
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from installer import claude_pane
from usage_app import report, self_command


def _bootstrap_arguments(argv: list[str]) -> list[str]:
    for statement in ast.parse(argv[-1]).body:
        if isinstance(statement, ast.Assign):
            target = statement.targets[0]
            if isinstance(target, ast.Attribute) and target.attr == "argv":
                arguments: list[str] = ast.literal_eval(statement.value)
                return arguments
    raise AssertionError("missing sys.argv in bootstrap")


@pytest.mark.parametrize("environment", ["source", "macos", "windows"])
def test_self_command_argv_and_unchanged_status(
    monkeypatch: pytest.MonkeyPatch, environment: str
) -> None:
    monkeypatch.setattr(sys, "frozen", environment != "source", raising=False)
    monkeypatch.setattr(sys, "platform", "win32" if environment == "windows" else "darwin")
    executable = (
        r"C:\Program Files\usage\usage.exe"
        if environment == "windows"
        else "/tmp/A space's/usage.app/Contents/MacOS/usage"
    )
    monkeypatch.setattr(sys, "executable", executable)
    monkeypatch.setattr(sys, "version_info", (3, 14, 0))
    status = self_command.self_command_argv("status", ["--json"])
    worker_args = ["--period", "all", "--language", "zh-TW's \\"]
    worker = self_command.self_command_argv("report", worker_args)
    assert claude_pane._status_argv() == status
    if environment == "windows":
        assert status == [executable, "status", "--json"]
        assert worker == [executable, "report", *worker_args]
        return
    status_invocation = "from usage_app import cli;sys.argv=['usage','status','--json'];cli.main()"
    if environment == "source":
        root = str(Path(claude_pane.__file__).resolve().parent.parent)
        prefix = f"import sys;sys.path.insert(0,{root!r});"
        expected = [executable, "-c", prefix + status_invocation]
    else:
        resources = str(Path(executable).resolve().parent.parent / "Resources")
        prefix = (
            f"import sys;sys.path[:0]=[{resources!r}+'/lib/python314.zip',"
            f"{resources!r}+'/lib/python3.14',"
            f"{resources!r}+'/lib/python3.14/lib-dynload',{resources!r}];"
        )
        expected = [
            "/usr/bin/env",
            f"PYTHONHOME={resources}",
            f"RESOURCEPATH={resources}",
            executable,
            "-c",
            prefix + status_invocation,
        ]
    assert status == expected
    assert worker[:-1] == expected[:-1]
    assert worker[-1].startswith(prefix)
    assert _bootstrap_arguments(worker) == ["usage", "report", *worker_args]
    assert worker[-1].endswith("sys.exit(report.main(sys.argv[2:]))")


@pytest.mark.parametrize(
    "period,language,default_range",
    [("all", "zh-TW", "last7"), ("today", "en", None), ("month", None, None)],
)
def test_report_main_passes_arguments_and_prints_path(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    period: str,
    language: str | None,
    default_range: str | None,
) -> None:
    agents = [object()]
    data = object()
    calls: list[Any] = []

    def build(received: Any, received_period: str) -> Any:
        calls.append((received, received_period))
        return data

    def save(received: Any, **kwargs: Any) -> str:
        calls.append((received, kwargs))
        print("earlier diagnostic")
        return "~/.usage-reports/分析.html"

    monkeypatch.setattr(report, "detect_agents", lambda: agents)
    monkeypatch.setattr(report, "build_report_data", build)
    monkeypatch.setattr(report, "save_and_open", save)
    argv = ["--period", period]
    options: dict[str, Any] = {"language": language}
    if language is not None:
        argv += ["--language", language]
    if default_range is not None:
        argv += ["--default-range", default_range]
        options["default_range"] = default_range
    assert report.main(argv) == 0
    assert calls == [(agents, period), (data, options)]
    captured = capsys.readouterr()
    assert captured.out.splitlines()[-1] == "~/.usage-reports/分析.html"
    assert captured.err == ""


@pytest.mark.parametrize("stage", ["detect_agents", "build_report_data", "save_and_open"])
def test_report_main_reports_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], stage: str
) -> None:
    monkeypatch.setattr(report, "detect_agents", lambda: [])
    monkeypatch.setattr(report, "build_report_data", lambda *_args: {})
    monkeypatch.setattr(report, "save_and_open", lambda *_args, **_kwargs: "unexpected")

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise OSError("報表失敗")

    monkeypatch.setattr(report, stage, fail)
    assert report.main(["--period", "all"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "OSError: 報表失敗\n"


@pytest.mark.parametrize("fail", [False, True])
def test_report_windows_streams_use_utf8(monkeypatch: pytest.MonkeyPatch, fail: bool) -> None:
    output, errors = io.BytesIO(), io.BytesIO()
    stdout = io.TextIOWrapper(output, encoding="ascii")
    stderr = io.TextIOWrapper(errors, encoding="ascii")
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)
    monkeypatch.setattr(report, "detect_agents", lambda: [])
    monkeypatch.setattr(report, "build_report_data", lambda *_args: {})

    def save(*args: Any, **kwargs: Any) -> str:
        if fail:
            raise OSError("報表失敗")
        return "~/.usage-reports/分析.html"

    monkeypatch.setattr(report, "save_and_open", save)
    assert report.main(["--period", "all"]) == int(fail)
    stdout.flush()
    stderr.flush()
    assert stdout.encoding == stderr.encoding == "utf-8"
    if fail:
        assert errors.getvalue().decode("utf-8") == "OSError: 報表失敗\n"
        assert output.getvalue() == b""
    else:
        assert output.getvalue().decode("utf-8") == "~/.usage-reports/分析.html\n"
        assert errors.getvalue() == b""


@pytest.mark.parametrize("exit_code", [0, 1])
def test_main_dispatches_report_before_logging(
    monkeypatch: pytest.MonkeyPatch, exit_code: int
) -> None:
    import main

    calls: list[Any] = []
    monkeypatch.setattr(sys, "argv", ["usage", "report", "--period", "all"])
    monkeypatch.setattr(main, "_setup_logging", lambda: pytest.fail("logging must not start"))
    monkeypatch.setattr(main, "parse_args", lambda: pytest.fail("app must not start"))

    def run(argv: list[str]) -> int:
        calls.append(argv)
        return exit_code

    monkeypatch.setattr(report, "main", run)
    with pytest.raises(SystemExit) as exc:
        main.main()
    assert exc.value.code == exit_code
    assert calls == [["--period", "all"]]


@pytest.fixture
def no_report_in_app(monkeypatch: pytest.MonkeyPatch) -> None:
    from analyzer import reporter

    monkeypatch.setattr(
        reporter, "build_report_data", lambda *_args, **_kwargs: pytest.fail("history loaded")
    )
    original_import = builtins.__import__

    def checked_import(name: str, *args: Any, **kwargs: Any) -> Any:
        assert name != "analyzer.reporter", "reporter imported by resident app"
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", checked_import)


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS menu worker")
@pytest.mark.parametrize("outcome", ["success", "failure", "empty-error", "timeout", "launch"])
def test_macos_report_subprocess_result(
    monkeypatch: pytest.MonkeyPatch, no_report_in_app: None, outcome: str
) -> None:
    from menubar import actions

    monkeypatch.setattr(sys, "frozen", False, raising=False)
    results: list[Any] = []
    app = SimpleNamespace(
        language="zh-TW",
        performSelectorOnMainThread_withObject_waitUntilDone_=lambda *args: results.append(args),
    )

    def run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert _bootstrap_arguments(argv) == [
            "usage",
            "report",
            "--period",
            "all",
            "--default-range",
            "last7",
            "--language",
            "zh-TW",
        ]
        assert kwargs == dict(capture_output=True, text=True, encoding="utf-8", timeout=600)
        if outcome == "timeout":
            raise subprocess.TimeoutExpired(argv, 600)
        if outcome == "launch":
            raise OSError("cannot launch")
        return subprocess.CompletedProcess(
            argv,
            int(outcome != "success"),
            stdout="diagnostic\n~/.usage-reports/分析.html\n",
            stderr="first\nValueError: 報表失敗\n" if outcome == "failure" else "",
        )

    monkeypatch.setattr(subprocess, "run", run)
    actions.analyze_usage_in_background(app, "last7")
    selector, result, wait = results[0]
    assert selector == "_finishAnalyzeUsage:"
    assert wait is False
    assert result["success"] is (outcome == "success")
    if outcome == "success":
        assert result["message"] == "~/.usage-reports/分析.html"
    elif outcome == "failure":
        assert result["message"] == "ValueError: 報表失敗"
    else:
        prefix = {
            "timeout": "TimeoutExpired:",
            "launch": "OSError: cannot launch",
            "empty-error": "CalledProcessError:",
        }
        assert result["message"].startswith(prefix[outcome])


@pytest.mark.parametrize(
    "project_range,period",
    [("1d", "today"), ("7d", "last7"), ("30d", "last30"), ("all", "all"), ("unknown", "month")],
)
@pytest.mark.parametrize("frozen", [False, True])
def test_windows_report_subprocess_arguments(
    monkeypatch: pytest.MonkeyPatch,
    no_report_in_app: None,
    project_range: str,
    period: str,
    frozen: bool,
) -> None:
    from wintray import app as wintray

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    calls: list[list[str]] = []

    def run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        arguments = argv[1:] if frozen else _bootstrap_arguments(argv)[1:]
        assert arguments == ["report", "--period", period, "--language", "zh-TW"]
        expected = dict(capture_output=True, text=True, encoding="utf-8", timeout=600)
        if frozen:
            expected["creationflags"] = 0x08000000
        assert kwargs == expected
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="report.html\n", stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    controller: Any = SimpleNamespace(language="zh-TW")
    wintray._WindowsTrayController._analyze_usage(controller, project_range)
    assert len(calls) == 1


@pytest.mark.parametrize("outcome", ["failure", "empty-error", "timeout", "launch"])
def test_windows_report_subprocess_propagates_errors(
    monkeypatch: pytest.MonkeyPatch, no_report_in_app: None, outcome: str
) -> None:
    from wintray import app as wintray

    def run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if outcome == "timeout":
            raise subprocess.TimeoutExpired(argv, 600)
        if outcome == "launch":
            raise OSError("cannot launch")
        return subprocess.CompletedProcess(
            argv,
            1,
            stdout="",
            stderr="first\nValueError: 報表失敗\n" if outcome == "failure" else "",
        )

    monkeypatch.setattr(subprocess, "run", run)
    expected = {
        "failure": RuntimeError,
        "empty-error": subprocess.CalledProcessError,
        "timeout": subprocess.TimeoutExpired,
        "launch": OSError,
    }
    controller: Any = SimpleNamespace(language="en")
    with pytest.raises(expected[outcome]) as exc:
        wintray._WindowsTrayController._analyze_usage(controller, "all")
    if outcome == "failure":
        assert str(exc.value) == "ValueError: 報表失敗"

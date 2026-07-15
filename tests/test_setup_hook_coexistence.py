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
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import main
import setup_hook
import usage_client
import usage_statusline_forwarder
from tests.helpers import SetupHookPaths, expected_statusline_command


@pytest.fixture
def setup_paths(patch_setup_hook_paths: Callable[..., SetupHookPaths]) -> SetupHookPaths:
    return patch_setup_hook_paths(
        hook_source_name="usage_statusline.py",
        forwarder_source_name="usage_statusline_forwarder.py",
        hook_source_text="print('usage')\n",
    )


def test_install_when_no_existing_statusline(
    setup_paths: SetupHookPaths,
) -> None:
    settings = setup_paths.settings
    hook_target = setup_paths.hook_target
    forwarder_target = setup_paths.forwarder_target

    assert setup_hook.setup() == 0
    data = json.loads(settings.read_text(encoding="utf-8"))

    assert data["statusLine"]["command"] == expected_statusline_command(hook_target)
    assert hook_target.exists()
    assert not forwarder_target.exists()


def test_install_when_tt_statusline_exists(
    setup_paths: SetupHookPaths,
) -> None:
    settings = setup_paths.settings
    hook_target = setup_paths.hook_target
    forwarder_target = setup_paths.forwarder_target
    legacy_name = "tt" + "-statusline.py"
    external = {"type": "command", "command": f"python3 ~/.claude/{legacy_name}"}
    settings.write_text(json.dumps({"statusLine": external}), encoding="utf-8")

    assert setup_hook.setup() == 0
    data = json.loads(settings.read_text(encoding="utf-8"))

    assert data["statusLine"]["command"] == expected_statusline_command(forwarder_target)
    assert data["usage"]["previousStatusLine"] == external
    assert hook_target.exists()
    assert forwarder_target.exists()


def test_install_when_forwarder_already_exists(
    setup_paths: SetupHookPaths,
) -> None:
    settings = setup_paths.settings
    forwarder_target = setup_paths.forwarder_target
    existing = {
        "type": "command",
        "command": expected_statusline_command(forwarder_target),
    }
    settings.write_text(json.dumps({"statusLine": existing}), encoding="utf-8")

    assert setup_hook.setup() == 0
    data = json.loads(settings.read_text(encoding="utf-8"))

    assert data == {"statusLine": existing}


def test_forwarder_calls_all_hooks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("a-statusline.py", "b-statusline.py", "c-statusline.py"):
        (tmp_path / name).write_text("", encoding="utf-8")
    (tmp_path / "usage-statusline-forwarder.py").write_text("", encoding="utf-8")

    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> SimpleNamespace:
        calls.append(cmd)
        assert kwargs["input"] == '{"x": 1}'
        assert kwargs["timeout"] == usage_statusline_forwarder.TIMEOUT_SECONDS
        return SimpleNamespace(stdout=Path(cmd[1]).name + "\n")

    monkeypatch.setattr(usage_statusline_forwarder, "HOOK_DIR", str(tmp_path))
    monkeypatch.setattr("usage_statusline_forwarder.subprocess.run", fake_run)
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"x": 1}'))
    stdout = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stdout)

    usage_statusline_forwarder.main()

    assert {Path(call[1]).name for call in calls} == {
        "a-statusline.py",
        "b-statusline.py",
        "c-statusline.py",
    }
    assert stdout.getvalue() == "a-statusline.py\nb-statusline.py\nc-statusline.py\n"


def test_forwarder_ignores_failed_hook(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ok = tmp_path / "ok-statusline.py"
    bad = tmp_path / "bad-statusline.py"
    ok.write_text("import sys\nsys.stdout.write('ok')\n", encoding="utf-8")
    bad.write_text("raise SystemExit(2)\n", encoding="utf-8")

    monkeypatch.setattr(usage_statusline_forwarder, "HOOK_DIR", str(tmp_path))
    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))
    stdout = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stdout)

    usage_statusline_forwarder.main()

    assert stdout.getvalue() == "ok"


def test_health_check_triggers_repair_when_displaced(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    setup_paths: SetupHookPaths,
) -> None:
    settings = setup_paths.settings
    hook_target = setup_paths.hook_target
    settings.write_text(
        json.dumps({"statusLine": {"type": "command", "command": "python3 other.py"}}),
        encoding="utf-8",
    )
    hook_target.write_text("print('installed')\n", encoding="utf-8")
    monkeypatch.setattr(main, "PREFERENCES_FILE", tmp_path / "usage-preferences.json")
    monkeypatch.setattr(main, "_show_repair_dialog", lambda: "repair")
    calls: list[bool] = []

    def fake_setup(*, force_forwarder: bool = False) -> int:
        calls.append(force_forwarder)
        return 0

    monkeypatch.setattr(setup_hook, "setup", fake_setup)

    main.health_check()

    assert calls == [True]


def test_health_check_triggers_repair_when_hook_detection_raises(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    setup_paths: SetupHookPaths,
) -> None:
    settings = setup_paths.settings
    hook_target = setup_paths.hook_target
    settings.write_text(
        json.dumps({"statusLine": {"type": "command", "command": "python3 usage-statusline.py"}}),
        encoding="utf-8",
    )
    hook_target.write_text("print('installed')\n", encoding="utf-8")
    (tmp_path / ".claude" / "usage-status.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(main, "PREFERENCES_FILE", tmp_path / "usage-preferences.json")
    monkeypatch.setattr(
        setup_hook,
        "_detect_current_state",
        lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr(main, "_show_repair_dialog", lambda: "repair")
    calls: list[bool] = []

    def fake_setup(*, force_forwarder: bool = False) -> int:
        calls.append(force_forwarder)
        return 0

    monkeypatch.setattr(setup_hook, "setup", fake_setup)

    main.health_check()

    assert calls == [True]


def test_health_check_does_not_prompt_on_first_run_when_hook_detection_raises(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    setup_paths: SetupHookPaths,
) -> None:
    _ = setup_paths
    monkeypatch.setattr(main, "PREFERENCES_FILE", tmp_path / "usage-preferences.json")
    monkeypatch.setattr(
        usage_client,
        "STATUS_FILE",
        str(tmp_path / ".claude" / "usage-status.json"),
    )
    monkeypatch.setattr(
        setup_hook,
        "_detect_current_state",
        lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    def fail_dialog() -> str:
        raise AssertionError("repair dialog should not be shown on first run")

    def fail_setup(*, force_forwarder: bool = False) -> int:
        _ = force_forwarder
        raise AssertionError("setup should not run on first run")

    monkeypatch.setattr(main, "_show_repair_dialog", fail_dialog)
    monkeypatch.setattr(setup_hook, "setup", fail_setup)

    main.health_check()


def test_save_preferences_is_atomic_when_replace_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prefs_file = tmp_path / "usage-preferences.json"
    prefs_file.write_text('{"existing": true}\n', encoding="utf-8")
    monkeypatch.setattr(main, "PREFERENCES_FILE", prefs_file)

    def fail_replace(src: str, dst: str | os.PathLike[str]) -> None:
        _ = src, dst
        raise OSError("replace failed")

    monkeypatch.setattr("main.os.replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        main._save_preferences({"existing": False})

    assert prefs_file.read_text(encoding="utf-8") == '{"existing": true}\n'
    assert list(tmp_path.glob("*.tmp")) == []

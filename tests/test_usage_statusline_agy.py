# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import session_hooks
import setup_hook
import statusline_settings
import usage_statusline_agy

FIXTURE = Path(__file__).parent / "fixtures" / "agy_statusline_input.json"


def _fixture_data() -> dict[str, Any]:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def test_render_fixture_contains_expected_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("USAGE_LANG", "en")

    output = usage_statusline_agy.render(_fixture_data())

    assert "project" in output
    assert "1%" in output
    assert "60%" in output
    assert "Context:" in output
    assert "0%" in output
    assert "Gemini 3.6 Flash (Low)" in output
    assert "\n" not in output


@pytest.mark.parametrize(
    ("model_id", "expected_five", "expected_weekly"),
    [
        ("Gemini 3.6 Flash", "10%", "20%"),
        ("Claude Opus 4.5", "70%", "80%"),
    ],
)
def test_render_selects_quota_bucket_for_model(
    monkeypatch: pytest.MonkeyPatch,
    model_id: str,
    expected_five: str,
    expected_weekly: str,
) -> None:
    monkeypatch.setenv("USAGE_LANG", "en")
    data = _fixture_data()
    data["terminal_width"] = 300
    data["model"]["id"] = model_id
    data["quota"] = {
        "gemini-5h": {"remaining_fraction": 0.9},
        "gemini-weekly": {"remaining_fraction": 0.8},
        "3p-5h": {"remaining_fraction": 0.3},
        "3p-weekly": {"remaining_fraction": 0.2},
    }

    output = usage_statusline_agy.render(data)

    assert expected_five in output
    assert expected_weekly in output


def test_render_degrades_when_quota_and_context_are_missing() -> None:
    data = _fixture_data()
    data["quota"] = {}
    data["context_window"] = None

    output = usage_statusline_agy.render(data)

    assert "project" in output
    assert "Gemini 3.6 Flash (Low)" in output


def _patch_agy_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, Path, Path]:
    settings = tmp_path / ".gemini" / "antigravity-cli" / "settings.json"
    target = settings.parent / "usage-statusline-agy.py"
    previous = settings.parent / "usage-previous-statusline.json"
    settings.parent.mkdir(parents=True)
    monkeypatch.setattr(setup_hook, "AGY_SETTINGS", settings)
    monkeypatch.setattr(setup_hook, "AGY_HOOK_TARGET", target)
    monkeypatch.setattr(setup_hook, "AGY_PREVIOUS_STATUSLINE", previous)
    return settings, target, previous


def test_setup_and_unsetup_agy_on_macos_preserve_settings_and_restore_statusline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings, target, previous = _patch_agy_paths(monkeypatch, tmp_path)
    monkeypatch.setattr("setup_hook.sys.platform", "darwin")
    original_statusline = {"type": "command", "command": "echo original", "enabled": True}
    original = {
        "permissions": {"allow": ["read"]},
        "trustedWorkspaces": ["/tmp/project"],
        "model": "Gemini 3.6 Flash",
        "toolPermission": "ask",
        "statusLine": original_statusline,
    }
    settings.write_text(json.dumps(original), encoding="utf-8")

    assert setup_hook._setup_agy()
    installed = json.loads(settings.read_text(encoding="utf-8"))
    assert {key: installed[key] for key in original if key != "statusLine"} == {
        key: value for key, value in original.items() if key != "statusLine"
    }
    assert installed["statusLine"] == {
        "type": "command",
        "command": f"/usr/bin/python3 {setup_hook._shell_arg(str(target))}",
        "enabled": True,
    }
    assert json.loads(previous.read_text(encoding="utf-8")) == original_statusline
    source = Path(setup_hook.__file__).parent / "usage_statusline_agy.py"
    assert target.read_bytes() == source.read_bytes()
    assert setup_hook.is_agy_setup()

    assert setup_hook._unsetup_agy()
    restored = json.loads(settings.read_text(encoding="utf-8"))
    assert restored == original
    # The script stays on disk so a CLI launching mid-toggle never reads a
    # settings file that points at a file that was just deleted.
    assert target.exists()
    assert not previous.exists()
    assert not setup_hook.is_agy_setup()


def test_setup_and_unsetup_agy_on_windows_use_discovered_python_and_sidecar(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings, target, previous = _patch_agy_paths(monkeypatch, tmp_path)
    original_statusline = {"type": "command", "command": "echo original", "enabled": True}
    original = {
        "permissions": {"allow": ["read"]},
        "trustedWorkspaces": [r"C:\project"],
        "model": "Gemini 3.6 Flash",
        "toolPermission": "ask",
        "statusLine": original_statusline,
    }
    python = r"C:\Program Files\Python\python.exe"
    short_python = r"C:\PROGRA~1\Python\python.exe"
    monkeypatch.setattr("setup_hook.sys.platform", "win32")
    monkeypatch.setattr(setup_hook, "_find_system_python", lambda: python)
    monkeypatch.setattr("setup_hook.shutil.which", lambda _name: None)
    monkeypatch.setattr(
        setup_hook,
        "_get_windows_short_path",
        lambda value: short_python if value == python else value,
    )
    settings.write_text(json.dumps(original), encoding="utf-8")

    assert setup_hook._setup_agy()
    installed = json.loads(settings.read_text(encoding="utf-8"))
    assert {key: installed[key] for key in original if key != "statusLine"} == {
        key: value for key, value in original.items() if key != "statusLine"
    }
    assert installed["statusLine"] == {
        "type": "command",
        "command": f"{short_python} {target}",
        "enabled": True,
    }
    assert '"' not in installed["statusLine"]["command"]
    assert json.loads(previous.read_text(encoding="utf-8")) == original_statusline
    source = Path(setup_hook.__file__).parent / "usage_statusline_agy.py"
    assert target.read_bytes() == source.read_bytes()
    assert setup_hook.is_agy_setup()

    assert setup_hook._unsetup_agy()
    assert json.loads(settings.read_text(encoding="utf-8")) == original
    assert target.exists()
    assert not previous.exists()
    assert not setup_hook.is_agy_setup()


def test_agy_windows_command_shortens_both_spaced_paths_without_quotes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    python = r"C:\Program Files\Python311\python.EXE"
    target = Path(r"C:\Users\Test User\.gemini\usage-statusline-agy.py")
    short_paths = {
        python: r"C:\PROGRA~1\PYTHON~1\python.EXE",
        str(target): r"C:\Users\TESTUS~1\.gemini\usage-statusline-agy.py",
    }
    monkeypatch.setattr("setup_hook.sys.platform", "win32")
    monkeypatch.setattr(setup_hook, "_find_system_python", lambda: python)
    monkeypatch.setattr("setup_hook.shutil.which", lambda _name: None)
    monkeypatch.setattr(setup_hook, "AGY_HOOK_TARGET", target)
    monkeypatch.setattr(
        setup_hook, "_get_windows_short_path", lambda value: short_paths[value]
    )

    command = setup_hook._agy_statusline_command()

    assert command == (
        r"C:\PROGRA~1\PYTHON~1\python.EXE "
        r"C:\Users\TESTUS~1\.gemini\usage-statusline-agy.py"
    )
    assert '"' not in command


def test_agy_windows_command_prefers_working_space_free_interpreter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    python = r"C:\Program Files\Python311\python.EXE"
    launcher = r"C:\Windows\py.exe"
    target = Path(r"C:\Users\test\.gemini\usage-statusline-agy.py")
    monkeypatch.setattr("setup_hook.sys.platform", "win32")
    monkeypatch.setattr(setup_hook, "_find_system_python", lambda: python)
    monkeypatch.setattr(
        "setup_hook.shutil.which", lambda name: launcher if name == "py" else None
    )
    monkeypatch.setattr(setup_hook, "_is_working_python", lambda value: value == launcher)
    monkeypatch.setattr(setup_hook, "AGY_HOOK_TARGET", target)

    command = setup_hook._agy_statusline_command()

    assert command == rf"{launcher} {target}"
    assert '"' not in command


def test_agy_windows_command_rejects_unchanged_spaced_short_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    python = r"C:\Program Files\Python311\python.EXE"
    monkeypatch.setattr("setup_hook.sys.platform", "win32")
    monkeypatch.setattr(setup_hook, "_find_system_python", lambda: python)
    monkeypatch.setattr("setup_hook.shutil.which", lambda _name: None)
    monkeypatch.setattr(setup_hook, "_get_windows_short_path", lambda value: value)

    with pytest.raises(RuntimeError, match=r"no usable 8\.3 short path") as exc_info:
        setup_hook._agy_statusline_command()

    message = str(exc_info.value)
    assert "Enable or create 8.3 short names" in message
    assert "path without spaces" in message


def test_agy_windows_command_reports_short_path_lookup_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    python = r"C:\Missing Python\python.exe"
    monkeypatch.setattr("setup_hook.sys.platform", "win32")
    monkeypatch.setattr(setup_hook, "_find_system_python", lambda: python)
    monkeypatch.setattr("setup_hook.shutil.which", lambda _name: None)

    def fail_short_path(_value: str) -> str:
        raise OSError(2, "file not found")

    monkeypatch.setattr(setup_hook, "_get_windows_short_path", fail_short_path)

    with pytest.raises(RuntimeError, match=r"could not obtain an 8\.3 short path") as exc_info:
        setup_hook._agy_statusline_command()

    assert "Ensure the file exists" in str(exc_info.value)


def test_setup_agy_on_windows_preserves_existing_sidecar_backup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings, _target, previous = _patch_agy_paths(monkeypatch, tmp_path)
    saved_statusline = {"type": "command", "command": "echo saved", "enabled": True}
    replacement_statusline = {
        "type": "command",
        "command": "echo replacement",
        "enabled": True,
    }
    monkeypatch.setattr("setup_hook.sys.platform", "win32")
    monkeypatch.setattr(setup_hook, "_find_system_python", lambda: r"C:\Python\python.exe")
    settings.write_text(json.dumps({"statusLine": replacement_statusline}), encoding="utf-8")
    previous.write_text(json.dumps(saved_statusline), encoding="utf-8")

    assert setup_hook._setup_agy()
    assert json.loads(previous.read_text(encoding="utf-8")) == saved_statusline
    assert setup_hook._unsetup_agy()
    restored = json.loads(settings.read_text(encoding="utf-8"))
    assert restored["statusLine"] == saved_statusline


@pytest.mark.parametrize("content", [None, "{broken", "[]"])
def test_setup_agy_refuses_missing_or_invalid_settings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    content: str | None,
) -> None:
    settings, target, previous = _patch_agy_paths(monkeypatch, tmp_path)
    if content is not None:
        settings.write_text(content, encoding="utf-8")

    assert not setup_hook._setup_agy()
    if content is None:
        assert not settings.exists()
    else:
        assert settings.read_text(encoding="utf-8") == content
    assert not target.exists()
    assert not previous.exists()


def test_agy_install_paths_are_noops_on_unsupported_platforms(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """self_heal calls _setup_agy directly, so the guard cannot live in its caller."""
    settings, target, previous = _patch_agy_paths(monkeypatch, tmp_path)
    original = json.dumps({"statusLine": {"type": "command", "command": "own.py"}})
    settings.write_text(original, encoding="utf-8")
    monkeypatch.setattr("setup_hook.sys.platform", "linux")

    assert not setup_hook._setup_agy()
    assert not setup_hook._unsetup_agy()
    assert not setup_hook.is_agy_setup()
    assert settings.read_text(encoding="utf-8") == original
    assert not target.exists()
    assert not previous.exists()


def test_agy_hook_script_staleness_detects_missing_and_changed_target(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _settings, target, _previous = _patch_agy_paths(monkeypatch, tmp_path)
    source = tmp_path / "usage_statusline_agy.py"
    source.write_bytes(b"new hook\n")
    monkeypatch.setattr(setup_hook, "_resolve_agy_hook_source", lambda: source)

    assert setup_hook._agy_hook_script_is_stale()
    target.write_bytes(b"old hook\n")
    assert setup_hook._agy_hook_script_is_stale()
    target.write_bytes(b"new hook\n")
    assert not setup_hook._agy_hook_script_is_stale()


def test_self_heal_updates_stale_agy_statusline_on_windows(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings, target, _previous = _patch_agy_paths(monkeypatch, tmp_path)
    settings.write_text("{}", encoding="utf-8")
    source = tmp_path / "usage_statusline_agy.py"
    source.write_bytes(b"new hook\n")
    target.write_bytes(b"old hook\n")
    logs: list[tuple[str, str]] = []
    _patch_claude_self_heal(monkeypatch)
    monkeypatch.setattr("setup_hook.sys.platform", "win32")
    monkeypatch.setattr(setup_hook, "_find_system_python", lambda: r"C:\Python\python.exe")
    monkeypatch.setattr(setup_hook, "_resolve_agy_hook_source", lambda: source)
    monkeypatch.setattr(statusline_settings, "_statusline_enabled", lambda: True)
    monkeypatch.setattr(
        session_hooks, "_append_self_heal_log", lambda action, detail: logs.append((action, detail))
    )

    session_hooks.self_heal()

    assert target.read_bytes() == source.read_bytes()
    assert setup_hook.is_agy_setup()
    assert logs == [("setup_agy", "installed or updated Antigravity status line")]


def _patch_claude_self_heal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_hooks, "_load_settings", lambda: {"statusLine": {}})
    monkeypatch.setattr(session_hooks, "_detect_current_state", lambda *args: "us-direct")
    monkeypatch.setattr(session_hooks, "is_setup", lambda: True)
    monkeypatch.setattr(session_hooks, "needs_update", lambda: False)
    monkeypatch.setattr(session_hooks, "_statusline_command_target_exists", lambda: True)
    monkeypatch.setattr(session_hooks, "_self_heal_resume", lambda: None)
    monkeypatch.setattr(session_hooks, "_self_heal_terse_mode", lambda: None)


def test_self_heal_installs_and_updates_agy_statusline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings, target, _previous = _patch_agy_paths(monkeypatch, tmp_path)
    settings.write_text("{}", encoding="utf-8")
    source = tmp_path / "usage_statusline_agy.py"
    source.write_bytes(b"new hook\n")
    logs: list[tuple[str, str]] = []
    _patch_claude_self_heal(monkeypatch)
    monkeypatch.setattr("setup_hook.sys.platform", "darwin")
    monkeypatch.setattr(setup_hook, "_resolve_agy_hook_source", lambda: source)
    monkeypatch.setattr(statusline_settings, "_statusline_enabled", lambda: True)
    monkeypatch.setattr(
        session_hooks, "_append_self_heal_log", lambda action, detail: logs.append((action, detail))
    )

    session_hooks.self_heal()

    assert setup_hook.is_agy_setup()
    assert target.read_bytes() == source.read_bytes()
    assert logs == [("setup_agy", "installed or updated Antigravity status line")]

    source.write_bytes(b"updated hook\n")
    session_hooks.self_heal()

    assert target.read_bytes() == source.read_bytes()
    assert logs[-1] == ("setup_agy", "installed or updated Antigravity status line")


def test_self_heal_agy_does_nothing_without_cli_settings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings, target, previous = _patch_agy_paths(monkeypatch, tmp_path)
    calls: list[None] = []
    _patch_claude_self_heal(monkeypatch)
    monkeypatch.setattr("setup_hook.sys.platform", "darwin")
    monkeypatch.setattr(statusline_settings, "_statusline_enabled", lambda: True)

    def setup_agy() -> bool:
        calls.append(None)
        return True

    monkeypatch.setattr(setup_hook, "_setup_agy", setup_agy)

    session_hooks.self_heal()

    assert calls == []
    assert not settings.exists()
    assert not target.exists()
    assert not previous.exists()


def test_self_heal_agy_stays_disabled_and_failure_does_not_block_resume(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings, _target, _previous = _patch_agy_paths(monkeypatch, tmp_path)
    settings.write_text("{}", encoding="utf-8")
    calls: list[str] = []
    _patch_claude_self_heal(monkeypatch)
    monkeypatch.setattr("setup_hook.sys.platform", "darwin")
    monkeypatch.setattr(statusline_settings, "_statusline_enabled", lambda: False)

    def setup_agy() -> bool:
        calls.append("setup")
        return True

    monkeypatch.setattr(setup_hook, "_setup_agy", setup_agy)
    monkeypatch.setattr(session_hooks, "_self_heal_resume", lambda: calls.append("resume"))

    session_hooks.self_heal()

    assert calls == ["resume"]

    monkeypatch.setattr(statusline_settings, "_statusline_enabled", lambda: True)
    monkeypatch.setattr(setup_hook, "is_agy_setup", lambda: False)

    def fail_setup() -> bool:
        calls.append("setup")
        raise OSError("broken agy")

    monkeypatch.setattr(setup_hook, "_setup_agy", fail_setup)
    session_hooks.self_heal()

    assert calls == ["resume", "setup", "resume"]


@pytest.mark.parametrize("platform", ["darwin", "win32"])
def test_agy_only_statusline_toggle_is_enabled_and_removable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    platform: str,
) -> None:
    state = {"enabled": False}
    monkeypatch.setattr("statusline_settings.sys.platform", platform)
    monkeypatch.setattr(
        statusline_settings, "_claude_settings_path", lambda: tmp_path / "settings.json"
    )
    monkeypatch.setattr(setup_hook, "setup", lambda: 1)
    monkeypatch.setattr(
        setup_hook, "_setup_agy", lambda: _set_agy_enabled(state, True)
    )
    monkeypatch.setattr(
        setup_hook, "_unsetup_agy", lambda: _set_agy_enabled(state, False)
    )
    monkeypatch.setattr(setup_hook, "is_agy_setup", lambda: state["enabled"])

    assert statusline_settings._toggle_statusline_settings() == ("install", 0)
    assert statusline_settings._statusline_enabled()
    assert statusline_settings._toggle_statusline_settings() == ("uninstall", 0)
    assert not statusline_settings._statusline_enabled()


def test_agy_sync_and_state_are_noops_on_unsupported_platforms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr("statusline_settings.sys.platform", "linux")

    def setup_agy() -> bool:
        calls.append("setup")
        return True

    def is_agy_setup() -> bool:
        calls.append("check")
        return True

    monkeypatch.setattr(setup_hook, "_setup_agy", setup_agy)
    monkeypatch.setattr(setup_hook, "is_agy_setup", is_agy_setup)
    monkeypatch.setattr(statusline_settings, "_load_claude_settings", lambda: {})

    statusline_settings._sync_agy_statusline(True)

    assert calls == []
    assert not statusline_settings._statusline_enabled()


def test_agy_failure_does_not_hide_claude_statusline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(statusline_settings, "_load_claude_settings", lambda: {"statusLine": {}})

    def fail_agy() -> bool:
        raise OSError("agy settings unreadable")

    monkeypatch.setattr(setup_hook, "is_agy_setup", fail_agy)

    assert statusline_settings._statusline_enabled()


def _set_agy_enabled(state: dict[str, bool], enabled: bool) -> bool:
    state["enabled"] = enabled
    return True

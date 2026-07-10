# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import json
import tomllib
from collections.abc import Callable
from pathlib import Path

import pytest

import session_hooks
from tests.helpers import TerseHookPaths


@pytest.fixture
def terse_paths(patch_terse_hook_paths: Callable[..., TerseHookPaths]) -> TerseHookPaths:
    return patch_terse_hook_paths()


def _terse_entries(settings: Path) -> list[dict[str, object]]:
    data = json.loads(settings.read_text(encoding="utf-8"))
    return [e for e in data["hooks"]["SessionStart"] if session_hooks._is_terse_entry(e)]


def _reminder_entries(settings: Path) -> list[dict[str, object]]:
    data = json.loads(settings.read_text(encoding="utf-8"))
    ups = data.get("hooks", {}).get("UserPromptSubmit", [])
    return [e for e in ups if session_hooks._is_terse_reminder_entry(e)]


def _codex_terse_entries(hooks_json: Path) -> list[dict[str, object]]:
    data = json.loads(hooks_json.read_text(encoding="utf-8"))
    return [e for e in data["hooks"]["SessionStart"] if session_hooks._is_terse_entry(e)]


def test_enable_registers_hook_and_writes_sidecar(terse_paths: TerseHookPaths) -> None:
    settings = terse_paths.settings

    assert session_hooks.enable_terse_mode() == 0
    assert session_hooks.is_terse_mode_enabled()
    assert terse_paths.terse_target.exists()
    assert terse_paths.sidecar.exists()

    entries = _terse_entries(settings)
    assert len(entries) == 1
    assert entries[0]["matcher"] == session_hooks.TERSE_MATCHER
    hooks = entries[0]["hooks"]
    assert isinstance(hooks, list)
    first_hook = hooks[0]
    assert isinstance(first_hook, dict)
    command = first_hook["command"]
    assert isinstance(command, str)
    assert str(terse_paths.terse_target) not in command
    assert str(terse_paths.source) in command
    bundle = json.loads(terse_paths.sidecar.read_text(encoding="utf-8"))
    assert {"zh-TW", "en", "ja", "ko", "zh-CN"} <= set(bundle)
    assert "Terse mode is on for this entire conversation" in bundle["en"]["instruction"]


def test_enable_is_idempotent(terse_paths: TerseHookPaths) -> None:
    session_hooks.enable_terse_mode()
    session_hooks.enable_terse_mode()
    assert len(_terse_entries(terse_paths.settings)) == 1


def test_enable_preserves_existing_hooks(terse_paths: TerseHookPaths) -> None:
    settings = terse_paths.settings
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {"matcher": "startup", "hooks": [{"type": "command", "command": "other"}]}
                    ],
                    "PreToolUse": [{"hooks": [{"type": "command", "command": "guard"}]}],
                }
            }
        ),
        encoding="utf-8",
    )

    session_hooks.enable_terse_mode()
    data = json.loads(settings.read_text(encoding="utf-8"))
    commands = [h["command"] for e in data["hooks"]["SessionStart"] for h in e["hooks"]]
    assert "other" in commands
    assert any("usage_terse_mode" in c for c in commands)
    assert data["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == "guard"


def test_disable_removes_entry_and_files(terse_paths: TerseHookPaths) -> None:
    session_hooks.enable_terse_mode()

    session_hooks.disable_terse_mode()
    assert not session_hooks.is_terse_mode_enabled()
    assert not terse_paths.terse_target.exists()
    assert not terse_paths.sidecar.exists()
    data = json.loads(terse_paths.settings.read_text(encoding="utf-8"))
    assert "hooks" not in data


def test_disable_keeps_other_session_start_hooks(terse_paths: TerseHookPaths) -> None:
    settings = terse_paths.settings
    session_hooks.enable_terse_mode()
    data = json.loads(settings.read_text(encoding="utf-8"))
    data["hooks"]["SessionStart"].insert(
        0, {"matcher": "startup", "hooks": [{"type": "command", "command": "other"}]}
    )
    settings.write_text(json.dumps(data), encoding="utf-8")

    session_hooks.disable_terse_mode()
    data = json.loads(settings.read_text(encoding="utf-8"))
    commands = [h["command"] for e in data["hooks"]["SessionStart"] for h in e["hooks"]]
    assert commands == ["other"]


def test_disable_preserves_user_hook_in_shared_entry(terse_paths: TerseHookPaths) -> None:
    settings = terse_paths.settings
    session_hooks.enable_terse_mode()
    data = json.loads(settings.read_text(encoding="utf-8"))
    data["hooks"]["SessionStart"][0]["hooks"].append(
        {"type": "command", "command": "echo my-own-hook"}
    )
    settings.write_text(json.dumps(data), encoding="utf-8")

    assert session_hooks.disable_terse_mode() == 0

    data = json.loads(settings.read_text(encoding="utf-8"))
    shared = data["hooks"]["SessionStart"][0]["hooks"]
    assert shared == [{"type": "command", "command": "echo my-own-hook"}]


def test_self_heal_restores_missing_script_when_enabled(terse_paths: TerseHookPaths) -> None:
    session_hooks.enable_terse_mode()
    terse_paths.terse_target.unlink()
    terse_paths.sidecar.unlink()

    session_hooks._self_heal_terse_mode()
    assert terse_paths.terse_target.exists()
    assert terse_paths.sidecar.exists()

    data = json.loads(terse_paths.settings.read_text(encoding="utf-8"))
    assert data["usage"]["selfHealLog"][-1]["action"] == "restore_terse_hook"
    assert data["usage"]["selfHealLog"][-1]["detail"] == "missing=script,sidecar"


def test_self_heal_updates_old_version(terse_paths: TerseHookPaths) -> None:
    session_hooks.enable_terse_mode()
    terse_paths.terse_target.write_text('__version__ = "0.1"\n', encoding="utf-8")

    session_hooks._self_heal_terse_mode()

    data = json.loads(terse_paths.settings.read_text(encoding="utf-8"))
    assert data["usage"]["selfHealLog"][-1]["action"] == "update_terse_hook"
    assert data["usage"]["selfHealLog"][-1]["detail"] == "0.1 -> 1.0"


def test_self_heal_noop_when_disabled(terse_paths: TerseHookPaths) -> None:
    session_hooks._self_heal_terse_mode()
    assert not terse_paths.terse_target.exists()


def test_enable_installs_codex_when_present(terse_paths: TerseHookPaths) -> None:
    terse_paths.codex_config.write_text('model = "gpt-5"\n', encoding="utf-8")

    assert session_hooks.enable_terse_mode() == 0

    assert terse_paths.codex_terse_target.exists()
    parsed = tomllib.loads(terse_paths.codex_config.read_text(encoding="utf-8"))
    assert parsed["features"]["hooks"] is True
    entries = _codex_terse_entries(terse_paths.codex_hooks_json)
    assert len(entries) == 1
    assert entries[0]["matcher"] == session_hooks.CODEX_TERSE_MATCHER
    hooks_list = entries[0]["hooks"]
    assert isinstance(hooks_list, list)
    hook = hooks_list[0]
    assert isinstance(hook, dict)
    assert hook["timeout"] == 5
    assert str(terse_paths.codex_terse_target) in hook["command"]


def test_enable_idempotent_on_codex_features_and_entries(terse_paths: TerseHookPaths) -> None:
    terse_paths.codex_config.write_text('model = "gpt-5"\n', encoding="utf-8")

    session_hooks.enable_terse_mode()
    session_hooks.enable_terse_mode()

    parsed = tomllib.loads(terse_paths.codex_config.read_text(encoding="utf-8"))
    assert parsed["features"]["hooks"] is True
    assert len(_codex_terse_entries(terse_paths.codex_hooks_json)) == 1


def test_enable_skips_codex_when_absent(terse_paths: TerseHookPaths) -> None:
    assert not terse_paths.codex_config.exists()

    session_hooks.enable_terse_mode()

    assert not terse_paths.codex_config.exists()
    assert not terse_paths.codex_hooks_json.exists()
    assert not terse_paths.codex_terse_target.exists()


def test_disable_keeps_codex_features_and_user_hooks(terse_paths: TerseHookPaths) -> None:
    terse_paths.codex_config.write_text("[features]\nhooks = true\n", encoding="utf-8")
    terse_paths.codex_hooks_json.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "matcher": "startup",
                            "hooks": [{"type": "command", "command": "echo user-hook"}],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    session_hooks.enable_terse_mode()

    session_hooks.disable_terse_mode()

    parsed = tomllib.loads(terse_paths.codex_config.read_text(encoding="utf-8"))
    assert parsed["features"]["hooks"] is True
    data = json.loads(terse_paths.codex_hooks_json.read_text(encoding="utf-8"))
    commands = [h["command"] for e in data["hooks"]["SessionStart"] for h in e["hooks"]]
    assert commands == ["echo user-hook"]
    assert not terse_paths.codex_terse_target.exists()


def test_disable_deletes_codex_hooks_json_when_empty(terse_paths: TerseHookPaths) -> None:
    terse_paths.codex_config.write_text('model = "gpt-5"\n', encoding="utf-8")
    session_hooks.enable_terse_mode()

    session_hooks.disable_terse_mode()

    assert not terse_paths.codex_hooks_json.exists()
    assert not terse_paths.codex_terse_target.exists()
    parsed = tomllib.loads(terse_paths.codex_config.read_text(encoding="utf-8"))
    assert parsed["features"]["hooks"] is True


def test_self_heal_restores_missing_codex_script(terse_paths: TerseHookPaths) -> None:
    terse_paths.codex_config.write_text('model = "gpt-5"\n', encoding="utf-8")
    session_hooks.enable_terse_mode()
    terse_paths.codex_terse_target.unlink()

    session_hooks._self_heal_terse_mode()

    assert terse_paths.codex_terse_target.exists()
    data = json.loads(terse_paths.settings.read_text(encoding="utf-8"))
    assert data["usage"]["selfHealLog"][-1]["action"] == "restore_terse_hook_codex"
    assert data["usage"]["selfHealLog"][-1]["detail"] == "missing=script"


def test_self_heal_restores_missing_codex_hooks_entry(terse_paths: TerseHookPaths) -> None:
    terse_paths.codex_config.write_text('model = "gpt-5"\n', encoding="utf-8")
    session_hooks.enable_terse_mode()
    # Wipe our entry but leave the script in place.
    terse_paths.codex_hooks_json.write_text('{"hooks": {}}', encoding="utf-8")

    session_hooks._self_heal_terse_mode()

    assert len(_codex_terse_entries(terse_paths.codex_hooks_json)) == 1
    data = json.loads(terse_paths.settings.read_text(encoding="utf-8"))
    assert data["usage"]["selfHealLog"][-1]["action"] == "restore_terse_hook_codex"
    assert data["usage"]["selfHealLog"][-1]["detail"] == "missing=hooks_entry"


def test_enable_registers_reminder_hook(terse_paths: TerseHookPaths) -> None:
    settings = terse_paths.settings

    assert session_hooks.enable_terse_mode() == 0
    assert terse_paths.terse_reminder_target.exists()
    assert session_hooks.is_terse_reminder_enabled()

    entries = _reminder_entries(settings)
    assert len(entries) == 1
    assert entries[0]["matcher"] == session_hooks.TERSE_REMINDER_MATCHER
    hooks = entries[0]["hooks"]
    assert isinstance(hooks, list)
    first_hook = hooks[0]
    assert isinstance(first_hook, dict)
    command = first_hook["command"]
    assert isinstance(command, str)
    assert str(terse_paths.terse_reminder_target) not in command
    assert str(terse_paths.reminder_source) in command


def test_enable_reminder_is_idempotent(terse_paths: TerseHookPaths) -> None:
    session_hooks.enable_terse_mode()
    session_hooks.enable_terse_mode()
    assert len(_reminder_entries(terse_paths.settings)) == 1
    assert len(_terse_entries(terse_paths.settings)) == 1


def test_disable_removes_reminder_entry_and_file(terse_paths: TerseHookPaths) -> None:
    session_hooks.enable_terse_mode()

    session_hooks.disable_terse_mode()
    assert not terse_paths.terse_reminder_target.exists()
    assert not session_hooks.is_terse_reminder_enabled()
    data = json.loads(terse_paths.settings.read_text(encoding="utf-8"))
    assert "UserPromptSubmit" not in data.get("hooks", {})


def test_disable_keeps_user_userpromptsubmit_hook(terse_paths: TerseHookPaths) -> None:
    settings = terse_paths.settings
    session_hooks.enable_terse_mode()
    data = json.loads(settings.read_text(encoding="utf-8"))
    data["hooks"]["UserPromptSubmit"][0]["hooks"].append(
        {"type": "command", "command": "echo my-own-prompt-hook"}
    )
    settings.write_text(json.dumps(data), encoding="utf-8")

    assert session_hooks.disable_terse_mode() == 0

    data = json.loads(settings.read_text(encoding="utf-8"))
    shared = data["hooks"]["UserPromptSubmit"][0]["hooks"]
    assert shared == [{"type": "command", "command": "echo my-own-prompt-hook"}]


def test_self_heal_backfills_reminder_for_legacy_user(terse_paths: TerseHookPaths) -> None:
    # Legacy state: terse SessionStart on (from an older build) but no reminder hook/script.
    session_hooks.enable_terse_mode()
    terse_paths.terse_reminder_target.unlink()
    data = json.loads(terse_paths.settings.read_text(encoding="utf-8"))
    data["hooks"].pop("UserPromptSubmit", None)
    if not data["hooks"]:
        data.pop("hooks", None)
    terse_paths.settings.write_text(json.dumps(data), encoding="utf-8")
    assert not session_hooks.is_terse_reminder_enabled()

    session_hooks._self_heal_terse_mode()

    assert terse_paths.terse_reminder_target.exists()
    assert len(_reminder_entries(terse_paths.settings)) == 1
    heal = json.loads(terse_paths.settings.read_text(encoding="utf-8"))
    assert heal["usage"]["selfHealLog"][-1]["action"] == "restore_terse_reminder_hook"
    assert heal["usage"]["selfHealLog"][-1]["detail"] == "missing=script,entry"


def test_self_heal_reminder_noop_when_disabled(terse_paths: TerseHookPaths) -> None:
    session_hooks._self_heal_terse_mode()
    assert not terse_paths.terse_reminder_target.exists()

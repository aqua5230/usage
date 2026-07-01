# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

import setup_hook
from tests.helpers import ResumeHookPaths


@pytest.fixture
def resume_paths(patch_resume_hook_paths: Callable[..., ResumeHookPaths]) -> ResumeHookPaths:
    return patch_resume_hook_paths()


def _resume_entries(settings: Path) -> list[dict[str, object]]:
    data = json.loads(settings.read_text(encoding="utf-8"))
    return [e for e in data["hooks"]["SessionStart"] if setup_hook._is_resume_entry(e)]


def test_enable_registers_hook_and_writes_sidecar(
    resume_paths: ResumeHookPaths,
) -> None:
    settings = resume_paths.settings
    resume_target = resume_paths.resume_target
    sidecar = resume_paths.sidecar

    assert setup_hook.enable_session_resume() == 0
    assert setup_hook.is_resume_enabled()
    assert resume_target.exists()
    assert sidecar.exists()

    entries = _resume_entries(settings)
    assert len(entries) == 1
    assert entries[0]["matcher"] == setup_hook.RESUME_MATCHER
    hooks = entries[0]["hooks"]
    assert isinstance(hooks, list)
    first_hook = hooks[0]
    assert isinstance(first_hook, dict)
    command = first_hook["command"]
    assert isinstance(command, str)
    assert str(resume_target) not in command
    assert str(resume_paths.source) in command
    # Sidecar carries the i18n-sourced prompt template for every shipped language.
    bundle = json.loads(sidecar.read_text(encoding="utf-8"))
    assert {"zh-TW", "en", "ja", "ko", "zh-CN"} <= set(bundle)
    assert "{project}" in bundle["en"]["prompt"]
    assert "lead" in bundle["en"]  # lead-in so Claude's first reply acknowledges the load
    assert bundle["en"]["empty"]  # greeting shown when there's no fresh progress to report
    assert "uncommitted" in bundle["en"]
    assert "diagnosis_reminder" in bundle["en"]
    assert "polluter_dirs" in bundle["en"]["diagnosis_causes"]


def test_enable_is_idempotent(resume_paths: ResumeHookPaths) -> None:
    settings = resume_paths.settings
    setup_hook.enable_session_resume()
    setup_hook.enable_session_resume()
    assert len(_resume_entries(settings)) == 1


def test_enable_preserves_existing_hooks(
    resume_paths: ResumeHookPaths,
) -> None:
    settings = resume_paths.settings
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

    setup_hook.enable_session_resume()
    data = json.loads(settings.read_text(encoding="utf-8"))
    commands = [h["command"] for e in data["hooks"]["SessionStart"] for h in e["hooks"]]
    assert "other" in commands
    assert any("usage_session_resume" in c for c in commands)
    assert data["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == "guard"


def test_disable_removes_entry_and_files(resume_paths: ResumeHookPaths) -> None:
    settings = resume_paths.settings
    resume_target = resume_paths.resume_target
    sidecar = resume_paths.sidecar
    setup_hook.enable_session_resume()

    setup_hook.disable_session_resume()
    assert not setup_hook.is_resume_enabled()
    assert not resume_target.exists()
    assert not sidecar.exists()
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert "hooks" not in data


def test_disable_keeps_other_session_start_hooks(
    resume_paths: ResumeHookPaths,
) -> None:
    settings = resume_paths.settings
    setup_hook.enable_session_resume()
    data = json.loads(settings.read_text(encoding="utf-8"))
    data["hooks"]["SessionStart"].insert(
        0, {"matcher": "startup", "hooks": [{"type": "command", "command": "other"}]}
    )
    settings.write_text(json.dumps(data), encoding="utf-8")

    setup_hook.disable_session_resume()
    data = json.loads(settings.read_text(encoding="utf-8"))
    commands = [h["command"] for e in data["hooks"]["SessionStart"] for h in e["hooks"]]
    assert commands == ["other"]


def test_self_heal_restores_missing_script_when_enabled(
    resume_paths: ResumeHookPaths,
) -> None:
    _settings = resume_paths.settings
    resume_target = resume_paths.resume_target
    sidecar = resume_paths.sidecar
    setup_hook.enable_session_resume()
    resume_target.unlink()
    sidecar.unlink()

    setup_hook._self_heal_resume()
    assert resume_target.exists()
    assert sidecar.exists()

    data = json.loads(_settings.read_text(encoding="utf-8"))
    detail = data["usage"]["selfHealLog"][-1]["detail"]
    assert data["usage"]["selfHealLog"][-1]["action"] == "restore_resume_hook"
    assert "missing=script,sidecar" in detail
    assert "registered=source" in detail
    assert "recent_claude_entries=" in detail


def test_self_heal_migrates_existing_target_command(
    resume_paths: ResumeHookPaths,
) -> None:
    settings = resume_paths.settings
    resume_target = resume_paths.resume_target
    sidecar = resume_paths.sidecar
    source = resume_paths.source
    resume_target.write_text('__version__ = "1.2"\n', encoding="utf-8")
    sidecar.write_text("{}", encoding="utf-8")
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "matcher": "startup|clear",
                            "custom": "keep",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": f"/usr/bin/python3 {resume_target}",
                                    "timeout": 3,
                                },
                                {"type": "command", "command": "other"},
                            ],
                        }
                    ],
                    "PreToolUse": [{"hooks": [{"type": "command", "command": "guard"}]}],
                }
            }
        ),
        encoding="utf-8",
    )

    setup_hook._self_heal_resume()

    data = json.loads(settings.read_text(encoding="utf-8"))
    session_entry = data["hooks"]["SessionStart"][0]
    migrated_hook = session_entry["hooks"][0]
    assert session_entry["matcher"] == "startup|clear"
    assert session_entry["custom"] == "keep"
    assert migrated_hook["type"] == "command"
    assert migrated_hook["timeout"] == 3
    assert str(resume_target) not in migrated_hook["command"]
    assert str(source) in migrated_hook["command"]
    assert session_entry["hooks"][1]["command"] == "other"
    assert data["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == "guard"
    # The stale "1.2" target also triggers a version update in the same pass, so the
    # migrate entry is no longer necessarily last — find it by action.
    migrate_entries = [
        e for e in data["usage"]["selfHealLog"] if e["action"] == "migrate_resume_command"
    ]
    assert migrate_entries
    log_entry = migrate_entries[-1]
    assert str(resume_target) in log_entry["detail"]
    assert str(source) in log_entry["detail"]


def test_self_heal_does_not_repeat_resume_command_migration(
    resume_paths: ResumeHookPaths,
) -> None:
    settings = resume_paths.settings
    sidecar = resume_paths.sidecar
    setup_hook.enable_session_resume()
    sidecar.write_text("{}", encoding="utf-8")
    data = json.loads(settings.read_text(encoding="utf-8"))
    data["usage"] = {
        "selfHealLog": [
            {
                "timestamp": "2026-01-01T00:00:00Z",
                "action": "migrate_resume_command",
                "detail": "already migrated",
            }
        ]
    }
    settings.write_text(json.dumps(data), encoding="utf-8")

    setup_hook._self_heal_resume()

    after = json.loads(settings.read_text(encoding="utf-8"))
    migrate_entries = [
        entry
        for entry in after["usage"]["selfHealLog"]
        if entry["action"] == "migrate_resume_command"
    ]
    assert len(migrate_entries) == 1


def test_self_heal_noop_when_disabled(
    resume_paths: ResumeHookPaths,
) -> None:
    resume_target = resume_paths.resume_target
    setup_hook._self_heal_resume()
    assert not resume_target.exists()


def test_disable_preserves_user_hook_in_shared_entry(
    resume_paths: ResumeHookPaths,
) -> None:
    # A user who tucked their own hook into the *same* SessionStart entry as ours must
    # not lose it when resume is disabled — we strip only our hook item, not the entry.
    settings = resume_paths.settings
    setup_hook.enable_session_resume()
    data = json.loads(settings.read_text(encoding="utf-8"))
    data["hooks"]["SessionStart"][0]["hooks"].append(
        {"type": "command", "command": "echo my-own-hook"}
    )
    settings.write_text(json.dumps(data), encoding="utf-8")

    assert setup_hook.disable_session_resume() == 0

    data = json.loads(settings.read_text(encoding="utf-8"))
    commands = [h["command"] for e in data["hooks"]["SessionStart"] for h in e["hooks"]]
    assert "echo my-own-hook" in commands  # user's hook survived
    assert not setup_hook.is_resume_enabled()  # ours is gone

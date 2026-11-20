# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from string import Formatter

import pytest

from installer import session_hooks
from tests.helpers import ResumeHookPaths


@pytest.fixture
def resume_paths(patch_resume_hook_paths: Callable[..., ResumeHookPaths]) -> ResumeHookPaths:
    return patch_resume_hook_paths()


def _resume_entries(settings: Path) -> list[dict[str, object]]:
    data = json.loads(settings.read_text(encoding="utf-8"))
    return [e for e in data["hooks"]["SessionStart"] if session_hooks._is_resume_entry(e)]


def test_enable_registers_hook_and_writes_sidecar(
    resume_paths: ResumeHookPaths,
) -> None:
    settings = resume_paths.settings
    resume_target = resume_paths.resume_target
    sidecar = resume_paths.sidecar

    assert session_hooks.enable_session_resume() == 0
    assert session_hooks.is_resume_enabled()
    assert resume_target.exists()
    assert sidecar.exists()

    entries = _resume_entries(settings)
    assert len(entries) == 1
    assert entries[0]["matcher"] == session_hooks.RESUME_MATCHER
    hooks = entries[0]["hooks"]
    assert isinstance(hooks, list)
    first_hook = hooks[0]
    assert isinstance(first_hook, dict)
    command = first_hook["command"]
    assert isinstance(command, str)
    assert resume_target.as_posix() in command
    # Sidecar carries the i18n-sourced prompt template for every shipped language.
    bundle = json.loads(sidecar.read_text(encoding="utf-8"))
    assert {"zh-TW", "en", "ja", "ko", "zh-CN"} <= set(bundle)
    assert "{project}" in bundle["en"]["prompt"]
    assert "lead" in bundle["en"]  # lead-in so Claude's first reply acknowledges the load
    assert bundle["en"]["empty"]  # greeting shown when there's no fresh progress to report
    assert "uncommitted" in bundle["en"]
    assert bundle["zh-TW"]["resume_cost"].startswith("這個對話放了 {idle}")
    assert "{tokens}" in bundle["en"]["resume_cost"]
    assert "diagnosis_reminder" in bundle["en"]
    assert "polluter_dirs" in bundle["en"]["diagnosis_causes"]
    for template in bundle.values():
        for key in ("summary", "last_reply"):
            assert [part[1] for part in Formatter().parse(template[key]) if part[1]] == ["text"]
        assert {part[1] for part in Formatter().parse(template["uncommitted"]) if part[1]} == {
            "branch",
            "count",
            "files",
        }


def test_enable_is_idempotent(resume_paths: ResumeHookPaths) -> None:
    settings = resume_paths.settings
    session_hooks.enable_session_resume()
    session_hooks.enable_session_resume()
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

    session_hooks.enable_session_resume()
    data = json.loads(settings.read_text(encoding="utf-8"))
    commands = [h["command"] for e in data["hooks"]["SessionStart"] for h in e["hooks"]]
    assert "other" in commands
    assert any("usage-session-resume" in c for c in commands)
    assert data["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == "guard"


def test_disable_removes_entry_and_files(resume_paths: ResumeHookPaths) -> None:
    settings = resume_paths.settings
    resume_target = resume_paths.resume_target
    sidecar = resume_paths.sidecar
    session_hooks.enable_session_resume()

    session_hooks.disable_session_resume()
    assert not session_hooks.is_resume_enabled()
    assert not resume_target.exists()
    assert not sidecar.exists()
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert "hooks" not in data


def test_disable_keeps_other_session_start_hooks(
    resume_paths: ResumeHookPaths,
) -> None:
    settings = resume_paths.settings
    session_hooks.enable_session_resume()
    data = json.loads(settings.read_text(encoding="utf-8"))
    data["hooks"]["SessionStart"].insert(
        0, {"matcher": "startup", "hooks": [{"type": "command", "command": "other"}]}
    )
    settings.write_text(json.dumps(data), encoding="utf-8")

    session_hooks.disable_session_resume()
    data = json.loads(settings.read_text(encoding="utf-8"))
    commands = [h["command"] for e in data["hooks"]["SessionStart"] for h in e["hooks"]]
    assert commands == ["other"]


def test_self_heal_restores_missing_script_when_enabled(
    resume_paths: ResumeHookPaths,
) -> None:
    _settings = resume_paths.settings
    resume_target = resume_paths.resume_target
    sidecar = resume_paths.sidecar
    session_hooks.enable_session_resume()
    resume_target.unlink()
    sidecar.unlink()

    session_hooks._self_heal_resume()
    assert resume_target.exists()
    assert sidecar.exists()

    data = json.loads(_settings.read_text(encoding="utf-8"))
    detail = data["usage"]["selfHealLog"][-1]["detail"]
    assert data["usage"]["selfHealLog"][-1]["action"] == "restore_resume_hook"
    assert "missing=script,sidecar" in detail
    assert "registered=target" in detail
    assert "recent_claude_entries=" in detail


def test_self_heal_restores_missing_sidecar_without_downgrading_script(
    resume_paths: ResumeHookPaths,
) -> None:
    session_hooks.enable_session_resume()
    newer_script = '__version__ = "99.0"\n'
    resume_paths.resume_target.write_text(newer_script, encoding="utf-8")
    resume_paths.sidecar.unlink()

    session_hooks._self_heal_resume()

    assert resume_paths.resume_target.read_text(encoding="utf-8") == newer_script
    assert json.loads(resume_paths.sidecar.read_text(encoding="utf-8"))["en"]["prompt"]
    log = json.loads(resume_paths.settings.read_text(encoding="utf-8"))["usage"]["selfHealLog"]
    assert log[-1]["action"] == "restore_resume_hook"
    assert "missing=sidecar" in log[-1]["detail"]


def test_self_heal_upgrade_to_117_rewrites_existing_sidecar(
    patch_resume_hook_paths: Callable[..., ResumeHookPaths],
) -> None:
    from usage_hooks import usage_session_resume

    source = Path(usage_session_resume.__file__).read_text(encoding="utf-8")
    paths = patch_resume_hook_paths(source_text=source)
    session_hooks.enable_session_resume()
    paths.resume_target.write_text('__version__ = "1.16"\n', encoding="utf-8")
    paths.sidecar.write_text('{"en": {"lead": "old version"}}', encoding="utf-8")

    session_hooks._self_heal_resume()

    assert session_hooks.RESUME_HOOK_VERSION == usage_session_resume.__version__ == "1.17"
    assert session_hooks._installed_resume_version() == "1.17"
    bundle = json.loads(paths.sidecar.read_text(encoding="utf-8"))
    assert bundle["en"]["lead"] != "old version"
    assert bundle["en"]["summary"] == "Summary at the end of the last session: {text}"
    assert bundle["en"]["last_reply"] == "Claude's last reply: {text}"


def test_self_heal_normalizes_existing_target_command(
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
                                    "command": f"/usr/bin/python3 {source}",
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

    session_hooks._self_heal_resume()

    data = json.loads(settings.read_text(encoding="utf-8"))
    other_entry, session_entry = data["hooks"]["SessionStart"]
    migrated_hook = session_entry["hooks"][0]
    assert session_entry["matcher"] == session_hooks.RESUME_MATCHER
    assert session_entry["custom"] == "keep"
    assert migrated_hook["type"] == "command"
    assert migrated_hook["timeout"] == 3
    assert resume_target.as_posix() in migrated_hook["command"]
    assert other_entry["matcher"] == "startup|clear"
    assert other_entry["hooks"] == [{"type": "command", "command": "other"}]
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
    session_hooks.enable_session_resume()
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

    session_hooks._self_heal_resume()

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
    session_hooks._self_heal_resume()
    assert not resume_target.exists()


def test_self_heal_upgrades_only_our_matcher(resume_paths: ResumeHookPaths) -> None:
    settings = resume_paths.settings
    session_hooks.enable_session_resume()
    data = json.loads(settings.read_text(encoding="utf-8"))
    own_entry = data["hooks"]["SessionStart"][0]
    own_entry["matcher"] = "startup|clear"
    other_entry = {
        "matcher": "startup|clear",
        "hooks": [{"type": "command", "command": "other"}],
    }
    data["hooks"]["SessionStart"].append(other_entry)
    settings.write_text(json.dumps(data), encoding="utf-8")

    session_hooks._self_heal_resume()

    after = json.loads(settings.read_text(encoding="utf-8"))
    assert after["hooks"]["SessionStart"][0]["matcher"] == session_hooks.RESUME_MATCHER
    assert after["hooks"]["SessionStart"][1] == other_entry


def test_self_heal_does_not_enable_resume_for_other_hooks(resume_paths: ResumeHookPaths) -> None:
    settings = resume_paths.settings
    data = {
        "hooks": {
            "SessionStart": [
                {"matcher": "startup|clear", "hooks": [{"type": "command", "command": "other"}]}
            ]
        }
    }
    settings.write_text(json.dumps(data), encoding="utf-8")

    session_hooks._self_heal_resume()

    assert json.loads(settings.read_text(encoding="utf-8")) == data
    assert not resume_paths.resume_target.exists()


def test_disable_preserves_user_hook_in_shared_entry(
    resume_paths: ResumeHookPaths,
) -> None:
    # A user who tucked their own hook into the *same* SessionStart entry as ours must
    # not lose it when resume is disabled — we strip only our hook item, not the entry.
    settings = resume_paths.settings
    session_hooks.enable_session_resume()
    data = json.loads(settings.read_text(encoding="utf-8"))
    data["hooks"]["SessionStart"][0]["hooks"].append(
        {"type": "command", "command": "echo my-own-hook"}
    )
    settings.write_text(json.dumps(data), encoding="utf-8")

    assert session_hooks.disable_session_resume() == 0

    data = json.loads(settings.read_text(encoding="utf-8"))
    commands = [h["command"] for e in data["hooks"]["SessionStart"] for h in e["hooks"]]
    assert "echo my-own-hook" in commands  # user's hook survived
    assert not session_hooks.is_resume_enabled()  # ours is gone


def test_hook_default_templates_match_written_sidecar(resume_paths: ResumeHookPaths) -> None:
    from usage_hooks import usage_session_resume

    session_hooks._write_resume_sidecar()
    sidecar = json.loads(resume_paths.sidecar.read_text(encoding="utf-8"))
    # Non-English fallbacks carry only the core keys; diagnosis wording falls back to English.
    for lang, template in usage_session_resume._DEFAULT_TEMPLATES.items():
        for key, value in template.items():
            assert value == sidecar[lang][key], (lang, key)


@pytest.mark.parametrize(
    ("lang", "no_invent", "greeting", "working_directory"),
    [
        ("zh-TW", "沒有的別編", "🐾 已接回上次進度，繼續吧！", "目前工作目錄"),
        (
            "en",
            "invent nothing",
            "🐾 Picked up where you left off — let's keep going!",
            "Current working directory",
        ),
        ("zh-CN", "没有的别编", "🐾 已接回上次进度，继续吧！", "当前工作目录"),
        (
            "ja",
            "無いことは創作しないこと",
            "🐾 前回の続きを引き継ぎました！そのまま続けましょう！",
            "現在の作業ディレクトリ",
        ),
        (
            "ko",
            "없는 것은 지어내지 마세요",
            "🐾 지난 작업을 불러왔어요! 이어서 가볼까요?",
            "현재 작업 디렉터리",
        ),
    ],
)
def test_five_language_leads_keep_greeting_and_no_invent_rule_and_describe_workspace(
    resume_paths: ResumeHookPaths, lang: str, no_invent: str, greeting: str, working_directory: str
) -> None:
    session_hooks._write_resume_sidecar()
    template = json.loads(resume_paths.sidecar.read_text(encoding="utf-8"))[lang]

    assert greeting in template["lead"]
    # The "invent nothing" rule dates from ad5d2949; shortening the lead must keep it.
    assert no_invent in template["lead"]
    assert template["uncommitted"].startswith(working_directory)

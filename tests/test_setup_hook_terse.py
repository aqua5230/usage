# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Callable
from pathlib import Path

import pytest

from installer import session_hooks
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


def test_enable_registers_hook_and_writes_sidecar(
    terse_paths: TerseHookPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = terse_paths.settings
    monkeypatch.setattr(session_hooks, "detect_lang", lambda: "zh-TW")

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
    assert terse_paths.terse_target.as_posix() in command
    bundle = json.loads(terse_paths.sidecar.read_text(encoding="utf-8"))
    assert bundle["lang"] == "zh-TW"
    assert {"zh-TW", "en", "ja", "ko", "zh-CN"} <= set(bundle)
    assert "Terse mode is on for this entire conversation" in bundle["en"]["instruction"]
    assert "plain is the style" in bundle["en"]["instruction"]
    assert "白話是風格" in bundle["zh-TW"]["instruction"]
    assert (
        "工具或子代理的輸出不要原文轉貼：先讀懂再用白話重寫成結論，只有程式碼、指令、路徑、錯誤"
        "訊息照原文保留。" in bundle["zh-TW"]["instruction"]
    )
    assert (
        "Never paste a tool's or subagent's output verbatim: read it, then rewrite it as a "
        "plain-language conclusion — only code, commands, paths, and error messages stay "
        "verbatim." in bundle["en"]["instruction"]
    )
    assert (
        "工具或子代理的输出不要原文转贴：先读懂再用白话重写成结论，只有代码、指令、路径、错误"
        "信息照原文保留。" in bundle["zh-CN"]["instruction"]
    )
    assert (
        "ツールやサブエージェントの出力をそのまま貼り付けないこと。まず理解し、平易な言葉で結"
        "論として書き直す。原文のまま残すのはコード、コマンド、パス、エラーメッセージだけ。"
        in bundle["ja"]["instruction"]
    )
    assert (
        "도구나 서브에이전트의 출력을 그대로 붙여넣지 말 것: 먼저 이해한 뒤 쉬운 말로 결론으로 "
        "다시 쓰고, 코드·명령어·경로·오류 메시지만 원문 그대로 둔다."
        in bundle["ko"]["instruction"]
    )
    assert (
        "名詞化還原成動詞：進行修改→改、做出決定→決定。刪只預告不給資訊的句子：接下來我要說明、值"
        "得注意的是、在深入之前。每句先已知後新知。"
        in bundle["zh-TW"]["instruction"]
    )
    assert (
        "名词化还原成动词：进行修改→改、做出决定→决定。删只预告不给信息的句子：接下来我要说明、值"
        "得注意的是、在深入之前。每句先已知后新知。"
        in bundle["zh-CN"]["instruction"]
    )
    assert (
        "Zombie nouns to verbs: \"make a decision\" to \"decide\". Cut metadiscourse: \"Let me ex"
        "plain\", \"It's worth noting\", \"Before diving in\". Given info first in a sentence, ne"
        "w info last. "
        in bundle["en"]["instruction"]
    )
    assert (
        "名詞化は動詞に戻す（修正を行う→修正する）。予告だけの文は削る（「これから説明します」「"
        "注目すべきは」）。各文は既知が先、新情報が後。"
        in bundle["ja"]["instruction"]
    )
    assert (
        "명사화는 동사로 (수정을 진행한다 → 고친다). 예고만 하는 문장은 삭제 (\"이제 설명하겠습니"
        "다\", \"주목할 점은\"). 각 문장은 아는 것 먼저, 새 정보 나중. "
        in bundle["ko"]["instruction"]
    )
    assert "plain-spoken" in bundle["en"]["reminder"]


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
    assert any("usage-terse-mode" in c for c in commands)
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


def test_strip_hook_entries_keeps_user_backup_command() -> None:
    entry = {
        "hooks": [
            {"type": "command", "command": "python3 /opt/my-usage-terse-mode-backup.py"}
        ]
    }

    assert session_hooks._strip_hook_entries(entry, session_hooks._TERSE_MARKERS) == entry


def test_strip_hook_entries_removes_usage_command() -> None:
    entry = {
        "hooks": [
            {
                "type": "command",
                "command": "/usr/bin/python3 /Users/me/.claude/usage-terse-mode.py",
            }
        ]
    }

    assert session_hooks._strip_hook_entries(entry, session_hooks._TERSE_MARKERS) is None


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
    assert (
        data["usage"]["selfHealLog"][-1]["detail"] == f"0.1 -> {session_hooks.TERSE_HOOK_VERSION}"
    )


def test_installed_terse_version_returns_none_for_truncated_version(
    terse_paths: TerseHookPaths,
) -> None:
    terse_paths.terse_target.write_text("__version__\n", encoding="utf-8")

    assert session_hooks._installed_terse_version() is None


def test_installed_resume_version_returns_none_for_truncated_version(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    resume_target = tmp_path / "usage-session-resume.py"
    resume_target.write_text("__version__\n", encoding="utf-8")
    monkeypatch.setattr(session_hooks, "RESUME_HOOK_TARGET", resume_target)

    assert session_hooks._installed_resume_version() is None


def test_missing_terse_artifacts_includes_invalid_sidecar(terse_paths: TerseHookPaths) -> None:
    session_hooks.enable_terse_mode()
    terse_paths.sidecar.write_text("{", encoding="utf-8")

    assert "sidecar" in session_hooks._missing_terse_artifacts()


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
    assert terse_paths.codex_terse_target.as_posix() in hook["command"]


def test_setup_codex_terse_keeps_unreadable_hooks_json_unchanged(
    terse_paths: TerseHookPaths,
) -> None:
    terse_paths.codex_config.write_text('model = "gpt-5"\n', encoding="utf-8")
    terse_paths.codex_hooks_json.write_bytes(b"\xff\xfe{")
    config_before = terse_paths.codex_config.read_bytes()
    hooks_before = terse_paths.codex_hooks_json.read_bytes()

    session_hooks._setup_codex_terse()

    assert terse_paths.codex_config.read_bytes() == config_before
    assert terse_paths.codex_hooks_json.read_bytes() == hooks_before
    assert not terse_paths.codex_terse_target.exists()


def test_setup_codex_terse_creates_missing_hooks_json(terse_paths: TerseHookPaths) -> None:
    terse_paths.codex_config.write_text('model = "gpt-5"\n', encoding="utf-8")

    session_hooks._setup_codex_terse()

    assert terse_paths.codex_hooks_json.exists()
    assert len(_codex_terse_entries(terse_paths.codex_hooks_json)) == 1


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
    assert terse_paths.terse_reminder_target.as_posix() in command


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


def test_self_heal_updates_old_reminder_version(terse_paths: TerseHookPaths) -> None:
    session_hooks.enable_terse_mode()
    terse_paths.terse_reminder_target.write_text('__version__ = "1.0"\n', encoding="utf-8")

    session_hooks._self_heal_terse_mode()

    assert session_hooks._installed_terse_reminder_version() == (
        session_hooks.TERSE_REMINDER_HOOK_VERSION
    )
    data = json.loads(terse_paths.settings.read_text(encoding="utf-8"))
    assert data["usage"]["selfHealLog"][-1]["action"] == "update_terse_reminder_hook"
    assert data["usage"]["selfHealLog"][-1]["detail"] == (
        f"1.0 -> {session_hooks.TERSE_REMINDER_HOOK_VERSION}"
    )


def test_self_heal_reminder_noop_when_disabled(terse_paths: TerseHookPaths) -> None:
    session_hooks._self_heal_terse_mode()
    assert not terse_paths.terse_reminder_target.exists()

def test_terse_script_version_matches_hook_constant() -> None:
    """The self-heal compares the installed script's __version__ against
    TERSE_HOOK_VERSION. If the two drift apart the comparison never matches and
    every session rewrites the sidecar, so keep them in lockstep."""
    source = (Path(__file__).resolve().parents[1] / "usage_terse_mode.py").read_text(
        encoding="utf-8"
    )
    match = re.search(r'^__version__ = "([^"]+)"$', source, re.M)
    assert match, "usage_terse_mode.py has no __version__ line"
    assert match.group(1) == session_hooks.TERSE_HOOK_VERSION

    reminder = (Path(__file__).resolve().parents[1] / "usage_terse_reminder.py").read_text(
        encoding="utf-8"
    )
    reminder_match = re.search(r'^__version__ = "([^"]+)"$', reminder, re.M)
    assert reminder_match, "usage_terse_reminder.py has no __version__ line"
    assert reminder_match.group(1) == session_hooks.TERSE_REMINDER_HOOK_VERSION

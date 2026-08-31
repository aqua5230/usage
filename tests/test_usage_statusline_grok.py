# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

import usage_statusline_grok
from installer import session_hooks, setup_hook, statusline_settings

FIXTURE = Path(__file__).parent / "fixtures" / "grok_statusline_input.json"
_ANSI = re.compile(r"\033\[[0-9;]*m")


def _fixture_data() -> dict[str, Any]:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _write_billing_log(path: Path, used: float = 42.0) -> None:
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "msg": "billing: fetched credits config",
                "ctx": {
                    "config": {
                        "creditUsagePercent": used,
                        "currentPeriod": {"end": "2099-09-01T15:50:08.729634+00:00"},
                    }
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _visible(value: str) -> str:
    return _ANSI.sub("", value)


def test_render_fixture_contains_expected_status(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    log = tmp_path / ".grok" / "logs" / "unified.jsonl"
    _write_billing_log(log)
    monkeypatch.setattr(usage_statusline_grok, "GROK_LOG_PATH", log)
    monkeypatch.setenv("USAGE_LANG", "zh-TW")
    monkeypatch.setenv("COLUMNS", "300")

    output = _visible(usage_statusline_grok.render(_fixture_data()))

    assert "project(main)" in output
    assert "週配額:■■■□□□□□ 42%" in output
    assert re.search(r"\(剩[0-9]+d[0-9]+h\)", output)
    assert "對話窗:■□□□□□□□ 8% / 2.0M" in output
    assert "會話時長:20min" in output
    assert "Grok 4.6/深思" in output
    assert output.count("\n") == 1


def test_render_omits_quota_when_log_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(usage_statusline_grok, "GROK_LOG_PATH", tmp_path / "missing.jsonl")
    monkeypatch.setenv("USAGE_LANG", "en")

    output = _visible(usage_statusline_grok.render(_fixture_data()))

    assert "Weekly" not in output
    assert "Context:" in output
    assert "Session:20min" in output
    assert "Grok 4.6/Deep" in output


def test_render_omits_quota_when_latest_log_entry_is_invalid(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    log = tmp_path / ".grok" / "logs" / "unified.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text(
        '{"msg":"billing: fetched credits config","ctx":{"config":{"creditUsagePercent":"bad"}}}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(usage_statusline_grok, "GROK_LOG_PATH", log)
    monkeypatch.setenv("USAGE_LANG", "en")

    output = _visible(usage_statusline_grok.render(_fixture_data()))

    assert "Weekly" not in output
    assert "Context:" in output


def test_render_degrades_when_context_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    log = tmp_path / ".grok" / "logs" / "unified.jsonl"
    _write_billing_log(log)
    data = _fixture_data()
    data["context_window"] = None
    monkeypatch.setattr(usage_statusline_grok, "GROK_LOG_PATH", log)
    monkeypatch.setenv("USAGE_LANG", "en")

    output = _visible(usage_statusline_grok.render(data))

    assert "Weekly:" in output
    assert "Context:" not in output
    assert "Session:20min" in output


def test_render_degrades_for_narrow_terminal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    log = tmp_path / ".grok" / "logs" / "unified.jsonl"
    _write_billing_log(log)
    monkeypatch.setattr(usage_statusline_grok, "GROK_LOG_PATH", log)
    monkeypatch.setenv("USAGE_LANG", "en")
    monkeypatch.setenv("COLUMNS", "40")

    output = _visible(usage_statusline_grok.render(_fixture_data()))

    first_line = output.splitlines()[0]
    assert "Weekly:42%" in first_line
    assert "Context:8%" in first_line
    assert "left" not in first_line
    assert "■" not in first_line


def _patch_grok_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, Path, Path]:
    settings = tmp_path / ".grok" / "config.toml"
    target = settings.parent / "usage-statusline-grok.py"
    previous = settings.parent / "usage-previous-statusline-grok.json"
    settings.parent.mkdir(parents=True)
    monkeypatch.setattr(setup_hook, "GROK_SETTINGS", settings)
    monkeypatch.setattr(setup_hook, "GROK_HOOK_TARGET", target)
    monkeypatch.setattr(setup_hook, "GROK_PREVIOUS_STATUSLINE", previous)
    return settings, target, previous


def test_setup_and_unsetup_grok_restore_existing_status_line_verbatim(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings, target, previous = _patch_grok_paths(monkeypatch, tmp_path)
    original = (
        '# Keep this comment exactly.\n'
        '[ui]\n'
        'theme = "dark"\n'
        '\n'
        '[ui.status_line] # previous row\n'
        'type = "builtin"\n'
        'items = ["cwd", "model"]\n'
        '\n'
        '[other]\n'
        'keep = true\n'
    )
    settings.write_text(original, encoding="utf-8")
    monkeypatch.setattr("installer.setup_hook.sys.platform", "darwin")

    assert setup_hook._setup_grok()
    installed = settings.read_text(encoding="utf-8")
    assert '[ui.status_line]\ntype = "command"' in installed
    assert f'command = "/usr/bin/python3 {target}"' in installed
    assert previous.read_text(encoding="utf-8") == (
        '[ui.status_line] # previous row\ntype = "builtin"\nitems = ["cwd", "model"]\n\n'
    )
    source = Path(setup_hook.__file__).parent.parent / "usage_statusline_grok.py"
    assert target.read_bytes() == source.read_bytes()
    assert setup_hook.is_grok_setup()

    assert setup_hook._unsetup_grok()
    assert settings.read_text(encoding="utf-8") == original
    assert target.exists()
    assert not previous.exists()
    assert not setup_hook.is_grok_setup()


def test_setup_and_unsetup_grok_restore_config_without_prior_status_line(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings, target, previous = _patch_grok_paths(monkeypatch, tmp_path)
    original = '[ui]\ntheme = "dark"\n'
    settings.write_text(original, encoding="utf-8")
    monkeypatch.setattr("installer.setup_hook.sys.platform", "darwin")

    assert setup_hook._setup_grok()
    assert not previous.exists()
    assert setup_hook._unsetup_grok()
    assert settings.read_text(encoding="utf-8") == original
    assert target.exists()


@pytest.mark.parametrize("content", ["{broken", "[ui.status_line]\ntype = ["])
def test_setup_grok_refuses_missing_or_invalid_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    content: str,
) -> None:
    settings, target, previous = _patch_grok_paths(monkeypatch, tmp_path)
    settings.write_text(content, encoding="utf-8")
    monkeypatch.setattr("installer.setup_hook.sys.platform", "darwin")

    assert not setup_hook._setup_grok()
    assert not target.exists()
    assert not previous.exists()


def test_setup_grok_refuses_missing_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings, target, previous = _patch_grok_paths(monkeypatch, tmp_path)
    monkeypatch.setattr("installer.setup_hook.sys.platform", "darwin")

    assert not setup_hook._setup_grok()
    assert not settings.exists()
    assert not target.exists()
    assert not previous.exists()


def test_self_heal_installs_grok_statusline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings, target, _previous = _patch_grok_paths(monkeypatch, tmp_path)
    settings.write_text("[ui]\ntheme = \"dark\"\n", encoding="utf-8")
    logs: list[tuple[str, str]] = []
    monkeypatch.setattr("installer.setup_hook.sys.platform", "darwin")
    monkeypatch.setattr(setup_hook, "AGY_SETTINGS", tmp_path / "missing-agy-settings.json")
    monkeypatch.setattr(session_hooks, "_load_settings", lambda: {"statusLine": {}})
    monkeypatch.setattr(session_hooks, "_detect_current_state", lambda *args: "us-direct")
    monkeypatch.setattr(session_hooks, "is_setup", lambda: True)
    monkeypatch.setattr(session_hooks, "needs_update", lambda: False)
    monkeypatch.setattr(session_hooks, "_statusline_command_target_exists", lambda: True)
    monkeypatch.setattr(session_hooks, "_read_codex_config", lambda: None)
    monkeypatch.setattr(session_hooks, "_self_heal_resume", lambda: None)
    monkeypatch.setattr(session_hooks, "_self_heal_terse_mode", lambda: None)
    monkeypatch.setattr(statusline_settings, "_statusline_enabled", lambda: True)
    monkeypatch.setattr(
        session_hooks, "_append_self_heal_log", lambda action, detail: logs.append((action, detail))
    )

    session_hooks.self_heal()

    assert target.exists()
    assert setup_hook.is_grok_setup()
    assert logs == [("setup_grok", "installed or updated Grok status line")]

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

import setup_hook
import usage_statusline_agy

FIXTURE = Path(__file__).parent / "fixtures" / "agy_statusline_input.json"


def _fixture_data() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


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


def test_setup_and_unsetup_agy_preserve_settings_and_restore_statusline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings, target, previous = _patch_agy_paths(monkeypatch, tmp_path)
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
        "command": f"/usr/bin/python3 {target}",
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

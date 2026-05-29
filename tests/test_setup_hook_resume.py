from __future__ import annotations

import json
from pathlib import Path

import pytest

import setup_hook


def _patch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, Path, Path]:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    settings = claude_dir / "settings.json"
    resume_target = claude_dir / "usage-session-resume.py"
    sidecar = claude_dir / "usage-resume-prompt.json"
    source = tmp_path / "resume_source.py"
    source.write_text('__version__ = "1.0"\nprint("resume")\n', encoding="utf-8")
    monkeypatch.setattr(setup_hook, "CLAUDE_SETTINGS", settings)
    monkeypatch.setattr(setup_hook, "RESUME_HOOK_TARGET", resume_target)
    monkeypatch.setattr(setup_hook, "RESUME_PROMPT_SIDECAR", sidecar)
    monkeypatch.setattr(setup_hook, "_resolve_resume_source", lambda: source)
    return settings, resume_target, sidecar


def _resume_entries(settings: Path) -> list[dict[str, object]]:
    data = json.loads(settings.read_text(encoding="utf-8"))
    return [e for e in data["hooks"]["SessionStart"] if setup_hook._is_resume_entry(e)]


def test_enable_registers_hook_and_writes_sidecar(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings, resume_target, sidecar = _patch(monkeypatch, tmp_path)

    assert setup_hook.enable_session_resume() == 0
    assert setup_hook.is_resume_enabled()
    assert resume_target.exists()
    assert sidecar.exists()

    entries = _resume_entries(settings)
    assert len(entries) == 1
    assert entries[0]["matcher"] == setup_hook.RESUME_MATCHER
    # Sidecar carries the i18n-sourced prompt template for every shipped language.
    bundle = json.loads(sidecar.read_text(encoding="utf-8"))
    assert {"zh-TW", "en", "ja", "ko", "zh-CN"} <= set(bundle)
    assert "{project}" in bundle["en"]["prompt"]
    assert "lead" in bundle["en"]  # lead-in so Claude's first reply acknowledges the load


def test_enable_is_idempotent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    settings, _, _ = _patch(monkeypatch, tmp_path)
    setup_hook.enable_session_resume()
    setup_hook.enable_session_resume()
    assert len(_resume_entries(settings)) == 1


def test_enable_preserves_existing_hooks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings, _, _ = _patch(monkeypatch, tmp_path)
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
    assert any("usage-session-resume" in c for c in commands)
    assert data["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == "guard"


def test_disable_removes_entry_and_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings, resume_target, sidecar = _patch(monkeypatch, tmp_path)
    setup_hook.enable_session_resume()

    setup_hook.disable_session_resume()
    assert not setup_hook.is_resume_enabled()
    assert not resume_target.exists()
    assert not sidecar.exists()
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert "hooks" not in data


def test_disable_keeps_other_session_start_hooks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings, _, _ = _patch(monkeypatch, tmp_path)
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
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _settings, resume_target, sidecar = _patch(monkeypatch, tmp_path)
    setup_hook.enable_session_resume()
    resume_target.unlink()
    sidecar.unlink()

    setup_hook._self_heal_resume()
    assert resume_target.exists()
    assert sidecar.exists()


def test_self_heal_noop_when_disabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _settings, resume_target, _sidecar = _patch(monkeypatch, tmp_path)
    setup_hook._self_heal_resume()
    assert not resume_target.exists()

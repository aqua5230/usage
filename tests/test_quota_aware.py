from __future__ import annotations

import io
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from installer import session_hooks, setup_hook
from quota import quota_snapshot
from usage_hooks import usage_quota_aware as hook

NOW = 1_800_000_000.0
RESET = NOW + 4800


@pytest.fixture
def paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(hook, "CLAUDE_STATUS", tmp_path / "claude.json")
    monkeypatch.setattr(hook, "QUOTA_SNAPSHOT", tmp_path / "snapshot.json")
    monkeypatch.setattr(hook, "STATE_PATH", tmp_path / "state.json")
    return tmp_path


def claude(five: float = 0, weekly: float = 0, reset: float = RESET) -> None:
    hook.CLAUDE_STATUS.write_text(
        json.dumps(
            {
                "rate_limits": {
                    "five_hour": {"used_percentage": five, "resets_at": reset},
                    "seven_day": {"used_percentage": weekly, "resets_at": reset},
                }
            }
        )
    )


def snapshot(age: float = 0) -> None:
    hook.QUOTA_SNAPSHOT.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": datetime.fromtimestamp(NOW - age, UTC).isoformat(),
                "agents": {
                    "codex": {
                        "available": True,
                        "five_hour": {
                            "used_percent": 91,
                            "resets_at": RESET,
                        },
                    },
                    "antigravity": {
                        "available": True,
                        "groups": [
                            {
                                "name": "Gemini",
                                "five_hour": {
                                    "used_percent": 82,
                                    "resets_in_seconds": 2400,
                                },
                            }
                        ],
                    },
                },
            }
        )
    )


def test_low_quota_is_silent(paths: Path) -> None:
    claude(79, 94)
    assert hook.reminder("one", NOW) == ""
    assert not hook.STATE_PATH.exists()


def test_thresholds_and_sessions(paths: Path) -> None:
    claude(82)
    assert "Claude Code 5-hour quota: 82% used, resets in 1h 20m." in hook.reminder("one", NOW)
    assert hook.reminder("one", NOW) == ""
    claude(91)
    assert "91% used" in hook.reminder("one", NOW)
    assert hook.reminder("one", NOW) == ""
    assert "91% used" in hook.reminder("two", NOW)
    claude(96)
    assert "96% used" in hook.reminder("one", NOW)
    claude(82)
    assert hook.reminder("one", NOW) == ""


def test_weekly_threshold(paths: Path) -> None:
    claude(0, 96)
    assert "weekly quota: 96% used" in hook.reminder("one", NOW)


def test_expired_window(paths: Path) -> None:
    claude(99, 99, NOW)
    assert hook.reminder("one", NOW) == ""


def test_stale_snapshot_only_uses_claude(paths: Path) -> None:
    claude(82)
    snapshot(901)
    output = hook.reminder("one", NOW)
    assert "Claude Code" in output
    assert "Codex" not in output
    assert "Antigravity" not in output


def test_snapshot_and_agy_reset(paths: Path) -> None:
    snapshot()
    output = hook.reminder("one", NOW)
    assert "Codex 5-hour quota: 91% used" in output
    assert "Antigravity (Gemini) 5-hour quota: 82% used, resets in 40m." in output
    state = json.loads(hook.STATE_PATH.read_text(encoding="utf-8"))
    assert any(value["resets_at"] == NOW + 2400 for value in state.values())
    assert hook.reminder("one", NOW) == ""


def test_agy_reset_drift_is_not_a_new_window(paths: Path) -> None:
    snapshot()
    assert "Antigravity" in hook.reminder("one", NOW)
    snapshot(-1)  # one second later: generated_at + resets_in_seconds lands a second off
    assert hook.reminder("one", NOW + 1) == ""


@pytest.mark.parametrize("path_name", ["QUOTA_SNAPSHOT", "STATE_PATH"])
def test_corrupt_files(paths: Path, path_name: str) -> None:
    claude(82)
    getattr(hook, path_name).write_text("broken")
    assert "82% used" in hook.reminder("one", NOW)


@pytest.mark.parametrize("stdin", ["broken", "[]", "null", "42", "{}", '{"session_id": 4}'])
def test_bad_stdin(
    paths: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], stdin: str
) -> None:
    claude(82)
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    hook.main()
    assert capsys.readouterr().out == ""


def test_exception_silent(
    paths: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"session_id": "one"}'))

    def fail(*args: Any) -> str:
        raise OSError("state write failed")

    monkeypatch.setattr(hook, "reminder", fail)
    hook.main()
    assert capsys.readouterr().out == ""


def test_expired_state_pruned_and_new_reset(paths: Path) -> None:
    claude(82)
    hook.reminder("one", NOW)
    claude(82, reset=RESET + 7200)
    assert "82% used" in hook.reminder("one", RESET + 1)
    state = json.loads(hook.STATE_PATH.read_text(encoding="utf-8"))
    assert len(state) == 1
    assert not list(paths.glob("*.tmp"))


def test_install_remove_and_upgrade(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    settings_path = tmp_path / "claude/settings.json"
    settings_path.parent.mkdir()
    target = settings_path.parent / "usage-quota-aware.py"
    monkeypatch.setattr(setup_hook, "_claude_settings_path", lambda: settings_path)
    monkeypatch.setattr(session_hooks, "QUOTA_AWARE_HOOK_TARGET", target)
    monkeypatch.setattr(setup_hook, "_claude_settings_dir_exists", lambda: True)
    monkeypatch.setattr(session_hooks, "_append_self_heal_log", lambda *args: None)
    existing = {"matcher": "", "hooks": [{"type": "command", "command": "echo other"}]}
    settings_path.write_text(json.dumps({"hooks": {"UserPromptSubmit": [existing]}}))
    assert not session_hooks.is_quota_aware_enabled()
    session_hooks._self_heal_quota_aware()
    assert not target.exists()
    assert session_hooks.enable_quota_aware() == 0
    assert session_hooks.enable_quota_aware() == 0
    assert session_hooks.is_quota_aware_enabled()
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    assert len(settings["hooks"]["UserPromptSubmit"]) == 2
    assert settings["hooks"]["UserPromptSubmit"][0] == existing
    target.write_text('__version__ = "0.1"')
    session_hooks._self_heal_quota_aware()
    assert session_hooks._installed_quota_aware_version() == session_hooks.QUOTA_AWARE_HOOK_VERSION
    target.unlink()
    session_hooks._self_heal_quota_aware()
    assert target.exists()
    assert session_hooks.disable_quota_aware() == 0
    assert not target.exists()
    assert not session_hooks.is_quota_aware_enabled()
    assert json.loads(settings_path.read_text(encoding="utf-8"))["hooks"]["UserPromptSubmit"] == [
        existing
    ]


def test_shared_entry_preserved(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.json"
    monkeypatch.setattr(setup_hook, "_claude_settings_path", lambda: settings_path)
    monkeypatch.setattr(session_hooks, "QUOTA_AWARE_HOOK_TARGET", tmp_path / "hook.py")
    other = {"type": "command", "command": "echo other"}
    settings_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "UserPromptSubmit": [
                        {
                            "matcher": "",
                            "hooks": [
                                other,
                                {
                                    "type": "command",
                                    "command": "/usr/bin/python3 /tmp/usage-quota-aware.py",
                                },
                            ],
                        }
                    ]
                }
            }
        )
    )
    session_hooks.disable_quota_aware()
    assert json.loads(settings_path.read_text(encoding="utf-8"))["hooks"]["UserPromptSubmit"][0][
        "hooks"
    ] == [other]


def test_snapshot_atomic_and_local(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import usage_cli
    from loaders import agy_quota_probe

    monkeypatch.setattr(quota_snapshot, "SNAPSHOT_PATH", tmp_path / "quota.json")
    monkeypatch.setattr(
        usage_cli, "RATE_LIMIT_LOADERS", {"claude-code": lambda: None, "codex": lambda: None}
    )
    monkeypatch.setattr(usage_cli, "_status_grok", lambda now: {"available": False})

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Network quota loader must not be called")

    monkeypatch.setattr(agy_quota_probe, "load_quota", fail)
    quota_snapshot.write_snapshot()
    payload = json.loads(quota_snapshot.SNAPSHOT_PATH.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["generated_at"]
    assert set(payload["agents"]) == {"claude-code", "codex", "antigravity", "grok"}
    assert not list(tmp_path.glob("*.tmp"))

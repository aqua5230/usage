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
    monkeypatch.setattr(hook, "_local", lambda ts: datetime.fromtimestamp(ts, UTC))
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
    output = hook.reminder("one", NOW)
    assert "Claude Code 5-hour quota: 82% used, resets in 1h 20m (at 09:20 local time)." in output
    assert hook.reminder("one", NOW) == ""
    claude(91)
    assert "91% used" in hook.reminder("one", NOW)
    assert hook.reminder("one", NOW) == ""
    assert "91% used" in hook.reminder("two", NOW)
    claude(96)
    assert "96% used" in hook.reminder("one", NOW)
    claude(82)
    assert hook.reminder("one", NOW) == ""


def test_reset_and_current_clock_time(paths: Path) -> None:
    claude(91, reset=NOW + 20 * 3600)
    output = hook.reminder("one", NOW)
    assert "resets in 20h 0m (at Sat 04:00 local time)." in output
    assert "\nCurrent local time: Fri 08:00.\nClaude Code's own quota:" in output


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
    assert 'Antigravity CLI (agy) model group "Gemini": 5-hour quota: 82% used' in output
    assert (
        "resets in 40m (at 08:40 local time). Only limits work sent to agy with those models."
        in output
    )
    state = json.loads(hook.STATE_PATH.read_text(encoding="utf-8"))
    assert any(value["resets_at"] == NOW + 2400 for value in state.values())
    assert hook.reminder("one", NOW) == ""


@pytest.mark.parametrize("tool", ["codex", "muse", "antigravity"])
@pytest.mark.parametrize(
    ("updated_at", "hours"),
    [
        (datetime.fromtimestamp(NOW - 172800, UTC).isoformat(), 48),
        (datetime.fromtimestamp(NOW - 3600, UTC).isoformat(), 1),
        (datetime.fromtimestamp(NOW - 600, UTC).isoformat(), None),
        (None, None),
        ("invalid", None),
        ("2026-01-01T00:00:00", None),
    ],
)
def test_per_tool_observation_age(
    paths: Path, tool: str, updated_at: str | None, hours: int | None
) -> None:
    snapshot()
    data = json.loads(hook.QUOTA_SNAPSHOT.read_text())
    agent: dict[str, Any] = {
        "available": True,
        "age_seconds": 0,
        "seven_day": {"used_percent": 96, "resets_at": RESET},
    }
    if updated_at is not None:
        agent["updated_at"] = updated_at
    if tool == "antigravity":
        agent["groups"] = [{"name": "Gemini", "seven_day": agent.pop("seven_day")}]
        agent["groups"][0]["updated_at"] = datetime.fromtimestamp(NOW, UTC).isoformat()
    data["agents"] = {tool: agent}
    hook.QUOTA_SNAPSHOT.write_text(json.dumps(data))
    claude(96)

    output = hook.reminder("one", NOW)
    line = next(line for line in output.splitlines() if "weekly quota: 96%" in line)
    if hours is None:
        assert "last updated" not in output
    else:
        assert line.endswith(f" (last updated {hours}h ago; it may have reset since)")
        assert output.count("last updated") == 1
    assert "last updated" not in next(
        line for line in output.splitlines() if "Claude Code 5-hour quota" in line
    )
    assert hook.reminder("one", NOW) == ""


def agy_weekly() -> None:
    snapshot()
    data = json.loads(hook.QUOTA_SNAPSHOT.read_text())
    data["agents"].pop("codex")
    data["agents"]["antigravity"]["groups"] = [
        {
            "name": "CLAUDE AND GPT MODELS",
            "seven_day": {"used_percent": 100, "resets_in_seconds": 177300},
        }
    ]
    hook.QUOTA_SNAPSHOT.write_text(json.dumps(data))


def test_agy_weekly_has_explicit_scope_and_own_quota(paths: Path) -> None:
    claude(3, 12)
    agy_weekly()
    output = hook.reminder("one", NOW)
    assert output.startswith(
        '[usage quota] Antigravity CLI (agy) model group "CLAUDE AND GPT MODELS": '
        "weekly quota: 100% used, resets in 49h 15m (at Sun 09:15 local time). "
        "Only limits work sent to agy with those models.\n"
    )
    assert output.endswith(
        "Claude Code's own quota: 5-hour 3% used, resets in 1h 20m (at 09:20 local time); "
        "weekly 12% used, resets in 1h 20m (at 09:20 local time). "
        "This Claude Code session runs on this quota."
    )
    assert hook.reminder("one", NOW) == ""


def test_spent_agy_group_names_groups_that_still_have_quota(paths: Path) -> None:
    claude(3, 12)
    agy_weekly()
    data = json.loads(hook.QUOTA_SNAPSHOT.read_text())
    data["agents"]["antigravity"]["groups"].append(
        {
            "name": "GEMINI MODELS",
            "five_hour": {"used_percent": 1, "resets_in_seconds": 9000},
            "seven_day": {"used_percent": 7.6, "resets_in_seconds": 500000},
        }
    )
    hook.QUOTA_SNAPSHOT.write_text(json.dumps(data))

    output = hook.reminder("one", NOW)

    assert (
        'Other agy model groups still have quota: "GEMINI MODELS" 7.6% used. '
        "Work sent to agy with those models is unaffected, "
        "so Antigravity as a whole is not used up.\n"
    ) in output


def test_no_open_group_line_when_every_agy_group_is_spent(paths: Path) -> None:
    claude(3, 12)
    agy_weekly()
    assert "Other agy model groups" not in hook.reminder("one", NOW)


@pytest.mark.parametrize("status", [None, "broken", '{"rate_limits": {}}'])
def test_missing_own_quota_is_explicit(paths: Path, status: str | None) -> None:
    if status is not None:
        hook.CLAUDE_STATUS.write_text(status)
    agy_weekly()
    output = hook.reminder("one", NOW)
    assert output.endswith(
        "Claude Code's own quota: unknown. This Claude Code session runs on this quota."
    )


def test_own_quota_agrees_with_threshold_reminder(paths: Path) -> None:
    claude(96, 100)
    output = hook.reminder("one", NOW)
    assert "Claude Code 5-hour quota: 96% used, resets in 1h 20m (at 09:20 local time)." in output
    assert "Claude Code weekly quota: 100% used, resets in 1h 20m (at 09:20 local time)." in output
    assert output.count("Claude Code's own quota:") == 1
    assert output.endswith(
        "Claude Code's own quota: 5-hour 96% used, resets in 1h 20m (at 09:20 local time); "
        "weekly 100% used, resets in 1h 20m (at 09:20 local time). "
        "This Claude Code session runs on this quota."
    )
    assert "unknown" not in output


@pytest.mark.parametrize("used", [0, 100])
def test_own_quota_boundary_percentages(paths: Path, used: float) -> None:
    claude(used, used)
    agy_weekly()
    output = hook.reminder("one", NOW)
    assert f"Claude Code's own quota: 5-hour {used}% used" in output
    assert f"weekly {used}% used" in output


def test_expired_own_quota_is_unknown(paths: Path) -> None:
    claude(100, 100, NOW - 1)
    agy_weekly()
    output = hook.reminder("one", NOW)
    assert "Claude Code's own quota: unknown." in output
    assert "Claude Code 5-hour quota:" not in output


def test_partial_own_quota_keeps_missing_window_unknown(paths: Path) -> None:
    hook.CLAUDE_STATUS.write_text(
        json.dumps({"rate_limits": {"five_hour": {"used_percentage": 0, "resets_at": RESET}}})
    )
    agy_weekly()
    output = hook.reminder("one", NOW)
    assert "5-hour 0% used, resets in 1h 20m (at 09:20 local time); weekly unknown." in output


def test_empty_agy_groups(paths: Path) -> None:
    agy_weekly()
    data = json.loads(hook.QUOTA_SNAPSHOT.read_text())
    data["agents"]["antigravity"]["groups"] = []
    hook.QUOTA_SNAPSHOT.write_text(json.dumps(data))
    claude(0, 0)
    assert hook.reminder("one", NOW) == ""
    claude(80, 0)
    output = hook.reminder("one", NOW)
    assert "Antigravity" not in output
    assert "Claude Code's own quota: 5-hour 80% used" in output


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
    target.write_text('__version__ = "99.0"')
    session_hooks._self_heal_quota_aware()
    assert session_hooks._installed_quota_aware_version() == "99.0"
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
    from loaders import agy_quota_probe
    from quota import status_payload

    monkeypatch.setattr(quota_snapshot, "SNAPSHOT_PATH", tmp_path / "quota.json")
    monkeypatch.setattr(
        status_payload, "RATE_LIMIT_LOADERS", {"claude-code": lambda: None, "codex": lambda: None}
    )
    monkeypatch.setattr(status_payload, "_status_grok", lambda now: {"available": False})

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Network quota loader must not be called")

    monkeypatch.setattr(agy_quota_probe, "load_quota", fail)
    quota_snapshot.write_snapshot()
    payload = json.loads(quota_snapshot.SNAPSHOT_PATH.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["generated_at"]
    assert set(payload["agents"]) == {"claude-code", "codex", "antigravity", "grok", "muse"}
    assert not list(tmp_path.glob("*.tmp"))


def test_muse_reminder_scope_threshold_and_dedup(paths: Path) -> None:
    snapshot()
    data = json.loads(hook.QUOTA_SNAPSHOT.read_text())
    data["agents"]["muse"] = {
        "available": True,
        "five_hour": {"used_percent": 82, "resets_at": RESET},
        "seven_day": {"used_percent": 96, "resets_at": RESET + 86400},
    }
    hook.QUOTA_SNAPSHOT.write_text(json.dumps(data))
    output = hook.reminder("muse", NOW)
    assert "Muse 5-hour quota: 82% used" in output
    assert "Muse weekly quota: 96% used" in output
    assert "Only limits work sent to Muse." in output
    assert hook.reminder("muse", NOW) == ""
    data["agents"]["muse"]["five_hour"]["used_percent"] = 91
    hook.QUOTA_SNAPSHOT.write_text(json.dumps(data))
    assert "Muse 5-hour quota: 91% used" in hook.reminder("muse", NOW)


@pytest.mark.parametrize(
    "available,reset,age", [(False, RESET, 0), (True, NOW, 0), (True, RESET, 901)]
)
def test_muse_reminder_ignores_unavailable_expired_stale(
    paths: Path, available: bool, reset: float, age: float
) -> None:
    snapshot(age)
    data = json.loads(hook.QUOTA_SNAPSHOT.read_text())
    data["agents"] = {
        "muse": {"available": available, "five_hour": {"used_percent": 99, "resets_at": reset}}
    }
    hook.QUOTA_SNAPSHOT.write_text(json.dumps(data))
    assert hook.reminder("muse", NOW) == ""


def test_quota_carried_from_another_session_is_not_this_accounts(paths: Path) -> None:
    claude(95, 99)
    status = json.loads(hook.CLAUDE_STATUS.read_text())
    status["_rate_limits_session_id"] = "before-login-switch"
    hook.CLAUDE_STATUS.write_text(json.dumps(status))
    assert hook.reminder("one", NOW) == ""
    status["_rate_limits_session_id"] = "one"
    hook.CLAUDE_STATUS.write_text(json.dumps(status))
    assert "Claude Code 5-hour quota: 95% used" in hook.reminder("one", NOW)


def test_reset_drift_within_a_window_is_announced_once(paths: Path) -> None:
    claude(91, reset=NOW + 4800 - 31)
    assert "91% used" in hook.reminder("one", NOW)
    claude(91, reset=NOW + 4800 + 29)
    assert hook.reminder("one", NOW) == ""
    claude(91, reset=NOW + 4800 + 3600)
    assert "91% used" in hook.reminder("one", NOW)


def service_snapshot(
    *,
    name: str = "Codex",
    status: str = "partial_outage",
    abnormal: Any = True,
    source: str = "fetched",
    age: float = 0,
) -> None:
    hook.SERVICE_SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    hook.SERVICE_SNAPSHOT.write_text(
        json.dumps(
            {
                "generated_at": datetime.fromtimestamp(NOW - age, UTC).isoformat(),
                "services": [
                    {
                        "service_name": name,
                        "is_abnormal": abnormal,
                        "status": status,
                        "description": "Elevated errors",
                        "source": source,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_service_incident_changes_and_recovers_once_per_session(paths: Path) -> None:
    service_snapshot()
    assert hook.reminder("one", NOW) == (
        "[usage service status] Codex API official status: partial_outage (Elevated errors). "
        "If a codex exec dispatch fails or hangs, suspect this incident first: "
        "don't retry repeatedly or debug the task brief; switch to another agent "
        "or tell the user. If you are not sending work to Codex, don't mention it."
    )
    assert hook.reminder("one", NOW + 1) == ""
    assert "Codex API official status: partial_outage" in hook.reminder("two", NOW + 1)
    service_snapshot(status="major_outage", source="cache")
    assert "official status: major_outage" in hook.reminder("one", NOW + 2)
    assert hook.reminder("one", NOW + 3) == ""
    service_snapshot(status="operational", abnormal=False)
    assert hook.reminder("one", NOW + 4) == (
        "[usage service status] Codex API official status is back to operational; "
        "the earlier incident notice no longer applies."
    )
    assert hook.reminder("one", NOW + 5) == ""
    records = json.loads(hook.STATE_PATH.read_text())["services"]
    assert json.dumps(["one", "Codex"]) not in records
    assert json.dumps(["two", "Codex"]) in records
    assert "back to operational" in hook.reminder("two", NOW + 5)


def test_suppressed_service_alert_is_not_called_recovered(paths: Path) -> None:
    service_snapshot(status="degraded_performance")
    assert "official status: degraded_performance" in hook.reminder("one", NOW)
    service_snapshot(status="degraded_performance", abnormal=False)
    assert hook.reminder("one", NOW + 1) == (
        "[usage service status] Codex API official status is still degraded_performance, "
        "but it looks like a long-running minor issue; treat the service as usable and the "
        "earlier incident notice as no longer applying."
    )
    assert hook.reminder("one", NOW + 2) == ""


@pytest.mark.parametrize("status", ["unknown", "under_maintenance"])
def test_unrecognized_service_status_neither_announces_nor_recovers(
    paths: Path, status: str
) -> None:
    service_snapshot()
    assert "official status: partial_outage" in hook.reminder("one", NOW)
    service_snapshot(status=status, abnormal=status != "unknown")
    assert hook.reminder("one", NOW + 1) == ""
    assert json.dumps(["one", "Codex"]) in json.loads(hook.STATE_PATH.read_text())["services"]


@pytest.mark.parametrize("name,label", [("Claude", "Claude Code / Claude API"), ("Other", "Other")])
def test_service_claude_and_unknown_wording(paths: Path, name: str, label: str) -> None:
    service_snapshot(name=name)
    assert hook.reminder("one", NOW) == (
        f"[usage service status] {label} official status: partial_outage (Elevated errors). "
        "Slow responses, API errors, or failed subagents in this session may come "
        "from this incident, not from the code; say so if it happens. "
        "Otherwise don't mention it."
    )
    service_snapshot(name=name, status="operational", abnormal=False)
    assert f"{label} official status is back to operational" in hook.reminder("one", NOW)


@pytest.mark.parametrize("source", ["stale", "fallback", "unknown"])
@pytest.mark.parametrize("abnormal", [True, False, "false", 0, 1, None])
def test_untrusted_service_does_not_announce_or_recover(
    paths: Path, source: str, abnormal: Any
) -> None:
    service_snapshot(source=source, abnormal=abnormal)
    assert hook.reminder("one", NOW) == ""
    service_snapshot()
    hook.reminder("one", NOW)
    previous = hook.STATE_PATH.read_text()
    service_snapshot(source=source, abnormal=abnormal)
    assert hook.reminder("one", NOW) == ""
    assert hook.STATE_PATH.read_text() == previous


@pytest.mark.parametrize("abnormal", ["true", "false", 0, 1, None])
def test_service_requires_boolean_abnormal(paths: Path, abnormal: Any) -> None:
    service_snapshot(abnormal=abnormal)
    assert hook.reminder("one", NOW) == ""
    assert not hook.STATE_PATH.exists()


@pytest.mark.parametrize("generated", [None, "invalid", "2026-01-01T00:00:00", "old"])
@pytest.mark.parametrize("abnormal", [True, False])
def test_invalid_or_expired_service_snapshot_does_not_recover(
    paths: Path, generated: Any, abnormal: bool
) -> None:
    service_snapshot()
    hook.reminder("one", NOW)
    previous = hook.STATE_PATH.read_text()
    service_snapshot(abnormal=abnormal, age=901)
    data = json.loads(hook.SERVICE_SNAPSHOT.read_text())
    if generated != "old":
        data["generated_at"] = generated
    hook.SERVICE_SNAPSHOT.write_text(json.dumps(data))
    assert hook.reminder("one", NOW) == ""
    assert hook.reminder("new-session", NOW) == ""
    assert hook.STATE_PATH.read_text() == previous


@pytest.mark.parametrize("payload", ["broken", "[]", '{"services": []}'])
def test_bad_service_snapshot_does_not_block_quota(paths: Path, payload: str) -> None:
    hook.SERVICE_SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    hook.SERVICE_SNAPSHOT.write_text(payload)
    claude(82)
    assert hook.reminder("one", NOW).startswith("[usage quota] Claude Code 5-hour quota:")


def test_service_snapshot_boundary_and_malformed_entries(paths: Path) -> None:
    service_snapshot(age=900)
    data = json.loads(hook.SERVICE_SNAPSHOT.read_text())
    data["services"] += [None, "broken", {}, {"source": "cache", "is_abnormal": True}]
    hook.SERVICE_SNAPSHOT.write_text(json.dumps(data))
    output = hook.reminder("one", NOW)
    assert output.startswith("[usage service status] Codex API official status:")
    assert "[usage quota]" not in output
    assert "Before starting a large task" not in output
    assert "Claude Code's own quota" not in output


def test_quota_only_unchanged_and_both_blocks_ordered(paths: Path) -> None:
    claude(82)
    quota = hook.reminder("quota-only", NOW)
    assert quota == (
        "[usage quota] Claude Code 5-hour quota: 82% used, resets in 1h 20m "
        "(at 09:20 local time). Only limits work run in Claude Code.\n"
        "Quotas for other tools or model groups do not limit this Claude Code session. "
        "Before starting a large task (many files, long runs, subagents) that will use one "
        "of these quotas, tell the user the remaining quota and reset time, and ask whether "
        "to do a smaller part now or wait for the reset. Otherwise, just proceed and don't "
        "mention quota.\nCurrent local time: Fri 08:00.\n"
        "Claude Code's own quota: 5-hour 82% used, resets in 1h 20m "
        "(at 09:20 local time); weekly 0% used, resets in 1h 20m "
        "(at 09:20 local time). This Claude Code session runs on this quota."
    )
    service_snapshot()
    both = hook.reminder("both", NOW)
    assert both.startswith(quota + "\n\n[usage service status] ")
    assert hook.reminder("both", NOW) == ""
    service_snapshot(status="major_outage")
    assert hook.reminder("both", NOW).startswith("[usage service status] ")
    state = json.loads(hook.STATE_PATH.read_text())
    assert state[json.dumps(["both", "Claude Code", "five_hour"])] == {
        "resets_at": RESET,
        "level": 80,
    }
    assert state["services"][json.dumps(["both", "Codex"])] == {
        "status": "major_outage",
        "at": NOW,
    }
    claude(91)
    assert hook.reminder("both", NOW).startswith("[usage quota] ")
    assert hook.reminder("both", NOW) == ""


def test_service_records_pruned_and_saved_without_notices(paths: Path) -> None:
    expired = json.dumps(["old", "Codex"])
    current = json.dumps(["other", "Claude"])
    quota_key = json.dumps(["one", "Claude Code", "five_hour"])
    quota_record = {"resets_at": RESET, "level": 80}
    hook.STATE_PATH.write_text(
        json.dumps(
            {
                quota_key: quota_record,
                "services": {
                    expired: {"status": "partial_outage", "at": NOW - 7 * 86400 - 1},
                    current: {"status": "major_outage", "at": NOW - 7 * 86400},
                    "bad": {"status": "partial_outage", "at": "invalid"},
                },
            }
        )
    )
    assert hook.reminder("one", NOW) == ""
    state = json.loads(hook.STATE_PATH.read_text())
    assert state[quota_key] == quota_record
    assert state["services"] == {current: {"status": "major_outage", "at": NOW - 7 * 86400}}
    assert not list(paths.glob("*.tmp"))


def test_service_normal_without_record_is_silent(paths: Path) -> None:
    service_snapshot(status="operational", abnormal=False)
    assert hook.reminder("one", NOW) == ""
    assert not hook.STATE_PATH.exists()


def test_service_hook_versions_match() -> None:
    assert hook.__version__ == session_hooks.QUOTA_AWARE_HOOK_VERSION == "1.7"

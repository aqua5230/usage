from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from adapters import rate_limits
from loaders import claude_desktop
from loaders import claude_usage as usage_client
from menubar import state as state_module
from quota import status_payload
from quota.burn_rate import BurnRateTracker
from tui import app as tui
from usage_common.i18n import _t

NOW = 2_000_000_000.0


@pytest.fixture
def quota_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    for attr in ("STATUS_FILE", "LEGACY_STATUS_FILE", "TT_STATUS_FILE"):
        monkeypatch.setattr(usage_client, attr, str(tmp_path / attr))
    monkeypatch.setattr(usage_client, "_claude_json_file", lambda: str(tmp_path / "cli.json"))
    monkeypatch.setattr("loaders.claude_usage.time.time", lambda: NOW)
    monkeypatch.setenv("USAGE_LANG", "en")
    path = tmp_path / claude_desktop.HISTORY_NAME
    monkeypatch.setattr(claude_desktop, "desktop_history_paths", lambda: (path,))
    path.write_text(
        json.dumps(
            {"version": 1, "samples": [{"t": NOW * 1000, "org": "a", "u": {"fh": 11, "sd": 0}}]}
        ),
        encoding="utf-8",
    )
    return path


def test_desktop_only_client_returns_quota_without_reset_time(quota_file: Path) -> None:
    result = asyncio.run(usage_client.ClaudeUsageClient().fetch_once())
    assert result.state == usage_client.PollState.SUCCESS
    assert result.snapshot is not None
    assert result.snapshot.current_percent == 11
    assert result.snapshot.weekly_percent == 0
    assert result.snapshot.current_reset_at is None
    assert result.snapshot.weekly_reset_at is None
    assert result.snapshot.data_source == "claude-desktop"
    assert result.message == _t("en", "claude_desktop_updated", minutes=0)
    assert tui.format_countdown(None, "en", NOW) == _t("en", "resets_in_placeholder")


def test_hook_retains_priority_and_reset_times(quota_file: Path) -> None:
    Path(usage_client.STATUS_FILE).write_text(
        json.dumps(
            {
                "rate_limits": {
                    "five_hour": {"used_percentage": 22, "resets_at": NOW + 100},
                    "seven_day": {"used_percentage": 33, "resets_at": NOW + 200},
                }
            }
        ),
        encoding="utf-8",
    )
    result = asyncio.run(usage_client.ClaudeUsageClient().fetch_once())
    assert result.snapshot is not None
    assert result.snapshot.data_source == "hook"
    assert result.snapshot.current_percent == 22
    assert result.snapshot.current_reset_at == NOW + 100


def test_incomplete_hook_uses_desktop_quota(quota_file: Path) -> None:
    Path(usage_client.STATUS_FILE).write_text('{"rate_limits":{}}', encoding="utf-8")
    result = asyncio.run(usage_client.ClaudeUsageClient().fetch_once())
    assert result.snapshot is not None
    assert result.snapshot.current_percent == 11


@pytest.mark.parametrize("language", ["en", "zh-TW", "zh-CN", "ja", "ko"])
def test_local_cached_resets_reach_client_panel_tui_and_cli(
    quota_file: Path, monkeypatch: pytest.MonkeyPatch, language: str
) -> None:
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from tests.test_chromium_cache import Response, _cache

    _cache(
        quota_file.parent / "Cache/Cache_Data",
        Response(
            url=b"https://claude.ai/api/organizations/a/usage",
            payload={
                "five_hour": {
                    "utilization": 11,
                    "resets_at": datetime.fromtimestamp(NOW + 100, UTC).isoformat(),
                },
                "seven_day": {
                    "utilization": 0,
                    "resets_at": datetime.fromtimestamp(NOW + 200, UTC).isoformat(),
                },
            },
        ),
    )
    result = asyncio.run(usage_client.ClaudeUsageClient().fetch_once())
    snapshot = result.snapshot
    assert snapshot is not None and snapshot.data_source == "claude-desktop"
    assert snapshot.current_reset_at == NOW + 100
    assert snapshot.weekly_reset_at == NOW + 200
    row = state_module._quota_row(
        "Session", 11, snapshot.current_reset_at, NOW, state_module.CLAUDE_COLOR, language
    )
    assert row.available and row.percent == 11
    assert row.reset_text != _t(language, "reset_placeholder")
    assert tui.format_countdown(snapshot.current_reset_at, language, NOW) != _t(
        language, "resets_in_placeholder"
    )
    monkeypatch.setattr(
        rate_limits,
        "datetime",
        SimpleNamespace(
            now=lambda _: datetime.fromtimestamp(NOW, UTC), fromtimestamp=datetime.fromtimestamp
        ),
    )
    quota = rate_limits.load_rate_limits()
    assert quota is not None
    payload = status_payload._status_agent(quota, int(NOW))
    assert payload["five_hour"]["resets_in_seconds"] == 100
    assert payload["seven_day"]["resets_in_seconds"] == 200


def test_claude_code_cache_retains_priority(quota_file: Path) -> None:
    Path(usage_client._claude_json_file()).write_text(
        json.dumps(
            {
                "cachedUsageUtilization": {
                    "fetchedAtMs": (NOW - 10) * 1000,
                    "utilization": {
                        "five_hour": {"utilization": 22, "resets_at": "2040-01-01T00:00:00+00:00"}
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    result = asyncio.run(usage_client.ClaudeUsageClient().fetch_once())
    assert result.snapshot is not None
    assert result.snapshot.data_source == "claude-json"
    assert result.snapshot.current_percent == 22


def test_desktop_quota_reaches_popover_and_tui(quota_file: Path) -> None:
    result = asyncio.run(usage_client.ClaudeUsageClient().fetch_once())
    missing = state_module._missing_row("Session", state_module.CODEX_COLOR)
    state = state_module.build_popover_state(
        outcome=result,
        codex_rows=(missing, missing),
        agy_rows=(missing, missing),
        agy_group_name="",
        grok_row=missing,
        projects=[],
        projects_yesterday=[],
        projects_7d=[],
        projects_30d=[],
        projects_all=[],
        language="en",
        group=0,
        burn_rate_trackers={
            name: BurnRateTracker() for name in ("claude_session", "claude_weekly")
        },
        today_text="",
        yesterday_text="",
        statusline={},
        show_install_button=False,
        hide_claude=False,
        hide_codex=False,
        hide_agy=True,
        hide_grok=True,
        codex_stale=None,
        agy_stale=None,
        grok_stale=None,
    )
    assert state.claude_session.display_percent == 11
    assert state.claude_weekly.display_percent == 0
    assert state.claude_session.reset_text == _t("en", "reset_placeholder")
    assert result.message is not None and result.message in state.status_text
    assert tui.render_screen(tui.AppViewState(language="en", snapshot=result.snapshot), 0)


def test_desktop_quota_reaches_status_json(
    quota_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for attr in ("STATUS_FILE", "LEGACY_STATUS_FILE", "TT_STATUS_FILE"):
        monkeypatch.setattr(rate_limits, attr, str(quota_file.parent / attr))
    quota = rate_limits.load_rate_limits()
    assert quota is not None
    payload = status_payload._status_agent(quota, int(NOW))
    assert payload["available"]
    assert payload["five_hour"]["used_percent"] == 11
    assert payload["five_hour"]["resets_at"] is None
    assert payload["five_hour"]["resets_in_seconds"] is None


def test_desktop_age_is_recomputed_without_file_change(
    quota_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = usage_client.ClaudeUsageClient()
    monkeypatch.setattr("loaders.claude_usage.time.time", lambda: NOW + 31 * 60)
    result = asyncio.run(client.fetch_once())
    assert result.snapshot is not None and result.snapshot.is_stale
    assert result.message == _t("en", "claude_desktop_stale", minutes=31)
    monkeypatch.setattr(
        "loaders.claude_usage.time.time", lambda: NOW + claude_desktop.MAX_AGE_SECONDS + 1
    )
    result = asyncio.run(client.fetch_once())
    assert result.snapshot is None


@pytest.mark.parametrize("language", ["en", "zh-TW", "zh-CN", "ja", "ko"])
def test_unknown_reset_keeps_valid_percentage_and_tray_label(language: str) -> None:
    row = state_module._quota_row(
        "Session",
        11,
        None,
        NOW,
        state_module.CLAUDE_COLOR,
        language,
        allow_unknown_reset=True,
    )
    assert row.available
    assert row.display_percent == 11
    assert row.percent_text == _t(language, "percent_used", value="11")
    assert row.reset_text == _t(language, "reset_placeholder")
    assert not row.reset_done and not row.warning
    # Existing sources still need reset timestamps; do not alter Codex's behavior.
    assert not state_module._quota_row("Session", 11, None, NOW, state_module.CODEX_COLOR).available

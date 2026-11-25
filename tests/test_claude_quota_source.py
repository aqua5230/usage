# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from adapters import rate_limits
from loaders import claude_desktop, claude_usage
from menubar import state
from quota.burn_rate import BurnRateTracker
from quota.notifications import QuotaNotifier
from tests.test_chromium_cache import Response, _simple_cache
from usage_common.i18n import _t

NOW = 2_000_000_000.0
FIVE_RESET = NOW + 4 * 3600
WEEKLY_RESET = NOW + 3 * 86_400


@pytest.fixture
def sources(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    for module in (claude_usage, rate_limits):
        for name in ("STATUS_FILE", "LEGACY_STATUS_FILE", "TT_STATUS_FILE"):
            monkeypatch.setattr(module, name, str(tmp_path / name))
    monkeypatch.setattr(claude_usage, "_claude_json_file", lambda: str(tmp_path / ".claude.json"))
    monkeypatch.setattr(claude_usage, "_claude_projects_dirs", lambda: [tmp_path / "projects"])
    monkeypatch.setattr(claude_usage, "_recent_activity_cache", None)
    monkeypatch.setattr(claude_usage, "current_hook_state", lambda: "us-direct")
    monkeypatch.setattr("loaders.claude_usage.time.time", lambda: NOW)
    monkeypatch.setenv("USAGE_LANG", "en")
    return tmp_path


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def _iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, UTC).isoformat()


def _write_hook(
    sources: Path,
    *,
    age: float = 20 * 60,
    received_at: float | None = None,
    legacy: bool = False,
    account: str | None = "A",
    include_account: bool = True,
    weekly_only: bool = False,
    five_reset: float = FIVE_RESET,
    weekly_reset: float | None = WEEKLY_RESET,
    percent: float = 12.25,
) -> None:
    observed_at = NOW - age
    windows = {"seven_day": {"used_percentage": percent, "resets_at": weekly_reset}}
    if not weekly_only:
        windows["five_hour"] = {"used_percentage": percent, "resets_at": five_reset}
    received_at = observed_at if received_at is None else received_at
    data: dict[str, Any] = {
        "rate_limits": windows,
        "_received_at_ts": received_at,
        "_received_at": _iso(received_at),
        "model": {"display_name": "Claude Test"},
    }
    if not legacy:
        data["_rate_limits_observed_at"] = dict.fromkeys(windows, observed_at)
    if include_account:
        data["_rate_limits_account_uuid"] = account
    _write_json(sources / "STATUS_FILE", data)


def _write_cache(
    sources: Path,
    *,
    age: float | None = 2 * 60,
    account: str | None = "A",
    tagged: bool = True,
    weekly_only: bool = False,
    five_reset: float = FIVE_RESET,
    weekly_reset: float = WEEKLY_RESET,
    org: str | None = None,
) -> None:
    data: dict[str, Any] = {}
    if account is not None:
        data["oauthAccount"] = {"accountUuid": account}
        if org is not None:
            data["oauthAccount"]["organizationUuid"] = org
    if age is not None:
        windows = {"seven_day": {"utilization": 33, "resets_at": _iso(weekly_reset)}}
        if not weekly_only:
            windows["five_hour"] = {"utilization": 22, "resets_at": _iso(five_reset)}
        data["cachedUsageUtilization"] = {
            "fetchedAtMs": (NOW - age) * 1000,
            "utilization": windows,
        }
        if tagged:
            data["cachedUsageUtilization"]["accountUuid"] = account
    _write_json(sources / ".claude.json", data)


def _poll(client: claude_usage.ClaudeUsageClient | None = None) -> claude_usage.PollOutcome:
    return asyncio.run((client or claude_usage.ClaudeUsageClient()).fetch_once())


def _snapshot(source: str) -> claude_usage.UsageSnapshot:
    outcome = _poll()
    assert outcome.state is claude_usage.PollState.SUCCESS
    assert outcome.snapshot is not None
    assert outcome.snapshot.data_source == source
    return outcome.snapshot


@pytest.mark.parametrize("ahead", [1, 10 * 60])
def test_active_hook_wins_despite_newer_cache(sources: Path, ahead: int) -> None:
    _write_hook(sources, age=60)
    _write_cache(sources, age=60 - ahead)
    assert _snapshot("hook").polled_at == NOW - 60


def test_idle_hook_switches_to_newer_same_account_cache(sources: Path) -> None:
    _write_hook(sources)
    _write_cache(sources)
    snapshot = _snapshot("claude-json")
    assert (snapshot.current_percent, snapshot.weekly_percent, snapshot.account_uuid) == (
        22,
        33,
        "A",
    )


def test_hook_repaint_does_not_refresh_quota_observation(sources: Path) -> None:
    _write_hook(sources, received_at=NOW)
    _write_cache(sources)
    assert _snapshot("claude-json").polled_at == NOW - 120


@pytest.mark.parametrize(("age", "source"), [(20 * 60, "claude-json"), (60, "hook")])
def test_legacy_hook_uses_receive_time(sources: Path, age: int, source: str) -> None:
    _write_hook(sources, age=age, legacy=True)
    _write_cache(sources, age=59)
    _snapshot(source)


def test_idle_hook_keeps_quota_when_cache_is_older(sources: Path) -> None:
    _write_hook(sources, age=40 * 60)
    _write_cache(sources, age=50 * 60)
    assert _snapshot("hook").polled_at == NOW - 40 * 60


@pytest.mark.parametrize("legacy_without_timestamp", [False, True])
def test_cache_reports_a_new_window_after_the_hook_reset(
    sources: Path, legacy_without_timestamp: bool
) -> None:
    _write_hook(
        sources,
        age=180,
        five_reset=NOW - 120,
        legacy=legacy_without_timestamp,
        received_at=0 if legacy_without_timestamp else None,
    )
    _write_cache(sources, age=60, five_reset=NOW + 5 * 3600)
    snapshot = _snapshot("claude-json")
    assert snapshot.current_percent == 22
    assert snapshot.current_reset_at == NOW + 5 * 3600


def test_cache_cannot_move_a_reset_back_a_window(sources: Path) -> None:
    _write_hook(sources, age=22 * 60)
    _write_cache(sources, five_reset=FIVE_RESET - 5 * 3600)
    assert _snapshot("hook").current_reset_at == FIVE_RESET


@pytest.mark.parametrize("weekly_only", [False, True])
def test_cache_must_cover_all_hook_windows(sources: Path, weekly_only: bool) -> None:
    _write_hook(sources, weekly_only=weekly_only)
    _write_cache(sources, weekly_only=True)
    snapshot = _snapshot("claude-json" if weekly_only else "hook")
    assert snapshot.current_percent == (None if weekly_only else 12)


def test_cache_with_future_fetch_time_cannot_replace_hook(sources: Path) -> None:
    _write_hook(sources)
    _write_cache(sources, age=-3600)
    _snapshot("hook")


def test_account_change_uses_cache_even_with_fresh_hook(sources: Path) -> None:
    _write_hook(sources, age=60)
    _write_cache(sources, age=59, account="B")
    snapshot = _snapshot("claude-json")
    assert snapshot.account_uuid == "B"
    assert snapshot.current_percent == 22


def test_account_change_without_cache_awaits_new_quota(
    sources: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_hook(sources, age=60)
    _write_cache(sources, account="B", age=None)
    desktop = sources / claude_desktop.HISTORY_NAME
    _write_json(
        desktop,
        {"version": 2, "samples": [{"t": NOW * 1000, "org": "desktop", "u": {"fh": 54}}]},
    )
    monkeypatch.setattr(claude_desktop, "desktop_history_paths", lambda: (desktop,))
    assert claude_desktop.load_desktop_quota(NOW) is not None
    monkeypatch.setattr(
        claude_desktop, "load_desktop_quota", lambda _: pytest.fail("Desktop must not be read")
    )
    client = claude_usage.ClaudeUsageClient()
    for _ in range(2):
        outcome = _poll(client)
        assert outcome.state is claude_usage.PollState.LOADING
        assert outcome.message == "awaiting_rate_limits"
        assert outcome.snapshot is None


@pytest.mark.parametrize(
    ("hook_account", "include_account", "current_account"),
    [(None, True, "B"), (None, False, "B"), ("A", True, None)],
)
def test_unknown_account_keeps_fresh_hook(
    sources: Path, hook_account: str | None, include_account: bool, current_account: str | None
) -> None:
    _write_hook(sources, age=60, account=hook_account, include_account=include_account)
    _write_cache(sources, age=59, account=current_account)
    assert _snapshot("hook").account_uuid == (hook_account or current_account)


@pytest.mark.parametrize(
    ("hook_state", "age", "active", "key"),
    [
        ("us-direct", 40 * 60, True, "claude_json_updated"),
        ("us-forwarder", 7 * 3600, True, "claude_json_stale"),
        ("none", 40 * 60, True, claude_usage.HOOK_BROKEN_NOT_INSTALLED),
        ("none", 40 * 60, False, "claude_json_updated"),
    ],
)
def test_cache_message_reflects_age_and_hook_installation(
    sources: Path,
    monkeypatch: pytest.MonkeyPatch,
    hook_state: str,
    age: int,
    active: bool,
    key: str,
) -> None:
    _write_hook(sources, age=age + 20 * 60)
    _write_cache(sources, age=age)
    monkeypatch.setattr(claude_usage, "current_hook_state", lambda: hook_state)
    if active:
        path = sources / "projects" / "demo" / "session.jsonl"
        path.parent.mkdir(parents=True)
        path.write_text("{}\n", encoding="utf-8")
        os.utime(path, (NOW - 60, NOW - 60))
    if hook_state != "none":
        monkeypatch.setattr(
            claude_usage, "_hook_broken_message", lambda *_: pytest.fail("hook diagnosis ran")
        )

    outcome = _poll()
    assert outcome.snapshot is not None and outcome.snapshot.data_source == "claude-json"
    expected_text = _t("en", key, minutes=age // 60)
    assert outcome.message == (
        key if key == claude_usage.HOOK_BROKEN_NOT_INSTALLED else expected_text
    )
    assert state._status_message_value(outcome, "data_stale_hint", "en") == expected_text


def test_lunch_break_does_not_mark_hook_stale(sources: Path) -> None:
    _write_hook(sources, age=40 * 60)
    outcome = _poll()
    assert outcome.snapshot is not None and outcome.snapshot.data_source == "hook"
    assert outcome.snapshot.is_stale is False
    assert outcome.message is None


@pytest.mark.parametrize(
    ("hook_age", "cache_account", "cache_age", "source"),
    [
        (20 * 60, "A", 120, "claude-json"),
        (60, "B", 59, "claude-json"),
        (60, "B", None, None),
        (60, "A", 59, "hook"),
    ],
)
def test_cli_and_app_agree_on_quota_source(
    sources: Path,
    monkeypatch: pytest.MonkeyPatch,
    hook_age: int,
    cache_account: str,
    cache_age: int | None,
    source: str | None,
) -> None:
    _write_hook(sources, age=hook_age)
    _write_cache(sources, account=cache_account, age=cache_age)
    monkeypatch.setattr(
        claude_desktop, "load_desktop_quota", lambda _: pytest.fail("Desktop must not be read")
    )
    outcome = _poll()
    cli = rate_limits.load_rate_limits()
    if source is None:
        assert outcome.state is claude_usage.PollState.LOADING
        assert cli is None
        return

    assert outcome.snapshot is not None and outcome.snapshot.data_source == source
    assert cli is not None
    assert (cli.five_hour_resets_at, cli.seven_day_resets_at) == (FIVE_RESET, WEEKLY_RESET)
    if source == "hook":
        assert (cli.five_hour_pct, cli.seven_day_pct) == (12.25, 12.25)
        assert cli.model == "Claude Test"
        assert cli.updated_at == _iso(NOW - hook_age)
    else:
        assert (cli.five_hour_pct, cli.seven_day_pct) == (
            outcome.snapshot.current_percent,
            outcome.snapshot.weekly_percent,
        )
        assert cli.model == ""
        assert cli.updated_at == _iso(outcome.snapshot.polled_at)


@pytest.mark.parametrize(
    ("accounts", "restored"), [(("A", "B"), False), (("A", "A"), True), ((None, None), True)]
)
def test_quota_notifications_track_each_claude_account(
    sources: Path, accounts: tuple[str | None, str | None], restored: bool
) -> None:
    pytest.importorskip("objc")
    from menubar import notify

    notifier = QuotaNotifier()
    missing = state._missing_row("Session", state.CODEX_COLOR)

    def observe(account: str | None, percent: float) -> list[tuple[str, str]]:
        _write_hook(sources, account=account, percent=percent)
        panel = state.build_popover_state(
            outcome=_poll(),
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
            today_total=state.PeriodTotal(),
            yesterday_total=state.PeriodTotal(),
            show_install_button=False,
            hide_claude=False,
            hide_codex=False,
            hide_agy=True,
            hide_grok=True,
            codex_stale=None,
            agy_stale=None,
            grok_stale=None,
        )
        assert panel.claude_account == (account or "")
        return [
            (event.kind, event.channel)
            for event in notifier.update(
                notify.notification_channels(panel), notify.notification_scopes(panel)
            )
        ]

    channels = ("claude_session", "claude_weekly")
    assert observe(accounts[0], 100) == [("depleted", channel) for channel in channels]
    assert observe(accounts[1], 20) == (
        [("restored", channel) for channel in channels] if restored else []
    )


def test_time_adjusted_preserves_account_uuid(sources: Path) -> None:
    _write_cache(sources, account="A", tagged=False)
    snapshot = claude_usage._read_claude_json_snapshot()
    assert snapshot is not None and snapshot.account_uuid == "A"
    assert claude_usage._time_adjusted(snapshot).account_uuid == "A"


@pytest.mark.parametrize(
    ("observed", "received", "expected"),
    [
        ({"five_hour": NOW - 30, "seven_day": NOW - 90}, NOW, NOW - 30),
        ({"five_hour": NOW - 90, "seven_day": NOW + 60}, NOW, NOW + 60),
        ({"five_hour": NOW + 61, "seven_day": NOW - 60}, NOW, NOW - 60),
        (NOW - 30, NOW, NOW - 30),
        ({"five_hour": float("nan"), "seven_day": -1}, NOW, NOW),
        ({"five_hour": True, "seven_day": float("inf")}, 0, None),
        (NOW + 61, NOW + 61, None),
        (str(NOW), -1, None),
    ],
)
def test_hook_observed_at_validates_legacy_and_per_window_times(
    observed: object, received: object, expected: float | None
) -> None:
    data = {"_rate_limits_observed_at": observed, "_received_at_ts": received}
    assert claude_usage._hook_observed_at(data, NOW) == expected


def test_unknown_weekly_reset_does_not_block_newer_cache(sources: Path) -> None:
    _write_hook(sources, weekly_reset=None)
    _write_cache(sources, weekly_reset=NOW - 120)
    assert _snapshot("claude-json").weekly_reset_at == NOW - 120


def _desktop(
    monkeypatch: pytest.MonkeyPatch, *, age: float = 60, org: str | None = "org-a"
) -> None:
    quota = claude_desktop.DesktopQuota(55, 8, NOW - age, FIVE_RESET, WEEKLY_RESET, org=org)
    monkeypatch.setattr(claude_desktop, "load_desktop_quota", lambda _now, _org: quota)


def test_idle_hook_switches_to_newer_same_org_desktop_quota(
    sources: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Quota used in the desktop app after the last terminal reply never reaches the hook.
    _write_hook(sources, age=10 * 60)
    _write_cache(sources, age=None, org="org-a")
    _desktop(monkeypatch)
    snapshot = _snapshot("claude-desktop")
    assert (snapshot.current_percent, snapshot.weekly_percent, snapshot.account_uuid) == (
        55,
        8,
        "A",
    )
    assert (snapshot.current_reset_at, snapshot.weekly_reset_at) == (FIVE_RESET, WEEKLY_RESET)
    cli = rate_limits.load_rate_limits()
    assert cli is not None and (cli.five_hour_pct, cli.seven_day_pct) == (55, 8)


@pytest.mark.parametrize(
    ("desktop_age", "desktop_org", "signed_in_org"),
    [
        (10 * 60, "org-a", "org-a"),
        (11 * 60, "org-a", "org-a"),
        (60, "org-b", "org-a"),
        (60, "org-a", None),
        (60, None, "org-a"),
    ],
)
def test_hook_keeps_quota_unless_desktop_is_newer_for_the_same_org(
    sources: Path,
    monkeypatch: pytest.MonkeyPatch,
    desktop_age: int,
    desktop_org: str | None,
    signed_in_org: str | None,
) -> None:
    _write_hook(sources, age=10 * 60)
    _write_cache(sources, age=None, org=signed_in_org)
    _desktop(monkeypatch, age=desktop_age, org=desktop_org)
    assert _snapshot("hook").current_percent == 12
    cli = rate_limits.load_rate_limits()
    assert cli is not None and cli.five_hour_pct == 12.25


def test_recent_hook_skips_desktop_scan(sources: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_hook(sources, age=60)
    _write_cache(sources, age=None, org="org-a")
    monkeypatch.setattr(
        claude_desktop, "load_desktop_quota", lambda _: pytest.fail("Desktop must not be read")
    )
    assert _snapshot("hook").polled_at == NOW - 60
    assert rate_limits.load_rate_limits() is not None


@pytest.mark.parametrize(
    ("cached_age", "desktop_age", "source", "percent"),
    [
        (None, 580, "claude-desktop", 55),
        (270, 60, "claude-desktop", 55),
        (60, 270, "claude-json", 22),
        (60, 60, "claude-json", 22),
    ],
)
def test_newest_eligible_quota_wins_in_app_and_cli(
    sources: Path,
    monkeypatch: pytest.MonkeyPatch,
    cached_age: float | None,
    desktop_age: float,
    source: str,
    percent: int,
) -> None:
    _write_hook(sources, age=600 if cached_age is None else 1200)
    _write_cache(sources, age=cached_age, org="org-a")
    _desktop(monkeypatch, age=desktop_age)
    assert _snapshot(source).current_percent == percent
    cli = rate_limits.load_rate_limits()
    assert cli is not None and cli.five_hour_pct == percent


def test_polls_reuse_claude_json_and_skip_unknown_or_mismatched_orgs(
    sources: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_hook(sources)
    _write_cache(sources, age=None)
    history = sources / claude_desktop.HISTORY_NAME
    _write_json(
        history,
        {"version": 2, "samples": [{"org": "org-b", "t": NOW * 1000, "u": {"fh": 91}}]},
    )
    discoveries = []
    reads = []
    read_config = claude_usage._read_claude_json

    def read() -> claude_usage._ClaudeJson:
        reads.append(True)
        return read_config()

    def paths() -> tuple[Path, ...]:
        discoveries.append(True)
        return (history,)

    def forbidden(*args: object) -> None:
        pytest.fail("must not scan HTTP cache for an unknown or mismatched organization")

    monkeypatch.setattr(claude_usage, "_read_claude_json", read)
    monkeypatch.setattr(claude_desktop, "desktop_history_paths", paths)
    monkeypatch.setattr(claude_desktop, "load_cached_json", forbidden)
    client = claude_usage.ClaudeUsageClient()
    for _ in range(2):
        outcome = _poll(client)
        assert outcome.snapshot is not None and outcome.snapshot.data_source == "hook"
    assert reads == [True]
    assert discoveries == []

    _write_cache(sources, age=None, org="org-a")
    config_path = sources / ".claude.json"
    os.utime(config_path, (NOW, NOW))
    for _ in range(2):
        outcome = _poll(client)
        assert outcome.snapshot is not None and outcome.snapshot.data_source == "hook"
    assert reads == [True, True]
    assert discoveries == [True, True]
    cli = rate_limits.load_rate_limits()
    assert cli is not None and cli.five_hour_pct == 12.25


def test_two_desktop_profiles_only_compare_the_signed_in_org(
    sources: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_hook(sources)
    _write_cache(sources, age=None, org="org-a")
    histories = []
    for org, age, percent in (("org-a", 80, 55), ("org-b", 20, 91)):
        profile = sources / org
        profile.mkdir()
        history = profile / claude_desktop.HISTORY_NAME
        _write_json(
            history,
            {
                "version": 2,
                "samples": [{"org": org, "t": (NOW - age) * 1000, "u": {"fh": percent}}],
            },
        )
        histories.append(history)
    monkeypatch.setattr(claude_desktop, "desktop_history_paths", lambda: tuple(histories))
    assert _snapshot("claude-desktop").current_percent == 55
    cli = rate_limits.load_rate_limits()
    assert cli is not None and cli.five_hour_pct == 55


@pytest.mark.parametrize("org", ["org-a", "org-b", None])
def test_cache_without_history_requires_matching_code_org(
    sources: Path, monkeypatch: pytest.MonkeyPatch, org: str | None
) -> None:
    _write_cache(sources, age=None, org=org)
    monkeypatch.setattr(
        claude_desktop, "desktop_history_paths", lambda: (sources / claude_desktop.HISTORY_NAME,)
    )
    _simple_cache(
        sources / "Cache" / "Cache_Data",
        Response(url=b"https://claude.ai/api/organizations/org-a/usage?via=plan"),
        Response(url=b"https://claude.ai/api/organizations/org-c/usage?via=plan"),
    )
    gui = _poll().snapshot
    cli = rate_limits.load_rate_limits()
    if org == "org-a":
        assert gui is not None and gui.current_percent == 14 and gui.weekly_percent == 1
        assert cli is not None and cli.five_hour_pct == 14 and cli.seven_day_pct == 1
    else:
        assert gui is None and cli is None

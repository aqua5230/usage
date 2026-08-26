# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from loaders.grok_quota_probe import GrokQuotaResult
from menubar import grok as menubar_grok
from menubar import state as menubar_state
from usage_client import PollOutcome, PollState


def _quota() -> GrokQuotaResult:
    return GrokQuotaResult(
        used_percent=18.0,
        period_end="2026-09-01T15:50:08+00:00",
        fetched_at="2026-08-26T09:13:58+00:00",
        subscription_tier="SuperGrok Lite",
    )


def test_project_quota_builds_one_weekly_row() -> None:
    now = datetime(2026, 8, 26, 12, tzinfo=UTC).timestamp()

    projection = menubar_grok.project_quota(_quota(), "en", now=now)

    assert projection is not None
    assert projection.weekly.title == "Weekly"
    assert projection.weekly.percent == 18.0
    assert projection.weekly.percent_text == "18% used"


def test_load_refresh_result_hides_card_when_grok_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(menubar_grok, "find_grok", lambda: None)
    monkeypatch.setattr(
        menubar_grok,
        "load_quota",
        lambda: pytest.fail("load_quota must not run without Grok CLI data"),
    )

    result = menubar_grok.load_refresh_result("en")

    assert result.hide_grok is True
    assert result.projection is None


def test_build_popover_state_includes_grok_row_and_visibility() -> None:
    projection = menubar_grok.project_quota(
        _quota(), "en", now=datetime(2026, 8, 26, 12, tzinfo=UTC).timestamp()
    )
    assert projection is not None
    missing = menubar_state._missing_row

    state = menubar_state.build_popover_state(
        outcome=PollOutcome(PollState.LOADING),
        codex_rows=(
            missing("Session", menubar_state.CODEX_COLOR),
            missing("Weekly", menubar_state.CODEX_COLOR),
        ),
        agy_rows=(
            missing("Session", menubar_state.AGY_COLOR),
            missing("Weekly", menubar_state.AGY_COLOR),
        ),
        agy_group_name="",
        grok_row=projection.weekly,
        projects=[],
        projects_yesterday=[],
        projects_7d=[],
        projects_30d=[],
        projects_all=[],
        language="en",
        group=0,
        burn_rate_trackers={},
        today_text="",
        yesterday_text="",
        statusline={},
        show_install_button=False,
        hide_claude=True,
        hide_codex=True,
        hide_agy=True,
        hide_grok=False,
        codex_stale=None,
        agy_stale=None,
        grok_stale=projection.stale,
    )

    assert state.hide_grok is False
    assert state.grok_weekly.percent == 18.0
    assert state.card_order == ("claude", "codex", "agy", "grok")

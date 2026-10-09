from __future__ import annotations

import json
from pathlib import Path

import pytest

from loaders import claude_desktop as desktop
from tests.test_chromium_cache import NOW, Response, _cache


def _history(path: Path, age: float, org: str = "org-a") -> None:
    path.write_text(
        json.dumps(
            {
                "version": 2,
                "samples": [{"t": (NOW - age) * 1000, "org": org, "u": {"fh": 0, "sd": 11}}],
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.parametrize("age", [desktop.MAX_AGE_SECONDS + 1, 6 * 3600, 3 * 86400])
def test_fresh_http_quota_survives_expired_history(tmp_path: Path, age: float) -> None:
    path = tmp_path / desktop.HISTORY_NAME
    _history(path, age)
    _cache(tmp_path / "Cache/Cache_Data", Response(fetched=NOW - 30))
    quota = desktop._read_history(path, NOW)
    assert quota is not None
    assert (quota.current_percent, quota.weekly_percent) == (14, 1)
    assert quota.polled_at == NOW - 30
    assert quota.current_reset_at == NOW + 100
    assert quota.weekly_reset_at == NOW + 200


@pytest.mark.parametrize(
    "response",
    [
        Response(fetched=NOW - desktop.MAX_AGE_SECONDS - 1),
        Response(url=b"https://claude.ai/api/organizations/other/usage"),
        Response(payload={"five_hour": {"utilization": "invalid"}}),
        Response(active=False),
    ],
)
def test_unusable_http_response_cannot_revive_expired_history(
    tmp_path: Path, response: Response
) -> None:
    path = tmp_path / desktop.HISTORY_NAME
    _history(path, 6 * 3600)
    _cache(tmp_path / "Cache/Cache_Data", response)
    assert desktop._read_history(path, NOW) is None


def test_fresh_http_quota_eventually_expires(tmp_path: Path) -> None:
    path = tmp_path / desktop.HISTORY_NAME
    _history(path, 6 * 3600)
    _cache(tmp_path / "Cache/Cache_Data", Response())
    assert desktop._read_history(path, NOW) is not None
    assert desktop._read_history(path, NOW + desktop.MAX_AGE_SECONDS + 1) is None


def test_future_history_is_not_an_account_anchor(tmp_path: Path) -> None:
    path = tmp_path / desktop.HISTORY_NAME
    _history(path, -61)
    _cache(tmp_path / "Cache/Cache_Data", Response())
    assert desktop._read_history(path, NOW) is None


@pytest.mark.parametrize("org", ["", None, 123, "missing", "\ud800"])
def test_invalid_latest_org_cannot_use_fresh_previous_account_cache(
    tmp_path: Path, org: object
) -> None:
    path = tmp_path / desktop.HISTORY_NAME
    _history(path, 7 * 3600)
    history = json.loads(path.read_text(encoding="utf-8"))
    latest = {"t": (NOW - 6 * 3600) * 1000, "org": org, "u": {"fh": 0, "sd": 11}}
    if org == "missing":
        del latest["org"]
    history["samples"].append(latest)
    path.write_text(json.dumps(history), encoding="utf-8")
    _cache(tmp_path / "Cache/Cache_Data", Response())
    assert desktop._read_history(path, NOW) is None


def test_partial_fresh_response_does_not_fill_from_expired_history(tmp_path: Path) -> None:
    path = tmp_path / desktop.HISTORY_NAME
    _history(path, 6 * 3600)
    _cache(
        tmp_path / "Cache/Cache_Data",
        Response(payload={"five_hour": {"utilization": 14}}),
    )
    quota = desktop._read_history(path, NOW)
    assert quota == desktop.DesktopQuota(14, None, NOW)

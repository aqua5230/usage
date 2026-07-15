# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>

from __future__ import annotations

import json
import os
import platform
import shutil
import sys
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request

import pytest

import agy_quota_probe
from agy_quota_probe import (
    AgyQuotaGroup,
    AgyQuotaResult,
    AgyQuotaWindow,
)
from agy_quota_probe import (
    find_agy as find_agy,
)

_TOKEN_URL = agy_quota_probe._TOKEN_URL
_QUOTA_URL = agy_quota_probe._QUOTA_URL

# A reset time comfortably in the future so minute rounding never flips the sign
# during a test run; we only assert structure, not the exact countdown.
_FUTURE_RESET = (datetime.now(UTC) + timedelta(days=7)).isoformat()


class _FakeResponse:
    """Minimal file-like object that json.load can read inside a with-block."""

    def __init__(self, payload: object) -> None:
        self._data = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def read(self) -> bytes:
        return self._data


def _build_urlopen(
    routing: dict[str, object],
) -> tuple[Callable[..., _FakeResponse], list[tuple[str, str | None]]]:
    """Return a fake urlopen plus a log of (url, Authorization) per call."""
    visited: list[tuple[str, str | None]] = []

    def fake(request: Request, timeout: float = 0.0) -> _FakeResponse:  # noqa: ARG001
        visited.append((request.full_url, request.get_header("Authorization")))
        for prefix, payload in routing.items():
            if request.full_url == prefix:
                return _FakeResponse(payload)
        raise AssertionError(f"unexpected request to {request.full_url}")

    return fake, visited


def _write_token(
    path: Path,
    *,
    access_token: str = "old-token",
    refresh_token: str | None = "rt-secret",
    expiry: datetime | None = None,
) -> None:
    token: dict[str, object] = {"access_token": access_token, "token_type": "Bearer"}
    if refresh_token is not None:
        token["refresh_token"] = refresh_token
    token["expiry"] = (expiry or datetime.now(UTC) + timedelta(hours=1)).isoformat()
    path.write_text(
        json.dumps({"token": token, "auth_method": "consumer"}),
        encoding="utf-8",
    )


@pytest.fixture(autouse=True)
def _reset_token_cache() -> Iterator[None]:
    agy_quota_probe._token_cache.clear()
    yield
    agy_quota_probe._token_cache.clear()


# --- find_agy (unchanged behavior) -----------------------------------------


def test_find_agy_returns_path_from_which(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _: "/custom/bin/agy")

    assert agy_quota_probe.find_agy() == "/custom/bin/agy"


def test_find_agy_falls_back_to_user_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    agy_path = tmp_path / ".local" / "bin" / "agy"
    agy_path.parent.mkdir(parents=True)
    agy_path.touch()
    agy_path.chmod(0o755)
    monkeypatch.setattr(shutil, "which", lambda _: None)
    monkeypatch.setattr(
        os.path,
        "expanduser",
        lambda path: str(tmp_path / path.removeprefix("~/")),
    )

    assert agy_quota_probe.find_agy() == str(agy_path)


def test_find_agy_returns_none_when_all_paths_miss(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(shutil, "which", lambda _: None)
    monkeypatch.setattr(
        os.path,
        "expanduser",
        lambda path: str(tmp_path / path.removeprefix("~/")),
    )

    assert agy_quota_probe.find_agy() is None


# --- token freshness + refresh --------------------------------------------


def test_resolve_access_token_uses_disk_token_when_not_expired(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    token_path = tmp_path / "antigravity-oauth-token"
    _write_token(token_path, access_token="fresh-from-disk")
    monkeypatch.setattr(agy_quota_probe, "_TOKEN_PATH", token_path)
    urlopen, visited = _build_urlopen({})
    monkeypatch.setattr(agy_quota_probe, "urlopen", urlopen)

    assert agy_quota_probe._resolve_access_token(15.0) == "fresh-from-disk"
    assert visited == []  # no refresh, no API call


def test_resolve_access_token_falls_back_to_windows_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agy_quota_probe, "_TOKEN_PATH", Path("missing-antigravity-token"))
    monkeypatch.setattr(sys, "platform", "win32")
    credential_payload = {
        "token": {
            "access_token": "fresh-from-credential-manager",
            "expiry": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        }
    }
    calls: list[None] = []

    def read_credential() -> object:
        calls.append(None)
        return credential_payload

    monkeypatch.setattr(agy_quota_probe, "_read_windows_credential", read_credential)

    assert agy_quota_probe._resolve_access_token(15.0) == "fresh-from-credential-manager"
    assert calls == [None]


def test_parse_windows_credential_blob_reads_utf16le_json() -> None:
    payload = {"token": {"access_token": "credential-token", "expiry": "2030-01-01T00:00:00Z"}}
    blob = json.dumps(payload).encode("utf-16-le")

    assert agy_quota_probe._parse_windows_credential_blob(blob) == payload


def test_user_agent_uses_current_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(platform, "machine", lambda: "AMD64")

    assert agy_quota_probe._user_agent() == "antigravity/1.11.3 Windows/AMD64"


def test_resolve_access_token_refreshes_when_expired(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    token_path = tmp_path / "antigravity-oauth-token"
    _write_token(token_path, expiry=datetime.now(UTC) - timedelta(minutes=5))
    monkeypatch.setattr(agy_quota_probe, "_TOKEN_PATH", token_path)
    urlopen, visited = _build_urlopen(
        {_TOKEN_URL: {"access_token": "refreshed-token", "expires_in": 3600}}
    )
    monkeypatch.setattr(agy_quota_probe, "urlopen", urlopen)

    assert agy_quota_probe._resolve_access_token(15.0) == "refreshed-token"
    assert visited[0][0] == _TOKEN_URL
    # The refreshed token is cached for subsequent probes.
    assert agy_quota_probe._token_cache.get("access_token") == "refreshed-token"

    # A second resolution reuses the cache without hitting the network again.
    visited.clear()
    assert agy_quota_probe._resolve_access_token(15.0) == "refreshed-token"
    assert visited == []


def test_refresh_token_returns_none_on_http_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_error(request: Request, timeout: float = 0.0) -> object:  # noqa: ARG001
        raise URLError("boom")

    monkeypatch.setattr(agy_quota_probe, "urlopen", raise_error)

    assert agy_quota_probe._refresh_token("rt", 15.0) is None


# --- response parsing ------------------------------------------------------


def _groups_payload(groups: list[dict[str, object]], *, wrap: str | None = None) -> object:
    body: dict[str, object] = {"groups": groups}
    if wrap is None:
        return body
    return {wrap: body}


def _bucket(
    *,
    bucket_id: str = "weekly",
    name: str | None = None,
    window: str = "WEEK",
    remaining: object,
    reset_time: str | None = _FUTURE_RESET,
    disabled: bool | None = None,
) -> dict[str, object]:
    if name is None:
        name = "Five Hour Limit" if bucket_id == "session" else "Weekly Limit"
    bucket: dict[str, object] = {
        "bucketId": bucket_id,
        "displayName": name,
        "window": window,
    }
    bucket.update(remaining if isinstance(remaining, dict) else {"remainingFraction": remaining})
    if reset_time is not None:
        bucket["resetTime"] = reset_time
    if disabled is not None:
        bucket["disabled"] = disabled
    return bucket


def _gemini_group(buckets: list[dict[str, object]]) -> dict[str, object]:
    return {"displayName": "Gemini Models", "buckets": buckets}


def test_extract_groups_finds_direct_response_summary_and_nested() -> None:
    group = _gemini_group([_bucket(remaining=0.83, bucket_id="weekly")])

    direct = agy_quota_probe._extract_groups(_groups_payload([group]))
    assert direct is not None and len(direct) == 1

    wrapped = agy_quota_probe._extract_groups(_groups_payload([group], wrap="response"))
    assert wrapped is not None and len(wrapped) == 1

    summary = agy_quota_probe._extract_groups(_groups_payload([group], wrap="summary"))
    assert summary is not None and len(summary) == 1


def test_build_result_parses_group_and_windows() -> None:
    groups_raw = [
        _gemini_group(
            [
                _bucket(remaining=0.8328, bucket_id="weekly", name="Weekly Limit"),
                _bucket(remaining=0.9527, bucket_id="session", name="Five Hour", window="5h"),
            ]
        )
    ]

    result = agy_quota_probe._build_result(groups_raw)

    assert result is not None
    assert [group.name for group in result.groups] == ["GEMINI MODELS"]
    gemini = result.groups[0]
    assert gemini.models == ["Gemini Flash", "Gemini Pro"]
    assert gemini.weekly.remaining_percent == pytest.approx(83.28)
    assert gemini.weekly.resets_in_minutes is not None and gemini.weekly.resets_in_minutes > 0
    assert gemini.weekly.resets_in is not None and "h" in gemini.weekly.resets_in
    assert gemini.five_hour.remaining_percent == pytest.approx(95.27)
    assert gemini.five_hour.resets_in is not None


def test_build_result_handles_remaining_fraction_three_shapes() -> None:
    for remaining in (
        {"remainingFraction": 0.5},
        {"remaining": {"remainingFraction": 0.5}},
        {"remaining": {"case": "remainingFraction", "value": 0.5}},
    ):
        groups_raw = [_gemini_group([_bucket(remaining=remaining, bucket_id="weekly")])]
        result = agy_quota_probe._build_result(groups_raw)
        assert result is not None
        assert result.groups[0].weekly.remaining_percent == pytest.approx(50.0)


def test_build_result_full_bucket_without_reset_time_is_full_window() -> None:
    groups_raw = [
        _gemini_group(
            [_bucket(remaining=1.0, bucket_id="weekly", reset_time=None)]
        )
    ]

    result = agy_quota_probe._build_result(groups_raw)

    assert result is not None
    assert result.groups[0].weekly == AgyQuotaWindow(100.0, None, None)


def test_build_result_non_full_bucket_without_reset_time_has_no_countdown() -> None:
    groups_raw = [
        _gemini_group([_bucket(remaining=0.4, bucket_id="weekly", reset_time=None)])
    ]

    result = agy_quota_probe._build_result(groups_raw)

    assert result is not None
    window = result.groups[0].weekly
    assert window.remaining_percent == pytest.approx(40.0)
    assert window.resets_in is None
    assert window.resets_in_minutes is None


def test_build_result_skips_disabled_bucket_and_fills_missing_window_as_full() -> None:
    groups_raw = [
        _gemini_group(
            [
                _bucket(
                    remaining=0.1,
                    bucket_id="weekly",
                    disabled=True,
                ),
                _bucket(remaining=0.7, bucket_id="session", window="5h"),
            ]
        )
    ]

    result = agy_quota_probe._build_result(groups_raw)

    assert result is not None
    gemini = result.groups[0]
    # Disabled weekly dropped; only the session bucket survived.
    assert gemini.weekly == AgyQuotaWindow(100.0, None, None)
    assert gemini.five_hour.remaining_percent == pytest.approx(70.0)


def test_build_result_returns_none_when_no_known_group() -> None:
    groups_raw: list[dict[str, object]] = [{"displayName": "Unknown Tier", "buckets": []}]

    assert agy_quota_probe._build_result(groups_raw) is None


def test_build_result_splits_gemini_and_claude_gpt_groups() -> None:
    groups_raw: list[dict[str, object]] = [
        {"displayName": "Gemini Models", "buckets": [_bucket(remaining=0.9, bucket_id="weekly")]},
        {
            "displayName": "Claude and GPT Models",
            "buckets": [_bucket(remaining=0.2, bucket_id="session", window="5h")],
        },
    ]

    result = agy_quota_probe._build_result(groups_raw)

    assert result is not None
    assert [group.name for group in result.groups] == [
        "GEMINI MODELS",
        "CLAUDE AND GPT MODELS",
    ]
    assert result.groups[1].models == ["Claude Opus", "Claude Sonnet", "GPT-OSS"]


# --- probe_quota end-to-end (mocked HTTP) ----------------------------------


def test_probe_quota_returns_none_without_token_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(agy_quota_probe, "_TOKEN_PATH", tmp_path / "missing-token")
    monkeypatch.setattr(agy_quota_probe, "_read_windows_credential", lambda: None)
    urlopen, visited = _build_urlopen({})
    monkeypatch.setattr(agy_quota_probe, "urlopen", urlopen)

    assert agy_quota_probe.probe_quota() is None
    assert visited == []


def test_probe_quota_refreshes_then_fetches_quota(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    token_path = tmp_path / "antigravity-oauth-token"
    _write_token(token_path, expiry=datetime.now(UTC) - timedelta(minutes=5))
    monkeypatch.setattr(agy_quota_probe, "_TOKEN_PATH", token_path)
    quota_payload = _groups_payload(
        [_gemini_group([_bucket(remaining=0.8328, bucket_id="weekly")])], wrap="response"
    )
    urlopen, visited = _build_urlopen(
        {
            _TOKEN_URL: {"access_token": "refreshed-token", "expires_in": 3600},
            _QUOTA_URL: quota_payload,
        }
    )
    monkeypatch.setattr(agy_quota_probe, "urlopen", urlopen)

    result = agy_quota_probe.probe_quota()

    assert result is not None
    assert result.groups[0].name == "GEMINI MODELS"
    assert result.groups[0].weekly.remaining_percent == pytest.approx(83.28)
    # Two calls: refresh then quota; the quota call carried the refreshed token.
    assert [url for url, _auth in visited] == [_TOKEN_URL, _QUOTA_URL]
    assert visited[1][1] == "Bearer refreshed-token"


def test_probe_quota_returns_none_on_http_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    token_path = tmp_path / "antigravity-oauth-token"
    _write_token(token_path)  # not expired, so only the quota call is attempted
    monkeypatch.setattr(agy_quota_probe, "_TOKEN_PATH", token_path)

    def raise_error(request: Request, timeout: float = 0.0) -> object:  # noqa: ARG001
        raise URLError("offline")

    monkeypatch.setattr(agy_quota_probe, "urlopen", raise_error)

    assert agy_quota_probe.probe_quota() is None


def test_probe_quota_returns_none_when_response_has_no_groups(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    token_path = tmp_path / "antigravity-oauth-token"
    _write_token(token_path)
    monkeypatch.setattr(agy_quota_probe, "_TOKEN_PATH", token_path)
    urlopen, _visited = _build_urlopen({_QUOTA_URL: {"unrelated": "payload"}})
    monkeypatch.setattr(agy_quota_probe, "urlopen", urlopen)

    assert agy_quota_probe.probe_quota() is None


# --- load_quota + cache ----------------------------------------------------


def test_load_quota_returns_fresh_cache_without_probing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "agy_quota_cache.json"
    cached = _result(datetime.now(UTC))
    monkeypatch.setattr(agy_quota_probe, "CACHE_PATH", cache_path)
    agy_quota_probe._write_cache(cached)
    monkeypatch.setattr(agy_quota_probe, "probe_quota", _unexpected_probe)

    assert agy_quota_probe.load_quota() == cached


def test_load_quota_probes_when_cache_is_stale(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "agy_quota_cache.json"
    stale = _result(datetime.now(UTC) - timedelta(minutes=16))
    fresh = _result(datetime.now(UTC))
    monkeypatch.setattr(agy_quota_probe, "CACHE_PATH", cache_path)
    agy_quota_probe._write_cache(stale)
    monkeypatch.setattr(agy_quota_probe, "probe_quota", lambda: fresh)

    assert agy_quota_probe.load_quota(max_age_minutes=15) == fresh
    assert agy_quota_probe._read_cache() == fresh


def test_load_quota_returns_stale_cache_when_probe_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "agy_quota_cache.json"
    stale = _result(datetime.now(UTC) - timedelta(minutes=16))
    monkeypatch.setattr(agy_quota_probe, "CACHE_PATH", cache_path)
    agy_quota_probe._write_cache(stale)
    monkeypatch.setattr(agy_quota_probe, "probe_quota", lambda: None)

    assert agy_quota_probe.load_quota(max_age_minutes=15) == stale


def _result(fetched_at: datetime) -> AgyQuotaResult:
    window = AgyQuotaWindow(83.28, "2h 5m", 125)
    group = AgyQuotaGroup("TEST MODELS", ["Test One"], window, window)
    return AgyQuotaResult([group], fetched_at.isoformat())


def _unexpected_probe() -> AgyQuotaResult | None:
    raise AssertionError("fresh cache must not call probe_quota")

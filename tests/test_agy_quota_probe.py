# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>

from __future__ import annotations

import json
import os
import platform
import shutil
import sys
import time
from base64 import b64encode
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from email.message import Message
from email.utils import format_datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest

from loaders import agy_quota_probe
from loaders.agy_quota_probe import (
    AgyQuotaGroup,
    AgyQuotaResult,
    AgyQuotaWindow,
)
from loaders.agy_quota_probe import (
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

    def read(self, amount: int | None = None) -> bytes:
        return self._data[:amount]


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


def _build_http_error_urlopen(
    code: int,
    retry_after: str | None = None,
) -> tuple[Callable[..., _FakeResponse], list[tuple[str, str | None]]]:
    """Return a fake urlopen that records one route and raises HTTPError."""
    visited: list[tuple[str, str | None]] = []

    def fake(request: Request, timeout: float = 0.0) -> _FakeResponse:  # noqa: ARG001
        visited.append((request.full_url, request.get_header("Authorization")))
        headers = Message()
        if retry_after is not None:
            headers["Retry-After"] = retry_after
        raise HTTPError(request.full_url, code, "HTTP error", headers, None)

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
def _reset_token_cache(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    agy_quota_probe._token_cache.clear()
    agy_quota_probe._rate_limit_until_monotonic = 0.0
    agy_quota_probe._group_seen_at.clear()
    monkeypatch.setattr(agy_quota_probe, "_read_macos_credential", lambda: None)
    yield
    agy_quota_probe._token_cache.clear()
    agy_quota_probe._rate_limit_until_monotonic = 0.0
    agy_quota_probe._group_seen_at.clear()


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


def test_quota_url_matches_cli_backend() -> None:
    assert _QUOTA_URL == (
        "https://daily-cloudcode-pa.googleapis.com/v1internal:retrieveUserQuotaSummary"
    )


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


def test_resolve_access_token_prefers_macos_keychain(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    token_path = tmp_path / "antigravity-oauth-token"
    _write_token(token_path, access_token="stale-file-token")
    monkeypatch.setattr(agy_quota_probe, "_TOKEN_PATH", token_path)
    monkeypatch.setattr(sys, "platform", "darwin")
    credential_payload = {
        "token": {
            "access_token": "fresh-from-keychain",
            "expiry": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        }
    }
    monkeypatch.setattr(
        agy_quota_probe,
        "_read_macos_credential",
        lambda: credential_payload,
    )

    assert agy_quota_probe._resolve_access_token(15.0) == "fresh-from-keychain"


def test_resolve_access_token_falls_back_when_macos_keychain_is_unusable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    token_path = tmp_path / "antigravity-oauth-token"
    _write_token(token_path, access_token="fresh-from-file")
    monkeypatch.setattr(agy_quota_probe, "_TOKEN_PATH", token_path)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(agy_quota_probe, "_read_macos_credential", lambda: None)

    assert agy_quota_probe._resolve_access_token(15.0) == "fresh-from-file"


def test_parse_keyring_secret_reads_go_keyring_base64_json() -> None:
    payload = {
        "token": {
            "access_token": "credential-token",
            "expiry": "2030-01-01T00:00:00Z",
        }
    }
    encoded = b"go-keyring-base64:" + b64encode(json.dumps(payload).encode("utf-8"))

    assert agy_quota_probe._parse_keyring_secret(encoded) == payload


def test_parse_keyring_secret_rejects_invalid_base64() -> None:
    assert agy_quota_probe._parse_keyring_secret(b"go-keyring-base64:not base64") is None


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


# --- HTTP 429 backoff ------------------------------------------------------


def test_post_json_429_uses_retry_after_seconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    urlopen, visited = _build_http_error_urlopen(429, "120")
    monkeypatch.setattr(agy_quota_probe, "urlopen", urlopen)
    monkeypatch.setattr(time, "monotonic", lambda: 1000.0)

    assert agy_quota_probe._post_json(_QUOTA_URL, "token", {}, 15.0) is None
    assert agy_quota_probe._rate_limit_until_monotonic == 1120.0
    assert [url for url, _auth in visited] == [_QUOTA_URL]


def test_post_json_429_uses_retry_after_http_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    retry_at = datetime.now(UTC) + timedelta(seconds=120)
    urlopen, _visited = _build_http_error_urlopen(
        429,
        format_datetime(retry_at, usegmt=True),
    )
    monkeypatch.setattr(agy_quota_probe, "urlopen", urlopen)
    monkeypatch.setattr(time, "monotonic", lambda: 1000.0)

    assert agy_quota_probe._post_json(_QUOTA_URL, "token", {}, 15.0) is None
    assert agy_quota_probe._rate_limit_until_monotonic == pytest.approx(
        1120.0,
        abs=1.0,
    )


def test_post_json_429_without_retry_after_uses_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    urlopen, _visited = _build_http_error_urlopen(429)
    monkeypatch.setattr(agy_quota_probe, "urlopen", urlopen)
    monkeypatch.setattr(time, "monotonic", lambda: 1000.0)

    assert agy_quota_probe._post_json(_QUOTA_URL, "token", {}, 15.0) is None
    assert agy_quota_probe._rate_limit_until_monotonic == 1060.0


def test_post_json_429_with_invalid_retry_after_uses_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    urlopen, _visited = _build_http_error_urlopen(429, "not-a-date")
    monkeypatch.setattr(agy_quota_probe, "urlopen", urlopen)
    monkeypatch.setattr(time, "monotonic", lambda: 1000.0)

    assert agy_quota_probe._post_json(_QUOTA_URL, "token", {}, 15.0) is None
    assert agy_quota_probe._rate_limit_until_monotonic == 1060.0


def test_post_json_429_caps_retry_after_at_one_hour(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    urlopen, _visited = _build_http_error_urlopen(429, "999999")
    monkeypatch.setattr(agy_quota_probe, "urlopen", urlopen)
    monkeypatch.setattr(time, "monotonic", lambda: 1000.0)

    assert agy_quota_probe._post_json(_QUOTA_URL, "token", {}, 15.0) is None
    assert agy_quota_probe._rate_limit_until_monotonic == 4600.0


def test_load_quota_does_not_request_during_backoff(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "agy_quota_cache.json"
    stale = _result(datetime.now(UTC) - timedelta(minutes=16))
    monkeypatch.setattr(agy_quota_probe, "CACHE_PATH", cache_path)
    agy_quota_probe._write_cache(stale)
    urlopen, visited = _build_urlopen({})
    monkeypatch.setattr(agy_quota_probe, "urlopen", urlopen)
    monkeypatch.setattr(time, "monotonic", lambda: 1000.0)
    agy_quota_probe._rate_limit_until_monotonic = 1060.0

    assert agy_quota_probe.load_quota(max_age_minutes=15) == stale
    assert visited == []


def test_load_quota_requests_after_backoff_expires(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "agy_quota_cache.json"
    token_path = tmp_path / "antigravity-oauth-token"
    stale = _result(datetime.now(UTC) - timedelta(minutes=16))
    _write_token(token_path)
    monkeypatch.setattr(agy_quota_probe, "CACHE_PATH", cache_path)
    monkeypatch.setattr(agy_quota_probe, "_TOKEN_PATH", token_path)
    agy_quota_probe._write_cache(stale)
    quota_payload = _groups_payload([_gemini_group([_bucket(remaining=0.5, bucket_id="weekly")])])
    urlopen, visited = _build_urlopen({_QUOTA_URL: quota_payload})
    monkeypatch.setattr(agy_quota_probe, "urlopen", urlopen)
    monkeypatch.setattr(time, "monotonic", lambda: 1060.0)
    agy_quota_probe._rate_limit_until_monotonic = 1060.0

    result = agy_quota_probe.load_quota(max_age_minutes=15)

    assert result is not None and result != stale
    assert [url for url, _auth in visited] == [_QUOTA_URL]


def test_post_json_non_429_http_error_does_not_set_backoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    urlopen, _visited = _build_http_error_urlopen(500, "120")
    monkeypatch.setattr(agy_quota_probe, "urlopen", urlopen)
    monkeypatch.setattr(time, "monotonic", lambda: 1000.0)

    assert agy_quota_probe._post_json(_QUOTA_URL, "token", {}, 15.0) is None
    assert agy_quota_probe._rate_limit_until_monotonic == 0.0


def test_refresh_token_429_sets_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    urlopen, visited = _build_http_error_urlopen(429, "90")
    monkeypatch.setattr(agy_quota_probe, "urlopen", urlopen)
    monkeypatch.setattr(time, "monotonic", lambda: 1000.0)

    assert agy_quota_probe._refresh_token("rt", 15.0) is None
    assert agy_quota_probe._rate_limit_until_monotonic == 1090.0
    assert [url for url, _auth in visited] == [_TOKEN_URL]


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
    assert gemini.weekly is not None
    assert gemini.weekly.remaining_percent == pytest.approx(83.28)
    assert gemini.weekly.resets_in_minutes is not None and gemini.weekly.resets_in_minutes > 0
    assert gemini.weekly.resets_in is not None and "h" in gemini.weekly.resets_in
    assert gemini.five_hour is not None
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
        assert result.groups[0].weekly is not None
        assert result.groups[0].weekly.remaining_percent == pytest.approx(50.0)


def test_build_result_full_bucket_without_reset_time_is_full_window() -> None:
    groups_raw = [_gemini_group([_bucket(remaining=1.0, bucket_id="weekly", reset_time=None)])]

    result = agy_quota_probe._build_result(groups_raw)

    assert result is not None
    assert result.groups[0].weekly == AgyQuotaWindow(100.0, None, None)


def test_build_result_non_full_bucket_without_reset_time_has_no_countdown() -> None:
    groups_raw = [_gemini_group([_bucket(remaining=0.4, bucket_id="weekly", reset_time=None)])]

    result = agy_quota_probe._build_result(groups_raw)

    assert result is not None
    window = result.groups[0].weekly
    assert window is not None
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
    assert gemini.five_hour is not None
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
    assert result.groups[0].weekly is not None
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


@pytest.mark.parametrize(
    "endpoint,code,body,expired",
    [
        ("token", 401, b"", True),
        ("token", 400, b'{"error":"invalid_grant"}', True),
        ("token", 400, b'{"error":"invalid_client"}', False),
        ("token", 400, b"broken", False),
        ("quota", 401, b"", True),
        ("quota", 400, b'{"error":"invalid_grant"}', False),
    ],
)
def test_auth_expiration_marker(
    monkeypatch: pytest.MonkeyPatch, endpoint: str, code: int, body: bytes, expired: bool
) -> None:
    from io import BytesIO

    def fail(*args: object, **kwargs: object) -> object:
        raise HTTPError("https://test", code, "failed", Message(), BytesIO(body))

    monkeypatch.setattr(agy_quota_probe, "urlopen", fail)
    if endpoint == "token":
        assert agy_quota_probe._refresh_token("refresh", 1) is None
    else:
        assert agy_quota_probe._post_json(_QUOTA_URL, "token", {}, 1) is None
    assert agy_quota_probe.auth_expired() is expired


def test_successful_probe_clears_expiration_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    result = AgyQuotaResult(groups=[], fetched_at=datetime.now(UTC).isoformat())
    agy_quota_probe.AUTH_EXPIRED_PATH.touch()
    monkeypatch.setattr(agy_quota_probe, "_resolve_access_token", lambda timeout: "token")
    monkeypatch.setattr(agy_quota_probe, "_post_json", lambda *args: {})
    monkeypatch.setattr(agy_quota_probe, "_extract_groups", lambda raw: [{}])
    monkeypatch.setattr(agy_quota_probe, "_build_result", lambda raw, models=None: result)
    assert agy_quota_probe.probe_quota() == result
    assert not agy_quota_probe.auth_expired()


def test_unusable_probe_keeps_expiration_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    agy_quota_probe.AUTH_EXPIRED_PATH.touch()
    monkeypatch.setattr(agy_quota_probe, "_resolve_access_token", lambda timeout: "token")
    monkeypatch.setattr(agy_quota_probe, "_post_json", lambda *args: {})
    monkeypatch.setattr(agy_quota_probe, "_extract_groups", lambda raw: [{}])
    monkeypatch.setattr(agy_quota_probe, "_build_result", lambda raw, models=None: None)
    assert agy_quota_probe.probe_quota() is None
    assert agy_quota_probe.auth_expired()


def test_token_error_body_read_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    from io import BytesIO

    reads: list[int | None] = []

    class Body(BytesIO):
        def read(self, size: int | None = -1) -> bytes:
            reads.append(size)
            return super().read(size)

    def fail(*args: object, **kwargs: object) -> object:
        raise HTTPError(
            "https://test", 400, "failed", Message(), Body(b'{"error":"invalid_grant"}')
        )

    monkeypatch.setattr(agy_quota_probe, "_MAX_RESPONSE_BYTES", 8)
    monkeypatch.setattr(agy_quota_probe, "urlopen", fail)
    assert agy_quota_probe._refresh_token("refresh", 1) is None
    assert reads == [9]
    assert not agy_quota_probe.auth_expired()


def test_marker_write_and_delete_errors_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise OSError("read-only")

    with monkeypatch.context() as patch:
        patch.setattr(Path, "touch", fail)
        agy_quota_probe._mark_auth_expired()
    agy_quota_probe.AUTH_EXPIRED_PATH.touch()
    monkeypatch.setattr(Path, "unlink", fail)
    result = AgyQuotaResult(groups=[], fetched_at=datetime.now(UTC).isoformat())
    monkeypatch.setattr(agy_quota_probe, "_resolve_access_token", lambda timeout: "token")
    monkeypatch.setattr(agy_quota_probe, "_post_json", lambda *args: {})
    monkeypatch.setattr(agy_quota_probe, "_extract_groups", lambda raw: [{}])
    monkeypatch.setattr(agy_quota_probe, "_build_result", lambda raw, models=None: result)
    assert agy_quota_probe.probe_quota() == result
    assert agy_quota_probe.auth_expired()


def _two_groups(fetched_at: datetime) -> AgyQuotaResult:
    window = AgyQuotaWindow(84.9, "126h 6m", 7566)
    gemini = AgyQuotaGroup("GEMINI MODELS", ["Gemini Flash"], window, window)
    claude = AgyQuotaGroup("CLAUDE AND GPT MODELS", ["Claude Opus"], window, window)
    return AgyQuotaResult([gemini, claude], fetched_at.isoformat())


def _only_claude(fetched_at: datetime) -> AgyQuotaResult:
    window = AgyQuotaWindow(0.0, "63h 51m", 3831)
    claude = AgyQuotaGroup("CLAUDE AND GPT MODELS", ["Claude Opus"], window, window)
    return AgyQuotaResult([claude], fetched_at.isoformat())


def test_carry_keeps_group_the_api_skipped_once() -> None:
    now = datetime.now(UTC)
    full = _two_groups(now)
    agy_quota_probe._carry_missing_groups(full, None)

    merged = agy_quota_probe._carry_missing_groups(_only_claude(now), full)

    assert [group.name for group in merged.groups] == ["GEMINI MODELS", "CLAUDE AND GPT MODELS"]
    assert merged.groups[0] == full.groups[0]
    assert merged.groups[1].weekly is not None
    assert merged.groups[1].weekly.remaining_percent == 0.0


def test_carry_drops_group_unseen_past_grace(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(UTC)
    full = _two_groups(now)
    agy_quota_probe._carry_missing_groups(full, None)
    agy_quota_probe._group_seen_at["GEMINI MODELS"] = now - timedelta(minutes=31)

    merged = agy_quota_probe._carry_missing_groups(_only_claude(now), full)

    assert [group.name for group in merged.groups] == ["CLAUDE AND GPT MODELS"]


def test_carry_does_not_revive_group_after_restart() -> None:
    now = datetime.now(UTC)

    merged = agy_quota_probe._carry_missing_groups(_only_claude(now), _two_groups(now))

    assert [group.name for group in merged.groups] == ["CLAUDE AND GPT MODELS"]


def test_load_quota_writes_carried_group_to_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    now = datetime.now(UTC)
    monkeypatch.setattr(agy_quota_probe, "CACHE_PATH", tmp_path / "agy_quota_cache.json")
    full = _two_groups(now - timedelta(minutes=6))
    agy_quota_probe._carry_missing_groups(full, None)
    agy_quota_probe._write_cache(full)
    monkeypatch.setattr(agy_quota_probe, "probe_quota", lambda: _only_claude(now))

    loaded = agy_quota_probe.load_quota()

    assert loaded is not None
    assert [group.name for group in loaded.groups] == ["GEMINI MODELS", "CLAUDE AND GPT MODELS"]
    cached = agy_quota_probe._read_cache()
    assert cached is not None
    assert [group.name for group in cached.groups] == ["GEMINI MODELS", "CLAUDE AND GPT MODELS"]


@pytest.mark.parametrize("minutes, weekly", [(300, False), (305, False), (306, True)])
def test_probe_models_fallback_selects_lowest_gemini(
    monkeypatch: pytest.MonkeyPatch, minutes: int, weekly: bool
) -> None:
    reset = (datetime.now(UTC) + timedelta(minutes=minutes)).isoformat()
    models = {
        "gemini-pro": {"quotaInfo": {"remainingFraction": 0.8, "resetTime": _FUTURE_RESET}},
        "gemini-flash": {"quotaInfo": {"remainingFraction": "0.5", "resetTime": reset}},
        "claude-opus": {"quotaInfo": {"resetTime": reset}},
        "claude-sonnet": {"quotaInfo": {"remainingFraction": 0.01, "resetTime": reset}},
        "chat_test": {"quotaInfo": {"remainingFraction": 1}},
        "tab_test": {"quotaInfo": {"remainingFraction": 1}},
    }
    summary = _groups_payload(
        [
            {
                "displayName": "Claude and GPT models",
                "buckets": [_bucket(remaining=0.7, bucket_id="weekly")],
            }
        ]
    )
    calls = []

    def post(url: str, token: str, body: dict[str, object], timeout: float) -> object:
        calls.append((url, token, body, timeout))
        return summary if url == _QUOTA_URL else {"models": models}

    monkeypatch.setattr(agy_quota_probe, "_resolve_access_token", lambda timeout: "same-token")
    monkeypatch.setattr(agy_quota_probe, "_post_json", post)
    result = agy_quota_probe.probe_quota(7)
    assert result is not None and len(result.groups) == 2
    gemini = result.groups[0]
    assert gemini.name == "GEMINI MODELS"
    assert gemini.models == ["Gemini Flash", "Gemini Pro"]
    window = gemini.weekly if weekly else gemini.five_hour
    assert window is not None and window.remaining_percent == 50
    assert (gemini.five_hour if weekly else gemini.weekly) is None
    assert calls == [
        (_QUOTA_URL, "same-token", {}, 7),
        (agy_quota_probe._MODELS_URL, "same-token", {}, 7),
    ]


@pytest.mark.parametrize(
    "models",
    [None, {"models": {}}, {"models": {"claude": {"quotaInfo": {"resetTime": _FUTURE_RESET}}}}],
)
def test_probe_models_unavailable_keeps_summary(
    monkeypatch: pytest.MonkeyPatch, models: object
) -> None:
    summary = _groups_payload([{"displayName": "Claude and GPT models", "buckets": []}])
    monkeypatch.setattr(agy_quota_probe, "_resolve_access_token", lambda timeout: "token")
    monkeypatch.setattr(
        agy_quota_probe, "_post_json", lambda url, *args: summary if url == _QUOTA_URL else models
    )
    result = agy_quota_probe.probe_quota()
    assert result is not None
    assert [group.name for group in result.groups] == ["CLAUDE AND GPT MODELS"]


def test_probe_summary_gemini_does_not_fetch_models(monkeypatch: pytest.MonkeyPatch) -> None:
    summary = _groups_payload([_gemini_group([])])
    urlopen, visited = _build_urlopen({_QUOTA_URL: summary})
    monkeypatch.setattr(agy_quota_probe, "_resolve_access_token", lambda timeout: "token")
    monkeypatch.setattr(agy_quota_probe, "urlopen", urlopen)
    assert agy_quota_probe.probe_quota() is not None
    assert visited == [(_QUOTA_URL, "Bearer token")]


@pytest.mark.parametrize("weekly", [True, False])
def test_cache_roundtrips_unreported_window(weekly: bool) -> None:
    window = AgyQuotaWindow(50, "1h 0m", 60)
    group = AgyQuotaGroup(
        "GEMINI MODELS", ["Gemini Flash"], window if weekly else None, None if weekly else window
    )
    result = AgyQuotaResult([group], datetime.now(UTC).isoformat())
    agy_quota_probe._write_cache(result)
    payload = json.loads(agy_quota_probe.CACHE_PATH.read_text())
    assert payload["groups"][0]["five_hour" if weekly else "weekly"] is None
    assert agy_quota_probe._read_cache() == result


# conftest disables the CLI probe for every test; keep the real one for these.
_real_probe_via_cli = agy_quota_probe._probe_via_cli


def _usage_command_output(now: datetime) -> bytes:
    """Shape of ``agy -p /usage --output-format json`` from agy 1.4.0."""

    def bucket(bucket_id: str, window: str, fraction: float, hours: float) -> dict[str, object]:
        reset = (now + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
        return {
            "id": bucket_id,
            "window": window,
            "remaining_fraction": fraction,
            "reset_time": reset,
        }

    groups = [
        {
            "name": "Gemini Models",
            "buckets": [
                bucket("gemini-weekly", "weekly", 0.9342781901359558, 157),
                bucket("gemini-5h", "5h", 0.9983674883842468, 4),
            ],
        },
        {
            "name": "Claude and GPT models",
            "buckets": [
                bucket("3p-weekly", "weekly", 0, 49),
                {"id": "3p-5h", "window": "5h", "disabled": True, "remaining_fraction": 1},
            ],
        },
        {
            "name": "Gemini 4 Argon",
            "buckets": [bucket("gemini-argon-wtu-weekly", "weekly", 0, 160)],
        },
    ]
    payload = {"status": "SUCCESS", "command": {"name": "usage", "data": {"groups": groups}}}
    return json.dumps(payload).encode()


def _fake_cli(
    monkeypatch: pytest.MonkeyPatch, stdout: bytes, returncode: int = 0
) -> list[list[str]]:
    calls: list[list[str]] = []

    def run(command: list[str], **kwargs: object) -> object:
        calls.append(command)
        return type("Completed", (), {"returncode": returncode, "stdout": stdout})()

    monkeypatch.setattr(agy_quota_probe, "find_agy", lambda: "/bin/agy")
    monkeypatch.setattr("loaders.agy_quota_probe.subprocess.run", run)
    return calls


def test_cli_probe_reads_three_groups_with_argon_weekly_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _fake_cli(monkeypatch, _usage_command_output(datetime.now(UTC)))

    result = _real_probe_via_cli(15)

    assert result is not None
    assert calls[0][:5] == ["/bin/agy", "-p", "/usage", "--output-format", "json"]
    gemini, claude, argon = result.groups
    assert gemini.name == "GEMINI MODELS"
    assert gemini.weekly is not None and gemini.weekly.remaining_percent == pytest.approx(
        93.43, abs=0.01
    )
    assert gemini.five_hour is not None and gemini.five_hour.remaining_percent == pytest.approx(
        99.84, abs=0.01
    )
    assert claude.name == "CLAUDE AND GPT MODELS"
    assert claude.weekly is not None and claude.weekly.remaining_percent == 0
    assert claude.five_hour == AgyQuotaWindow(100.0, None, None)
    assert argon.name == "GEMINI 4 ARGON"
    assert argon.models == ["Gemini 4 Argon"]
    assert argon.five_hour is None
    assert argon.weekly is not None and argon.weekly.remaining_percent == 0


@pytest.mark.parametrize(
    ("stdout", "returncode"),
    [
        (b"{}", 1),
        (b"not json", 0),
        (b'{"status": "SUCCESS", "response": "unknown command"}', 0),
    ],
)
def test_cli_probe_returns_none_on_unusable_output(
    monkeypatch: pytest.MonkeyPatch, stdout: bytes, returncode: int
) -> None:
    _fake_cli(monkeypatch, stdout, returncode)
    assert _real_probe_via_cli(15) is None


def test_probe_quota_prefers_cli_over_api(monkeypatch: pytest.MonkeyPatch) -> None:
    result = AgyQuotaResult(groups=[], fetched_at=datetime.now(UTC).isoformat())
    agy_quota_probe.AUTH_EXPIRED_PATH.touch()
    monkeypatch.setattr(agy_quota_probe, "_probe_via_cli", lambda timeout: result)
    monkeypatch.setattr(
        agy_quota_probe, "_resolve_access_token", lambda timeout: pytest.fail("API must not run")
    )

    assert agy_quota_probe.probe_quota() == result
    assert not agy_quota_probe.auth_expired()


@pytest.mark.parametrize(
    ("name", "expected"),
    [("", None), ("gemini 4 argon", "argon"), ("GEMINI MODELS", "gemini")],
)
def test_group_id_argon_boundaries(name: str, expected: str | None) -> None:
    assert agy_quota_probe._group_id({"name": name}) == expected


def test_assemble_groups_argon_missing_windows() -> None:
    assert agy_quota_probe._assemble_groups({}) == []
    groups = agy_quota_probe._assemble_groups({"argon": {}})
    assert len(groups) == 1
    assert groups[0].name == "GEMINI 4 ARGON"
    assert groups[0].weekly == AgyQuotaWindow(100.0, None, None)
    assert groups[0].five_hour is None


@pytest.mark.parametrize("minutes, expected", [(5, 0), (25, 15)])
def test_carry_ages_both_reset_countdowns(minutes: int, expected: int) -> None:
    fetched = datetime(2026, 1, 1, 11, 50, tzinfo=UTC)
    window = AgyQuotaWindow(20, f"{minutes}m", minutes)
    cached = AgyQuotaResult(
        [AgyQuotaGroup("GEMINI MODELS", [], window, window)], fetched.isoformat()
    )
    agy_quota_probe._carry_missing_groups(cached, None)
    merged = agy_quota_probe._carry_missing_groups(
        _only_claude(fetched + timedelta(minutes=10)), cached
    )
    group = next(group for group in merged.groups if group.name == "GEMINI MODELS")
    for carried in (group.weekly, group.five_hour):
        assert carried is not None
        assert carried.resets_in_minutes == expected
        assert carried.resets_in == f"{expected}m"
    assert cached.groups[0].weekly == window
    if expected:
        # A future reset keeps the same absolute time after rebasing.
        assert datetime.fromisoformat(merged.fetched_at) + timedelta(minutes=expected) == (
            fetched + timedelta(minutes=minutes)
        )
    else:
        from menubar.agy import project_quota

        projection = project_quota(
            merged, "en", now=datetime.fromisoformat(merged.fetched_at).timestamp()
        )
        assert projection is not None
        assert projection.weekly.reset_done
        assert projection.session.reset_done

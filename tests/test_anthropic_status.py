# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

import anthropic_status


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    cache_path = tmp_path / ".usage" / "anthropic_status_cache.json"
    monkeypatch.setattr(anthropic_status, "CACHE_PATH", cache_path)
    monkeypatch.setattr(anthropic_status, "_last_failure_at", None)
    yield cache_path


def _payload(
    code_status: str = "operational",
    api_status: str = "operational",
    *,
    indicator: str = "none",
    incidents: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    return {
        "status": {"indicator": indicator, "description": "All Systems Operational"},
        "components": [
            {"name": "Claude Code", "status": code_status},
            {"name": "Claude API (api.anthropic.com)", "status": api_status},
        ],
        "incidents": incidents or [],
    }


def _mock_response(monkeypatch: pytest.MonkeyPatch, payload: dict[str, object]) -> None:
    def fake_urlopen(request: urllib.request.Request, timeout: int) -> FakeResponse:
        assert request.full_url == anthropic_status.STATUS_URL
        assert request.get_header("User-agent") == anthropic_status.USER_AGENT
        assert timeout == 10
        return FakeResponse(payload)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)


def test_operational_components_report_normal(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_response(monkeypatch, _payload())

    result = anthropic_status.get_anthropic_status()

    assert result == anthropic_status.AnthropicStatus(
        False, "operational", "Claude Code and Claude API are operational.", "fetched"
    )


def test_degraded_claude_code_reports_abnormal(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_response(monkeypatch, _payload(code_status="degraded_performance"))

    result = anthropic_status.get_anthropic_status()

    assert result.is_abnormal is True
    assert result.status == "degraded_performance"
    assert result.source == "fetched"


def test_unrelated_incident_does_not_report_abnormal(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_response(
        monkeypatch,
        _payload(incidents=[{"name": "Microsoft Office add-in outage", "status": "investigating"}]),
    )

    result = anthropic_status.get_anthropic_status()

    assert result.is_abnormal is False
    assert result.status == "operational"


def test_download_failure_uses_stale_cache(
    isolated_cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    isolated_cache.parent.mkdir()
    isolated_cache.write_text(json.dumps(_payload(code_status="partial_outage")), encoding="utf-8")
    expired = time.time() - anthropic_status.CACHE_TTL_SECONDS - 1
    os.utime(isolated_cache, (expired, expired))

    def offline(*args: object, **kwargs: object) -> FakeResponse:
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(urllib.request, "urlopen", offline)

    result = anthropic_status.get_anthropic_status()

    assert result.is_abnormal is True
    assert result.status == "partial_outage"
    assert result.source == "stale"


def test_expired_cache_is_refetched(isolated_cache: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    isolated_cache.parent.mkdir()
    isolated_cache.write_text(json.dumps(_payload(code_status="major_outage")), encoding="utf-8")
    expired = time.time() - anthropic_status.CACHE_TTL_SECONDS - 1
    os.utime(isolated_cache, (expired, expired))
    _mock_response(monkeypatch, _payload())

    result = anthropic_status.get_anthropic_status()

    assert result.source == "fetched"
    assert result.status == "operational"
    assert json.loads(isolated_cache.read_text(encoding="utf-8")) == _payload()

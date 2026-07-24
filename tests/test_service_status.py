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

import service_status


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
    monkeypatch.setattr(service_status, "_last_failure_at", {})
    yield tmp_path / ".usage"


def _config(
    config: service_status.ServiceStatusConfig, cache_dir: Path
) -> service_status.ServiceStatusConfig:
    return service_status.ServiceStatusConfig(
        config.service_name,
        config.status_url,
        config.component_names,
        cache_dir / config.cache_path.name,
    )


def _claude_payload(
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


def _mock_response(
    monkeypatch: pytest.MonkeyPatch,
    config: service_status.ServiceStatusConfig,
    payload: dict[str, object],
) -> None:
    def fake_urlopen(request: urllib.request.Request, timeout: int) -> FakeResponse:
        assert request.full_url == config.status_url
        assert request.get_header("User-agent") == service_status.USER_AGENT
        assert timeout == 10
        return FakeResponse(payload)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)


def test_operational_components_report_normal(
    isolated_cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(service_status.CLAUDE_STATUS, isolated_cache)
    _mock_response(monkeypatch, config, _claude_payload())

    result = service_status.get_service_status(config)

    assert result == service_status.ServiceStatus(
        "Claude", False, "operational", "Relevant components are operational.", "fetched"
    )


def test_degraded_claude_code_reports_abnormal(
    isolated_cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(service_status.CLAUDE_STATUS, isolated_cache)
    _mock_response(monkeypatch, config, _claude_payload(code_status="degraded_performance"))

    result = service_status.get_service_status(config)

    assert result.is_abnormal is True
    assert result.status == "degraded_performance"
    assert result.source == "fetched"


def test_unrelated_incident_does_not_report_abnormal(
    isolated_cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(service_status.CLAUDE_STATUS, isolated_cache)
    _mock_response(
        monkeypatch,
        config,
        _claude_payload(),
    )

    result = service_status.get_service_status(config)

    assert result.is_abnormal is False
    assert result.status == "operational"


def test_download_failure_uses_stale_cache(
    isolated_cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(service_status.CLAUDE_STATUS, isolated_cache)
    config.cache_path.parent.mkdir()
    config.cache_path.write_text(
        json.dumps(_claude_payload(code_status="partial_outage")), encoding="utf-8"
    )
    expired = time.time() - service_status.CACHE_TTL_SECONDS - 1
    os.utime(config.cache_path, (expired, expired))

    def offline(*args: object, **kwargs: object) -> FakeResponse:
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(urllib.request, "urlopen", offline)

    result = service_status.get_service_status(config)

    assert result.is_abnormal is True
    assert result.status == "partial_outage"
    assert result.source == "stale"


def test_expired_cache_is_refetched(isolated_cache: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config(service_status.CLAUDE_STATUS, isolated_cache)
    config.cache_path.parent.mkdir()
    config.cache_path.write_text(
        json.dumps(_claude_payload(code_status="major_outage")), encoding="utf-8"
    )
    expired = time.time() - service_status.CACHE_TTL_SECONDS - 1
    os.utime(config.cache_path, (expired, expired))
    _mock_response(monkeypatch, config, _claude_payload())

    result = service_status.get_service_status(config)

    assert result.source == "fetched"
    assert result.status == "operational"
    assert json.loads(config.cache_path.read_text(encoding="utf-8")) == _claude_payload()


def test_codex_only_checks_codex_api_component(
    isolated_cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(service_status.CODEX_STATUS, isolated_cache)
    payload: dict[str, object] = {
        "status": {"indicator": "major"},
        "components": [
            {"name": "Codex API", "status": "operational"},
            {"name": "Responses API", "status": "major_outage"},
        ],
    }
    _mock_response(monkeypatch, config, payload)

    result = service_status.get_service_status(config)

    assert config.component_names == ("Codex API",)
    assert result.service_name == "Codex"
    assert result.is_abnormal is False


def test_codex_api_outage_reports_abnormal(
    isolated_cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(service_status.CODEX_STATUS, isolated_cache)
    payload: dict[str, object] = {
        "components": [{"name": "Codex API", "status": "partial_outage"}]
    }
    _mock_response(monkeypatch, config, payload)

    result = service_status.get_service_status(config)

    assert result.is_abnormal is True
    assert result.status == "partial_outage"

# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
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

    def read(self, amount: int | None = None) -> bytes:
        return self._body[:amount]


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setattr(service_status, "_last_failure_at", {})
    cache_dir = tmp_path / ".usage"
    monkeypatch.setattr(
        service_status, "ALERT_STATE_PATH", cache_dir / "service_alert_state.json"
    )
    yield cache_dir


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


def _codex_payload(
    status: str = "degraded_performance",
    *,
    incidents: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    return {
        "components": [{"name": "Codex API", "status": status}],
        "incidents": incidents or [],
    }


def _incident(status: str, *, hours_ago: int) -> dict[str, str]:
    updated_at = datetime.now(UTC) - timedelta(hours=hours_ago)
    return {"name": "Elevated error rates", "status": status, "updated_at": updated_at.isoformat()}


def _write_alert_state(cache_dir: Path, state: dict[str, object]) -> Path:
    path = cache_dir / "service_alert_state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state), encoding="utf-8")
    return path


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


def test_settled_monitoring_incident_suppresses_degraded_status(
    isolated_cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(service_status.CODEX_STATUS, isolated_cache)
    _mock_response(
        monkeypatch,
        config,
        _codex_payload(incidents=[_incident("monitoring", hours_ago=5)]),
    )

    result = service_status.get_service_status(config)

    assert result.is_abnormal is False
    assert result.status == "degraded_performance"
    assert "monitoring" in result.description


def test_recent_monitoring_incident_keeps_degraded_status_abnormal(
    isolated_cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(service_status.CODEX_STATUS, isolated_cache)
    _mock_response(
        monkeypatch,
        config,
        _codex_payload(incidents=[_incident("monitoring", hours_ago=1)]),
    )

    result = service_status.get_service_status(config)

    assert result.is_abnormal is True
    assert result.status == "degraded_performance"


def test_investigating_incident_prevents_degraded_status_suppression(
    isolated_cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(service_status.CODEX_STATUS, isolated_cache)
    _mock_response(
        monkeypatch,
        config,
        _codex_payload(
            incidents=[
                _incident("monitoring", hours_ago=5),
                _incident("investigating", hours_ago=1),
            ]
        ),
    )

    result = service_status.get_service_status(config)

    assert result.is_abnormal is True
    assert result.status == "degraded_performance"


def test_settled_monitoring_incident_does_not_suppress_major_outage(
    isolated_cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(service_status.CODEX_STATUS, isolated_cache)
    _mock_response(
        monkeypatch,
        config,
        _codex_payload(
            "major_outage",
            incidents=[_incident("monitoring", hours_ago=5)],
        ),
    )

    result = service_status.get_service_status(config)

    assert result.is_abnormal is True
    assert result.status == "major_outage"


def test_long_observed_degraded_status_is_suppressed_without_incidents(
    isolated_cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = 2_000_000.0
    monkeypatch.setattr(time, "time", lambda: now)
    _write_alert_state(
        isolated_cache,
        {
            "Codex": {
                "status": "degraded_performance",
                "first_seen_at": now - 25 * 3600,
            }
        },
    )
    config = _config(service_status.CODEX_STATUS, isolated_cache)
    _mock_response(monkeypatch, config, _codex_payload())

    result = service_status.get_service_status(config)

    assert result.is_abnormal is False
    assert result.status == "degraded_performance"
    assert "observed unchanged" in result.description


def test_changed_status_resets_observation_time_without_suppression(
    isolated_cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = 2_000_000.0
    monkeypatch.setattr(time, "time", lambda: now)
    state_path = _write_alert_state(
        isolated_cache,
        {"Codex": {"status": "operational", "first_seen_at": now - 25 * 3600}},
    )
    config = _config(service_status.CODEX_STATUS, isolated_cache)
    _mock_response(monkeypatch, config, _codex_payload())

    result = service_status.get_service_status(config)

    assert result.is_abnormal is True
    assert json.loads(state_path.read_text(encoding="utf-8"))["Codex"] == {
        "first_seen_at": now,
        "status": "degraded_performance",
    }


def test_missing_alert_state_is_treated_as_first_observation(
    isolated_cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(service_status.CODEX_STATUS, isolated_cache)
    _mock_response(monkeypatch, config, _codex_payload())

    result = service_status.get_service_status(config)

    assert result.is_abnormal is True
    assert (isolated_cache / "service_alert_state.json").is_file()


def test_corrupt_alert_state_is_treated_as_first_observation(
    isolated_cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_path = isolated_cache / "service_alert_state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text("{not json", encoding="utf-8")
    config = _config(service_status.CODEX_STATUS, isolated_cache)
    _mock_response(monkeypatch, config, _codex_payload())

    result = service_status.get_service_status(config)

    assert result.is_abnormal is True
    assert json.loads(state_path.read_text(encoding="utf-8"))["Codex"]["status"] == (
        "degraded_performance"
    )


@pytest.mark.parametrize("config", [service_status.CLAUDE_STATUS, service_status.CODEX_STATUS])
def test_configured_feeds_use_components_not_the_truncated_summary(
    config: service_status.ServiceStatusConfig,
) -> None:
    """Statuspage's summary payload is capped at the first 25 components.

    OpenAI publishes 34, so "Codex API" (position 27) never appears there and
    _build_status() could only ever return "unknown" — silently, because an
    absent component is indistinguishable from a healthy one to the caller.
    Mocked payload tests cannot catch picking the wrong endpoint, so pin it.
    """
    assert config.status_url.endswith("/api/v2/components.json")
    assert "summary.json" not in config.status_url


@pytest.mark.parametrize("config", [service_status.CLAUDE_STATUS, service_status.CODEX_STATUS])
def test_live_feed_actually_publishes_every_watched_component(
    config: service_status.ServiceStatusConfig,
) -> None:
    """Hit the real endpoint so a renamed or dropped component fails loudly.

    Every other test here feeds a hand-written payload, so the allowlist can
    drift away from what the vendor actually publishes without any test noticing
    — which is exactly how the Codex banner went dark.
    """
    try:
        with urllib.request.urlopen(config.status_url, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        pytest.skip(f"status feed unreachable: {error}")

    published = {
        component["name"]
        for component in payload.get("components", [])
        if isinstance(component, dict) and isinstance(component.get("name"), str)
    }
    missing = [name for name in config.component_names if name not in published]

    assert not missing, (
        f"{config.service_name} no longer publishes {missing}; "
        f"the banner will silently report 'unknown'. Published: {sorted(published)}"
    )

# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Read public service-status feeds, never LLM usage APIs.

This module downloads only public Statuspage JSON. It does not call an LLM
usage API and therefore does not collect or infer account usage.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 300
FAILURE_RETRY_SECONDS = 60
MONITORING_SETTLED_SECONDS = 4 * 3600
OBSERVED_STALE_SECONDS = 24 * 3600
SUPPRESSIBLE_STATUSES = ("degraded_performance",)
USER_AGENT = "usage/0.9"
# Statuspage summaries are tens of KB; cap the read so a broken endpoint cannot
# make us buffer an unbounded response.
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
ALERT_STATE_PATH = Path(os.path.expanduser("~/.usage/service_alert_state.json"))

StatusSource = Literal["fetched", "cache", "stale", "fallback"]
_SEVERITY = {
    "operational": 0,
    "degraded_performance": 1,
    "partial_outage": 2,
    "major_outage": 3,
}


@dataclass(frozen=True)
class ServiceStatusConfig:
    """The public status-page details for one tool."""

    service_name: str
    status_url: str
    component_names: tuple[str, ...]
    cache_path: Path


CLAUDE_STATUS = ServiceStatusConfig(
    service_name="Claude",
    status_url="https://status.claude.com/api/v2/summary.json",
    component_names=("Claude Code", "Claude API (api.anthropic.com)"),
    cache_path=Path(os.path.expanduser("~/.usage/anthropic_status_cache.json")),
)
CODEX_STATUS = ServiceStatusConfig(
    service_name="Codex",
    status_url="https://status.openai.com/api/v2/summary.json",
    # Do not include shared OpenAI API components (for example Responses): they
    # affect all API users and do not necessarily affect the Codex CLI.
    component_names=("Codex API",),
    cache_path=Path(os.path.expanduser("~/.usage/openai_status_cache.json")),
)


@dataclass(frozen=True)
class ServiceStatus:
    """Service state relevant to one supported tool."""

    service_name: str
    is_abnormal: bool
    status: str
    description: str
    source: StatusSource


_last_failure_at: dict[str, float] = {}


def get_service_status(config: ServiceStatusConfig) -> ServiceStatus:
    """Return the worst status among this tool's relevant components."""
    cached = _read_cache(config)
    if cached is not None:
        return _build_status(config, cached, "cache")

    stale_cached = _read_cache(config, allow_stale=True)
    if _retry_is_delayed(config):
        return _status_from_stale_or_fallback(config, stale_cached)

    payload = _fetch_status(config)
    if payload is not None:
        _write_cache(config, payload)
        _clear_failure_retry(config)
        return _build_status(config, payload, "fetched")

    _record_failure(config)
    return _status_from_stale_or_fallback(config, stale_cached)


def _status_from_stale_or_fallback(
    config: ServiceStatusConfig, payload: dict[str, Any] | None
) -> ServiceStatus:
    if payload is not None:
        return _build_status(config, payload, "stale")
    return ServiceStatus(config.service_name, False, "unknown", "Status unavailable.", "fallback")


def _build_status(
    config: ServiceStatusConfig, payload: dict[str, Any], source: StatusSource
) -> ServiceStatus:
    components = payload.get("components")
    if not isinstance(components, list):
        return ServiceStatus(config.service_name, False, "unknown", "Status unavailable.", source)

    component_statuses = {
        component.get("name"): component.get("status")
        for component in components
        if isinstance(component, dict)
        and isinstance(component.get("name"), str)
        and isinstance(component.get("status"), str)
    }
    statuses = tuple(component_statuses.get(name) for name in config.component_names)
    valid_statuses = tuple(
        status for status in statuses if isinstance(status, str) and status in _SEVERITY
    )
    if len(valid_statuses) != len(config.component_names):
        return ServiceStatus(config.service_name, False, "unknown", "Status unavailable.", source)

    worst_status = max(valid_statuses, key=lambda status: _SEVERITY[status])
    affected = [
        name
        for name, status in zip(config.component_names, valid_statuses, strict=True)
        if status != "operational"
    ]
    if not affected:
        status = ServiceStatus(
            config.service_name, False, worst_status, "Relevant components are operational.", source
        )
    else:
        status = ServiceStatus(
            config.service_name,
            True,
            worst_status,
            f"{', '.join(affected)}: {worst_status}.",
            source,
        )
    return _apply_alert_suppression(config, payload, status)


def _apply_alert_suppression(
    config: ServiceStatusConfig, payload: dict[str, Any], status: ServiceStatus
) -> ServiceStatus:
    observed_stale = _observe_status(config.service_name, status.status)
    if not status.is_abnormal or status.status not in SUPPRESSIBLE_STATUSES:
        return status

    incidents = payload.get("incidents")
    if isinstance(incidents, list):
        incident_statuses = [
            incident.get("status") for incident in incidents if isinstance(incident, dict)
        ]
        if any(value in {"investigating", "identified"} for value in incident_statuses):
            return status

        if incidents and len(incident_statuses) == len(incidents) and all(
            value == "monitoring" for value in incident_statuses
        ):
            updated_times: list[datetime] = []
            for incident in incidents:
                updated_at = incident.get("updated_at")
                if not isinstance(updated_at, str):
                    break
                try:
                    updated_time = datetime.fromisoformat(updated_at)
                except ValueError:
                    break
                if updated_time.tzinfo is None:
                    break
                updated_times.append(updated_time)
            if len(updated_times) == len(incidents):
                latest_update = max(updated_times)
                age_seconds = (datetime.now(UTC) - latest_update).total_seconds()
                if age_seconds > MONITORING_SETTLED_SECONDS:
                    return ServiceStatus(
                        status.service_name,
                        False,
                        status.status,
                        "Alert suppressed: all incidents have remained in monitoring "
                        "for more than 4 hours.",
                        status.source,
                    )

    if observed_stale:
        return ServiceStatus(
            status.service_name,
            False,
            status.status,
            "Alert suppressed: this status has been observed unchanged for more than 24 hours.",
            status.source,
        )
    return status


def _observe_status(service_name: str, status: str) -> bool:
    state = _read_alert_state()
    now = time.time()
    previous = state.get(service_name)
    if (
        isinstance(previous, dict)
        and previous.get("status") == status
        and isinstance(previous.get("first_seen_at"), int | float)
        and not isinstance(previous.get("first_seen_at"), bool)
    ):
        first_seen_at = float(previous["first_seen_at"])
        return now - first_seen_at > OBSERVED_STALE_SECONDS

    state[service_name] = {"status": status, "first_seen_at": now}
    _write_alert_state(state)
    return False


def _read_alert_state() -> dict[str, Any]:
    try:
        with ALERT_STATE_PATH.open(encoding="utf-8") as file:
            state = json.load(file)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.debug("failed to read service alert state: %s", exc)
        return {}
    return state if isinstance(state, dict) else {}


def _write_alert_state(state: dict[str, Any]) -> None:
    tmp_path: str | None = None
    try:
        ALERT_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=ALERT_STATE_PATH.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(state, file, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp_path, ALERT_STATE_PATH)
        tmp_path = None
    except OSError as exc:
        logger.warning("failed to write service alert state: %s", exc)
    finally:
        if tmp_path is not None:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)


def _read_cache(
    config: ServiceStatusConfig, *, allow_stale: bool = False
) -> dict[str, Any] | None:
    try:
        if not allow_stale and (
            time.time() - config.cache_path.stat().st_mtime
        ) > CACHE_TTL_SECONDS:
            return None
        with config.cache_path.open(encoding="utf-8") as file:
            payload = json.load(file)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.debug("failed to read %s status cache: %s", config.service_name, exc)
        return None
    return payload if isinstance(payload, dict) else None


def _fetch_status(config: ServiceStatusConfig) -> dict[str, Any] | None:
    request = urllib.request.Request(config.status_url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError("status response exceeds the size limit")
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, TimeoutError, UnicodeDecodeError, ValueError) as exc:
        logger.warning(
            "failed to fetch %s status from %s: %s",
            config.service_name,
            config.status_url,
            exc,
        )
        return None
    return payload if isinstance(payload, dict) else None


def _write_cache(config: ServiceStatusConfig, payload: dict[str, Any]) -> None:
    tmp_path: str | None = None
    try:
        config.cache_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=config.cache_path.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp_path, config.cache_path)
        tmp_path = None
    except OSError as exc:
        logger.warning("failed to write %s status cache: %s", config.service_name, exc)
    finally:
        if tmp_path is not None:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)


def _retry_is_delayed(config: ServiceStatusConfig) -> bool:
    failed_at = _last_failure_at.get(config.service_name)
    return failed_at is not None and time.monotonic() - failed_at < FAILURE_RETRY_SECONDS


def _record_failure(config: ServiceStatusConfig) -> None:
    _last_failure_at[config.service_name] = time.monotonic()


def _clear_failure_retry(config: ServiceStatusConfig) -> None:
    _last_failure_at.pop(config.service_name, None)

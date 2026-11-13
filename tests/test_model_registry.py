# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import importlib
import json
import logging
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from adapters.types import UsageEntry as AdapterUsageEntry
from loaders import agy_loader, agy_quota_probe, cache_quarantine
from loaders.history_loader import UsageEntry as HistoryUsageEntry
from quota import model_registry, quota_snapshot
from usage_common import pricing, service_status


def _write_codex_cache(
    path: Path,
    *,
    identity: str | None = "fake-identity-1",
    models: list[dict[str, str]] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "fetched_at": "2026-11-13T13:36:20Z",
        "etag": 'W/"fake-etag-1"',
        "client_version": "0.0.0-test",
        "models": models if models is not None else [],
    }
    if identity is not None:
        payload["identity"] = identity
    path.write_text(json.dumps(payload), encoding="utf-8")


def _agy_result(*groups: tuple[str, list[str]]) -> agy_quota_probe.AgyQuotaResult:
    return agy_quota_probe.AgyQuotaResult(
        groups=[
            agy_quota_probe.AgyQuotaGroup(
                name=name,
                models=list(models),
                weekly=None,
                five_hour=None,
            )
            for name, models in groups
        ],
        fetched_at="2026-11-13T13:36:20+00:00",
    )


def _adapter_entry(agent_id: str, model: str) -> AdapterUsageEntry:
    return AdapterUsageEntry(
        timestamp=datetime(2026, 11, 13, 12, 0, tzinfo=UTC),
        session_id="sess-1",
        message_id="msg-1",
        request_id="req-1",
        model=model,
        input_tokens=10,
        output_tokens=20,
        cache_creation_tokens=0,
        cache_read_tokens=0,
        cost_usd=None,
        project="proj",
        agent_id=agent_id,
    )


def _history_entry(model: str) -> HistoryUsageEntry:
    return HistoryUsageEntry(
        timestamp=datetime(2026, 11, 13, 12, 0, tzinfo=UTC),
        session_id="sess-1",
        message_id="msg-1",
        request_id="req-1",
        model=model,
        input_tokens=10,
        output_tokens=20,
        cache_creation_tokens=0,
        cache_read_tokens=0,
        cost_usd=None,
        project="proj",
    )


def _read_registry() -> dict[str, Any]:
    raw = model_registry.REGISTRY_PATH.read_text(encoding="utf-8")
    return cast(dict[str, Any], json.loads(raw))


def test_first_run_marks_all_sources_as_baseline(monkeypatch: pytest.MonkeyPatch) -> None:
    _write_codex_cache(
        model_registry.CODEX_MODELS_CACHE_PATH,
        identity="fake-identity-1",
        models=[
            {"slug": "gpt-6.1-sol", "visibility": "list", "display_name": "GPT-6.1-Sol"},
            {"slug": "codex-auto-review", "visibility": "hide", "display_name": "Hidden"},
        ],
    )
    monkeypatch.setattr(
        agy_quota_probe,
        "_read_cache",
        lambda: _agy_result(("GEMINI MODELS", ["Gemini Flash", "Gemini Pro"])),
    )
    monkeypatch.setattr(
        pricing,
        "is_model_priced",
        lambda model: model in {"gpt-6.1-sol", "claude-opus-4-8"},
    )
    entries = [
        _adapter_entry("claude-code", "claude-opus-4-8"),
        _adapter_entry("grok", "grok-unpriced-preview"),
    ]

    model_registry.update(entries=entries)

    data = _read_registry()
    assert data["schema_version"] == 1
    assert data["codex_identity"] == "fake-identity-1"
    items = data["items"]
    assert set(items) == {
        "codex_catalog:gpt-6.1-sol",
        "agy_group:gemini models",
        "usage_log:claude-opus-4-8",
        "usage_log:grok-unpriced-preview",
    }
    assert items["codex_catalog:gpt-6.1-sol"]["agent"] == "codex"
    assert items["codex_catalog:gpt-6.1-sol"]["baseline"] is True
    assert items["codex_catalog:gpt-6.1-sol"]["priced"] is True
    assert datetime.fromisoformat(items["codex_catalog:gpt-6.1-sol"]["first_seen"]).tzinfo == UTC

    assert items["agy_group:gemini models"]["agent"] == "antigravity"
    assert items["agy_group:gemini models"]["models"] == ["Gemini Flash", "Gemini Pro"]
    assert items["agy_group:gemini models"]["baseline"] is True
    assert items["agy_group:gemini models"]["priced"] is None

    assert items["usage_log:claude-opus-4-8"]["agent"] == "claude-code"
    assert items["usage_log:claude-opus-4-8"]["baseline"] is True
    assert items["usage_log:claude-opus-4-8"]["priced"] is True

    assert items["usage_log:grok-unpriced-preview"]["agent"] == "grok"
    assert items["usage_log:grok-unpriced-preview"]["baseline"] is True
    assert items["usage_log:grok-unpriced-preview"]["priced"] is False


def test_codex_missing_or_corrupt_is_skipped_without_quarantine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    quarantine_calls: list[tuple[Path, str]] = []
    monkeypatch.setattr(
        cache_quarantine, "quarantine", lambda path, reason: quarantine_calls.append((path, reason))
    )
    monkeypatch.setattr(agy_quota_probe, "_read_cache", lambda: None)
    monkeypatch.setattr(pricing, "is_model_priced", lambda _model: True)

    model_registry.CODEX_MODELS_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    model_registry.CODEX_MODELS_CACHE_PATH.write_text("{broken json", encoding="utf-8")

    model_registry.update(entries=[_adapter_entry("claude-code", "claude-opus-4-8")])

    assert quarantine_calls == []
    data = _read_registry()
    assert list(data["items"]) == ["usage_log:claude-opus-4-8"]
    assert data["codex_identity"] is None


def test_codex_models_cache_path_respects_codex_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    orig_registry = model_registry.REGISTRY_PATH
    orig_codex = model_registry.CODEX_MODELS_CACHE_PATH
    custom_home = tmp_path / "custom-codex"
    monkeypatch.setenv("CODEX_HOME", str(custom_home))
    reloaded = importlib.reload(model_registry)
    try:
        expected = custom_home / "models_cache.json"
        assert expected == reloaded.CODEX_MODELS_CACHE_PATH
    finally:
        monkeypatch.delenv("CODEX_HOME", raising=False)
        importlib.reload(model_registry)
        model_registry.REGISTRY_PATH = orig_registry
        model_registry.CODEX_MODELS_CACHE_PATH = orig_codex


def test_usage_log_filters_invalid_models_and_handles_history_entry_without_agent_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agy_quota_probe, "_read_cache", lambda: None)
    monkeypatch.setattr(pricing, "is_model_priced", lambda _model: True)

    entries = [
        _adapter_entry("claude-code", ""),
        _adapter_entry("claude-code", "   "),
        _adapter_entry("claude-code", "unknown"),
        _adapter_entry("claude-code", "UNKNOWN"),
        _adapter_entry("claude-code", "<synthetic>"),
        _adapter_entry("claude-code", "sub-orchestrator-v1"),
        _adapter_entry("claude-code", "Orchestrator"),
        _history_entry("claude-sonnet-4-6"),
    ]

    model_registry.update(entries=entries)

    data = _read_registry()
    assert list(data["items"]) == ["usage_log:claude-sonnet-4-6"]
    assert data["items"]["usage_log:claude-sonnet-4-6"]["agent"] == "unknown"


def test_corrupt_registry_is_quarantined_and_treated_as_first_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agy_quota_probe, "_read_cache", lambda: None)
    monkeypatch.setattr(pricing, "is_model_priced", lambda _model: True)

    model_registry.REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    model_registry.REGISTRY_PATH.write_text("{corrupt", encoding="utf-8")

    model_registry.update(entries=[_adapter_entry("claude-code", "claude-opus-4-8")])

    backups = list(cache_quarantine.QUARANTINE_DIR.glob("model_registry.json.*.bak"))
    assert len(backups) == 1
    data = _read_registry()
    assert data["items"]["usage_log:claude-opus-4-8"]["baseline"] is True


def test_schema_mismatch_rebuilds_as_baseline_without_quarantine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    quarantine_calls: list[tuple[Path, str]] = []
    monkeypatch.setattr(
        cache_quarantine, "quarantine", lambda path, reason: quarantine_calls.append((path, reason))
    )
    monkeypatch.setattr(agy_quota_probe, "_read_cache", lambda: None)
    monkeypatch.setattr(pricing, "is_model_priced", lambda _model: True)

    model_registry.REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    model_registry.REGISTRY_PATH.write_text(
        json.dumps(
            {
                "schema_version": 99,
                "codex_identity": "fake-old-id",
                "items": {"usage_log:old-model": {"name": "old-model", "baseline": True}},
            }
        ),
        encoding="utf-8",
    )

    model_registry.update(entries=[_adapter_entry("claude-code", "claude-opus-4-8")])

    assert quarantine_calls == []
    data = _read_registry()
    assert data["schema_version"] == 1
    assert list(data["items"]) == ["usage_log:claude-opus-4-8"]
    assert data["items"]["usage_log:claude-opus-4-8"]["baseline"] is True


def test_append_only_preserves_disappeared_items_and_ignores_reappearance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pricing, "is_model_priced", lambda _model: True)
    _write_codex_cache(
        model_registry.CODEX_MODELS_CACHE_PATH,
        identity="fake-identity-1",
        models=[{"slug": "gpt-6.1-sol", "visibility": "list"}],
    )
    monkeypatch.setattr(
        agy_quota_probe,
        "_read_cache",
        lambda: _agy_result(("GEMINI MODELS", ["Gemini Pro"])),
    )

    model_registry.update(entries=[_adapter_entry("claude-code", "claude-opus-4-8")])
    first_data = _read_registry()
    original_first_seen = first_data["items"]["codex_catalog:gpt-6.1-sol"]["first_seen"]

    # All sources disappear on refresh 2 -> items remain untouched.
    model_registry.CODEX_MODELS_CACHE_PATH.unlink()
    monkeypatch.setattr(agy_quota_probe, "_read_cache", lambda: None)
    model_registry.update(entries=[])

    second_data = _read_registry()
    assert second_data == first_data

    # Item reappears on refresh 3 -> still baseline=True, original first_seen kept.
    _write_codex_cache(
        model_registry.CODEX_MODELS_CACHE_PATH,
        identity="fake-identity-1",
        models=[{"slug": "gpt-6.1-sol", "visibility": "list"}],
    )
    model_registry.update(entries=None)

    third_data = _read_registry()
    assert third_data["items"]["codex_catalog:gpt-6.1-sol"]["baseline"] is True
    assert third_data["items"]["codex_catalog:gpt-6.1-sol"]["first_seen"] == original_first_seen


def test_codex_identity_change_marks_new_codex_models_as_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agy_quota_probe, "_read_cache", lambda: None)
    monkeypatch.setattr(pricing, "is_model_priced", lambda _model: True)

    _write_codex_cache(
        model_registry.CODEX_MODELS_CACHE_PATH,
        identity="fake-identity-1",
        models=[{"slug": "gpt-6.1-sol", "visibility": "list"}],
    )
    model_registry.update(entries=[_adapter_entry("claude-code", "claude-opus-5-5")])

    # Account switches to fake-identity-2 with a new Codex model while a new usage_log model
    # arrives.
    _write_codex_cache(
        model_registry.CODEX_MODELS_CACHE_PATH,
        identity="fake-identity-2",
        models=[
            {"slug": "gpt-6.1-sol", "visibility": "list"},
            {"slug": "gpt-6.2-pro", "visibility": "list"},
        ],
    )
    model_registry.update(entries=[_adapter_entry("claude-code", "claude-mythos-6")])

    data = _read_registry()
    assert data["codex_identity"] == "fake-identity-2"
    assert data["items"]["codex_catalog:gpt-6.2-pro"]["baseline"] is True
    assert data["items"]["usage_log:claude-mythos-6"]["baseline"] is False


def test_new_items_and_agy_group_normalization_and_priced_recalculation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    known_priced: set[str] = set()
    monkeypatch.setattr(pricing, "is_model_priced", lambda model: model in known_priced)
    monkeypatch.setattr(
        agy_quota_probe,
        "_read_cache",
        lambda: _agy_result(("GEMINI MODELS", ["Gemini Flash"])),
    )

    model_registry.update(entries=[_adapter_entry("claude-code", "claude-baseline")])
    baseline_data = _read_registry()
    assert baseline_data["items"]["usage_log:claude-baseline"]["baseline"] is True
    assert baseline_data["items"]["usage_log:claude-baseline"]["priced"] is False

    # Refresh 2: new unpriced model + normalized agy group with updated models list.
    monkeypatch.setattr(
        agy_quota_probe,
        "_read_cache",
        lambda: _agy_result(
            ("  gemini   models  ", ["Gemini Flash", "Gemini Pro"]),
            ("Claude GPT", ["Claude Sonnet"]),
        ),
    )
    model_registry.update(entries=[_adapter_entry("claude-code", "claude-new-model")])

    data_r2 = _read_registry()
    assert data_r2["items"]["agy_group:gemini models"]["baseline"] is True
    assert data_r2["items"]["agy_group:gemini models"]["models"] == ["Gemini Flash", "Gemini Pro"]
    assert data_r2["items"]["agy_group:claude gpt"]["baseline"] is False
    assert data_r2["items"]["agy_group:claude gpt"]["priced"] is None
    assert data_r2["items"]["usage_log:claude-new-model"]["baseline"] is False
    assert data_r2["items"]["usage_log:claude-new-model"]["priced"] is False

    # Refresh 3: pricing table now knows both models; only non-baseline recalculates priced.
    known_priced.update({"claude-baseline", "claude-new-model"})
    model_registry.update(entries=[])

    data_r3 = _read_registry()
    assert data_r3["items"]["usage_log:claude-baseline"]["priced"] is False
    assert data_r3["items"]["usage_log:claude-new-model"]["priced"] is True


def test_agy_log_models_baseline_then_new_with_suffixes_collapsed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agy_quota_probe, "_read_cache", lambda: None)
    monkeypatch.setattr(pricing, "is_model_priced", lambda model: model == "gemini-4-hydrogen")
    agy_models: list[str] = []
    monkeypatch.setattr(
        agy_loader,
        "load_entries",
        lambda hours_back=0: [SimpleNamespace(model=model) for model in agy_models],
    )

    model_registry.update(entries=[_history_entry("claude-sonnet-5-5")])
    assert not any(key.startswith("agy_log:") for key in _read_registry()["items"])

    # First Antigravity sighting is a baseline even though the registry already exists.
    agy_models[:] = ["gemini-4-hydrogen", "gemini-3.8-flash-n", "gemini-3.8-flash-tiered"]
    model_registry.update(entries=[])
    items = _read_registry()["items"]
    assert items["agy_log:gemini-4-hydrogen"]["baseline"] is True
    assert items["agy_log:gemini-4-hydrogen"]["agent"] == "antigravity"
    assert items["agy_log:gemini-3.8-flash"]["baseline"] is True
    assert "agy_log:gemini-3.8-flash-n" not in items

    agy_models[:] = [
        "gemini-5-neon-high",
        "gemini-5-neon-xhigh",
        "claude-sonnet-5-5-medium",
        "gemini-pro-orchestrator-g1-pro",
        "unknown",
    ]
    model_registry.update(entries=[])
    items = _read_registry()["items"]
    new_agy = [key for key, item in items.items() if item["baseline"] is False]
    assert new_agy == ["agy_log:gemini-5-neon"]
    assert items["agy_log:gemini-5-neon"]["name"] == "gemini-5-neon"
    assert items["agy_log:gemini-5-neon"]["priced"] is False
    # Already known from Claude Code's own logs, so Antigravity does not announce it again.
    assert "agy_log:claude-sonnet-5-5" not in items


def test_no_write_when_unchanged_and_atomic_write_cleans_tmp_on_failure(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(agy_quota_probe, "_read_cache", lambda: None)
    monkeypatch.setattr(pricing, "is_model_priced", lambda _model: True)

    model_registry.update(entries=[_adapter_entry("claude-code", "claude-opus-4-8")])
    before_bytes = model_registry.REGISTRY_PATH.read_bytes()

    replace_calls = 0
    real_replace = os.replace

    def tracked_replace(src: str | Path, dst: str | Path) -> None:
        nonlocal replace_calls
        replace_calls += 1
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", tracked_replace)
    model_registry.update(entries=[_adapter_entry("claude-code", "claude-opus-4-8")])
    assert replace_calls == 0

    def failing_replace(_src: str | Path, _dst: str | Path) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", failing_replace)
    with caplog.at_level(logging.WARNING, logger=model_registry.__name__):
        model_registry.update(entries=[_adapter_entry("claude-code", "claude-sonnet-5")])

    assert list(model_registry.REGISTRY_PATH.parent.glob("*.tmp")) == []
    assert model_registry.REGISTRY_PATH.read_bytes() == before_bytes
    assert any("Model registry update failed" in record.message for record in caplog.records)


def test_update_swallows_unexpected_exceptions(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def boom() -> tuple[dict[str, Any] | None, bool]:
        raise RuntimeError("unexpected")

    monkeypatch.setattr(model_registry, "_load_registry", boom)
    with caplog.at_level(logging.WARNING, logger=model_registry.__name__):
        model_registry.update(entries=[])

    assert any("Model registry update failed" in record.message for record in caplog.records)


@pytest.mark.skipif(sys.platform != "darwin", reason="menubar/refresh requires macOS imports")
@pytest.mark.parametrize("mock", [False, True])
def test_menubar_refresh_calls_model_registry_only_outside_mock_mode(
    monkeypatch: pytest.MonkeyPatch, mock: bool
) -> None:
    from loaders.claude_usage import PollOutcome, PollState
    from menubar import agy, grok, muse, refresh, state

    captured: list[Any] = []
    monkeypatch.setattr(model_registry, "update", lambda entries=None: captured.append(entries))
    monkeypatch.setattr(quota_snapshot, "write_snapshot", lambda: None)
    monkeypatch.setattr(service_status, "write_snapshot", lambda _statuses: None)
    monkeypatch.setattr(refresh, "get_service_status", lambda _cfg: SimpleNamespace())

    sample_entries = [_history_entry("claude-opus-4-8")]

    async def fake_fetch() -> PollOutcome:
        return PollOutcome(PollState.LOADING)

    missing = state._missing_row("Session", state.CODEX_COLOR)
    app = SimpleNamespace(
        language="en",
        mock=mock,
        latest_state=state._empty_state("en"),
        _load_history_entries=lambda: sample_entries,
        _project_rows=lambda **_kwargs: [],
        _fetch=fake_fetch,
        _statusline_setup_available=lambda: False,
        tracker=SimpleNamespace(group=lambda: 0),
        burn_rate_trackers={},
        _history_load_error_key=None,
    )
    sources = refresh.RefreshSources(
        codex_result={"codex_rows": (missing, missing), "codex_5h_pct": None},
        history_scan=None,
        agy_result=agy.AgyRefreshResult(None, True),
        agy_projection=agy.fallback_projection("en"),
        grok_result=grok.GrokRefreshResult(None, True),
        grok_projection=grok.fallback_projection("en"),
        debug_timing=False,
        muse_result=muse.MuseRefreshResult(None, True),
        muse_projection=muse.fallback_projection("en"),
    )

    refresh.build_result(app, sources)

    assert captured == ([] if mock else [sample_entries])


@pytest.mark.parametrize("mock", [False, True])
def test_wintray_refresh_calls_model_registry_only_outside_mock_mode(
    monkeypatch: pytest.MonkeyPatch, mock: bool
) -> None:
    from menubar import state as menubar_state
    from quota import quota_snapshot
    from wintray import app as wintray_app

    captured: list[Any] = []
    monkeypatch.setattr(model_registry, "update", lambda entries=None: captured.append(entries))
    monkeypatch.setattr(quota_snapshot, "write_snapshot", lambda: None)

    controller = wintray_app._WindowsTrayController(mock=mock, interval=60)
    monkeypatch.setattr(controller, "_ensure_windows_watcher", lambda: None)
    monkeypatch.setattr(
        controller, "_build_state", lambda **_kwargs: menubar_state._empty_state("en")
    )
    monkeypatch.setattr(controller, "_process_quota_notifications", lambda _state: None)
    monkeypatch.setattr(controller, "_update_tray", lambda: None)

    controller._refresh_worker()

    assert captured == ([] if mock else [None])


def test_update_5000_entries_completes_well_under_50ms(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agy_quota_probe, "_read_cache", lambda: None)
    monkeypatch.setattr(pricing, "is_model_priced", lambda _model: True)

    models = [f"claude-test-{idx}" for idx in range(10)]
    entries = [_history_entry(models[i % len(models)]) for i in range(5000)]

    # Warm baseline so steady-state refresh only performs lookup/dedup.
    model_registry.update(entries=entries)

    start = time.perf_counter()
    model_registry.update(entries=entries)
    elapsed_ms = (time.perf_counter() - start) * 1000
    assert elapsed_ms < 50.0


def test_source_seen_for_first_time_later_is_baseline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pricing, "is_model_priced", lambda model: True)
    monkeypatch.setattr(agy_quota_probe, "_read_cache", lambda: None)
    model_registry.update(entries=[_adapter_entry("claude-code", "claude-opus-5-5")])

    # Later refresh: agy gets probed and Codex gets installed for the first time.
    monkeypatch.setattr(
        agy_quota_probe, "_read_cache", lambda: _agy_result(("GEMINI MODELS", ["Gemini Flash"]))
    )
    _write_codex_cache(
        model_registry.CODEX_MODELS_CACHE_PATH,
        models=[{"slug": "gpt-6.1-sol", "visibility": "list"}],
    )
    model_registry.update(entries=[_adapter_entry("claude-code", "claude-fable-5-2")])
    items = _read_registry()["items"]
    assert items["agy_group:gemini models"]["baseline"] is True
    assert items["codex_catalog:gpt-6.1-sol"]["baseline"] is True
    assert items["usage_log:claude-fable-5-2"]["baseline"] is False

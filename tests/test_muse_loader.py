# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import pricing
from adapters import muse
from loaders import muse_loader
from pricing import _fallback_pricing, _resolve_model_key


def _session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "muse" / "sessions"
    monkeypatch.setattr(muse_loader, "MUSE_SESSIONS_DIR", root)
    path = root / "2026" / "09" / "25" / "session-1" / "session.jsonl"
    path.parent.mkdir(parents=True)
    return path


def _event(
    record_id: str,
    timestamp: datetime,
    kind: str,
    usage: dict[str, int],
    *,
    model: str = "muse-spark-1.3",
) -> dict[str, object]:
    review = kind == "automated_review_completed"
    return {
        "id": record_id,
        "recorded_at": int(timestamp.timestamp()) * 1_000_000 + timestamp.microsecond,
        "payload_type": "runtime.session",
        "payload": {
            "kind": "approval" if review else "run",
            "event": {
                "kind": kind,
                "model": {"provider_id": "meta", "model_id": model} if review else model,
                "usage": usage,
            },
        },
    }


def _write(path: Path, records: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")


def test_loads_runs_and_independent_reviews_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _session(tmp_path, monkeypatch)
    now = datetime.now(UTC).replace(microsecond=588779)
    run = _event(
        "run-1",
        now,
        "model_completed",
        {
            "input_tokens": 100,
            "output_tokens": 10,
            "cached_tokens": 70,
            "cache_read_tokens": 70,
            "cache_write_tokens": 0,
        },
    )
    review = _event(
        "review-1",
        now + timedelta(seconds=1),
        "automated_review_completed",
        {
            "input_tokens": 50,
            "non_cached_input_tokens": 30,
            "cached_input_tokens": 20,
            "output_tokens": 4,
            "total_tokens": 54,
        },
        model="muse-spark-1.3-contributor",
    )
    project = tmp_path / "client"
    project.mkdir()
    _write(
        path,
        [
            {
                "payload_type": "runtime.session.route_facts",
                "payload": {"record": {"cwd": "/fallback"}},
            },
            run,
            {
                "payload_type": "runtime.session.metadata",
                "payload": {"record": {"workspace_root": str(project)}},
            },
            review,
            {"retained_frame": {}, "children": [{"record_json": json.dumps(run)}]},
            {
                "payload_type": "runtime.session",
                "payload": {
                    "kind": "run",
                    "event": {
                        "kind": "goal_usage_attribution",
                        "record": {"quantity": {"input_tokens": 100}},
                    },
                },
            },
        ],
    )

    entries = muse_loader.load_entries()

    assert len(entries) == 2
    assert entries[0].timestamp.microsecond == 588779
    assert (entries[0].input_tokens, entries[0].output_tokens, entries[0].cache_read_tokens) == (
        30,
        10,
        70,
    )
    assert entries[0].total_tokens == 110
    assert (entries[1].input_tokens, entries[1].cache_read_tokens) == (30, 20)
    assert entries[1].model == "muse-spark-1.3-contributor"
    assert all(entry.project == "client" for entry in entries)
    monkeypatch.setattr(pricing, "get_pricing", pricing._fallback_pricing)
    assert pricing.calculate_cost(entries[0]) == pytest.approx(
        30 * 1.25e-6 + 10 * 4.25e-6 + 70 * 0.15e-6
    )
    assert pricing.calculate_cost(entries[1]) == pytest.approx(
        30 * 0.1e-6 + 4 * 0.2e-6 + 20 * 0.002e-6
    )
    assert [entry.agent_id for entry in muse.load_entries()] == ["muse", "muse"]
    assert muse.detect() is not None


def test_filters_old_calls_and_uses_route_facts_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _session(tmp_path, monkeypatch)
    old = datetime.now(UTC) - timedelta(hours=3)
    recent = datetime.now(UTC)
    _write(
        path,
        [
            {
                "payload_type": "runtime.session.route_facts",
                "payload": {"record": {"cwd": "/tmp/fallback-project"}},
            },
            _event("old", old, "model_completed", {"input_tokens": 1, "output_tokens": 1}),
            _event("new", recent, "model_completed", {"input_tokens": 2, "output_tokens": 1}),
        ],
    )

    entries = muse_loader.load_entries(hours_back=1)

    assert len(entries) == 1
    assert entries[0].message_id == "new"
    assert entries[0].project == "fallback-project"


def test_prefilter_skips_irrelevant_large_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _session(tmp_path, monkeypatch)
    path.write_bytes(b'{"prompt":"' + b"x" * 100_000 + b'"}\n')
    monkeypatch.setattr(json, "loads", lambda _raw: pytest.fail("parsed prompt"))

    assert muse_loader.load_entries() == []


def test_muse_models_resolve_to_distinct_meta_prices() -> None:
    prices = _fallback_pricing()
    normal = _resolve_model_key("muse-spark-1.3", prices)
    contributor = _resolve_model_key("muse-spark-1.3-contributor", prices)

    assert normal == "meta/muse-spark-1.3"
    assert contributor == "meta/muse-spark-1.3-contributor"
    assert prices[normal]["input_cost_per_token"] > prices[contributor]["input_cost_per_token"]

# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from analyzer import diagnoser
import usage_diagnosis_snapshot as mod


def test_refresh_snapshot_writes_payload_with_generated_at_and_fingerprint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    snapshot = tmp_path / "usage-diagnosis.json"
    monkeypatch.setattr(mod, "SNAPSHOT_PATH", snapshot)
    monkeypatch.setattr(
        diagnoser,
        "_load_records",
        lambda date_from, date_to: (
            [],
            [SimpleNamespace(total_tokens=400)],
        ),
    )
    monkeypatch.setattr(
        diagnoser,
        "analyze_loaded_records",
        lambda **kwargs: diagnoser.DiagnosisResult(
            total_waste_usd=0.0,
            monthly_savings_estimate_usd=0.0,
            total_waste_tokens=40,
            fixable_waste_tokens=20,
            findings=[
                diagnoser.DiagnosisFinding(
                    severity="critical",
                    kind="polluter_dirs",
                    headline_plain="plain",
                    headline_detail="detail",
                    estimated_waste_usd=0.0,
                    estimated_waste_tokens=20,
                    items=[{"label": "node_modules", "n": 3}],
                )
            ],
            suggested_claudeignore="node_modules/",
            has_data=True,
        ),
    )
    now = datetime(2026, 6, 11, 1, 0, tzinfo=timezone.utc)

    assert mod.refresh_snapshot(now=now) is True

    payload = json.loads(snapshot.read_text(encoding="utf-8"))
    assert payload["generated_at"] == "2026-06-11T01:00:00Z"
    assert payload["waste_pct"] == 10.0
    assert payload["findings_fingerprint"].startswith("polluter_dirs:")


def test_refresh_snapshot_skips_when_snapshot_is_younger_than_one_day(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    snapshot = tmp_path / "usage-diagnosis.json"
    monkeypatch.setattr(mod, "SNAPSHOT_PATH", snapshot)
    snapshot.write_text(
        json.dumps({"generated_at": "2026-06-11T01:00:00Z", "findings": []}),
        encoding="utf-8",
    )

    def fail(*args: object, **kwargs: object) -> object:
        raise AssertionError("refresh should be skipped while the snapshot is fresh")

    monkeypatch.setattr(diagnoser, "_load_records", fail)

    assert (
        mod.refresh_snapshot(now=datetime(2026, 6, 11, 12, 0, tzinfo=timezone.utc))
        is False
    )

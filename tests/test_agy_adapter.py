# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

import adapters.registry as registry
import agy_loader
from adapters import agy
from adapters.types import AgentInfo
from i18n import t


@pytest.fixture
def sessions_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    directory = tmp_path / "conversations"
    monkeypatch.setattr(agy_loader, "AGY_SESSIONS_DIR", directory)
    return directory


def test_detect_uses_antigravity_sessions_directory(sessions_dir: Path) -> None:
    assert agy.detect() is None

    sessions_dir.mkdir()

    assert agy.detect() == AgentInfo(
        id="antigravity",
        name=t("agy_name"),
        data_dir=str(sessions_dir),
        installed=True,
    )


def test_load_entries_maps_usage_without_precomputing_cost(
    monkeypatch: pytest.MonkeyPatch,
    sessions_dir: Path,
) -> None:
    source_entries = [
        agy_loader.AgyUsageEntry(
            timestamp=datetime(2026, 7, 12, tzinfo=UTC),
            model="gemini-3-flash-a",
            input_tokens=120,
            output_tokens=30,
            cache_read_tokens=90,
            thinking_tokens=40,
            dedup_key="request-1",
            session_id="session-1",
        ),
        agy_loader.AgyUsageEntry(
            timestamp=datetime(2026, 7, 12, 1, tzinfo=UTC),
            model="gemini-default",
            input_tokens=10,
            output_tokens=2,
            cache_read_tokens=0,
            thinking_tokens=0,
            dedup_key="request-2",
            session_id="session-2",
        ),
    ]
    calls: dict[str, int] = {}

    def fake_load_entries_with_stats(hours_back: int = 0) -> agy_loader.AgyLoadResult:
        calls["hours_back"] = hours_back
        return agy_loader.AgyLoadResult(source_entries, skipped_missing_dedup_key=0)

    monkeypatch.setattr(agy_loader, "load_entries_with_stats", fake_load_entries_with_stats)

    entries = agy.load_entries(hours_back=24)

    assert calls == {"hours_back": 24}
    assert [(entry.model, entry.output_tokens) for entry in entries] == [
        ("gemini-3-flash-preview", 30),
        ("gemini-default", 2),
    ]
    assert entries[0].total_tokens == 240
    assert entries[0].message_id == "request-1"
    assert entries[0].request_id == ""
    assert entries[0].cache_creation_tokens == 0
    assert entries[0].cost_usd is None
    assert entries[0].project == "unknown"
    assert entries[0].agent_id == "antigravity"


def test_normalize_model_covers_tokscale_aliases() -> None:
    assert [
        agy._normalize_model(model)
        for model in [
            "gemini-3-flash-c",
            "gemini-3-flash",
            "gemini-3.1-pro-high",
            "gemini-3.1-pro-low",
            "gemini-3-pro-high",
            "gemini-3-pro-low",
            "gemini-3.5-flash-low",
        ]
    ] == [
        "gemini-3-flash-preview",
        "gemini-3-flash-preview",
        "gemini-3.1-pro",
        "gemini-3.1-pro",
        "gemini-3-pro",
        "gemini-3-pro",
        "gemini-3.5-flash-low",
    ]


def test_registry_includes_antigravity(monkeypatch: pytest.MonkeyPatch) -> None:
    info = AgentInfo("antigravity", "Antigravity", "~/.gemini", True)
    monkeypatch.setattr("adapters.registry.claude.detect", lambda: None)
    monkeypatch.setattr("adapters.registry.codex.detect", lambda: None)
    monkeypatch.setattr("adapters.registry.agy.detect", lambda: info)

    assert registry.detect_agents() == [info]

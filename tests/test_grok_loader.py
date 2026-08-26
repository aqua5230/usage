# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from loaders import grok_loader
from loaders.history_loader import UsageEntry

_SID = "01a03d99-8448-79c3-9d38-c2d71322a08f"
_CWD = "/tmp/usage-grok-project"


@pytest.fixture
def grok_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, Path]:
    grok_home = tmp_path / ".grok"
    log_path = grok_home / "logs" / "unified.jsonl"
    config_path = grok_home / "config.toml"
    log_path.parent.mkdir(parents=True)
    monkeypatch.setattr(grok_loader, "GROK_HOME", grok_home)
    monkeypatch.setattr(grok_loader, "GROK_LOG_PATH", log_path)
    monkeypatch.setattr(grok_loader, "GROK_CONFIG_PATH", config_path)
    return log_path, config_path


def _write_config(path: Path, default: str = "grok-4.6") -> None:
    path.write_text(f'[models]\ndefault = "{default}"\n', encoding="utf-8")


def _event(ts: str, sid: str, msg: str, ctx: dict[str, object]) -> str:
    return json.dumps({"ts": ts, "sid": sid, "msg": msg, "ctx": ctx})


def _inference_ctx(
    loop_index: int,
    *,
    prompt_tokens: int = 43700,
    cached_prompt_tokens: int = 43392,
    completion_tokens: int = 72,
    reasoning_tokens: int = 13,
) -> dict[str, object]:
    return {
        "loop_index": loop_index,
        "prompt_tokens": prompt_tokens,
        "cached_prompt_tokens": cached_prompt_tokens,
        "completion_tokens": completion_tokens,
        "reasoning_tokens": reasoning_tokens,
    }


def _write_log(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_load_entries_maps_inference_and_looks_up_model_and_project(
    grok_paths: tuple[Path, Path],
) -> None:
    log_path, config_path = grok_paths
    _write_config(config_path, default="should-not-be-used")
    _write_log(
        log_path,
        [
            _event(
                "2026-08-26T10:24:27.064Z",
                _SID,
                "session created",
                {"cwd": _CWD},
            ),
            _event(
                "2026-08-26T10:24:27.200Z",
                _SID,
                "model changed",
                {"model": "grok-4.6"},
            ),
            _event(
                "2026-08-26T10:24:38.127Z",
                _SID,
                "shell.turn.inference_done",
                _inference_ctx(1),
            ),
            _event(
                "2026-08-26T10:24:45.146Z",
                _SID,
                "shell.turn.inference_done",
                _inference_ctx(
                    2,
                    prompt_tokens=32215,
                    cached_prompt_tokens=18688,
                    completion_tokens=329,
                    reasoning_tokens=40,
                ),
            ),
        ],
    )

    entries = grok_loader.load_entries()

    assert len(entries) == 2
    first, second = entries
    assert first.timestamp == datetime(2026, 8, 26, 10, 24, 38, 127000, tzinfo=UTC)
    assert first.session_id == _SID
    assert first.message_id == f"{_SID}:1"
    assert first.request_id == f"{_SID}:1"
    assert first.model == "grok-4.6"
    assert first.input_tokens == 43700 - 43392
    assert first.output_tokens == 72
    assert first.cache_creation_tokens == 0
    assert first.cache_read_tokens == 43392
    assert first.cost_usd is None
    assert first.project == "usage-grok-project"
    assert second.message_id == f"{_SID}:2"
    assert second.input_tokens == 32215 - 18688
    assert second.output_tokens == 329
    assert second.cache_read_tokens == 18688
    assert second.model == "grok-4.6"
    assert second.project == "usage-grok-project"
    assert [entry.timestamp for entry in entries] == sorted(
        entry.timestamp for entry in entries
    )


def test_load_entries_uses_model_in_effect_after_mid_session_switch(
    grok_paths: tuple[Path, Path],
) -> None:
    log_path, config_path = grok_paths
    _write_config(config_path)
    sid = "01a039b3-7a4a-7372-a3fd-4ed1068aad06"
    _write_log(
        log_path,
        [
            _event("2026-08-25T16:14:19.500Z", sid, "session created", {"cwd": _CWD}),
            _event("2026-08-25T16:14:19.557Z", sid, "model changed", {"model": "grok-4.6"}),
            _event(
                "2026-08-25T16:14:21.454Z",
                sid,
                "shell.turn.inference_done",
                _inference_ctx(1, prompt_tokens=100, cached_prompt_tokens=10),
            ),
            _event(
                "2026-08-25T16:14:22.590Z",
                sid,
                "model changed",
                {"model": "deepseek-chat"},
            ),
            _event(
                "2026-08-25T16:14:24.059Z",
                sid,
                "shell.turn.inference_done",
                _inference_ctx(2, prompt_tokens=200, cached_prompt_tokens=20),
            ),
        ],
    )

    entries = grok_loader.load_entries()

    assert [entry.model for entry in entries] == ["grok-4.6", "deepseek-chat"]
    assert [entry.message_id for entry in entries] == [f"{sid}:1", f"{sid}:2"]


def test_load_entries_falls_back_to_config_default_without_model_changed(
    grok_paths: tuple[Path, Path],
) -> None:
    log_path, config_path = grok_paths
    _write_config(config_path, default="deepseek-reasoner")
    _write_log(
        log_path,
        [
            _event("2026-08-26T10:24:27.064Z", _SID, "session created", {"cwd": _CWD}),
            _event(
                "2026-08-26T10:24:38.127Z",
                _SID,
                "shell.turn.inference_done",
                _inference_ctx(1),
            ),
        ],
    )

    entries = grok_loader.load_entries()

    assert len(entries) == 1
    assert entries[0].model == "deepseek-reasoner"


def test_load_entries_returns_empty_list_when_log_is_missing(
    grok_paths: tuple[Path, Path],
) -> None:
    log_path, config_path = grok_paths
    _write_config(config_path)
    assert not log_path.exists()

    assert grok_loader.load_entries() == []


def test_load_entries_skips_malformed_json_and_keeps_valid_rows(
    grok_paths: tuple[Path, Path],
) -> None:
    log_path, config_path = grok_paths
    _write_config(config_path)
    _write_log(
        log_path,
        [
            _event("2026-08-26T10:24:27.064Z", _SID, "session created", {"cwd": _CWD}),
            _event("2026-08-26T10:24:27.200Z", _SID, "model changed", {"model": "grok-4.6"}),
            "{not json}",
            _event(
                "2026-08-26T10:24:38.127Z",
                _SID,
                "shell.turn.inference_done",
                _inference_ctx(1),
            ),
            _event(
                "2026-08-26T10:24:45.146Z",
                _SID,
                "shell.turn.inference_done",
                _inference_ctx(2, prompt_tokens=10, cached_prompt_tokens=0),
            ),
        ],
    )

    entries = grok_loader.load_entries()

    assert len(entries) == 2
    assert [entry.message_id for entry in entries] == [f"{_SID}:1", f"{_SID}:2"]


def test_load_entries_skips_legacy_inference_without_token_fields(
    grok_paths: tuple[Path, Path],
) -> None:
    log_path, config_path = grok_paths
    _write_config(config_path)
    _write_log(
        log_path,
        [
            _event("2026-08-26T10:24:27.200Z", _SID, "model changed", {"model": "grok-4.6"}),
            _event(
                "2026-06-06T16:06:43.986Z",
                _SID,
                "shell.turn.inference_done",
                {"loop_index": 1, "model_elapsed_ms": 1656},
            ),
            _event(
                "2026-08-26T10:24:38.127Z",
                _SID,
                "shell.turn.inference_done",
                _inference_ctx(1),
            ),
        ],
    )

    entries = grok_loader.load_entries()

    assert len(entries) == 1
    assert entries[0].message_id == f"{_SID}:1"
    assert entries[0].input_tokens == 308


def test_load_entries_uses_empty_project_without_session_created(
    grok_paths: tuple[Path, Path],
) -> None:
    log_path, config_path = grok_paths
    _write_config(config_path)
    _write_log(
        log_path,
        [
            _event("2026-08-26T10:24:27.200Z", _SID, "model changed", {"model": "grok-4.6"}),
            _event(
                "2026-08-26T10:24:38.127Z",
                _SID,
                "shell.turn.inference_done",
                _inference_ctx(1),
            ),
        ],
    )

    entries = grok_loader.load_entries()

    assert len(entries) == 1
    assert entries[0].project == ""
    assert entries[0].model == "grok-4.6"


def test_load_entries_keeps_reused_loop_index_as_separate_requests(
    grok_paths: tuple[Path, Path],
) -> None:
    log_path, config_path = grok_paths
    _write_config(config_path)
    _write_log(
        log_path,
        [
            _event("2026-08-26T10:24:27.200Z", _SID, "model changed", {"model": "grok-4.6"}),
            _event(
                "2026-08-26T10:24:38.127Z",
                _SID,
                "shell.turn.inference_done",
                _inference_ctx(1, prompt_tokens=100, cached_prompt_tokens=0),
            ),
            _event(
                "2026-08-26T10:25:13.533Z",
                _SID,
                "shell.turn.inference_done",
                _inference_ctx(1, prompt_tokens=200, cached_prompt_tokens=0),
            ),
        ],
    )

    entries = grok_loader.load_entries()

    assert len(entries) == 2
    assert entries[0].message_id == entries[1].message_id == f"{_SID}:1"
    assert [entry.input_tokens for entry in entries] == [100, 200]


def test_load_entries_filters_by_hours_back(grok_paths: tuple[Path, Path]) -> None:
    log_path, config_path = grok_paths
    _write_config(config_path)
    now = datetime.now(UTC)
    old_ts = (now - timedelta(hours=5)).isoformat().replace("+00:00", "Z")
    recent_ts = (now - timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
    model_ts = (now - timedelta(hours=6)).isoformat().replace("+00:00", "Z")
    _write_log(
        log_path,
        [
            _event(model_ts, _SID, "model changed", {"model": "grok-4.6"}),
            _event(
                old_ts,
                _SID,
                "shell.turn.inference_done",
                _inference_ctx(1, prompt_tokens=50, cached_prompt_tokens=0),
            ),
            _event(
                recent_ts,
                _SID,
                "shell.turn.inference_done",
                _inference_ctx(2, prompt_tokens=80, cached_prompt_tokens=0),
            ),
        ],
    )

    all_entries = grok_loader.load_entries()
    recent_entries = grok_loader.load_entries(hours_back=1)

    assert len(all_entries) == 2
    assert len(recent_entries) == 1
    assert recent_entries[0].message_id == f"{_SID}:2"
    assert recent_entries[0].model == "grok-4.6"


def test_load_entries_falls_back_to_unknown_without_config(
    grok_paths: tuple[Path, Path],
) -> None:
    log_path, _config_path = grok_paths
    _write_log(
        log_path,
        [
            _event(
                "2026-08-26T10:24:38.127Z",
                _SID,
                "shell.turn.inference_done",
                _inference_ctx(1),
            ),
        ],
    )

    entries = grok_loader.load_entries()

    assert len(entries) == 1
    assert entries[0].model == "unknown"
    assert isinstance(entries[0], UsageEntry)
    assert entries[0].cost_usd is None

# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from analyzer import ai_updates_loader


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def _payload(*, include_invalid: bool = False) -> dict[str, Any]:
    tools: list[dict[str, Any]] = [
        {
            "id": "codex",
            "name": "Codex",
            "versions": [
                {
                    "version": "0.141.0",
                    "period": "2026-06-18",
                    "items": [
                        {
                            "title": {"en": "Remote execution"},
                            "body": {"en": "Remote execution got better."},
                            "original": "Remote execution got better.",
                        }
                    ],
                }
            ],
        }
    ]
    if include_invalid:
        tools.extend(
            [
                {"id": "broken"},
                {
                    "id": "claude_code",
                    "name": "Claude Code",
                    "versions": [
                        {
                            "version": "2.1.183",
                            "period": "2026-06-13 ~ 06-19",
                            "items": [
                                {
                                    "title": {"en": "Valid title"},
                                    "body": {"en": "Valid body"},
                                    "original": "Valid original.",
                                },
                                {
                                    "title": {"en": "Missing original"},
                                    "body": {"en": "Should be skipped"},
                                },
                            ],
                        },
                        {
                            "version": "2.1.182",
                            "period": "2026-06-10 ~ 06-12",
                            "items": [],
                        },
                    ],
                },
                {
                    "id": "agy",
                    "name": "agy",
                    "versions": [
                        {
                            "version": "1.0.10",
                            "period": "最新版 1.0.10",
                            "items": [
                                {
                                    "title": "not-a-dict",
                                    "body": {"en": "Bad title type"},
                                    "original": "Bad title type.",
                                },
                                {
                                    "title": {"en": "Bad body"},
                                    "body": "not-a-dict",
                                    "original": "Bad body type.",
                                },
                            ],
                        }
                    ],
                },
                {
                    "id": "empty_versions",
                    "name": "Empty Versions",
                    "versions": [
                        {
                            "version": "0.0.1",
                            "period": "2026-06-10",
                            "items": [],
                        }
                    ],
                },
            ]
        )
    return {"tools": tools}


@pytest.fixture(autouse=True)
def _patch_cache_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(ai_updates_loader, "CACHE_PATH", tmp_path / "ai_updates_cache.json")


def test_load_ai_updates_prefers_fresh_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    ai_updates_loader.CACHE_PATH.write_text(
        json.dumps(_payload()),
        encoding="utf-8",
    )

    def fail_urlopen(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network should not be used")

    monkeypatch.setattr(urllib.request, "urlopen", fail_urlopen)

    result = ai_updates_loader.load_ai_updates()

    assert result == _payload()["tools"]


def test_load_ai_updates_refetches_when_cache_is_legacy_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy_payload = {
        "tools": [
            {
                "id": "codex",
                "name": "Codex",
                "version": "0.141.0",
                "period": "2026-06-18",
                "items": [
                    {
                        "title": {"en": "Remote execution"},
                        "body": {"en": "Remote execution got better."},
                        "original": "Remote execution got better.",
                    }
                ],
            }
        ]
    }
    ai_updates_loader.CACHE_PATH.write_text(
        json.dumps(legacy_payload),
        encoding="utf-8",
    )

    payload = _payload()

    def fake_urlopen(*_args: object, **_kwargs: object) -> _FakeResponse:
        return _FakeResponse(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    result = ai_updates_loader.load_ai_updates()

    assert result == payload["tools"]


def test_load_ai_updates_fetches_and_caches_when_cache_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _payload()

    def fake_urlopen(*_args: object, **_kwargs: object) -> _FakeResponse:
        return _FakeResponse(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    result = ai_updates_loader.load_ai_updates()

    assert result == payload["tools"]
    assert json.loads(ai_updates_loader.CACHE_PATH.read_text(encoding="utf-8")) == payload


def test_load_ai_updates_returns_stale_cache_when_fetch_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _payload()
    ai_updates_loader.CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    ai_updates_loader.CACHE_PATH.write_text(json.dumps(payload), encoding="utf-8")
    stale_mtime = time.time() - ai_updates_loader.CACHE_TTL_SECONDS - 5
    os.utime(ai_updates_loader.CACHE_PATH, (stale_mtime, stale_mtime))

    def fail_urlopen(*_args: object, **_kwargs: object) -> None:
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(urllib.request, "urlopen", fail_urlopen)

    result = ai_updates_loader.load_ai_updates()

    assert result == payload["tools"]


def test_load_ai_updates_returns_none_for_invalid_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {"generated_at": "2026-06-20"}

    def fake_urlopen(*_args: object, **_kwargs: object) -> _FakeResponse:
        return _FakeResponse(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    assert ai_updates_loader.load_ai_updates() is None


def test_load_ai_updates_skips_tools_missing_required_fields() -> None:
    ai_updates_loader.CACHE_PATH.write_text(
        json.dumps(_payload(include_invalid=True)),
        encoding="utf-8",
    )

    result = ai_updates_loader.load_ai_updates()

    assert result == [
        *_payload()["tools"],
        {
            "id": "claude_code",
            "name": "Claude Code",
            "versions": [
                {
                    "version": "2.1.183",
                    "period": "2026-06-13 ~ 06-19",
                    "items": [
                        {
                            "title": {"en": "Valid title"},
                            "body": {"en": "Valid body"},
                            "original": "Valid original.",
                        }
                    ],
                }
            ],
        },
    ]


def test_load_ai_updates_skips_invalid_items_and_empty_tools() -> None:
    payload = _payload(include_invalid=True)

    normalized = ai_updates_loader._normalize_payload(payload)

    assert normalized == [
        *_payload()["tools"],
        {
            "id": "claude_code",
            "name": "Claude Code",
            "versions": [
                {
                    "version": "2.1.183",
                    "period": "2026-06-13 ~ 06-19",
                    "items": [
                        {
                            "title": {"en": "Valid title"},
                            "body": {"en": "Valid body"},
                            "original": "Valid original.",
                        }
                    ],
                }
            ],
        },
    ]


def test_load_ai_updates_returns_none_for_bad_json_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ai_updates_loader.CACHE_PATH.write_text("{", encoding="utf-8")

    def fail_urlopen(*_args: object, **_kwargs: object) -> None:
        raise urllib.error.URLError("network disabled in test")

    monkeypatch.setattr(urllib.request, "urlopen", fail_urlopen)

    assert ai_updates_loader.load_ai_updates() is None

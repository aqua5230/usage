from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path
from typing import Any

import pytest

import ai_daily_loader


class _Response:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return self.payload

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def _item() -> dict[str, Any]:
    localized = {key: "text" for key in ("zh-TW", "zh-CN", "en", "ja", "ko")}
    return {"title": localized, "body": localized, "original": "original"}


def _payload() -> dict[str, Any]:
    return {
        "generated_at": "2026-07-13T00:00:00Z",
        "tools": [{
            "id": "codex", "name": "Codex", "versions": [
                {"version": "1", "period": "today", "curated": True, "items": [_item()]},
                {
                    "version": "0",
                    "period": "yesterday",
                    "curated": False,
                    "items": [{"original": "raw"}],
                },
            ],
        }],
    }


@pytest.fixture(autouse=True)
def _cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(ai_daily_loader, "CACHE_PATH", tmp_path / "ai_daily.json")


def test_fresh_cache_skips_network(monkeypatch: pytest.MonkeyPatch) -> None:
    ai_daily_loader.CACHE_PATH.write_text(json.dumps(_payload()), encoding="utf-8")
    monkeypatch.setattr(urllib.request, "urlopen", lambda *_a, **_k: pytest.fail("network"))
    assert ai_daily_loader.load_ai_daily() == _payload()


def test_bad_json_fetch_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", lambda *_a, **_k: _Response(b"{"))
    assert ai_daily_loader.load_ai_daily() is None


def test_offline_returns_stale_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    ai_daily_loader.CACHE_PATH.write_text(json.dumps(_payload()), encoding="utf-8")
    stale = time.time() - ai_daily_loader.CACHE_TTL_SECONDS - 1
    os.utime(ai_daily_loader.CACHE_PATH, (stale, stale))
    def offline(*_args: object, **_kwargs: object) -> None:
        raise OSError("offline")

    monkeypatch.setattr(urllib.request, "urlopen", offline)
    assert ai_daily_loader.load_ai_daily() == _payload()


@pytest.mark.parametrize("mutation", [
    lambda data: data.pop("generated_at"),
    lambda data: data["tools"][0]["versions"][0].update(curated="yes"),
    lambda data: data["tools"][0]["versions"][1]["items"][0].update(title={}),
    lambda data: data["tools"][0]["versions"][0]["items"][0]["title"].pop("ko"),
])
def test_schema_rejects_invalid_payload(mutation: Any) -> None:
    data = _payload()
    mutation(data)
    assert ai_daily_loader._normalize_payload(data) is None


def test_schema_accepts_curated_and_raw_shapes() -> None:
    assert ai_daily_loader._normalize_payload(_payload()) == _payload()

# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>

from __future__ import annotations

import socket
import urllib.request

import pytest

from usage_common import network


@pytest.fixture(autouse=True)
def _no_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(urllib.request, "getproxies", dict)


class _Connection:
    def __enter__(self) -> _Connection:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def test_reachable_when_connection_opens(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[tuple[str, int], float]] = []

    def connect(address: tuple[str, int], timeout: float) -> _Connection:
        seen.append((address, timeout))
        return _Connection()

    monkeypatch.setattr(socket, "create_connection", connect)

    assert network.google_auth_reachable(timeout=1.5) is True
    assert seen == [(("oauth2.googleapis.com", 443), 1.5)]


@pytest.mark.parametrize("error", [socket.gaierror("no dns"), TimeoutError(), OSError("down")])
def test_unreachable_when_connection_fails(monkeypatch: pytest.MonkeyPatch, error: OSError) -> None:
    def connect(address: tuple[str, int], timeout: float) -> _Connection:
        raise error

    monkeypatch.setattr(socket, "create_connection", connect)

    assert network.google_auth_reachable() is False


def test_configured_proxy_counts_as_reachable(monkeypatch: pytest.MonkeyPatch) -> None:
    def connect(address: tuple[str, int], timeout: float) -> _Connection:
        raise AssertionError("a proxy-only network blocks the direct probe")

    monkeypatch.setattr(urllib.request, "getproxies", lambda: {"https": "http://proxy:8080"})
    monkeypatch.setattr(socket, "create_connection", connect)

    assert network.google_auth_reachable() is True

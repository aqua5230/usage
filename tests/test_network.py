# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>

from __future__ import annotations

import socket
import subprocess
import threading
import time
import urllib.request

import pytest

from loaders.agy_quota_probe import _probe_via_cli
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


@pytest.mark.parametrize("no_proxy", ["oauth2.googleapis.com", ".googleapis.com", "*"])
def test_proxy_bypass_keeps_offline_probe_and_does_not_launch_cli(
    monkeypatch: pytest.MonkeyPatch, no_proxy: str
) -> None:
    from loaders import agy_quota_probe

    monkeypatch.setattr(
        urllib.request, "getproxies", lambda: {"https": "http://proxy:8080", "no": no_proxy}
    )
    monkeypatch.setenv("no_proxy", no_proxy)
    probes = []

    def connect(address: tuple[str, int], timeout: float) -> _Connection:
        probes.append(address)
        raise OSError("offline")

    def launch(*args: object, **kwargs: object) -> None:
        raise AssertionError("offline checks must not launch the CLI")

    monkeypatch.setattr(socket, "create_connection", connect)
    monkeypatch.setattr(agy_quota_probe, "google_auth_reachable", network.google_auth_reachable)
    monkeypatch.setattr(agy_quota_probe, "find_agy", lambda: "/fake/agy")
    monkeypatch.setattr(agy_quota_probe, "_credential_fingerprint", lambda: "fake")
    monkeypatch.setattr(subprocess, "run", launch)

    assert network.google_auth_reachable() is False
    assert _probe_via_cli(15) is None
    assert probes == [("oauth2.googleapis.com", 443)] * 2
    assert not agy_quota_probe.CLI_SIGNED_OUT_PATH.exists()


def test_hung_dns_returns_within_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def resolve(*args: object, **kwargs: object) -> list[object]:
        try:
            entered.set()
            release.wait()
            raise socket.gaierror("no dns")
        finally:
            finished.set()

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    start = time.monotonic()
    try:
        assert network.google_auth_reachable(timeout=0.05) is False
        assert entered.is_set()
        assert time.monotonic() - start < 0.5
    finally:
        release.set()
        assert finished.wait(0.5)


def test_no_proxy_alone_keeps_the_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, int]] = []

    def connect(address: tuple[str, int], timeout: float) -> _Connection:
        seen.append(address)
        raise OSError("down")

    monkeypatch.setattr(urllib.request, "getproxies", lambda: {"no": "localhost"})
    monkeypatch.setattr(socket, "create_connection", connect)

    assert network.google_auth_reachable() is False
    assert seen == [("oauth2.googleapis.com", 443)]

# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Cheap reachability check used before launching CLIs that may fall back to a browser login."""

from __future__ import annotations

import socket
import threading
import urllib.request
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeoutError

# The host the Antigravity CLI refreshes its OAuth token against.
_GOOGLE_AUTH_HOST = "oauth2.googleapis.com"
_PROBE_TIMEOUT_SECONDS = 3.0


def google_auth_reachable(timeout: float = _PROBE_TIMEOUT_SECONDS) -> bool:
    """Return whether a TCP connection to Google's OAuth host can be opened.

    Right after a sleep wake the network is often still down. The Antigravity CLI
    treats a failed token refresh as "not logged in" and opens a browser sign-in
    page, so callers skip launching it while this returns False.

    A proxy-only network blocks this direct probe even though the CLI can connect
    through the proxy, so a configured proxy counts as reachable.
    """
    if urllib.request.getproxies():
        return True
    result: Future[bool] = Future()

    def probe() -> None:
        try:
            with socket.create_connection((_GOOGLE_AUTH_HOST, 443), timeout=timeout):
                result.set_result(True)
        except OSError:
            result.set_result(False)
        except BaseException as exc:
            result.set_exception(exc)

    threading.Thread(target=probe, daemon=True).start()
    try:
        return result.result(timeout=timeout)
    except FutureTimeoutError:
        return False

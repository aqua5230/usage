# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Launch decisions and background release fetching, independent of either UI."""

from __future__ import annotations

import json
import logging
import threading
import urllib.error
import urllib.request
import webbrowser
from collections.abc import Callable, Mapping
from typing import Any, Literal

from updates.checker import (
    MAX_RESPONSE_BYTES,
    ReleaseCheckResult,
    ReleaseInfo,
    _release_from_payload,
    compare_versions,
)
from usage_common.prefs import _load_preferences, _save_preferences

logger = logging.getLogger(__name__)


def launch_action(
    current_version: str, snapshot: Mapping[str, Any]
) -> Literal["fetch", "record", "none"]:
    """Decide before any startup migration has written preferences."""
    if "last_launched_version" not in snapshot:
        return "fetch" if snapshot else "record"
    previous = snapshot["last_launched_version"]
    if not isinstance(previous, str):
        return "record"
    try:
        comparison = compare_versions(current_version, previous)
    except ValueError:
        return "record"
    return "fetch" if comparison > 0 else "record" if comparison < 0 else "none"


def release_action(result: ReleaseCheckResult) -> Literal["retry", "record", "show"]:
    """Only failed requests retry; missing releases and empty notes finish silently."""
    if result.failed:
        return "retry"
    if result.release is None or not result.release.body.strip():
        return "record"
    return "show"


def fetch_release(version: str, *, timeout: float = 5.0) -> ReleaseCheckResult:
    request = urllib.request.Request(
        f"https://api.github.com/repos/aqua5230/usage/releases/tags/v{version}",
        headers={"Accept": "application/vnd.github+json", "User-Agent": f"usage/{version}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError("release response exceeds the size limit")
        release = _release_from_payload(json.loads(raw.decode("utf-8")))
        if release is None or release.version != version:
            raise ValueError("release response does not match the launched version")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return ReleaseCheckResult(None)
        logger.warning("What's new request failed for %s: HTTP %s", version, exc.code)
        return ReleaseCheckResult(None, failed=True)
    except (ValueError, urllib.error.URLError, OSError) as exc:
        logger.warning("What's new request failed for %s: %s", version, exc)
        return ReleaseCheckResult(None, failed=True)
    return ReleaseCheckResult(release)


def record_version(version: str) -> None:
    # Preserve preferences changed while the network request or dialog was pending.
    preferences = _load_preferences()
    preferences["last_launched_version"] = version
    _save_preferences(preferences)


def start_notice(
    version: str,
    snapshot: Mapping[str, Any],
    show: Callable[[ReleaseInfo], bool],
    dispatch: Callable[[Callable[[], None]], None],
) -> None:
    action = launch_action(version, snapshot)
    if action == "record":
        record_version(version)
    elif action == "fetch":
        threading.Thread(
            target=_fetch_and_dispatch, args=(version, show, dispatch), daemon=True
        ).start()


def _fetch_and_dispatch(
    version: str,
    show: Callable[[ReleaseInfo], bool],
    dispatch: Callable[[Callable[[], None]], None],
) -> None:
    result = fetch_release(version)
    action = release_action(result)
    if action == "record":
        record_version(version)
    elif action == "show" and result.release is not None:
        release = result.release

        def finish() -> None:
            open_notes = show(release)
            record_version(version)
            if open_notes:
                webbrowser.open(release.html_url)

        dispatch(finish)

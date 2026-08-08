# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Shared disk cache lifecycle control flow for usage loaders."""

from __future__ import annotations

import contextlib
from collections.abc import Callable


def needs_cache_seed(seeded: bool) -> bool:
    return not seeded


def flush_caches_if_due(
    dirty: bool,
    last_flush_at: float | None,
    monotonic: Callable[[], float],
    interval_s: float,
    flush: Callable[[], None],
    *,
    force: bool = False,
) -> tuple[bool, float | None]:
    if not dirty:
        return dirty, last_flush_at
    now = monotonic()
    if not force and last_flush_at is not None and now - last_flush_at < interval_s:
        return dirty, last_flush_at
    flush()
    return False, now


def flush_caches_on_terminate(flush: Callable[[], None]) -> None:
    with contextlib.suppress(Exception):
        flush()

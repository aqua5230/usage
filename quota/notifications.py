# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from quota.burn_rate import RESET_DROP_PERCENT

if TYPE_CHECKING:
    from menubar.state import QuotaRowState


def quota_reading(row: QuotaRowState, available: bool = True) -> tuple[float | None, bool]:
    """An available empty reading silently closes an expired quota window."""
    if available and row.available and row.reset_done:
        return None, True
    available = available and row.available and not getattr(row, "carried", False)
    return row.percent, available


NotificationKind = Literal["warn", "depleted", "restored"]

VALID_CHANNELS = frozenset(
    {
        "claude_session",
        "claude_weekly",
        "codex_session",
        "codex_weekly",
        "agy_session",
        "agy_weekly",
        "muse_session",
        "muse_weekly",
    }
)

CHANNEL_HIDE_PREF_KEYS: dict[str, str] = {
    "claude_": "hide_claude_section",
    "codex_": "hide_codex_section",
    "agy_": "hide_agy_section",
    "muse_": "hide_muse_section",
}


def channel_hide_pref_key(channel: str) -> str | None:
    """Return the preference key that hides ``channel``'s card, or ``None``."""
    for prefix, pref_key in CHANNEL_HIDE_PREF_KEYS.items():
        if channel.startswith(prefix):
            return pref_key
    return None


@dataclass(slots=True)
class NotificationEvent:
    kind: NotificationKind
    channel: str
    threshold: float | None


@dataclass(slots=True)
class _ChannelState:
    last_percent: float | None = None
    warned_thresholds: set[float] = field(default_factory=set)
    depleted: bool = False


class QuotaNotifier:
    def __init__(self, thresholds: list[float] | None = None) -> None:
        values = [90.0] if thresholds is None else thresholds
        self.set_thresholds(values)
        # Keyed by (channel, scope): one channel can show different quota pools,
        # e.g. Antigravity's Gemini and Argon groups. Switching the shown pool
        # must not read as a reset of the other one.
        self._channels: dict[tuple[str, str], _ChannelState] = {}

    def set_thresholds(self, values: list[float]) -> None:
        """Replace thresholds without resetting channel observations or warning latches."""
        self.thresholds = sorted({float(value) for value in values})

    def update(
        self,
        channels: dict[str, tuple[float | None, bool]],
        scopes: dict[str, str] | None = None,
    ) -> list[NotificationEvent]:
        events: list[NotificationEvent] = []
        for channel, (percent, available) in channels.items():
            if channel not in VALID_CHANNELS:
                continue
            scope = (scopes or {}).get(channel, "")
            events.extend(self._update_channel(channel, scope, percent, available))
        return events

    def _update_channel(
        self,
        channel: str,
        scope: str,
        percent: float | None,
        available: bool,
    ) -> list[NotificationEvent]:
        state = self._channels.setdefault((channel, scope), _ChannelState())
        events: list[NotificationEvent] = []
        if not available:
            return events
        if percent is None:
            self._channels[(channel, scope)] = _ChannelState()
            return events
        current = float(percent) if percent is not None else None

        reset = (
            current is not None
            and state.last_percent is not None
            and (state.last_percent - current) > RESET_DROP_PERCENT
        )
        if reset:
            was_depleted = state.depleted
            state.warned_thresholds.clear()
            state.depleted = False
            if was_depleted and available and current is not None and current < 100.0:
                events.append(NotificationEvent("restored", channel, None))

        depleted = current is not None and current >= 100.0
        if depleted:
            if not state.depleted:
                events.append(NotificationEvent("depleted", channel, None))
            state.depleted = True
        elif current is not None:
            previous = state.last_percent
            crossed = [
                threshold
                for threshold in self.thresholds
                if (threshold <= current if previous is None else previous < threshold <= current)
                and threshold not in state.warned_thresholds
            ]
            if crossed:
                # One reading can cross several thresholds at once — a first
                # observation already past 90%, or a single large jump. Warn on the
                # highest and latch the rest so one reading sends one notification.
                state.warned_thresholds.update(crossed)
                events.append(NotificationEvent("warn", channel, crossed[-1]))

        if current is not None:
            state.last_percent = current
        return events

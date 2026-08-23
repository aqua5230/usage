# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from burn_rate import RESET_DROP_PERCENT

NotificationKind = Literal["warn", "depleted", "restored"]

VALID_CHANNELS = frozenset(
    {
        "claude_session",
        "claude_weekly",
        "codex_session",
        "codex_weekly",
        "agy_session",
        "agy_weekly",
    }
)


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
        self.thresholds = sorted({float(value) for value in values})
        self._channels = {channel: _ChannelState() for channel in VALID_CHANNELS}

    def update(
        self,
        channels: dict[str, tuple[float | None, bool]],
    ) -> list[NotificationEvent]:
        events: list[NotificationEvent] = []
        for channel, (percent, available) in channels.items():
            if channel not in VALID_CHANNELS:
                continue
            events.extend(self._update_channel(channel, percent, available))
        return events

    def _update_channel(
        self,
        channel: str,
        percent: float | None,
        available: bool,
    ) -> list[NotificationEvent]:
        state = self._channels[channel]
        events: list[NotificationEvent] = []
        if not available:
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
            if previous is not None:
                for threshold in self.thresholds:
                    crossed = previous < threshold <= current
                    if crossed and threshold not in state.warned_thresholds:
                        events.append(NotificationEvent("warn", channel, threshold))
                        state.warned_thresholds.add(threshold)
            state.depleted = False

        if current is not None:
            state.last_percent = current
        return events

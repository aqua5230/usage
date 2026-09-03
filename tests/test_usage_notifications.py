# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

from usage_notifications import QuotaNotifier


def test_threshold_warn_only_triggers_once_until_reset() -> None:
    notifier = QuotaNotifier([90.0])

    assert notifier.update({"claude_session": (89.0, True)}) == []
    events = notifier.update({"claude_session": (90.0, True)})
    assert [(event.kind, event.channel, event.threshold) for event in events] == [
        ("warn", "claude_session", 90.0)
    ]

    assert notifier.update({"claude_session": (95.0, True)}) == []
    assert notifier.update({"claude_session": (91.0, True)}) == []


def test_reset_unlocks_threshold_latch() -> None:
    notifier = QuotaNotifier([90.0])

    notifier.update({"codex_weekly": (89.0, True)})
    notifier.update({"codex_weekly": (91.0, True)})
    assert notifier.update({"codex_weekly": (20.0, True)}) == []
    events = notifier.update({"codex_weekly": (92.0, True)})

    assert [(event.kind, event.channel, event.threshold) for event in events] == [
        ("warn", "codex_weekly", 90.0)
    ]


def test_depleted_triggers_only_when_percent_at_capacity() -> None:
    notifier = QuotaNotifier([90.0])

    events = notifier.update({"claude_weekly": (100.0, True)})
    assert [(event.kind, event.channel, event.threshold) for event in events] == [
        ("depleted", "claude_weekly", None)
    ]
    assert notifier.update({"claude_weekly": (100.0, True)}) == []

    assert notifier.update({"codex_session": (None, False)}) == []
    assert notifier.update({"codex_session": (None, False)}) == []


def test_missing_data_does_not_repeat_depleted_or_restore_until_percent_recovers() -> None:
    notifier = QuotaNotifier([90.0])

    events = notifier.update({"codex_session": (100.0, True)})
    assert [(event.kind, event.channel, event.threshold) for event in events] == [
        ("depleted", "codex_session", None)
    ]

    assert notifier.update({"codex_session": (None, False)}) == []

    events = notifier.update({"codex_session": (5.0, True)})
    assert [(event.kind, event.channel, event.threshold) for event in events] == [
        ("restored", "codex_session", None)
    ]


def test_restored_triggers_after_depleted_reset() -> None:
    notifier = QuotaNotifier([90.0])

    notifier.update({"claude_session": (99.0, True)})
    notifier.update({"claude_session": (100.0, True)})
    events = notifier.update({"claude_session": (5.0, True)})

    assert [(event.kind, event.channel, event.threshold) for event in events] == [
        ("restored", "claude_session", None)
    ]


def test_depleted_memory_survives_small_drop_until_reset() -> None:
    notifier = QuotaNotifier([90.0])

    notifier.update({"claude_session": (100.0, True)})
    assert notifier.update({"claude_session": (99.0, True)}) == []

    events = notifier.update({"claude_session": (5.0, True)})
    assert [(event.kind, event.channel, event.threshold) for event in events] == [
        ("restored", "claude_session", None)
    ]


def test_first_reading_above_threshold_sends_warning() -> None:
    notifier = QuotaNotifier([90.0])

    events = notifier.update({"claude_session": (95.0, True)})

    assert [(event.kind, event.channel, event.threshold) for event in events] == [
        ("warn", "claude_session", 90.0)
    ]


def test_restored_does_not_trigger_for_non_depleted_reset() -> None:
    notifier = QuotaNotifier([90.0])

    notifier.update({"codex_session": (80.0, True)})

    assert notifier.update({"codex_session": (10.0, True)}) == []


def test_agy_channels_send_threshold_notifications() -> None:
    notifier = QuotaNotifier([90.0])

    assert notifier.update({"agy_session": (89.0, True), "agy_weekly": (89.0, True)}) == []
    events = notifier.update({"agy_session": (90.0, True), "agy_weekly": (90.0, True)})

    assert [(event.channel, event.kind, event.threshold) for event in events] == [
        ("agy_session", "warn", 90.0),
        ("agy_weekly", "warn", 90.0),
    ]


def test_agy_stale_data_does_not_send_notifications() -> None:
    notifier = QuotaNotifier([90.0])

    notifier.update({"agy_session": (89.0, True)})

    assert notifier.update({"agy_session": (100.0, False)}) == []


def test_default_thresholds_warn_at_half_and_near_full() -> None:
    notifier = QuotaNotifier()

    assert notifier.thresholds == [50.0, 90.0]
    events = notifier.update({"codex_session": (52.0, True)})
    assert [(event.kind, event.threshold) for event in events] == [("warn", 50.0)]


def test_one_reading_crossing_two_thresholds_warns_once() -> None:
    notifier = QuotaNotifier([50.0, 90.0])

    events = notifier.update({"claude_session": (95.0, True)})
    assert [(event.kind, event.threshold) for event in events] == [("warn", 90.0)]
    assert notifier.update({"claude_session": (95.0, True)}) == []


def test_thresholds_still_warn_separately_when_crossed_one_at_a_time() -> None:
    notifier = QuotaNotifier([50.0, 90.0])

    assert notifier.update({"codex_session": (40.0, True)}) == []
    first = notifier.update({"codex_session": (55.0, True)})
    second = notifier.update({"codex_session": (95.0, True)})

    assert [(event.kind, event.threshold) for event in first] == [("warn", 50.0)]
    assert [(event.kind, event.threshold) for event in second] == [("warn", 90.0)]

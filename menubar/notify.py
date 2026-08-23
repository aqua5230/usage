# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

from typing import Any

import objc

from i18n import _t
from menubar.state import PopoverState, QuotaRowState


def user_notification_center() -> tuple[Any, dict[str, int]]:
    from UserNotifications import (
        UNAuthorizationOptionAlert,
        UNAuthorizationOptionBadge,
        UNAuthorizationOptionSound,
        UNUserNotificationCenter,
    )
    register_user_notification_block_metadata()

    return (
        UNUserNotificationCenter.currentNotificationCenter(),
        {
            "alert": int(UNAuthorizationOptionAlert),
            "badge": int(UNAuthorizationOptionBadge),
            "sound": int(UNAuthorizationOptionSound),
        },
    )


def user_notification_classes() -> tuple[Any, Any, Any]:
    register_user_notification_block_metadata()
    from UserNotifications import (
        UNMutableNotificationContent,
        UNNotificationRequest,
        UNNotificationSound,
    )

    return UNMutableNotificationContent, UNNotificationRequest, UNNotificationSound


def register_user_notification_block_metadata() -> None:
    objc.registerMetaDataForSelector(
        b"UNUserNotificationCenter",
        b"requestAuthorizationWithOptions:completionHandler:",
        {
            "arguments": {
                3: {
                    "callable": {
                        "retval": {"type": b"v"},
                        "arguments": {
                            0: {"type": b"^v"},
                            1: {"type": b"Z"},
                            2: {"type": b"@"},
                        },
                    },
                },
            },
        },
    )
    objc.registerMetaDataForSelector(
        b"UNUserNotificationCenter",
        b"addNotificationRequest:withCompletionHandler:",
        {
            "arguments": {
                3: {
                    "callable": {
                        "retval": {"type": b"v"},
                        "arguments": {
                            0: {"type": b"^v"},
                            1: {"type": b"@"},
                        },
                    },
                },
            },
        },
    )


def notification_tool(channel: str) -> str:
    return "Claude" if channel.startswith("claude_") else "Codex"


def notification_scope(language: str, channel: str) -> str:
    if channel.endswith("_session"):
        return _t(language, "session_label")
    return _t(language, "weekly_label")


def notification_row(state: PopoverState, channel: str) -> QuotaRowState:
    rows = {
        "claude_session": state.claude_session,
        "claude_weekly": state.claude_weekly,
        "codex_session": state.codex_session,
        "codex_weekly": state.codex_weekly,
    }
    return rows[channel]

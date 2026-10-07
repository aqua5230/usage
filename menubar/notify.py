# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import logging
import time
from typing import Any

import objc

from menubar.state import PopoverState, QuotaRowState
from usage_common.i18n import _t


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


logger = logging.getLogger(__name__)


ALERT_SOUND = "usage_uhoh.wav"


def notification_sound(sound_cls: Any, kind: str) -> Any:
    # "restored" is good news; only warn/depleted get the uh-oh.
    if kind == "restored":
        return sound_cls.defaultSound()
    return sound_cls.soundNamed_(ALERT_SOUND)


def register_user_notification_block_metadata() -> None:
    objc.registerMetaDataForSelector(
        b"UNUserNotificationCenter",
        b"getNotificationSettingsWithCompletionHandler:",
        {
            "arguments": {
                2: {
                    "callable": {
                        "retval": {"type": b"v"},
                        "arguments": {0: {"type": b"^v"}, 1: {"type": b"@"}},
                    }
                }
            }
        },
    )
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
    if channel.startswith("claude_"):
        return "Claude"
    if channel.startswith("agy_"):
        return "Antigravity"
    return "Codex"


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
        "agy_session": state.agy_session,
        "agy_weekly": state.agy_weekly,
    }
    return rows[channel]


# Keep the instance alive: UNUserNotificationCenter holds its delegate weakly.
_notification_delegate: Any = None


def install_notification_delegate(center: Any) -> None:
    global _notification_delegate
    if _notification_delegate is None:
        import UserNotifications  # noqa: F401 — load the delegate protocol lazily
        from Foundation import NSObject

        objc.registerMetaDataForSelector(
            b"UsageNotificationDelegate",
            b"userNotificationCenter:willPresentNotification:withCompletionHandler:",
            {
                "arguments": {
                    4: {
                        "callable": {
                            "retval": {"type": b"v"},
                            "arguments": {0: {"type": b"^v"}, 1: {"type": objc._C_NSUInteger}},
                        }
                    }
                }
            },
        )

        class UsageNotificationDelegate(  # type: ignore[call-arg]
            NSObject,  # type: ignore[misc]
            protocols=[objc.protocolNamed("UNUserNotificationCenterDelegate")],
        ):
            def userNotificationCenter_willPresentNotification_withCompletionHandler_(
                self,
                center: Any,
                notification: Any,
                completion: Any,
            ) -> None:
                completion((1 << 4) | (1 << 3) | (1 << 1))

        _notification_delegate = UsageNotificationDelegate.alloc().init()
    center.setDelegate_(_notification_delegate)


def _authorization_result(granted: bool, error: Any) -> None:
    # The file log keeps WARNING and up outside debug mode; a denial must reach it.
    log = logger.info if granted else logger.warning
    log("notification authorization granted=%s error=%s", granted, error)


def request_notification_authorization() -> None:
    try:
        center, constants = user_notification_center()
        try:
            install_notification_delegate(center)
        except Exception:
            logger.warning("notification delegate setup failed", exc_info=True)
        options = constants["badge"] | constants["sound"] | constants["alert"]
        center.requestAuthorizationWithOptions_completionHandler_(options, _authorization_result)
    except Exception:
        logger.warning("notification authorization failed", exc_info=True)


def send_simple_notification(title: str, body: str) -> None:
    try:
        center, _ = user_notification_center()
        content_cls, request_cls, sound_cls = user_notification_classes()
        content = content_cls.alloc().init()
        content.setTitle_(title)
        content.setBody_(body)
        content.setSound_(sound_cls.defaultSound())
        request = request_cls.requestWithIdentifier_content_trigger_(
            f"usage.keeper.{time.time_ns()}", content, None
        )

        def completed(error: Any) -> None:
            if error is not None:
                logger.warning("keeper notification failed: %s", error)

        center.addNotificationRequest_withCompletionHandler_(request, completed)
    except Exception:
        logger.warning("keeper notification failed", exc_info=True)

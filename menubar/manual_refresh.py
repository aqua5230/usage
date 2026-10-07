"""Status-chip feedback for user-requested refreshes."""

from __future__ import annotations

from typing import Any

from menubar.state import PopoverState
from usage_common.i18n import _t


def begin(state: PopoverState, *, queued: bool = False) -> None:
    if state.refresh_status is None:
        state.refresh_status = (state.status_text, state.status_long)
    state.refresh_queued = state.refresh_queued or queued
    state.status_text = _t(
        state.language, "status_text", value=_t(state.language, "status_refreshing")
    )
    state.status_long = False


def finish(
    previous: PopoverState | None, state: PopoverState, *, queued: bool = False
) -> PopoverState:
    if previous is not None and previous.refresh_status is not None:
        keep = previous.refresh_queued and queued
        previous.status_text, previous.status_long = previous.refresh_status
        previous.refresh_status = None
        previous.refresh_queued = False
        if keep:
            begin(state)
    return state


def finish_mac(app: Any, state: PopoverState) -> PopoverState:
    return finish(app.latest_state, state, queued=bool(app._refresh_queued))


def start_mac(app: Any) -> None:
    begin(app.latest_state, queued=bool(app._refresh_in_flight))
    app._refresh(queue_if_busy=True)
    if app._panel_window_is_visible():
        app.popover_controller.setState_(app.latest_state)


def fail_mac(app: Any) -> None:
    state = getattr(app, "latest_state", None)
    if state is not None:
        finish(state, state)
    app._refresh_in_flight = False
    if state is not None and app._panel_window_is_visible():
        app.popover_controller.setState_(state)

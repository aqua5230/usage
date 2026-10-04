from types import SimpleNamespace

import pytest

from i18n import _t
from menubar import manual_refresh
from menubar.state import _empty_state


@pytest.mark.parametrize("normal", ["status_synced", "data_stale_hint", "status_no_data"])
def test_manual_refresh_restores_new_status(normal: str) -> None:
    previous = _empty_state()
    manual_refresh.begin(previous)
    assert previous.status_text == "Status: ↻ Refreshing…"
    assert previous.status_long is False
    state = _empty_state()
    state.status_text = _t("en", "status_text", value=_t("en", normal))
    state.status_long = True
    assert manual_refresh.finish(previous, state) is state
    assert state.status_text == _t("en", "status_text", value=_t("en", normal))
    assert state.status_long is True
    assert state.refresh_status is None


def test_auto_refresh_never_changes_status() -> None:
    previous, state = _empty_state(), _empty_state()
    expected = state.status_text
    manual_refresh.finish(previous, state, queued=True)
    assert state.status_text == expected
    assert state.refresh_status is None


def test_manual_refresh_queued_behind_auto_waits_for_its_result() -> None:
    previous = _empty_state()
    manual_refresh.begin(previous, queued=True)
    state = manual_refresh.finish(previous, _empty_state(), queued=True)
    assert state.status_text == "Status: ↻ Refreshing…"
    result = manual_refresh.finish(state, _empty_state())
    assert result.status_text == _empty_state().status_text
    assert result.refresh_status is None


def test_mac_manual_refresh_pushes_status_and_failure_restores_it() -> None:
    state = _empty_state()
    expected = state.status_text
    pushed: list[str] = []
    calls: list[bool] = []
    app = SimpleNamespace(
        latest_state=state,
        _refresh_in_flight=False,
        _refresh=lambda *, queue_if_busy: calls.append(queue_if_busy),
        _panel_window_is_visible=lambda: True,
        popover_controller=SimpleNamespace(
            setState_=lambda state: pushed.append(state.status_text)
        ),
    )
    manual_refresh.start_mac(app)
    assert calls == [True]
    assert pushed == ["Status: ↻ Refreshing…"]
    manual_refresh.fail_mac(app)
    assert pushed == ["Status: ↻ Refreshing…", expected]
    assert app._refresh_in_flight is False

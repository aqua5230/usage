# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import panels
from panels.base import (
    ACTIVE_PANEL_DEFAULTS_KEY,
    load_active_panel_id,
    save_active_panel_id,
)
from panels.web_panel import HTMLPanel


class FakeDefaults:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.synchronized = False

    def stringForKey_(self, key: str) -> str | None:
        return self.values.get(key)

    def setObject_forKey_(self, value: str, key: str) -> None:
        self.values[key] = value

    def synchronize(self) -> None:
        self.synchronized = True


def test_registered_panel_ids_are_unique() -> None:
    ids = panels.panel_ids()

    assert ids == (
        "classic",
        "matrix",
        "win95",
        "newspaper",
        "cloud_observation",
        "aquarium",
        "prism_arcade",
        "black_hole",
        "lepidoptera",
        "world_cup",
    )
    assert len(ids) == len(set(ids))


def test_registered_panel_i18n_keys() -> None:
    keys = [panel.i18n_key for panel in panels.all_panels()]

    assert keys == [
        "panel_default_name",
        "panel_matrix",
        "panel_win95",
        "panel_newspaper",
        "panel_cloud_observation",
        "panel_aquarium",
        "panel_prism_arcade",
        "panel_black_hole",
        "panel_lepidoptera",
        "panel_world_cup",
    ]


def test_classic_panel_preferred_size() -> None:
    panel = panels.get_panel("classic")

    assert panel.preferred_size() == (364.0, 812.0)


def test_win95_panel_preferred_size() -> None:
    panel = panels.get_panel("win95")

    assert panel.preferred_size() == (364.0, 800.0)


def test_html_panels_place_analyze_and_cli_in_project_header() -> None:
    panel_dir = Path(__file__).resolve().parent.parent / "assets" / "panels"

    for panel_path in sorted(panel_dir.glob("*.html")):
        html = panel_path.read_text(encoding="utf-8")
        project_index = html.index('data-action="toggle-project-range"')
        footer_index = html.index('<section class="footer"')
        analyze_index = html.index('data-action="analyze"')
        cli_index = html.index('data-action="toggle-statusline"')

        assert project_index < analyze_index < footer_index, panel_path.name
        assert project_index < cli_index < footer_index, panel_path.name
        assert html.count('data-action="analyze"') == 1, panel_path.name
        assert "data-cli-panel" not in html
        assert "localStorage" not in html
        assert "renderCliStatus" not in html
        assert "cli-status" not in html
        assert 'class="action" data-action="analyze"' not in html


def test_html_panel_rows_are_initialized_once() -> None:
    panel_dir = Path(__file__).resolve().parent.parent / "assets" / "panels"

    for panel_path in sorted(panel_dir.glob("*.html")):
        html = panel_path.read_text(encoding="utf-8")
        if "function renderRow(" not in html:
            continue

        assert 'el.dataset.rowReady !== "true"' in html, panel_path.name
        assert 'el.dataset.rowReady = "true"' in html, panel_path.name


def test_classic_project_header_expands_for_action_row() -> None:
    panel_path = Path(__file__).resolve().parent.parent / "assets" / "panels" / "classic.html"
    html = panel_path.read_text(encoding="utf-8")
    project_brand_css = html[
        html.index('.card[data-card="projects"] .brand {') :
        html.index('.card[data-card="projects"] .brand-icon {')
    ]

    assert '<div class="project-actions">' in html
    assert "display: grid;" in project_brand_css
    assert "height: auto;" in project_brand_css
    assert "margin-bottom: 10px;" in project_brand_css


def test_missing_panel_id_falls_back_to_classic() -> None:
    panel = panels.get_panel("missing")

    assert panel.id == "classic"


def test_defaults_load_falls_back_to_classic() -> None:
    defaults = FakeDefaults()

    assert load_active_panel_id(defaults) == "classic"


def test_defaults_round_trip() -> None:
    defaults = FakeDefaults()

    save_active_panel_id("classic", defaults)

    assert defaults.values[ACTIVE_PANEL_DEFAULTS_KEY] == "classic"
    assert load_active_panel_id(defaults) == "classic"
    assert defaults.synchronized is True


def test_html_panel_requires_explicit_card_heights() -> None:
    constructor: Any = HTMLPanel

    with pytest.raises(TypeError):
        constructor("test", "panel_test", "test.html")
    with pytest.raises(TypeError):
        constructor("test", "panel_test", "test.html", codex_card_height=100.0)
    with pytest.raises(TypeError):
        constructor("test", "panel_test", "test.html", claude_card_height=100.0)


def test_evaluate_javascript_completion_handler_block_signature() -> None:
    # Regression: when WebKit is pulled in via objc.loadBundle (no framework
    # wrapper, e.g. a background/non-app launch), evaluateJavaScript:
    # completionHandler: used to raise "Argument 3 is a block, but no signature
    # available" the moment a Python completion handler was passed, crashing the
    # panel popover. web_panel registers the block metadata to prevent this.
    import panels.web_panel as web_panel

    WKWebView = getattr(web_panel, "WKWebView", None)
    WKWebViewConfiguration = getattr(web_panel, "WKWebViewConfiguration", None)
    if WKWebView is None or WKWebViewConfiguration is None:
        pytest.skip("WebKit unavailable in this environment")

    # Instantiating WKWebView needs a window-server connection; without one (headless
    # CI, SSH, a non-GUI agent) the process aborts rather than raising. CGMainDisplayID
    # returns 0 when no display is attached — a safe read that lets us skip first.
    from Quartz import CGMainDisplayID

    if CGMainDisplayID() == 0:
        pytest.skip("no window server (headless) — cannot instantiate WKWebView")

    from AppKit import NSMakeRect

    config = WKWebViewConfiguration.alloc().init()
    view = WKWebView.alloc().initWithFrame_configuration_(
        NSMakeRect(0, 0, 10, 10), config
    )
    # Must not raise TypeError about the missing block signature.
    view.evaluateJavaScript_completionHandler_("1+1", lambda value, error: None)


def test_web_panel_context_menu_removes_navigation_items() -> None:
    import panels.web_panel as web_panel

    class FakeMenuItem:
        def __init__(self, identifier: str | None) -> None:
            self.identifier = identifier

        def itemIdentifier(self) -> str | None:
            return self.identifier

    class FakeMenu:
        def __init__(self) -> None:
            self.reload = FakeMenuItem("WKMenuItemIdentifierReload")
            self.copy = FakeMenuItem("WKMenuItemIdentifierCopy")
            self.open_link = FakeMenuItem("WKMenuItemIdentifierOpenLinkInNewWindow")
            self.no_identifier = FakeMenuItem(None)
            self.items = [
                self.reload,
                self.copy,
                self.open_link,
                self.no_identifier,
            ]

        def itemArray(self) -> list[FakeMenuItem]:
            return self.items

        def removeItem_(self, item: FakeMenuItem) -> None:
            self.items.remove(item)

    menu = FakeMenu()

    web_panel._remove_navigation_menu_items(menu)

    assert menu.items == [menu.copy, menu.no_identifier]


def test_build_view_falls_back_to_error_panel_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # When the WKWebView panel can't be built/loaded, build_view must return a
    # native ErrorPanelView instead of degrading to a silent grey popover, and
    # that view must satisfy the injectState_/teardown surface the controller
    # drives it with. Failing inside _load_panel_html (before the WKWebView is
    # instantiated) keeps this independent of a window server.
    import panels.web_panel as web_panel
    from panels.web_panel import ErrorPanelView

    def boom(_filename: str) -> str:
        raise RuntimeError("kaboom")

    monkeypatch.setattr(web_panel, "_load_panel_html", boom)

    panel = HTMLPanel(
        "test",
        "panel_default_name",
        "test.html",
        claude_card_height=100.0,
        codex_card_height=100.0,
    )

    class Delegate:
        language = "en"

    view = panel.build_view(Delegate())
    assert isinstance(view, ErrorPanelView)
    view.injectState_({})  # no-op, must not raise
    view.teardown()  # no-op, must not raise


def test_web_panel_reloads_and_reinjects_after_content_termination() -> None:
    import panels.web_panel as web_panel

    class FakeWebView:
        def __init__(self) -> None:
            self._ready = True
            self._pending = None
            self._last_payload = {"codex": {"session": {"percent": 67}}}
            self._html = "<html>usage</html>"
            self.reloads = 0
            self.loaded_html: list[tuple[str, object | None]] = []

        def reload(self) -> None:
            self.reloads += 1

        def loadHTMLString_baseURL_(self, html: str, base_url: object | None) -> None:
            self.loaded_html.append((html, base_url))

    view = FakeWebView()

    web_panel._reload_web_panel(view)

    assert view._ready is False
    assert view._pending == {"codex": {"session": {"percent": 67}}}
    assert view.loaded_html == [("<html>usage</html>", None)]
    assert view.reloads == 0


def test_web_panel_reloads_when_state_injection_fails() -> None:
    import panels.web_panel as web_panel

    class FakeWebView:
        def __init__(self) -> None:
            self._ready = True
            self._pending = None
            self._last_payload = None
            self._html = "<html>usage</html>"
            self.reloads = 0
            self.loaded_html: list[tuple[str, object | None]] = []

        def reload(self) -> None:
            self.reloads += 1

        def loadHTMLString_baseURL_(self, html: str, base_url: object | None) -> None:
            self.loaded_html.append((html, base_url))

    view = FakeWebView()
    payload: dict[str, object] = {"projects": [{"name": "Eric-Tools"}]}

    web_panel._handle_injection_error(view, payload, "boom")

    assert view._ready is False
    assert view._pending == payload
    assert view.loaded_html == [("<html>usage</html>", None)]
    assert view.reloads == 0


def test_web_panel_caps_reloads_when_state_injection_keeps_failing() -> None:
    import panels.web_panel as web_panel

    class FakeWebView:
        def __init__(self) -> None:
            self._ready = True
            self._pending = None
            self._last_payload = None
            self._injection_retry_payload = None
            self._injection_reload_count = 0
            self._html = "<html>usage</html>"
            self.reloads = 0
            self.loaded_html: list[tuple[str, object | None]] = []

        def reload(self) -> None:
            self.reloads += 1

        def loadHTMLString_baseURL_(self, html: str, base_url: object | None) -> None:
            self.loaded_html.append((html, base_url))

    view = FakeWebView()
    payload: dict[str, object] = {"projects": [{"name": "Eric-Tools"}]}

    for _ in range(web_panel.MAX_INJECTION_RELOADS + 3):
        web_panel._handle_injection_error(view, payload, "boom")

    assert view.loaded_html == [
        ("<html>usage</html>", None),
        ("<html>usage</html>", None),
    ]
    assert view.reloads == 0
    assert view._pending is None

    web_panel._reload_web_panel(view)

    assert view.loaded_html == [
        ("<html>usage</html>", None),
        ("<html>usage</html>", None),
        ("<html>usage</html>", None),
    ]
    assert view.reloads == 0


def test_web_panel_reload_falls_back_to_reload_without_html() -> None:
    import panels.web_panel as web_panel

    class FakeWebView:
        def __init__(self) -> None:
            self._ready = True
            self._pending = None
            self._last_payload = None
            self._html = None
            self.reloads = 0

        def reload(self) -> None:
            self.reloads += 1

    view = FakeWebView()

    web_panel._reload_web_panel(view)

    assert view._ready is False
    assert view._pending is None
    assert view.reloads == 1

# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

WINDOW_DRAG_SCRIPT = """
<script>
(function() {
  var interactiveSelector = [
    "button",
    "a",
    "input",
    "textarea",
    "select",
    "option",
    "label",
    "[data-action]",
    "[contenteditable]",
    "[role='button']",
    ".tm-scroll",
    "[data-window-no-drag]"
  ].join(",");

  function isScrollable(element) {
    for (var current = element; current && current !== document.body;
         current = current.parentElement) {
      var style = window.getComputedStyle(current);
      var overflowY = style.overflowY;
      var overflowX = style.overflowX;
      if ((overflowY === "auto" || overflowY === "scroll")
          && current.scrollHeight > current.clientHeight) return true;
      if ((overflowX === "auto" || overflowX === "scroll")
          && current.scrollWidth > current.clientWidth) return true;
    }
    return false;
  }

  document.addEventListener("mousedown", function(event) {
    if (event.button !== 0) return;
    if (event.target.closest(interactiveSelector) || isScrollable(event.target)) return;
    var bridge = window.webkit && window.webkit.messageHandlers
      && window.webkit.messageHandlers.usage;
    if (bridge && typeof bridge.postMessage === "function") {
      bridge.postMessage(JSON.stringify({ action: "begin_window_drag" }));
    }
  }, true);
})();
</script>
""".strip()


def inject_window_drag_script(html: str) -> str:
    return html.replace("</body>", f"{WINDOW_DRAG_SCRIPT}\n</body>", 1)

# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>

from __future__ import annotations

import math

MIN_PANEL_HEIGHT = 240.0

CONTENT_HEIGHT_SCRIPT = """
<script>
(function() {
  var applyState = window.usageApplyState;
  if (typeof applyState !== "function") return;
  var scheduled = false;
  var lastPostedHeight = null;
  function naturalContentHeight() {
    var wrap = document.querySelector(".wrap");
    if (!wrap) return null;
    // A panel can explicitly mark a flexible region whose current laid-out
    // height is part of the design (for example, world_cup's empty pitch).
    // Preserve only those declared floors while releasing the viewport height
    // chain; ordinary content can still contract when a quota row disappears.
    var floors = Array.from(
      wrap.querySelectorAll("[data-usage-height-floor]"),
      function(element) {
        return {
          element: element,
          height: element.getBoundingClientRect().height,
          minHeight: element.style.minHeight
        };
      }
    );
    // Panels nest .wrap differently: most put it straight in <body>, but the
    // viewport-based ones (world_cup, aquarium, black_hole, ...) insert a
    // padded .viewport in between. Walk the real ancestor chain instead of
    // assuming a fixed depth, so every 100%-height link is released and every
    // layer's spacing is counted.
    var chain = [];
    for (var element = wrap; element; element = element.parentElement) {
      chain.push(element);
    }
    // A card written as `flex: 1` has a zero flex-basis, and its automatic
    // content-based minimum size is suppressed by the card's own
    // `overflow: hidden` (win95 and newspaper both need that for their chrome).
    // Releasing the height chain then lets such a card collapse to its header,
    // so the measured height misses every project row. Pin those stretchers to
    // their content size while measuring.
    var stretchers = [];
    Array.prototype.forEach.call(wrap.children, function(child) {
      var childStyle = window.getComputedStyle(child);
      if (parseFloat(childStyle.flexGrow) > 0 && parseFloat(childStyle.flexBasis) === 0) {
        stretchers.push({ element: child, flex: child.style.flex });
      }
    });
    var properties = ["height", "minHeight", "maxHeight"];
    var saved = chain.map(function(element) {
      return properties.map(function(property) { return element.style[property]; });
    });
    try {
      chain.forEach(function(element) {
        element.style.height = "auto";
        element.style.minHeight = "0";
        element.style.maxHeight = "none";
      });
      stretchers.forEach(function(stretcher) {
        stretcher.element.style.flex = "0 0 auto";
      });
      floors.forEach(function(floor) {
        floor.element.style.minHeight = floor.height + "px";
      });
      // Force reflow with viewport constraints disabled. Restoration remains
      // in this synchronous task, so the temporary styles are never painted.
      var total = wrap.getBoundingClientRect().height;
      chain.forEach(function(element, index) {
        var style = window.getComputedStyle(element);
        total += (parseFloat(style.marginTop) || 0) + (parseFloat(style.marginBottom) || 0);
        // wrap's own rect already covers its padding and border; every
        // ancestor wraps additional spacing around the measured box.
        if (index === 0) return;
        total +=
          (parseFloat(style.paddingTop) || 0) + (parseFloat(style.paddingBottom) || 0) +
          (parseFloat(style.borderTopWidth) || 0) + (parseFloat(style.borderBottomWidth) || 0);
      });
      return Math.ceil(total);
    } finally {
      stretchers.forEach(function(stretcher) {
        stretcher.element.style.flex = stretcher.flex;
      });
      chain.forEach(function(element, elementIndex) {
        properties.forEach(function(property, propertyIndex) {
          element.style[property] = saved[elementIndex][propertyIndex];
        });
      });
      floors.forEach(function(floor) {
        floor.element.style.minHeight = floor.minHeight;
      });
    }
  }
  function reportContentHeight() {
    scheduled = false;
    var height = naturalContentHeight();
    var bridge = window.webkit && window.webkit.messageHandlers
      && window.webkit.messageHandlers.usage;
    if (Number.isFinite(height) && height > 0 && height !== lastPostedHeight && bridge
        && typeof bridge.postMessage === "function") {
      lastPostedHeight = height;
      bridge.postMessage(JSON.stringify({ action: "content_height", height: height }));
    }
  }
  function requestContentHeight() {
    if (scheduled) return;
    scheduled = true;
    // Measure after the browser has committed DOM, font, and layout changes.
    // A second frame catches WebView2's first visible layout without relying
    // on a user clicking another control.
    requestAnimationFrame(function() {
      requestAnimationFrame(reportContentHeight);
    });
  }
  window.usageRequestContentHeight = requestContentHeight;
  window.usageInvalidateContentHeight = function() {
    lastPostedHeight = null;
    requestContentHeight();
  };
  window.usageApplyState = function usageApplyStateWithDynamicHeight(state) {
    var result = applyState.apply(this, arguments);
    requestContentHeight();
    return result;
  };
  var wrap = document.querySelector(".wrap");
  if (wrap && typeof MutationObserver === "function") {
    new MutationObserver(requestContentHeight).observe(wrap, {
      childList: true,
      characterData: true,
      subtree: true
    });
  }
  if (wrap && typeof ResizeObserver === "function") {
    new ResizeObserver(requestContentHeight).observe(wrap);
  }
  if (document.fonts && document.fonts.ready) {
    document.fonts.ready.then(requestContentHeight);
  }
  requestContentHeight();
})();
</script>
""".strip()


def inject_content_height_script(html: str) -> str:
    """Install the wrapper after the panel has defined usageApplyState."""
    return html.replace("</body>", f"{CONTENT_HEIGHT_SCRIPT}\n</body>", 1)


def clamp_content_height(height: object, maximum: float) -> float | None:
    """Validate an untrusted JS measurement and clamp it to the usable screen."""
    if isinstance(height, bool) or not isinstance(height, (int, float)):
        return None
    value = float(height)
    if not math.isfinite(value) or value <= 0 or maximum < MIN_PANEL_HEIGHT:
        return None
    return min(max(value, MIN_PANEL_HEIGHT), maximum)

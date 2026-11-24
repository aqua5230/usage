    // Count, then the unit in its own span so a narrow panel can shrink only the unit.
    function fillTokens(el, data, fallback) {
      if (!data.tokensCount) {
        el.textContent = data.tokensText || fallback;
        return;
      }
      const unit = document.createElement("span");
      unit.className = "proj-unit";
      unit.textContent = ` ${data.tokensUnit || ""}`;
      el.replaceChildren(data.tokensCount, unit);
    }

    const defaultPanelHooks = {
      accentFallback(cardEl, computedAccent) {
        return computedAccent;
      },
      // Color of the percent text below the danger threshold.
      percentColor(accent) {
        return accent;
      },
      applyFillVisual(fillEl, { available, percent, color }) {
        fillEl.style.width = available ? `${Math.max(0, Math.min(100, percent))}%` : "0%";
        fillEl.style.setProperty("--fill-color", color);
      },
      projectRankLabels: ["1", "2", "3"],
      renderProjectRow(p, index, ranks) {
        const row = document.createElement("div");
        row.className = "proj-row";
        const rank = document.createElement("span");
        rank.className = "proj-rank";
        rank.textContent = ranks[index];
        const name = document.createElement("span");
        name.className = "proj-name";
        name.textContent = p.name || "";
        const tok = document.createElement("span");
        tok.className = "proj-tokens";
        fillTokens(tok, p, "");
        const cost = document.createElement("span");
        cost.className = "proj-cost";
        cost.textContent = p.costText || "";
        const bar = document.createElement("div");
        bar.className = "proj-bar";
        const fill = document.createElement("div");
        fill.className = "proj-bar-fill";
        fill.style.width = `${p.sharePercent}%`;
        bar.append(fill);
        row.append(rank, name, tok, cost, bar);
        return row;
      },
      switchButtonStrategy(state) {
        // The switch button lives in the Claude card header; when that card is
        // hidden, move it to the next visible home so the menu stays reachable.
        const button = document.querySelector('[data-action="switch"]');
        if (!button) return;
        let host = document.querySelector('[data-card="claude"] .brand');
        let className = "switch";
        if (state.hideClaude && !state.hideCodex) {
          host = document.querySelector('[data-card="codex"] .brand');
        } else if (state.hideClaude && state.hideCodex && !state.hideAgy) {
          host = document.querySelector('[data-card="agy"] .brand');
        } else if (state.hideClaude && state.hideCodex && state.hideAgy && !state.hideGrok) {
          host = document.querySelector('[data-card="grok"] .brand');
        } else if (state.hideClaude && state.hideCodex && state.hideAgy && state.hideGrok && !state.hideMuse) {
          host = document.querySelector('[data-card="muse"] .brand');
        }
        if (!host || (state.hideClaude && state.hideCodex && state.hideAgy && state.hideGrok && state.hideMuse)) {
          host = document.querySelector(".footer .actions");
          className = "action";
        }
        if (!host) return;
        button.className = className;
        if (button.parentElement !== host) host.appendChild(button);
      },
      pointerdownExcludeSelector: "button, a, .codex-stale-info",
    };

    if (!window.PanelHooks || typeof window.PanelHooks !== "object") {
      window.PanelHooks = {};
    }
    Object.entries(defaultPanelHooks).forEach(([name, defaultValue]) => {
      if (window.PanelHooks[name] === undefined) {
        window.PanelHooks[name] = defaultValue;
      }
    });

    const I18N = {{I18N_BUNDLE}};
    const FALLBACK_LANGUAGE = "en";
    const root = document.documentElement;
    const switchHostStyle = document.createElement("style");
    switchHostStyle.textContent = `
      .usage-switch-host > h1,
      .usage-switch-host > .header-copy {
        flex: 0 0 auto !important;
        min-width: max-content !important;
        overflow: visible !important;
      }
      [data-card="codex"] .usage-switch-host > [data-codex-stale] {
        flex: 1 1 0 !important;
        min-width: 0 !important;
        overflow: hidden !important;
      }
      [data-card="codex"] .usage-switch-host [data-codex-stale-age] {
        display: block;
        min-width: 0;
        overflow: hidden;
        text-overflow: ellipsis;
      }
      /* Next to the settings button, a warning keeps only its icons; the age moves
         into the tooltip so the button stays inside the card. */
      .usage-switch-host > :is([data-agy-stale], [data-grok-stale], [data-muse-stale]) {
        flex: none !important;
        margin-left: auto;
      }
      .usage-switch-host :is([data-agy-stale-age], [data-grok-stale-age], [data-muse-stale-age]) {
        display: none !important;
      }
      /* The host's title no longer stretches, so push the button to the right edge
         as it sits in the Claude header; a visible warning takes that role instead. */
      .usage-switch-host > [data-action="switch"] {
        margin-left: auto;
      }
      .usage-switch-host > :is([data-agy-stale], [data-grok-stale], [data-muse-stale]):not([hidden]) ~ [data-action="switch"] {
        margin-left: 0;
      }
      /* Antigravity also carries the quota-group button, so its title has to give way too. */
      [data-card="agy"] .usage-switch-host > :is(h1, .header-copy) {
        flex: 0 1 auto !important;
        min-width: 0 !important;
        overflow: hidden !important;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      [data-card="grok"], [data-card="muse"] { cursor: grab; }
    `;
    document.head.appendChild(switchHostStyle);
    const compactCardsStyle = document.createElement("style");
    compactCardsStyle.textContent = `
      html.compact-cards .card:is([data-card="claude"], [data-card="codex"], [data-card="agy"], [data-card="grok"], [data-card="muse"]) {
        padding: 9px 13px 10px;
        min-height: 0;
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        column-gap: 12px;
      }
      html.compact-cards .card:is([data-card="claude"], [data-card="codex"], [data-card="agy"], [data-card="grok"], [data-card="muse"]) > :not(.row) {
        grid-column: 1 / -1;
      }
      html.compact-cards .card:is([data-card="claude"], [data-card="codex"], [data-card="agy"], [data-card="grok"], [data-card="muse"]) > :is(.brand, .header) {
        height: 26px;
        min-height: 0;
        gap: 8px;
        margin-bottom: 7px;
        padding-top: 0;
        padding-bottom: 0;
      }
      html.compact-cards .card:is([data-card="claude"], [data-card="codex"], [data-card="agy"], [data-card="grok"], [data-card="muse"]) :is(.brand, .header) :is(img, .brand-icon) {
        width: 24px;
        height: 24px;
        flex-basis: 24px;
        font-size: 16px;
        border-radius: 6px;
      }
      html.compact-cards .card:is([data-card="claude"], [data-card="codex"], [data-card="agy"], [data-card="grok"], [data-card="muse"]) :is(.brand, .header) h1 {
        font-size: 15px;
        line-height: 1.1;
      }
      /* The projects card keeps its layout; only its icon and title shrink to match the
         compact quota cards. Its header also holds the Today / Report tabs, so its height stays. */
      html.compact-cards .card[data-card="projects"] :is(.brand, .header) :is(img, .brand-icon) {
        width: 24px;
        height: 24px;
        flex-basis: 24px;
        font-size: 16px;
        border-radius: 6px;
      }
      html.compact-cards .card[data-card="projects"] :is(.brand, .header) h1 {
        font-size: 15px;
        line-height: 1.1;
      }
      html.compact-cards .card:is([data-card="claude"], [data-card="codex"], [data-card="agy"], [data-card="grok"], [data-card="muse"]) > .row {
        min-width: 0;
        padding-top: 0;
        margin-top: 0;
        border-top: none;
      }
      html.compact-cards .card:is([data-card="claude"], [data-card="codex"], [data-card="agy"], [data-card="grok"], [data-card="muse"]) .row-head {
        gap: 6px;
        margin-bottom: 4px;
      }
      html.compact-cards .card:is([data-card="claude"], [data-card="codex"], [data-card="agy"], [data-card="grok"], [data-card="muse"]) :is(.row-title, .percent) {
        font-size: 12px;
        line-height: 15px;
        white-space: nowrap;
      }
      html.compact-cards .card:is([data-card="claude"], [data-card="codex"], [data-card="agy"], [data-card="grok"], [data-card="muse"]) .reset {
        font-size: 11px;
        line-height: 14px;
        margin-top: 3px;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }
      html.compact-cards .card[data-compact-single="true"]:is([data-card="claude"], [data-card="codex"], [data-card="agy"], [data-card="grok"], [data-card="muse"]) > .row {
        grid-column: 1 / -1;
      }
      /* The compact "display: grid" above outranks each theme's .hide-* rule,
         so a hidden card must be hidden again here. */
      html.compact-cards.hide-claude .card[data-card="claude"],
      html.compact-cards.hide-codex .card[data-card="codex"],
      html.compact-cards.hide-agy .card[data-card="agy"],
      html.compact-cards.hide-grok .card[data-card="grok"],
      html.compact-cards.hide-muse .card[data-card="muse"] {
        display: none;
      }
    `;
    document.head.appendChild(compactCardsStyle);
    // The footer total reuses the project rows' number styles; drop their column sizing.
    const periodTotalStyle = document.createElement("style");
    periodTotalStyle.textContent = `
      [data-footer="today"] :is(.proj-tokens, .proj-cost) {
        min-width: 0;
        margin-left: 6px;
        text-align: left;
      }
      /* A small, quiet unit keeps the full count readable and leaves room for the project name. */
      .proj-unit {
        font-size: 0.72em;
        font-weight: 400;
        opacity: 0.7;
      }
    `;
    document.head.appendChild(periodTotalStyle);
    let currentLanguage = "en";
    let projectRange = "1d";
    let latestState = null;

    function languageTable(language) {
      return I18N[language] || I18N[FALLBACK_LANGUAGE] || {};
    }

    function t(key, params = {}) {
      const template = languageTable(currentLanguage)[key] || languageTable(FALLBACK_LANGUAGE)[key] || key;
      return template.replace(/\{(\w+)\}/g, (_, name) => `${params[name] ?? ""}`);
    }

    const cardSharing = (() => {
      const targets = [["threads", "#111", "@"], ["x", "#111", "X"], null,
        ["copy", "#8e8e93", "⧉"], ["save", "#3a8ef0", "↓"], null, ["more", "#c7c3be", "⋯"]];
      const bridge = () => window.webkit?.messageHandlers?.usage;
      // The Windows shim identifies itself before pywebview is ready.
      const canShare = () => window.usageHost !== "windows" && !window.pywebview
        && typeof bridge()?.postMessage === "function";
      const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

      const SHARE_LINK = "github.com/aqua5230/usage";
      const todayPalImages = {
        bear: "{{ASSET:panels/felt/pals/bear_card.webp}}",
        elephant: "{{ASSET:panels/felt/pals/elephant_card.webp}}",
        penguin: "{{ASSET:panels/felt/pals/penguin_card.webp}}",
        piglet: "{{ASSET:panels/felt/pals/piglet_card.webp}}",
        puppy: "{{ASSET:panels/felt/pals/puppy_card.webp}}",
        raccoon: "{{ASSET:panels/felt/pals/raccoon_card.webp}}",
        redpanda: "{{ASSET:panels/felt/pals/redpanda_card.webp}}",
        cockatoo: "{{ASSET:panels/felt/pals/cockatoo_card.webp}}",
        crab: "{{ASSET:panels/felt/pals/crab_card.webp}}",
        pufferfish: "{{ASSET:panels/felt/pals/pufferfish_card.webp}}",
        snail: "{{ASSET:panels/felt/pals/snail_card.webp}}",
      };
      const todayPalPool = Object.values(todayPalImages);
      // Use Felt's service colors in every copy of its card.
      const serviceColors = { claude: "#e8734a", codex: "#2fa7b8", agy: "#5b7fe0", grok: "#6c6470", muse: "#2f7de0" };

      function node(tag, className = "", text = "") {
        const element = document.createElement(tag);
        element.className = className;
        element.textContent = text;
        return element;
      }

      function icon() {
        const ns = "http://www.w3.org/2000/svg";
        const svg = document.createElementNS(ns, "svg");
        const attributes = { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", "stroke-width": "2.2",
          "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true" };
        for (const [name, value] of Object.entries(attributes)) svg.setAttribute(name, value);
        for (const d of ["M12 15V3M7 8l5-5 5 5", "M5 12v7a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-7"]) {
          const path = document.createElementNS(ns, "path");
          path.setAttribute("d", d);
          svg.append(path);
        }
        return svg;
      }

      // Use an opaque 4:5 sheet for social sites, with at least 80px around the card.
      function feltSheetPng(w, h, draw) {
        const W = 1080, H = 1350, scale = Math.min(6, (W - 160) / w, (H - 160) / h);
        const canvas = Object.assign(document.createElement("canvas"), { width: W, height: H });
        const g = canvas.getContext("2d", { alpha: false });
        const font = (weight, px) => `${weight} ${px}px ui-rounded,-apple-system,"PingFang TC",sans-serif`;
        const box = (x, y, width, height, radius) => {
          const r = Math.min(radius, width / 2, height / 2);
          g.beginPath();
          g.moveTo(x + r, y);
          g.arcTo(x + width, y, x + width, y + height, r);
          g.arcTo(x + width, y + height, x, y + height, r);
          g.arcTo(x, y + height, x, y, r);
          g.arcTo(x, y, x + width, y, r);
          g.closePath();
        };
        g.fillStyle = "#f3e6d0";
        g.fillRect(0, 0, W, H);
        g.translate((W - w * scale) / 2, (H - h * scale) / 2);
        g.scale(scale, scale);
        g.textBaseline = "middle";
        g.shadowColor = "rgba(50,28,8,.4)";
        g.shadowBlur = 60;
        g.shadowOffsetY = 40;
        box(0, 0, w, h, 12);
        g.fillStyle = "#d9a93a";
        g.fill();
        g.shadowColor = "transparent";
        const face = g.createLinearGradient(w * 0.59, 0, w * 0.41, h);
        face.addColorStop(0, "#fffaf0");
        face.addColorStop(1, "#f1dfbd");
        box(3, 3, w - 6, h - 6, 9);
        g.fillStyle = face;
        g.fill();
        box(4, 4, w - 8, h - 8, 8);
        g.strokeStyle = "#fff4d6";
        g.lineWidth = 2;
        g.stroke();
        draw(g, box, font);
        return canvas.toDataURL("image/png").split(",")[1];
      }

      const loadImg = async (url) => {
        const img = new Image();
        img.src = url;
        await img.decode();
        return img;
      };
      // A tag pill ending at x = right, like .pal-card .tag.
      const drawTag = (g, box, text, right) => {
        const w = g.measureText(text).width + 12;
        box(right - w, 11, w, 13, 6.5);
        g.fillStyle = "#d9a93a";
        g.fill();
        g.fillStyle = "#fffaf0";
        g.textAlign = "center";
        g.fillText(text, right - w / 2, 17.5);
      };

      // The frame stays in root CSS pixels and centers the card's zoomed layout box.
      function hold(card, { name, png, text, inDex = false, keepText = t("panel_card_close"), still }) {
        return new Promise((resolve) => {
          const z = Number(getComputedStyle(root).zoom) || 1;
          const viewH = innerHeight / z, viewW = innerWidth / z;
          const initial = card.getBoundingClientRect(), h = initial.height / z;
          const zoom = Math.min(1.8, Math.max(1, viewH - 120) / h, Math.max(1, viewW - 24) / (initial.width / z));
          const layer = inDex ? " over-dex" : "";
          const dim = node("div", `pal-dim${layer}`);
          const frame = node("div", "usage-card-hold");
          frame.style.zIndex = getComputedStyle(card).zIndex;
          const controls = node("div", `pal-share${layer}`);
          const go = node("button", "go"), keep = node("button", "keep", keepText);
          go.type = keep.type = "button";
          const status = node("span", "", t("panel_card_share"));
          go.append(icon(), status);
          if (canShare()) controls.append(go);
          controls.append(keep);
          document.body.append(dim, frame);
          frame.append(card);
          card.style.zoom = String(zoom);
          card.classList.add("hold");
          // Only the motion between layouts uses a transform. The resting card has no transform.
          const animateFrom = (from, effectiveZoom) => {
            const to = card.getBoundingClientRect();
            const dx = (from.left + from.width / 2 - to.left - to.width / 2) / effectiveZoom;
            const dy = (from.top + from.height / 2 - to.top - to.height / 2) / effectiveZoom;
            return card.animate([
              { transform: `translate(${dx}px, ${dy}px) scale(${from.width / to.width})` },
              { transform: "none" },
            ], { duration: 350, easing: "cubic-bezier(.3,1.3,.5,1)" });
          };
          const motion = still ? null : animateFrom(initial, z * zoom);
          requestAnimationFrame(() => dim.classList.add("on"));

          let menu, rowTimer, closing = false;
          const closeMenu = () => {
            menu?.remove();
            menu = null;
          };
          const finish = async (ms = 0) => {
            if (closing) return;
            closing = true;
            clearTimeout(rowTimer);
            closeMenu();
            await wait(ms);
            controls.remove();
            dim.classList.remove("on");
            const current = card.getBoundingClientRect();
            motion?.cancel();
            frame.replaceWith(card);
            card.classList.remove("hold");
            card.style.zoom = "";
            setTimeout(() => dim.remove(), 300);
            if (!still) await animateFrom(current, z).finished;
            resolve();
          };
          keep.addEventListener("click", () => finish());
          dim.addEventListener("click", () => finish());
          const share = async (target) => {
            closeMenu();
            go.disabled = true;
            try {
              const a = go.getBoundingClientRect();
              const image = await png();
              if (closing || !canShare()) return;
              bridge().postMessage(JSON.stringify({ action: "share_pal_card", target, name, png: image, text,
                anchor: { x: a.left, y: a.top, w: a.width, h: a.height } }));
              if (target === "more") return;
              go.classList.add("done");
              status.textContent = t(`panel_card_shared_${target}`);
              keep.remove();
              finish(1600);
            } catch (error) {
              console.error("Could not share the usage card", error);
              status.textContent = t("panel_card_share_error");
            } finally {
              go.disabled = closing;
            }
          };
          go.addEventListener("click", () => {
            if (menu) return closeMenu();
            menu = node("div", "pal-share-menu");
            for (const option of targets) {
              if (!option) {
                menu.append(node("hr"));
                continue;
              }
              const [target, color, glyph] = option;
              const item = node("button");
              item.type = "button";
              const mark = node("i", "", glyph);
              mark.style.background = color;
              item.append(mark, t(`panel_card_share_${target}`));
              item.addEventListener("click", () => share(target));
              menu.append(item);
            }
            document.body.append(menu);
            const b = go.getBoundingClientRect();
            const below = b.bottom / z + 6 + menu.offsetHeight <= viewH;
            menu.style.left = `${Math.max(0, Math.min(b.left / z, viewW - menu.offsetWidth))}px`;
            menu.style.top = `${Math.max(0, below ? b.bottom / z + 6 : b.top / z - 6 - menu.offsetHeight)}px`;
          });
          rowTimer = setTimeout(() => {
            document.body.append(controls);
            const r = card.getBoundingClientRect();
            controls.style.left = `${(r.left + r.width / 2) / z - controls.offsetWidth / 2}px`;
            controls.style.top = `${r.bottom / z + 12}px`;
            requestAnimationFrame(() => controls.classList.add("on"));
          }, still ? 0 : 380);
        });
      }

      function todayData(state) {
        const today = state?.footer?.today;
        const services = (today?.byService || []).filter(({ card, tokens }) =>
          QUOTA_CARD_IDS.includes(card) && Number.isFinite(tokens) && tokens > 0);
        const total = services.reduce((sum, row) => sum + row.tokens, 0);
        const percent = new Intl.NumberFormat(root.lang || undefined, { style: "percent", maximumFractionDigits: 1 });
        const rows = services.map(({ card, tokens, tokensText }) => ({
          name: t(`${card}_name`),
          tokensText,
          ratio: tokens / total,
          percentText: percent.format(tokens / total),
          color: serviceColors[card],
        }));
        return {
          tokens: today?.tokensCount || "0",
          date: new Date().toLocaleDateString(root.lang || undefined, { month: "numeric", day: "numeric", weekday: "short" }),
          rows,
        };
      }

      function buildTodayBreakdown(rows) {
        const group = node("div", "usage-today-breakdown");
        group.setAttribute("role", "group");
        group.setAttribute("aria-label", t("panel_today_breakdown"));
        const bar = node("div", "usage-today-bar");
        bar.setAttribute("aria-hidden", "true");
        group.append(bar);
        for (const row of rows) {
          const segment = node("i");
          segment.style.width = `${row.ratio * 100}%`;
          segment.style.backgroundColor = row.color;
          bar.append(segment);
          const line = node("div", "usage-today-row"), dot = node("i");
          dot.style.backgroundColor = row.color;
          line.append(dot, node("span", "", row.name), node("span", "", row.tokensText), node("span", "", row.percentText));
          group.append(line);
        }
        return group;
      }

      function drawTodayBreakdown(g, box, font, rows, { x, y, width, color, weight, size }) {
        if (!rows.length) return;
        g.save();
        box(x, y, width, 6, 3);
        g.clip();
        let left = x;
        for (const row of rows) {
          const length = row.ratio * width;
          g.fillStyle = row.color;
          g.fillRect(left, y, length, 6);
          left += length;
        }
        g.restore();
        g.font = font(weight, size);
        rows.forEach((row, index) => {
          const center = y + 14 + index * 13;
          box(x, center - 2.5, 5, 5, 2.5);
          g.fillStyle = row.color;
          g.fill();
          g.fillStyle = color;
          g.textAlign = "left";
          g.fillText(row.name, x + 9, center, width - 87);
          g.textAlign = "right";
          g.fillText(row.tokensText, x + width - 35, center, 38);
          g.fillText(row.percentText, x + width, center, 31);
        });
      }

      function buildDayCard(d) {
        const card = node("div", "pal-card day");
        const face = node("div", "pal-day");
        const top = node("div", "top");
        top.append(node("span", "", t("panel_today_title")), node("span", "tag", d.date));
        const hero = node("div", "hero");
        if (d.palImage) {
          const img = node("img");
          img.src = d.palImage;
          img.alt = "";
          hero.append(img);
        }
        const num = node("div", "num");
        num.append(node("span", "", t("panel_today_tokens")), node("b", "", d.tokens));
        face.append(top, hero, num);
        if (d.rows.length) face.append(buildTodayBreakdown(d.rows));
        face.append(node("div", "link", `usage · ${SHARE_LINK}`));
        card.append(face);
        return card;
      }
      // Layout numbers mirror the .pal-day CSS (168×236; content box from x 13 to 155).
      async function dayPng(d) {
        const img = d.palImage ? await loadImg(d.palImage) : null;
        return feltSheetPng(168, 236, (g, box, font) => {
          g.font = font(800, 9);
          g.fillStyle = "#8a5a10";
          g.fillText(t("panel_today_title"), 13, 18.5);
          drawTag(g, box, d.date, 155);
          g.save();
          box(13, 31, 142, 70, 8);
          g.clip();
          const glow = g.createRadialGradient(84, 54.8, 0, 84, 54.8, 127);
          glow.addColorStop(0, "#fff");
          glow.addColorStop(1, "#f2c9a0");
          g.fillStyle = glow;
          g.fillRect(13, 31, 142, 70);
          g.beginPath();
          g.ellipse(84, 93, 22, 3, 0, 0, Math.PI * 2);
          g.fillStyle = "rgba(60,38,20,.2)";
          g.fill();
          if (img) {
            const iw = (img.naturalWidth / img.naturalHeight) * 58;
            g.drawImage(img, 84 - iw / 2, 36, iw, 58);
          }
          g.restore();
          box(13.5, 31.5, 141, 69, 8);
          g.strokeStyle = "rgba(80,50,10,.12)";
          g.lineWidth = 1;
          g.stroke();
          g.textAlign = "center";
          g.fillStyle = "rgba(138,90,16,.8)";
          g.font = font(800, 8);
          g.fillText(t("panel_today_tokens"), 84, 113);
          g.fillStyle = "#4a2a04";
          let size = 20;
          g.font = font(900, size);
          while (g.measureText(d.tokens).width > 142 && size > 12) g.font = font(900, --size);
          g.fillText(d.tokens, 84, 129);
          drawTodayBreakdown(g, box, font, d.rows, {
            x: 13, y: 142, width: 142, color: "#4a2a04", weight: 800, size: 8,
          });
          g.textAlign = "center";
          g.fillStyle = "rgba(74,42,4,.7)";
          g.font = font(700, 7.4);
          g.fillText(`usage · ${SHARE_LINK}`, 84, 220);
        });
      }
      function feltTodayPreview(d, still) {
        const card = buildDayCard(d);
        const enter = async () => {
          // Very large totals shrink to fit the card instead of running past its edge.
          const b = card.querySelector(".num b");
          for (let px = 20; b.scrollWidth > b.clientWidth && px > 12; ) b.style.fontSize = `${--px}px`;
          if (!still) {
            await card.animate([{ transform: "translateY(40px) scale(.6)", opacity: 0 }, { transform: "none", opacity: 1 }],
              { duration: 380, easing: "cubic-bezier(.2,1.3,.4,1)" }).finished;
          }
        };
        return { card, enter, png: () => dayPng(d), still };
      }

      return { canShare, node, icon, hold, feltSheetPng, drawTag, loadImg, SHARE_LINK,
        todayData, todayPalImages, todayPalPool, feltTodayPreview };
    })();

    const todayShareStyle = document.createElement("style");
    todayShareStyle.textContent = `
      [data-footer="today"].has-today-share { padding-right: 32px; }
      .usage-today-share {
        position: absolute; z-index: 2; display: grid; place-items: center;
        box-sizing: border-box; width: 26px; height: 26px; padding: 0;
        border: 1px solid var(--today-share-border); border-radius: 50%;
        color: var(--today-share-text); background: var(--today-share-background); cursor: pointer;
      }
      .usage-today-share:hover { border-color: currentColor; }
      .usage-today-share svg { width: 13px; height: 13px; }
      .usage-card-hold {
        position: fixed; inset: 0; box-sizing: border-box; padding-bottom: 56px;
        display: grid; place-items: center; pointer-events: none;
      }
      .usage-card-hold > .pal-card.hold { position: relative; inset: auto; margin: 0; }
      .pal-card{position:fixed;left:50%;bottom:150px;width:136px;height:190px;margin-left:-68px;perspective:800px;pointer-events:none;z-index:48}
      .pal-card .top{display:flex;justify-content:space-between;align-items:center;width:100%;font-size:9px;font-weight:800;letter-spacing:.08em !important;color:#8a5a10}
      .pal-card .tag{padding:1px 6px;border-radius:99px;background:#d9a93a;color:#fffaf0;letter-spacing:.04em !important}
      .pal-card.day{width:168px;height:236px;margin-left:-84px;perspective:none}
      /* The panel's global font rules also match the share overlay. */
      :is(.pal-day,.pal-share,.pal-share-menu) *{font-family:inherit !important;letter-spacing:inherit !important}
      .pal-day,.pal-share,.pal-share-menu{letter-spacing:normal !important;color-scheme:light;
        text-rendering:auto;-webkit-font-smoothing:antialiased}
      .pal-day,.pal-share{font-family:ui-rounded,-apple-system,"PingFang TC",sans-serif !important}
      .pal-day{position:absolute;inset:0;box-sizing:border-box;display:flex;flex-direction:column;padding:9px 10px 8px;border-radius:12px;border:3px solid #d9a93a;
        background:linear-gradient(160deg,#fffaf0,#f1dfbd);box-shadow:inset 0 0 0 2px #fff4d6,0 10px 26px rgba(50,28,8,.45);
        font-size:16px;line-height:normal;color:#4a2a04}
      .pal-day .hero{position:relative;display:grid;place-items:end center;height:70px;margin-top:6px;border-radius:8px;overflow:hidden;
        background:radial-gradient(circle at 50% 34%,#fff 0,#f2c9a0 150%);box-shadow:inset 0 0 0 1px rgba(80,50,10,.12)}
      .pal-day .hero::after{content:"";position:absolute;bottom:5px;left:50%;width:44px;height:6px;margin-left:-22px;border-radius:50%;background:rgba(60,38,20,.2)}
      .pal-day .hero img{position:relative;z-index:1;height:58px;margin-bottom:7px}
      .pal-day .num{margin-top:7px;text-align:center}
      .pal-day .num span{display:block;font-size:8px;font-weight:800;letter-spacing:.12em !important;color:#8a5a10;opacity:.8}
      .pal-day .num b{display:block;font-size:20px;font-weight:900;line-height:1.05;font-variant-numeric:tabular-nums;letter-spacing:-.4px !important;white-space:nowrap}
      .pal-day .usage-today-breakdown{margin-top:4px}
      .pal-day .usage-today-row{font-size:8px;font-weight:800}
      .pal-day .link{margin-top:auto;text-align:center;font-size:7.4px;font-weight:700;opacity:.7;white-space:nowrap}
      .pal-dim{position:fixed;inset:0;z-index:47;background:rgba(40,26,14,.42);opacity:0;transition:opacity .3s}
      .pal-dim.on{opacity:1}
      .pal-dim.over-dex{z-index:51}
      .pal-share{position:fixed;display:flex;gap:8px;z-index:49;opacity:0;translate:0 6px;transition:opacity .25s,translate .25s}
      .pal-share.on{opacity:1;translate:0 0}
      .pal-share.over-dex{z-index:53}
      .pal-share>button{display:flex;align-items:center;gap:5px;padding:7px 15px;border:0;border-radius:99px;cursor:pointer;white-space:nowrap;
        font:800 12.5px/16px ui-rounded,-apple-system,"PingFang TC",sans-serif;box-shadow:inset 0 1px 0 rgba(255,255,255,.45),0 3px 8px rgba(40,25,10,.3)}
      .pal-share .go{color:#fffaf0;background:#d9a93a}
      .pal-share .go.done{background:#5b9a5b}
      .pal-share .keep{color:#4a2a04;background:#fbf3e4}
      .pal-share svg{width:13px;height:13px}
      .pal-share-menu{position:fixed;z-index:70;min-width:180px;padding:5px;border-radius:10px;background:rgba(246,244,242,.97);
        box-shadow:0 0 0 .5px rgba(0,0,0,.25),0 10px 30px rgba(0,0,0,.28);font-size:13px;line-height:1;
        font-family:-apple-system,"PingFang TC",sans-serif !important;color:#1d1d1f}
      .pal-share-menu button{display:flex;align-items:center;gap:9px;width:100%;padding:6px 9px;border:0;border-radius:6px;background:none;color:inherit;font:inherit;text-align:left}
      .pal-share-menu button:hover{background:#0a63d8;color:#fff}
      .pal-share-menu i{display:grid;place-items:center;width:20px;height:20px;border-radius:5px;font-style:normal;font-size:11px;font-weight:700;color:#fff}
      .pal-share-menu hr{height:1px;margin:4px 6px;border:0;background:rgba(0,0,0,.12)}
      .usage-today-breakdown { display: grid; align-content: start; gap: 3px; }
      .usage-today-row {
        display: grid; grid-template-columns: 5px minmax(0,1fr) 38px 31px; gap: 4px; align-items: center;
        height: 10px; line-height: 1;
        font-variant-numeric: tabular-nums;
      }
      .usage-today-row span:first-of-type { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
      .usage-today-row span ~ span { text-align: right; white-space: nowrap; }
      .usage-today-row i { width: 5px; height: 5px; border-radius: 50%; }
      .usage-today-bar { display: flex; height: 6px; border-radius: 3px; overflow: hidden; }
      .usage-today-bar i { flex-shrink: 0; }
      @media (prefers-reduced-motion: reduce) {
        .pal-dim, .pal-share { transition: none; }
      }
    `;
    document.head.appendChild(todayShareStyle);

    function updateShareButtonColors(button, today, footer) {
      const line = getComputedStyle(today), panel = getComputedStyle(footer), body = getComputedStyle(document.body);
      const transparent = "rgba(0, 0, 0, 0)";
      const firstColor = /#[0-9a-f]+|(?:rgba?|color)\([^()]+\)/i;
      const background = body.backgroundColor !== transparent ? body.backgroundColor
        : body.backgroundImage.match(firstColor)?.[0] || getComputedStyle(root).backgroundColor;
      const surface = panel.backgroundColor !== transparent ? panel.backgroundColor
        : panel.backgroundImage.match(firstColor)?.[0] || background;
      const border = [line, panel].find((style) => parseFloat(style.borderTopWidth) > 0)?.borderTopColor
        || `color-mix(in srgb, ${line.color} 35%, transparent)`;
      button.style.setProperty("--today-share-text", line.color);
      button.style.setProperty("--today-share-border", border);
      button.style.setProperty("--today-share-background", surface);
    }

    function mountTodayShare() {
      const today = document.querySelector('[data-footer="today"]');
      const footer = today?.closest(".footer");
      if (!footer || !cardSharing.canShare()) return null;

      const selectTodayPalImage = window.PanelHooks.selectTodayPalImage;
      const button = cardSharing.node("button", selectTodayPalImage ? "pal-day-share" : "usage-today-share");
      button.type = "button";
      button.append(cardSharing.icon());
      // The text row may clip its contents. Anchor the button outside its clipping box
      // and reserve horizontal space only, leaving its measured height alone.
      today.classList.add("has-today-share");
      footer.append(button);
      const position = () => {
        const row = today.getBoundingClientRect(), parent = button.offsetParent;
        if (!parent) return;
        const bounds = parent.getBoundingClientRect();
        const zoom = Number(getComputedStyle(root).zoom) || 1;
        button.style.top = `${(row.top + row.height / 2 - bounds.top) / zoom - parent.clientTop - 13}px`;
        if (!selectTodayPalImage) {
          button.style.left = `${(row.right - bounds.left) / zoom - parent.clientLeft - 26}px`;
        }
      };
      const size = new ResizeObserver(position);
      size.observe(footer);
      size.observe(today);
      const update = () => {
        button.title = t("panel_today_share");
        button.setAttribute("aria-label", button.title);
        if (!selectTodayPalImage) updateShareButtonColors(button, today, footer);
        position();
      };
      let open = false;
      button.addEventListener("click", async () => {
        if (open || !cardSharing.canShare()) return;
        open = true;
        let card;
        try {
          const data = cardSharing.todayData(latestState);
          const pool = cardSharing.todayPalPool;
          const palImage = selectTodayPalImage ? selectTodayPalImage() : pool[Math.floor(Math.random() * pool.length)];
          const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
          const preview = cardSharing.feltTodayPreview({ ...data, palImage }, still);
          card = preview.card;
          document.body.append(card);
          await preview.enter();
          await cardSharing.hold(card, { ...preview, name: "today", text: t("panel_today_share_text", data) });
        } finally {
          card?.remove();
          open = false;
        }
      });
      update();
      return update;
    }

    function labels() {
      return {
        session: t("session_label"),
        weekly: t("weekly_label"),
      };
    }

    function projectRangeLabel(range) {
      return `${projectRangeName(range)} ⇄`;
    }

    function projectRangeName(range) {
      if (range === "yesterday") return t("project_range_yesterday");
      if (range === "7d") return t("project_range_7d");
      if (range === "30d") return t("project_range_30d");
      if (range === "all") return t("project_range_all");
      return t("project_range_1d");
    }

    function applyStaticText() {
      document.documentElement.lang = currentLanguage === "zh-TW" ? "zh-Hant" : currentLanguage;
      document.querySelectorAll("[data-i18n]").forEach((node) => {
        const key = node.dataset.i18n;
        if (key) node.textContent = t(key);
      });
      const rangeButton = document.querySelector('[data-action="toggle-project-range"]');
      if (rangeButton) rangeButton.textContent = projectRangeLabel(projectRange);
    }

    window.usageFillTokens = fillTokens;

    window.usageSetLanguage = function usageSetLanguage(language) {
      currentLanguage = I18N[language] ? language : FALLBACK_LANGUAGE;
      applyStaticText();
      if (latestState) {
        window.usageApplyState({ ...latestState, language: currentLanguage });
      }
    };

    function cssVar(name) {
      return getComputedStyle(root).getPropertyValue(name).trim();
    }

    // Panels may draw a critical halo past this; colorFor's 80% only turns text red.
    const CRITICAL_PERCENT = 90;

    // Quiet until the quota is nearly gone: no in-between warning color.
    function colorFor(percent, fallback) {
      if (typeof percent !== "number") return fallback;
      return percent >= 80 ? cssVar("--danger") : fallback;
    }

    function renderRow(card, key, row) {
      const el = document.querySelector(`[data-card="${card}"] [data-row="${key}"]`);
      if (!el) return;
      el.hidden = card === "codex" && !row;
      if (el.hidden) return;
      const cardEl = el.closest(".card");
      if (!cardEl) return;
      const data = row || {
        percent: null,
        percentText: "--",
        resetText: t("reset_placeholder"),
        warning: false,
        available: false,
      };
      const available = data.available === true && typeof data.percent === "number";
      const accent = window.PanelHooks.accentFallback(
        cardEl,
        getComputedStyle(cardEl).getPropertyValue("--accent").trim()
      );
      const color = colorFor(data.percent, accent);
      el.dataset.available = available ? "true" : "false";
      if (el.dataset.rowReady !== "true") {
        el.innerHTML = `
          <div class="row-head">
            <div class="row-title"></div>
            <div class="percent"></div>
          </div>
          <div class="track"><div class="fill"></div></div>
          <div class="reset"></div>
        `;
        el.dataset.rowReady = "true";
      }
      const title = el.querySelector(".row-title");
      const percent = el.querySelector(".percent");
      const reset = el.querySelector(".reset");
      const fill = el.querySelector(".fill");
      if (!title || !percent || !reset || !fill) return;
      title.textContent = data.title != null ? data.title : labels()[key];
      const compact = root.classList.contains("compact-cards");
      percent.textContent = data.percentText || "--";
      reset.textContent = (compact ? data.resetTextCompact : data.resetText)
        || data.resetText || t("reset_placeholder");
      reset.dataset.warning = data.warning === true ? "true" : "false";
      percent.style.color = available
        ? colorFor(data.percent, window.PanelHooks.percentColor(accent))
        : "";
      window.PanelHooks.applyFillVisual(fill, { available, percent: data.percent, color });
      if (compact) percent.textContent = (available ? data.percentTextCompact : data.percentText) || "--";
    }

    function isCriticalRow(row) {
      return Boolean(row)
        && row.available === true
        && typeof row.percent === "number"
        && row.percent >= CRITICAL_PERCENT;
    }

    function applyCard(name, rows) {
      renderRow(name, "session", rows && rows.session);
      renderRow(name, "weekly", rows && rows.weekly);
      const cardEl = document.querySelector(`.card[data-card="${name}"]`);
      if (!cardEl) return;
      const critical = isCriticalRow(rows && rows.session)
        || isCriticalRow(rows && rows.weekly);
      cardEl.dataset.critical = critical ? "true" : "false";
    }

    function renderCodexStale(stale) {
      const staleEl = document.querySelector("[data-codex-stale]");
      const ageEl = document.querySelector("[data-codex-stale-age]");
      const tooltipEl = document.querySelector("[data-codex-stale-tooltip]");
      if (!staleEl || !ageEl || !tooltipEl) return;
      if (stale && stale.ageText) {
        ageEl.textContent = stale.ageText;
        tooltipEl.textContent = t("codex_stale_tooltip");
        staleEl.hidden = false;
        return;
      }
      ageEl.textContent = "";
      tooltipEl.textContent = "";
      staleEl.hidden = true;
    }

    function renderCodexCredits(credits) {
      const card = document.querySelector('[data-card="codex"]');
      if (!card) return;
      const existing = card.querySelector('[data-codex-credits]');
      if (!credits) {
        if (existing) existing.remove();
        return;
      }
      const el = existing || document.createElement("div");
      if (!existing) {
        el.className = "codex-credits";
        el.dataset.codexCredits = "";
        card.appendChild(el);
      }
      el.textContent = credits.unlimited
        ? t("codex_credits_unlimited")
        : t("codex_credits", { balance: credits.balance || "--" });
    }

    // In compact mode a card with one quota row lets that row span the card.
    function markSingleRowCards() {
      const compact = root.classList.contains("compact-cards");
      QUOTA_CARD_IDS.forEach((id) => {
        const card = document.querySelector(`.card[data-card="${id}"]`);
        if (!card) return;
        const rows = card.querySelectorAll("[data-row]:not([hidden])").length;
        card.dataset.compactSingle = compact && rows === 1 ? "true" : "false";
      });
    }

    function renderAgy(agy) {
      applyCard("agy", agy);
      const agySession = document.querySelector('[data-card="agy"] [data-row="session"]');
      if (agySession && agy && agy.weeklyOnly && root.classList.contains("compact-cards")) {
        agySession.hidden = true;
      }
      const groupButton = document.querySelector('[data-action="set_agy_quota_group"]');
      if (groupButton) {
        const groupName = (agy && agy.groupName) || "";
        const current = /argon/i.test(groupName) ? "argon"
          : /claude/i.test(groupName) ? "claude_gpt" : "gemini";
        groupButton.textContent = t("agy_group_" + current);
        const available = (agy && agy.availableGroups) || [];
        groupButton.hidden = !(agy && agy.groupSwitchable && available.length > 1);
        groupButton.dataset.group = available[(available.indexOf(current) + 1) % available.length] || current;
        groupButton.title = t("agy_group_switch_tooltip");
        groupButton.setAttribute("aria-label", t("agy_group_switch_tooltip"));
      }
      const staleEl = document.querySelector("[data-agy-stale]");
      const ageEl = document.querySelector("[data-agy-stale-age]");
      const tooltipEl = document.querySelector("[data-agy-stale-tooltip]");
      if (!staleEl || !ageEl || !tooltipEl) return;
      if (agy && agy.stale && agy.stale.ageText) {
        ageEl.textContent = agy.stale.ageText;
        tooltipEl.textContent = `${agy.stale.ageText} · ${agy.stale.tooltip || t("agy_stale_tooltip")}`;
        staleEl.hidden = false;
        return;
      }
      ageEl.textContent = "";
      tooltipEl.textContent = "";
      staleEl.hidden = true;
    }

    function renderGrok(grok) {
      applyCard("grok", grok);
      const staleEl = document.querySelector("[data-grok-stale]");
      const ageEl = document.querySelector("[data-grok-stale-age]");
      const tooltipEl = document.querySelector("[data-grok-stale-tooltip]");
      if (!staleEl || !ageEl || !tooltipEl) return;
      if (grok && grok.stale && grok.stale.ageText) {
        ageEl.textContent = grok.stale.ageText;
        tooltipEl.textContent = `${grok.stale.ageText} · ${t("grok_stale_tooltip")}`;
        staleEl.hidden = false;
        return;
      }
      ageEl.textContent = "";
      tooltipEl.textContent = "";
      staleEl.hidden = true;
    }

    function renderMuse(muse) {
      applyCard("muse", muse);
      const staleEl = document.querySelector("[data-muse-stale]");
      const ageEl = document.querySelector("[data-muse-stale-age]");
      const tooltipEl = document.querySelector("[data-muse-stale-tooltip]");
      if (!staleEl || !ageEl || !tooltipEl) return;
      if (muse && muse.stale && muse.stale.ageText) {
        ageEl.textContent = muse.stale.ageText;
        tooltipEl.textContent = `${muse.stale.ageText} · ${t("muse_stale_tooltip")}`;
        staleEl.hidden = false;
        return;
      }
      ageEl.textContent = "";
      tooltipEl.textContent = "";
      staleEl.hidden = true;
    }

    function renderHistoryLoadError(err) {
      const el = document.querySelector("[data-history-error]");
      const textEl = document.querySelector("[data-history-error-text]");
      const tooltipEl = document.querySelector("[data-history-error-tooltip]");
      if (!el || !textEl || !tooltipEl) return;
      if (err && err.reasonText) {
        textEl.textContent = err.reasonText;
        tooltipEl.textContent = t("history_load_error_tooltip");
        el.hidden = false;
        return;
      }
      textEl.textContent = "";
      tooltipEl.textContent = "";
      el.hidden = true;
    }

    function renderProjects(projects) {
      const list = document.querySelector('[data-project-list]');
      if (!list) return;
      const ranks = window.PanelHooks.projectRankLabels;
      const rows = (projects || []).slice(0, 3);
      const totalTokens = rows.reduce((s, p) => s + Math.max(0, Number(p.tokens) || 0), 0);
      list.replaceChildren();
      if (rows.length === 0) {
        const empty = document.createElement("div");
        empty.style.cssText = "color:var(--muted);font-size:13px;padding:8px 0";
        empty.textContent = t("projects_empty");
        list.append(empty);
        return;
      }
      rows.forEach((p, i) => {
        const tokens = Math.max(0, Number(p.tokens) || 0);
        const width = totalTokens > 0 ? Math.max(0, Math.min(100, (tokens / totalTokens) * 100)) : 0;
        const row = window.PanelHooks.renderProjectRow({ ...p, sharePercent: width }, i, ranks);
        if (row) list.append(row);
      });
    }

    // Same look as a project row: tokens in the projects card's accent, cost muted.
    function renderPeriodTotal(state) {
      const total = document.querySelector('[data-footer="today"]');
      if (!total) return;
      const yesterday = projectRange === "yesterday";
      const data = (yesterday ? state.footer.yesterday : state.footer.today) || {};
      const projectsCard = document.querySelector('.card[data-card="projects"]');
      if (projectsCard) {
        total.style.setProperty("--accent", getComputedStyle(projectsCard).getPropertyValue("--accent").trim());
      }
      const label = document.createElement("span");
      label.textContent = t(yesterday ? "yesterday_label" : "today_label");
      const tokens = document.createElement("span");
      tokens.className = "proj-tokens";
      fillTokens(tokens, data, "0");
      if (label.textContent.endsWith("：")) tokens.style.marginLeft = "0";
      const cost = document.createElement("span");
      cost.className = "proj-cost";
      cost.textContent = data.costText || "$0.00";
      total.replaceChildren(label, tokens, cost);
    }





    function relocateSwitchButton(state) {
      document.querySelectorAll(".usage-switch-host").forEach((host) => {
        host.classList.remove("usage-switch-host");
      });
      window.PanelHooks.switchButtonStrategy(state);
      const button = document.querySelector('[data-action="switch"]');
      const host = button && button.parentElement;
      // When a card with a stale notice hosts the button, the notice shrinks instead
      // of pushing the button out of the header.
      if (host && host.closest('[data-card="codex"], [data-card="agy"], [data-card="grok"], [data-card="muse"]')) {
        host.classList.add("usage-switch-host");
      }
    }

    const QUOTA_CARD_IDS = ["claude", "codex", "agy", "grok", "muse"];

    function applyCardOrder(order) {
      if (cardDrag && cardDrag.dragging) return;
      if (!Array.isArray(order) || order.length !== QUOTA_CARD_IDS.length || new Set(order).size !== QUOTA_CARD_IDS.length || !order.every((id) => QUOTA_CARD_IDS.includes(id))) return;
      const wrap = document.querySelector("main.wrap");
      const projects = document.querySelector('[data-card="projects"]');
      if (!wrap || !projects) return;
      const currentOrder = [...wrap.querySelectorAll(':scope > [data-card]')]
        .filter((card) => QUOTA_CARD_IDS.includes(card.dataset.card))
        .map((card) => card.dataset.card);
      if (order.every((id, index) => currentOrder[index] === id)) return;
      order.forEach((id) => {
        const card = document.querySelector(`[data-card="${id}"]`);
        if (card) wrap.insertBefore(card, projects);
      });
    }

    window.usageApplyState = function usageApplyState(state) {
      if (typeof state.system_accent_color === "string" && state.system_accent_color) {
        root.style.setProperty("--usage-system-accent", state.system_accent_color);
      } else {
        root.style.removeProperty("--usage-system-accent");
      }
      document.documentElement.classList.toggle('hide-codex', !!state.hideCodex);
      document.documentElement.classList.toggle('hide-claude', !!state.hideClaude);
      document.documentElement.classList.toggle('hide-agy', !!state.hideAgy);
      document.documentElement.classList.toggle('hide-grok', !!state.hideGrok);
      document.documentElement.classList.toggle('hide-muse', !!state.hideMuse);
      const visibleQuotaCards = QUOTA_CARD_IDS.filter((id) =>
        !state[`hide${id[0].toUpperCase()}${id.slice(1)}`]
        && document.querySelector(`.card[data-card="${id}"]`)
      ).length;
      root.classList.toggle("compact-cards", visibleQuotaCards >= 4);
      applyCardOrder(state.cardOrder);
      relocateSwitchButton(state);
      currentLanguage = I18N[state.language] ? state.language : currentLanguage;
      applyStaticText();
      applyCard("claude", state.claude);
      applyCard("codex", state.codex);
      renderCodexStale(state.codex && state.codex.stale);
      renderCodexCredits(state.codex && state.codex.credits);
      renderAgy(state.agy);
      renderGrok(state.grok);
      renderMuse(state.muse);
      markSingleRowCards();
      renderHistoryLoadError(state.historyError);
      latestState = state;
      renderProjects(
        projectRange === "1d" ? state.projects
        : projectRange === "yesterday" ? state.projectsYesterday
        : projectRange === "7d" ? state.projects7d
        : projectRange === "30d" ? state.projects30d
        : projectRange === "all" ? state.projectsAll
        : state.projects
      );
      const rate = document.querySelector('[data-footer="rate"]');
      const status = document.querySelector('[data-footer="status"]');
      const serviceAlerts = document.querySelector('[data-footer="service-alerts"]');
      const install = document.querySelector('[data-action="install"]');
      if (rate) rate.textContent = state.footer.rate || t("rate_text", { value: "--" });
      if (status) status.textContent = state.footer.status || t("status_text", { value: "--" });
      renderPeriodTotal(state);
      if (install) install.dataset.visible = state.footer.showInstall === true ? "true" : "false";
      if (serviceAlerts) {
        const alerts = state.footer.serviceAlerts || [];
        serviceAlerts.replaceChildren(...alerts.slice(0, 2).map((alert) => {
          const item = document.createElement("div");
          item.className = "service-alert";
          item.textContent = alert;
          return item;
        }));
        serviceAlerts.hidden = alerts.length === 0;
      }
      updateTodayShare?.();
    };

    document.addEventListener("click", (event) => {
      const button = event.target.closest("[data-action]");
      if (!button) return;
      if (button.dataset.action === "toggle-project-range") {
        projectRange = projectRange === "1d" ? "yesterday" : projectRange === "yesterday" ? "7d" : projectRange === "7d" ? "30d" : projectRange === "30d" ? "all" : "1d";
        button.textContent = projectRangeLabel(projectRange);
        if (latestState) {
          renderProjects(
            projectRange === "1d" ? latestState.projects
            : projectRange === "yesterday" ? latestState.projectsYesterday
            : projectRange === "7d" ? latestState.projects7d
            : projectRange === "30d" ? latestState.projects30d
            : projectRange === "all" ? latestState.projectsAll
            : latestState.projects
          );
          renderPeriodTotal(latestState);
          updateTodayShare?.();
          if (typeof window.usageRequestContentHeight === "function") {
            window.usageRequestContentHeight();
          }
        }
        return;
      }
      const bridge = window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.usage;
      if (bridge && typeof bridge.postMessage === "function") {
        bridge.postMessage(button.dataset.action === "set_agy_quota_group"
          ? JSON.stringify({ action: button.dataset.action, group: button.dataset.group })
          : button.dataset.action);
      }
    });

    let cardDrag = null;

    document.addEventListener("pointerdown", (event) => {
      const card = event.target.closest('[data-card="claude"], [data-card="codex"], [data-card="agy"], [data-card="grok"], [data-card="muse"]');
      if (!card || event.button !== 0 || event.target.closest(window.PanelHooks.pointerdownExcludeSelector)) return;
      cardDrag = { card, pointerId: event.pointerId, startY: event.clientY, dragging: false };
      card.setPointerCapture(event.pointerId);
    });

    document.addEventListener("pointermove", (event) => {
      if (!cardDrag || event.pointerId !== cardDrag.pointerId) return;
      if (!cardDrag.dragging) {
        if (Math.abs(event.clientY - cardDrag.startY) <= 4) return;
        cardDrag.dragging = true;
        cardDrag.card.classList.add("is-dragging");
        document.documentElement.classList.add("is-card-dragging");
      }
      event.preventDefault();
      const cards = [...document.querySelectorAll('[data-card="claude"], [data-card="codex"], [data-card="agy"], [data-card="grok"], [data-card="muse"]')]
        .filter((card) => card.offsetParent !== null);
      const target = cards.find((card) => card !== cardDrag.card && event.clientY < card.getBoundingClientRect().top + card.getBoundingClientRect().height / 2);
      if (target) target.parentElement.insertBefore(cardDrag.card, target);
      else {
        const projects = document.querySelector('[data-card="projects"]');
        if (projects) projects.parentElement.insertBefore(cardDrag.card, projects);
      }
    });

    function finishCardDrag(event) {
      if (!cardDrag || event.pointerId !== cardDrag.pointerId) return;
      const { card, dragging } = cardDrag;
      if (card.hasPointerCapture(event.pointerId)) card.releasePointerCapture(event.pointerId);
      card.classList.remove("is-dragging");
      document.documentElement.classList.remove("is-card-dragging");
      cardDrag = null;
      if (!dragging) return;
      const order = [...document.querySelectorAll('main.wrap > [data-card]')]
        .filter((item) => QUOTA_CARD_IDS.includes(item.dataset.card))
        .map((item) => item.dataset.card);
      const bridge = window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.usage;
      if (bridge && typeof bridge.postMessage === "function") {
        bridge.postMessage(JSON.stringify({ action: "set_card_order", order }));
      }
    }

    document.addEventListener("pointerup", finishCardDrag);
    document.addEventListener("pointercancel", finishCardDrag);

    const updateTodayShare = mountTodayShare();

    window.usageApplyState({
      language: "en",
      claude: { session: {}, weekly: {} },
      codex: { session: {}, weekly: {} },
      agy: { session: {}, weekly: {}, groupName: "" },
      grok: { weekly: {} },
      muse: { session: {}, weekly: {} },
      cardOrder: ["claude", "codex", "agy", "grok", "muse"],
      hideAgy: true,
      hideGrok: true,
      hideMuse: true,
      projects: [],
      projectsYesterday: [],
      projects7d: [],
      projects30d: [],
      projectsAll: [],
      footer: { rate: "Rate: --", status: "Status: Loading", today: { tokensText: "0", costText: "$0.00" }, yesterday: { tokensText: "0", costText: "$0.00" }, serviceAlerts: [], showInstall: false }
    });

// Real layout checks against the existing demo generator and production height bridge.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { pathToFileURL } = require('node:url');
const playwright = require('playwright');
const engine = process.env.USAGE_BROWSER_ENGINE || 'chromium';
assert.ok(['chromium', 'webkit'].includes(engine));

function footerErrors() {
  const errors = [];
  const inside = (a, b) => a.left >= b.left - 1 && a.right <= b.right + 1
    && a.top >= b.top - 1 && a.bottom <= b.bottom + 1;
  for (const element of document.querySelectorAll(
    '.footer [data-action], .footer .attribution, .footer .credit',
  )) {
    if (!element.getClientRects().length) continue;
    const box = element.getBoundingClientRect();
    const name = element.dataset.action || 'attribution';
    if (element.dataset.action) {
      for (const fraction of [0.25, 0.5, 0.75]) {
        const hit = document.elementFromPoint(
          box.left + box.width * fraction, box.top + box.height / 2,
        );
        if (hit !== element && !element.contains(hit)) {
          errors.push(`${name}: click area obstructed`);
        }
      }
    }
    if (!inside(box, { left: 0, top: 0, right: innerWidth, bottom: innerHeight })) {
      errors.push(`${name}: viewport`);
    }
    // The root's zoomed CSS box is not the viewport's clip rectangle.
    for (let parent = element.parentElement;
      parent && parent !== document.documentElement; parent = parent.parentElement) {
      const style = getComputedStyle(parent);
      if (parent.matches('.actions,.footer')
        || ['hidden', 'clip'].includes(style.overflowX)
        || ['hidden', 'clip'].includes(style.overflowY)) {
        if (!inside(box, parent.getBoundingClientRect())) {
          errors.push(`${name}: ancestor ${parent.className}`);
        }
      }
    }
    const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
    let text;
    while ((text = walker.nextNode())) {
      if (!text.textContent.trim()) continue;
      const range = document.createRange();
      range.selectNodeContents(text);
      for (const line of range.getClientRects()) {
        if (!inside(line, box)) errors.push(`${name}: text outside button`);
      }
    }
  }
  // A grid column can shrink while its text paints over adjacent buttons.
  const meta = document.querySelector('.footer .meta');
  if (meta) {
    const walker = document.createTreeWalker(meta, NodeFilter.SHOW_TEXT);
    let text;
    while ((text = walker.nextNode())) {
      if (!text.textContent.trim()) continue;
      const range = document.createRange();
      range.selectNodeContents(text);
      for (const line of range.getClientRects()) {
        for (const button of document.querySelectorAll('.footer [data-action]')) {
          if (!button.getClientRects().length) continue;
          const box = button.getBoundingClientRect();
          if (Math.min(line.right, box.right) - Math.max(line.left, box.left) > 1
            && Math.min(line.bottom, box.bottom) - Math.max(line.top, box.top) > 1) {
            errors.push('status text overlaps button');
          }
        }
      }
    }
  }
  return errors;
}

async function main() {
  const directory = process.argv[2];
  const browser = await playwright[engine].launch();
  let count = 0;
  try {
    const page = await browser.newPage();
    for (const panel of JSON.parse(fs.readFileSync(`${directory}/panels.json`))) {
      await page.goto(pathToFileURL(`${directory}/${panel.id}.html`).href);
      await page.evaluate(() => {
        window.testActions = [];
        window.testMessages = [];
        window.webkit.messageHandlers.usage.postMessage = raw => {
          let message;
          try { message = JSON.parse(raw); } catch { message = { action: raw }; }
          if (message.action === 'content_height') window.testHeight = message.height;
          else { window.testActions.push(message.action); window.testMessages.push(message); }
        };
      });
      // macOS uses 364 CSS px; Windows uses 380 before panel fitting.
      for (const width of new Set([panel.width, 320, 364, 380, 420])) {
        for (const language of ['en', 'zh-CN', 'zh-TW', 'ja', 'ko']) {
          for (const install of [false, true]) {
            await page.setViewportSize({ width, height: panel.height });
            await page.evaluate(({ language, install }) => {
              usageApplyPanelZoom(1);
              usageDemoSetLanguage(language);
              const state = structuredClone(usageDemoPayloads[language]);
              state.footer.showInstall = install;
              usageApplyState(state);
              window.testHeight = null;
              usageInvalidateContentHeight();
            }, { language, install });
            await page.waitForFunction(() => window.testHeight > 0);
            let height = await page.evaluate(() => window.testHeight);
            // Native fit_scale is continuous from 1 to the 0.6 legibility floor.
            for (const scale of [1, 0.8, 0.6]) {
              // Emulate native content_height -> resize -> zoom feedback, including
              // remeasurement after WebKit's rendered font metrics change.
              let settled = false;
              for (let attempt = 0; attempt < 8; attempt++) {
                await page.setViewportSize({
                  width: Math.ceil(width * scale), height: Math.ceil(height * scale),
                });
                await page.evaluate(({ scale, height }) => {
                  window.testHeight = null;
                  usageApplyPanelZoom(scale, height);
                  usageInvalidateContentHeight();
                }, { scale, height });
                await page.waitForFunction(() => window.testHeight > 0);
                const measured = await page.evaluate(() => window.testHeight);
                if (measured === height) { settled = true; break; }
                height = measured;
              }
              assert.ok(settled, `height did not settle: ${panel.id}/${width}/${scale}`);
              const errors = await page.evaluate(footerErrors);
              assert.deepEqual(errors, [], JSON.stringify({
                theme: panel.id, width, language, install, scale, errors,
              }));
              count++;
            }
          }
        }
      }
      const groupButton = page.locator('[data-action="set_agy_quota_group"]');
      if (await groupButton.count()) {
        await groupButton.click();
        assert.deepEqual(await page.evaluate(() => window.testMessages.at(-1)),
          { action: 'set_agy_quota_group', group: 'claude_gpt' });
      }
      // Exercise the real event handlers with a fake native bridge.
      for (const action of ['refresh', 'quit', 'install']) {
        await page.locator(`.footer [data-action="${action}"]`).click();
        assert.equal(await page.evaluate(() => window.testActions.at(-1)), action);
      }
    }
    console.log(`${engine}: ${count} footer layouts passed; all 14 themes retain button actions.`);
  } finally {
    await browser.close();
  }
}
module.exports = { footerErrors };
if (require.main === module) {
  main().catch(error => { console.error(error); process.exitCode = 1; });
}

// Exercise native height -> fit scale -> resize -> zoom feedback, not fixed zoom.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { pathToFileURL } = require('node:url');
const { footerErrors } = require('./panel_footer_layout.cjs');
const engine = process.env.USAGE_BROWSER_ENGINE || 'chromium';

async function frames(page, count = 4) {
  await page.evaluate(count => new Promise(resolve => {
    const frame = () => --count ? requestAnimationFrame(frame) : resolve();
    requestAnimationFrame(frame);
  }), count);
}

async function fit(page, width, maximum, label) {
  await frames(page);
  const history = [];
  for (let i = 0; i < 16; i++) {
    const height = await page.evaluate(() => window.testHeight);
    assert.ok(height > 0, label);
    history.push(height);
    const scale = Math.max(0.6, Math.min(1, maximum / height));
    await page.setViewportSize({
      width: Math.ceil(width * scale), height: Math.ceil(Math.min(maximum, height * scale)),
    });
    await page.evaluate(({ scale, height }) => usageApplyPanelZoom(scale, height), { scale, height });
    // No invalidation here: it would reset the production fit on every pass.
    await frames(page);
    if (await page.evaluate(() => window.testHeight) === height) {
      const reports = await page.evaluate(() => window.heightReports);
      await frames(page, 8);
      assert.equal(await page.evaluate(() => window.heightReports), reports, `${label}: keeps reporting`);
      assert.deepEqual(await page.evaluate(footerErrors), [], label);
      return height;
    }
  }
  assert.fail(`${label}: height did not settle: ${history}`);
}

async function main() {
  const directory = process.argv[2];
  const browser = await require('playwright')[engine].launch();
  let count = 0;
  try {
    const page = await browser.newPage();
    for (const panel of JSON.parse(fs.readFileSync(`${directory}/panels.json`))) {
      await page.goto(pathToFileURL(`${directory}/${panel.id}.html`).href);
      await page.evaluate(() => {
        window.heightReports = 0;
        window.webkit.messageHandlers.usage.postMessage = raw => {
          const message = JSON.parse(raw);
          if (message.action === 'content_height') {
            window.testHeight = message.height;
            window.heightReports++;
          }
        };
      });
      for (const width of [364, 380]) {
        for (const language of ['en', 'zh-CN', 'zh-TW', 'ja', 'ko']) {
          for (const install of [false, true]) {
            for (const maximum of [750, 950]) {
              const label = `${panel.id}/${width}/${language}/${install}/${maximum}`;
              await page.setViewportSize({ width, height: panel.height });
              await page.evaluate(({ language, install }) => {
                usageApplyPanelZoom(1);
                usageDemoSetLanguage(language);
                window.feedbackState = structuredClone(usageDemoPayloads[language]);
                feedbackState.footer.showInstall = install;
                usageApplyState(feedbackState);
                usageInvalidateContentHeight();
              }, { language, install });
              const full = await fit(page, width, maximum, label);
              // Ordinary repeated state injection must not restart a resize cycle.
              await page.evaluate(() => usageApplyState(feedbackState));
              assert.equal(await fit(page, width, maximum, label), full);
              count++;
            }
          }
        }
      }
      // Real content removal must still release the settled height floor.
      const full = await page.evaluate(() => window.testHeight);
      await page.evaluate(() => {
        feedbackState.hideClaude = true;
        feedbackState.hideCodex = true;
        feedbackState.hideAgy = true;
        feedbackState.hideGrok = true;
        feedbackState.footer.showInstall = false;
        usageApplyState(feedbackState);
      });
      const short = await fit(page, 380, 950, `${panel.id}/contract`);
      // World Cup deliberately preserves its empty pitch's current height;
      // it need not contract like content-sized panels when cards disappear.
      const hasFloor = await page.locator('[data-usage-height-floor]').count();
      assert.ok(hasFloor ? short <= full : short < full - 50,
        `${panel.id}: unexpected height after content removal (${full} -> ${short})`);
      await page.evaluate(() => usageApplyState(usageDemoPayloads.ko));
      const restored = await fit(page, 380, 750, `${panel.id}/restore`);
      assert.ok(hasFloor ? restored >= short : restored > short + 50);
      await checkScreenAndLanguageChanges(page, panel.id);
      console.log(`${panel.id}: feedback and content transitions passed`);
    }
    console.log(`${engine}: ${count} automatic-fit layouts passed`);
  } finally { await browser.close(); }
}

async function checkScreenAndLanguageChanges(page, theme) {
  // Change available screen space without clearing the current fit, then
  // switch translations/setup visibility without reloading the document.
  for (const maximum of [1250, 750, 950]) {
    await fit(page, 380, maximum, `${theme}/screen/${maximum}`);
  }
  for (const language of ['ja', 'zh-CN', 'en']) {
    await page.evaluate(language => usageDemoSetLanguage(language), language);
    await fit(page, 380, 750, `${theme}/language/${language}`);
    await page.evaluate(language => {
      const state = structuredClone(usageDemoPayloads[language]);
      state.footer.showInstall = true;
      usageApplyState(state);
    }, language);
    await fit(page, 380, 750, `${theme}/setup/${language}`);
  }
}

module.exports = { fit, checkScreenAndLanguageChanges };
if (require.main === module) {
  main().catch(error => { console.error(error); process.exitCode = 1; });
}

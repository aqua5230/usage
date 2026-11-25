// Run against demo pages freshly rendered from assets/panels, with a simulated native bridge.
const assert = require('node:assert/strict');
const { createHash } = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const playwright = require('playwright');

const engine = process.env.USAGE_BROWSER_ENGINE || 'chromium';
const assetDir = path.join(__dirname, '../assets/panels');
const i18n = require('../i18n.json').en;
const todaySelector = '[data-footer="today"]';
const buttonSelector = '.usage-today-share, .pal-day-share';
const privateValue = /private-project|\$987\.65|\$123\.45|111,111/;
const credit = 'usage · github.com/aqua5230/usage';
const palNames = ['bear', 'elephant', 'penguin', 'piglet', 'puppy', 'raccoon', 'redpanda',
  'cockatoo', 'crab', 'pufferfish', 'snail'];
const digest = value => createHash('sha256').update(value).digest('hex');
const palImages = palNames.map(name => digest(
  'data:image/webp;base64,' + fs.readFileSync(path.join(assetDir, `felt/pals/${name}_card.webp`), 'base64'),
));

async function prepareDemoTotals(page) {
  await page.evaluate(() => {
    for (const state of Object.values(usageDemoPayloads)) {
      state.footer.totalsReady = true;
      state.footer.today.day = '2026-11-24';
      state.footer.today.shareTokensCount = state.footer.today.tokensCount;
    }
    usageDemoSetLanguage(usageDemoLanguage);
  });
}

async function setLayout(page, { width, language, alerts, install, scale }) {
  await page.setViewportSize({ width: Math.round(width * scale), height: Math.round(1600 * scale) });
  return page.evaluate(async ({ language, alerts, install, scale, todaySelector, buttonSelector }) => {
    const state = structuredClone(usageDemoPayloads[language]);
    state.footer.serviceAlerts = alerts ? ['Service maintenance', 'Pending updates'] : [];
    state.footer.showInstall = install;
    let report;
    window.webkit.messageHandlers.usage.postMessage = raw => {
      const message = JSON.parse(raw);
      if (message.action === 'content_height') report = message.height;
    };
    usageApplyPanelZoom(scale, 1600);
    usageApplyState(state);
    usageInvalidateContentHeight();
    for (let frame = 0; frame < 8 && !report; frame++) {
      await new Promise(requestAnimationFrame);
    }
    const today = document.querySelector(todaySelector);
    const row = today.getBoundingClientRect();
    const footer = today.closest('.footer').getBoundingClientRect();
    const button = document.querySelector(buttonSelector);
    const b = button?.getBoundingClientRect();
    return {
      sizes: [row.height, footer.height, report],
      position: b && {
        inFooter: b.left >= footer.left && b.right <= footer.right
          && b.top >= footer.top && b.bottom <= footer.bottom,
        clickable: [0.25, 0.5, 0.75].every(fraction => button.contains(
          document.elementFromPoint(b.x + b.width / 2, b.y + b.height * fraction),
        )),
        right: Math.abs(b.right - row.right) <= 3,
        centered: Math.abs(b.y + b.height / 2 - row.y - row.height / 2) <= 1,
      },
    };
  }, { language, alerts, install, scale, todaySelector, buttonSelector });
}

async function checkHold(card, controls, { w, h, scale }) {
  await controls.waitFor({ state: 'visible' });
  await controls.evaluate(element => Promise.all(element.getAnimations().map(animation => animation.finished)));
  const layout = await card.evaluate((element, { w, h, scale }) => {
    const r = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    const b = document.querySelector('.pal-share.on')?.getBoundingClientRect();
    const zoom = Math.min(1.8, (innerHeight / scale - 120) / h, (innerWidth / scale - 24) / w);
    return {
      dx: r.left + r.width / 2 - innerWidth / 2,
      dy: r.top + r.height / 2 - (innerHeight - 56 * scale) / 2,
      dw: r.width - w * zoom * scale,
      buttonDx: b && b.left + b.width / 2 - r.left - r.width / 2,
      buttonDy: b && b.top - r.bottom - 12 * scale,
      zoom: Number(style.zoom), expectedZoom: zoom,
      transform: style.transform, scale: style.scale,
      imageTooLarge: [...element.querySelectorAll('img')].some(img =>
        img.naturalHeight !== 360 || img.getBoundingClientRect().height > img.naturalHeight),
    };
  }, { w, h, scale });
  for (const value of ['dx', 'dy', 'dw', 'buttonDx', 'buttonDy']) {
    assert.ok(Math.abs(layout[value]) <= 1, `${value}: ${JSON.stringify(layout)}`);
  }
  assert.ok(Math.abs(layout.zoom - layout.expectedZoom) < 0.001);
  assert.equal(layout.transform, 'none');
  assert.equal(layout.scale, 'none');
  assert.equal(layout.imageTooLarge, false);
}

async function checkCard(page, scale, feltCard) {
  await page.setViewportSize({ width: Math.round(364 * scale), height: Math.round(1600 * scale) });
  const services = [
    ['claude', 'Claude Code', 61728, '61.7K', '50%'],
    ['codex', 'Codex', 30864, '30.9K', '25%'],
    ['agy', 'Antigravity', 15432, '15.4K', '12.5%'],
    ['grok', 'Grok', 7716, '7.7K', '6.3%'],
    ['muse', 'Muse', 7716, '7.7K', '6.3%'],
  ];
  await page.evaluate(({ scale, services }) => {
    usageApplyPanelZoom(scale, 1600);
    const state = structuredClone(usageDemoPayloads.en);
    state.hideCodex = true;
    state.agy.weeklyOnly = true;
    state.footer.today.tokensCount = '123,456';
    state.footer.today.shareTokensCount = '123,456';
    state.footer.today.byService = services.map(([card, , tokens, tokensText]) => ({ card, tokens, tokensText }));
    state.footer.today.costText = '$987.65';
    state.footer.yesterday.tokensCount = '111,111';
    state.projects = [{ name: 'private-project', tokensCount: '250', costText: '$123.45', tokens: 250 }];
    state.projectsYesterday = state.projects;
    usageApplyState(state);
    document.querySelector('[data-action="toggle-project-range"]').click();
    window.shared = [];
    window.canvasText = [];
    window.canvasImages = [];
    const fillText = CanvasRenderingContext2D.prototype.fillText;
    CanvasRenderingContext2D.prototype.fillText = function(text, ...args) {
      window.canvasText.push(String(text));
      return fillText.call(this, text, ...args);
    };
    const drawImage = CanvasRenderingContext2D.prototype.drawImage;
    CanvasRenderingContext2D.prototype.drawImage = function(image, ...args) {
      window.canvasImages.push(image.src);
      return drawImage.call(this, image, ...args);
    };
    window.webkit.messageHandlers.usage.postMessage = raw => {
      const message = JSON.parse(raw);
      if (message.action === 'share_pal_card') {
        window.shared.push(message);
        window.usageShareCardResult({ requestId: message.requestId, success: true });
      }
    };
  }, { scale, services });
  if (feltCard) {
    await page.evaluate(random => {
      const originalRandom = Math.random;
      Math.random = () => {
        Math.random = originalRandom;
        return random;
      };
      document.querySelector('.usage-today-share').click();
    }, (feltCard.palIndex + 0.5) / palImages.length);
  } else {
    await page.locator(buttonSelector).click();
  }
  const card = page.locator('.pal-card.day');
  const controls = page.locator('.pal-share.on');
  const image = card.locator('.hero img');
  const imageSrc = await image.evaluate(async img => {
    await img.decode();
    return img.src;
  });
  const palIndex = palImages.indexOf(digest(imageSrc));
  assert.ok(palIndex >= 0, 'Today card must use visible pal card art');
  await checkHold(card, controls, { w: 168, h: 236, scale });
  const text = await card.textContent();
  assert.ok(text.includes('123,456'));
  assert.equal(await card.locator('.usage-today-breakdown').getAttribute('aria-label'), i18n.panel_today_breakdown);
  assert.deepEqual(await card.locator('.usage-today-row').evaluateAll(rows =>
    rows.map(row => [...row.querySelectorAll('span')].map(span => span.textContent))),
  services.map(([, name, , tokensText, percent]) => [name, tokensText, percent]));
  const widths = await card.locator('.usage-today-bar i').evaluateAll(segments =>
    segments.map(segment => parseFloat(segment.style.width)));
  assert.deepEqual(widths, services.map(([, , tokens]) => tokens / 123456 * 100));
  assert.ok(await card.evaluate(element => {
    const lastRow = element.querySelector('.usage-today-row:last-child').getBoundingClientRect();
    const credit = element.querySelector('.link').getBoundingClientRect();
    return lastRow.bottom <= credit.top;
  }));
  assert.doesNotMatch(text, privateValue);
  const date = await card.locator('.top .tag').textContent();
  assert.ok(date.trim());
  assert.equal(await card.locator('.link').textContent(), credit);
  const styles = await card.evaluate(element => Object.fromEntries(
    ['.pal-day', '.top', '.tag', '.hero', '.hero img', '.num span', '.num b',
      '.usage-today-row', '.usage-today-bar i', '.link'].map(selector => {
      const style = getComputedStyle(element.querySelector(selector));
      return [selector, ['backgroundColor', 'backgroundImage', 'color', 'fontFamily', 'fontSize',
        'fontWeight', 'letterSpacing', 'lineHeight', 'textShadow', 'textTransform', 'colorScheme',
        'textRendering', 'webkitFontSmoothing'].map(key => style[key])];
    }),
  ));
  if (feltCard) assert.deepEqual(styles, feltCard.styles);

  const share = controls.locator('.go');
  await share.click();
  const menu = page.locator('.pal-share-menu');
  assert.deepEqual(await menu.locator('button').allTextContents(), [
    `@${i18n.panel_card_share_threads}`, `X${i18n.panel_card_share_x}`, `⧉${i18n.panel_card_share_copy}`,
    `↓${i18n.panel_card_share_save}`, `⋯${i18n.panel_card_share_more}`,
  ]);
  await menu.getByRole('button', { name: /More/ }).click();
  await page.waitForFunction(() => window.shared.length === 1);
  const { message, canvasText, canvasImages } = await page.evaluate(() => ({
    message: window.shared[0], canvasText: window.canvasText, canvasImages: window.canvasImages,
  }));
  const { png, anchor, requestId, ...metadata } = message;
  assert.ok(Number.isInteger(requestId));
  assert.deepEqual(metadata, {
    action: 'share_pal_card', target: 'more', name: 'today',
    text: i18n.panel_today_share_text.replace('{tokens}', '123,456'),
  });
  assert.ok(anchor.w > 0 && anchor.h > 0);
  const bytes = Buffer.from(png, 'base64');
  assert.equal(bytes.subarray(0, 8).toString('hex'), '89504e470d0a1a0a');
  assert.deepEqual([bytes.readUInt32BE(16), bytes.readUInt32BE(20)], [1080, 1350]);
  assert.ok(canvasText.includes('123,456'));
  for (const [, name, , tokensText, percent] of services) {
    for (const value of [name, tokensText, percent]) {
      assert.ok(canvasText.includes(value), `PNG missing ${value}`);
    }
  }
  assert.ok(canvasText.includes(date));
  assert.ok(canvasText.includes(credit));
  assert.deepEqual(canvasImages.map(digest), [palImages[palIndex]]);
  assert.doesNotMatch(canvasText.join(' '), privateValue);
  const pngHash = digest(bytes);
  if (feltCard) {
    assert.equal(palIndex, feltCard.palIndex);
    assert.equal(pngHash, feltCard.pngHash, 'The same inputs must export the same PNG as Felt');
  }
  await controls.locator('.keep').click();
  await card.waitFor({ state: 'detached' });
  return { palIndex, pngHash, styles };
}

async function checkOptionalBreakdown(page) {
  const card = page.locator('.pal-card.day');
  const controls = page.locator('.pal-share.on');
  await page.setViewportSize({ width: 218, height: 174 });
  for (const tokens of [null, 0, 2000]) {
    await page.evaluate(tokens => {
      const data = structuredClone(usageDemoPayloads.en);
      data.footer.today.tokensCount = String(tokens || 0);
      data.footer.today.shareTokensCount = String(tokens || 0);
      if (tokens === null) delete data.footer.today.byService;
      else data.footer.today.byService = [{ card: 'codex', tokens, tokensText: '2.0K' }];
      usageApplyState(data);
    }, tokens);
    await page.locator(buttonSelector).dispatchEvent('click');
    await checkHold(card, controls, { w: 168, h: 236, scale: 0.6 });
    const group = card.locator('.usage-today-breakdown');
    assert.equal(await group.count(), tokens ? 1 : 0);
    if (tokens) {
      assert.equal(await group.locator('.usage-today-row').textContent(), 'Codex2.0K100%');
      assert.equal(await group.locator('.usage-today-bar i').evaluate(i => i.style.width), '100%');
    }
    await controls.locator('.keep').click();
    await card.waitFor({ state: 'detached' });
  }
}

async function checkRandomPalPool(page) {
  const card = page.locator('.pal-card.day');
  for (const [index, expected] of palImages.entries()) {
    await page.evaluate(random => {
      const originalRandom = Math.random;
      Math.random = () => random;
      document.querySelector('.usage-today-share').click();
      Math.random = originalRandom;
    }, (index + 0.5) / palImages.length);
    assert.equal(digest(await card.locator('.hero img').getAttribute('src')), expected, palNames[index]);
    await page.locator('.pal-share.on .keep').click();
    await card.waitFor({ state: 'detached' });
  }
}

async function checkFeltCollectibles(page, url) {
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await page.setViewportSize({ width: 340, height: 560 });
  await page.clock.setFixedTime(new Date(2026, 11, 2, 12));
  // There is one unlocked pal at this date, and it starts as the rare visitor.
  await page.addInitScript(() => {
    localStorage.setItem('usage-felt-hidden-seen', '[]');
    Math.random = () => 0.05;
  });
  await page.goto(url);
  assert.equal(await page.locator('.pal-book').getAttribute('title'), i18n.panel_felt_hidden_book);
  await page.evaluate(() => {
    usageApplyPanelZoom(0.6, 1600);
    usageDemoSetLanguage('zh-TW');
    const animate = Element.prototype.animate;
    Element.prototype.animate = function (keyframes, options) {
      if (this.matches('.pal-card') && keyframes[1]?.transform?.includes('scale(.1)')) {
        const from = this.getBoundingClientRect();
        const to = document.querySelector('.pal-book').getBoundingClientRect();
        const zoom = Number(getComputedStyle(document.documentElement).zoom);
        window.flight = {
          keyframe: keyframes[1].transform,
          x: (to.left + to.width / 2 - from.left - from.width / 2) / zoom,
          y: (to.top + to.height / 2 - from.top - from.height / 2) / zoom,
        };
      }
      return animate.call(this, keyframes, options);
    };
  });
  assert.equal(await page.locator('.pal-book').getAttribute('title'), require('../i18n.json')['zh-TW'].panel_felt_hidden_book);
  const card = page.locator('.pal-card:not(.day)');
  const controls = page.locator('.pal-share.on');
  for (const inDex of [false, true]) {
    if (inDex) {
      await page.locator('.pal-book').click();
      await page.locator('.pal-dex-cell.seen .share').evaluate(button => {
        button.click();
        button.click();
      });
      assert.equal(await card.count(), 1);
    }
    await page.waitForFunction(() => {
      const flip = document.querySelector('.pal-card.show:not(.face-up) .flip');
      return flip && flip.getAnimations().some(animation => animation.playState === 'running');
    });
    await checkHold(card, controls, { w: 136, h: 190, scale: 0.6 });
    assert.ok(await card.evaluate(element =>
      getComputedStyle(element.querySelector('.flip')).transformStyle === 'flat'
      && getComputedStyle(element.querySelector('.front')).backfaceVisibility === 'visible'
      && getComputedStyle(element.querySelector('.back')).display === 'none'));
    await controls.locator('.keep').click();
    await card.waitFor({ state: 'detached' });
    if (!inDex) {
      const flight = await page.evaluate(() => window.flight);
      const [, x, y] = flight.keyframe.match(/translate\(([^p]+)px, ([^p]+)px\)/);
      assert.ok(Math.abs(Number(x) - flight.x) < 0.1);
      assert.ok(Math.abs(Number(y) - flight.y) < 0.1);
    }
  }
  await page.locator('.pal-dex-x').click();
}

async function checkMidnightAndShareResult(page, url) {
  await page.setViewportSize({ width: 280, height: 600 });
  await page.clock.setFixedTime(new Date(2026, 10, 24, 23, 59));
  await page.goto(url);
  const button = page.locator(buttonSelector);
  const card = page.locator('.pal-card.day');
  assert.equal(await button.isDisabled(), true);
  await button.dispatchEvent('click');
  assert.equal(await card.count(), 0);
  await prepareDemoTotals(page);
  assert.equal(await button.isEnabled(), true);
  await page.clock.setFixedTime(new Date(2026, 10, 25, 0, 1));
  await button.dispatchEvent('click');
  assert.equal(await card.count(), 0);
  await page.evaluate(() => {
    const state = structuredClone(usageDemoPayloads.en);
    state.footer.today.day = '2026-11-25';
    state.footer.today.shareTokensCount = '0';
    usageApplyState(state);
    window.webkit.messageHandlers.usage.postMessage = raw => {
      const message = JSON.parse(raw);
      if (message.action === 'share_pal_card') window.shareRequest = message;
    };
  });
  await button.click();
  assert.equal(await card.locator('.num b').textContent(), '0');
  assert.equal(await card.locator('.top .tag').textContent(), 'Wed, 11/25');

  const controls = page.locator('.pal-share.on');
  const go = controls.locator('.go');
  await go.click();
  await page.locator('.pal-share-menu').getByRole('button', { name: /Save Image/ }).click();
  await page.waitForFunction(() => window.shareRequest?.target === 'save');
  assert.equal(await go.textContent(), i18n.panel_card_share);
  assert.equal(await go.isDisabled(), true);
  await page.evaluate(() => usageShareCardResult({ requestId: shareRequest.requestId, success: false }));
  await page.waitForFunction(text => document.querySelector('.pal-share .go').textContent === text,
    i18n.panel_card_save_error);
  assert.equal(await go.isEnabled(), true);
  assert.equal(await controls.locator('.keep').isVisible(), true);

  for (const target of ['threads', 'x']) {
    if (target === 'x') await button.click();
    await go.click();
    await page.locator('.pal-share-menu').getByRole('button', { name: new RegExp(i18n[`panel_card_share_${target}`]) }).click();
    await page.waitForFunction(target => window.shareRequest?.target === target, target);
    await page.evaluate(() => usageShareCardResult({ requestId: shareRequest.requestId, success: true }));
    assert.equal(await controls.locator('.go.done').textContent(), i18n[`panel_card_shared_${target}`]);
    const bounds = await controls.boundingBox();
    assert.ok(Math.abs(bounds.x + bounds.width / 2 - 140) < 1);
    assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= 280);
    await card.waitFor({ state: 'detached' });
  }
}

async function checkMissedUnlocks(page, url) {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.setViewportSize({ width: 364, height: 812 });
  await page.clock.setFixedTime(new Date(2026, 11, 16, 12));
  await page.goto(url);
  await page.evaluate(() => {
    // A fresh URL has already started a visit. Seed an empty book before restarting.
    localStorage.setItem('usage-felt-hidden-seen', '[]');
  });
  await page.reload();
  const book = page.locator('.pal-book span');
  await page.waitForFunction(() => document.querySelector('.pal-book span').textContent === '3/12');
  await page.reload();
  assert.equal(await book.textContent(), '3/12');
}

async function checkFileStorage(directory) {
  const profile = path.join(directory, 'usage-browser-profile');
  const url = pathToFileURL(path.join(directory, 'felt.html')).href;
  const saved = [
    ['usage-felt-hidden-seen', '["tuanli"]'],
    ['usage-felt-hello', '2026-11-24'],
    ['usage-felt-week', '{"claude":1796400000}'],
  ];
  for (const write of [true, false]) {
    const context = await playwright[engine].launchPersistentContext(profile, { reducedMotion: 'reduce' });
    try {
      const page = context.pages()[0] || await context.newPage();
      await page.addInitScript(() => { window.usageHost = 'windows'; });
      await page.clock.setFixedTime(new Date(2026, 10, 24, 12));
      await page.goto(url);
      if (write) {
        await page.evaluate(entries => {
          for (const [key, value] of entries) localStorage.setItem(key, value);
        }, saved);
        await page.goto(pathToFileURL(path.join(directory, 'classic.html')).href);
        await page.goto(url);
      }
      assert.deepEqual(await page.evaluate(entries =>
        entries.map(([key]) => [key, localStorage.getItem(key)]), saved), saved);
    } finally {
      await context.close();
    }
  }
}

async function main() {
  const directory = process.argv[2];
  const themes = ['felt', ...fs.readdirSync(assetDir)
    .filter(file => file.endsWith('.html') && file !== 'felt.html').map(file => path.parse(file).name)];
  const browser = await playwright[engine].launch();
  try {
    const page = await browser.newPage({ reducedMotion: 'reduce' });
    await page.clock.setFixedTime(new Date(2026, 10, 24, 12));
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.addInitScript(() => {
      const host = new URLSearchParams(location.search).get('host');
      if (host === 'browser') return;
      if (host === 'windows') window.usageHost = 'windows';
      if (host === 'pywebview') window.pywebview = {};
      window.webkit = { messageHandlers: { usage: { postMessage() {} } } };
    });
    const url = id => pathToFileURL(path.join(directory, `${id}.html`)).href;
    const layouts = [
      { width: 364, language: 'en', alerts: false, install: false, scale: 1 },
      { width: 320, language: 'ja', alerts: true, install: true, scale: 1 },
      { width: 380, language: 'zh-TW', alerts: true, install: false, scale: 0.6 },
    ];
    let feltCard;
    for (const id of themes) {
      const baseline = [];
      await page.goto(`${url(id)}?host=windows`);
      assert.equal(await page.locator(buttonSelector).count(), 0, `${id}: Windows`);
      if (id !== 'world_cup') {
        for (const layout of layouts) baseline.push(await setLayout(page, layout));
      }
      await page.goto(url(id));
      if (id === 'world_cup') {
        // The scoreboard has no Today line and its footer has room for the existing controls.
        assert.equal(await page.locator(todaySelector).count(), 0);
        assert.equal(await page.locator(buttonSelector).count(), 0);
        continue;
      }
      assert.equal(await page.locator(buttonSelector).count(), 1, id);
      await prepareDemoTotals(page);
      for (const [index, layout] of layouts.entries()) {
        const result = await setLayout(page, layout);
        assert.ok(result.sizes[2] > 0, `${id}: missing native height report`);
        assert.deepEqual(result.sizes, baseline[index].sizes, `${id}: footer or panel height changed`);
        assert.deepEqual(result.position, { inFooter: true, clickable: true, right: true, centered: true },
          `${id}/${layout.width}/${layout.scale}: share button placement`);
      }
      const result = await checkCard(page, id === 'felt' || id === 'classic' ? 0.6 : 1, feltCard);
      if (id === 'felt') feltCard = result;
      if (id === 'felt' || id === 'classic') await checkOptionalBreakdown(page);
      if (id === 'classic') await checkRandomPalPool(page);
      assert.deepEqual(errors, [], id);
    }
    for (const host of ['browser', 'pywebview']) {
      await page.goto(`${url('classic')}?host=${host}`);
      assert.equal(await page.locator(buttonSelector).count(), 0, host);
    }
    await checkMidnightAndShareResult(page, url('classic'));
    await checkMissedUnlocks(page, `${url('felt')}?host=windows`);
    await checkFeltCollectibles(page, url('felt'));
    assert.deepEqual(errors, []);
    console.log(`${engine}: tested ${themes.length - 1} share cards and World Cup's existing footer.`);
  } finally {
    await browser.close();
  }
  await checkFileStorage(directory);
}

main().catch(error => { console.error(error); process.exitCode = 1; });

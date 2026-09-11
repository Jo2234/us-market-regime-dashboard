// Run with: node scripts/verify_dashboard_browser.mjs [origin]
import { chromium } from '../frontend/node_modules/playwright/index.mjs';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
const origin = process.argv[2] || 'https://market-regime-dashboard-mu.vercel.app';
const directory = new URL(`../artifacts/${process.env.PLAYWRIGHT_OUTPUT || 'production-review'}/`, import.meta.url);
await mkdir(directory, { recursive: true });
const browser = await chromium.launch({ headless: true });
const results = [];
try {
  for (const [name, width, height] of [['desktop', 1440, 900], ['mobile', 375, 812]]) {
    const page = await browser.newPage({ viewport: { width, height }, hasTouch: name === 'mobile', isMobile: name === 'mobile', reducedMotion: 'reduce' });
    const errors = [];
    if (process.env.PLAYWRIGHT_OFFLINE === '1') {
      if (!process.env.PLAYWRIGHT_API_FIXTURE || !['localhost', '127.0.0.1'].includes(new URL(origin).hostname)) {
        throw new Error('Offline verification requires a fixture and loopback origin');
      }
      await page.route('**/*', route => new URL(route.request().url()).origin === new URL(origin).origin
        ? route.continue() : route.abort());
    }
    if (process.env.PLAYWRIGHT_API_FIXTURE) {
      const body = await readFile(process.env.PLAYWRIGHT_API_FIXTURE, 'utf8');
      await page.route('**/api/dashboard/summary*', route => route.fulfill({ contentType: 'application/json', body }));
    }
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
    await page.addInitScript(() => {
      Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'hidden' });
      Object.defineProperty(document, 'hidden', { configurable: true, get: () => true });
    });
    const liveResponse = page.waitForResponse(response => response.url().includes('/dashboard/summary') && !response.url().includes('cached_only') && response.status() === 200);
    const started = Date.now();
    await page.goto(origin, { waitUntil: 'domcontentloaded' });
    await page.getByLabel('Market overview', { exact: true }).waitFor({ timeout: 30_000 });
    const renderMs = Date.now() - started;
    await page.locator('[aria-label="Market overview"][aria-busy="false"]').waitFor({ timeout: 30_000 });
    const api = await (await liveResponse).json();
    const settledMs = Date.now() - started;
    const state = await page.evaluate(() => ({
      visibility: document.visibilityState,
      overflow: document.documentElement.scrollWidth > innerWidth,
      title: document.title,
      header: document.querySelector('.refresh-status')?.textContent,
      freshness: document.querySelector('.freshness-pill')?.textContent?.trim(),
      text: document.body.innerText,
    }));
    for (const symbol of ['SPY', 'QQQ']) {
      const item = api.major_indices.find(item => item.symbol === symbol);
      const quote = api.live_quotes?.[symbol];
      const price = api.market_status?.is_open && quote?.is_current_session && !quote?.is_stale ? quote.price : item.price;
      if (!state.text.includes(price.toFixed(2))) throw new Error(`${symbol} price does not match the API`);
    }
    // Delayed/missing sources are legitimate warnings, never a reason to hide
    // stale data just to pass browser QA. Check agreement with the API instead.
    if (state.header?.includes('Last updated')) throw new Error('Duplicate timestamp regression');
    const delivery = api.artifact_delivery;
    if (delivery?.view === 'historical' && state.freshness !== 'Historical snapshot') throw new Error('Historical view label mismatch');
    if (delivery?.view !== 'historical' && delivery?.status === 'pending' && !state.text.includes('Awaiting scheduled research snapshot')) throw new Error('Pending research label missing');
    if (delivery?.view !== 'historical' && delivery?.status === 'overdue' && state.freshness !== 'Research overdue') throw new Error('Overdue research label missing');
    if (state.freshness === 'Fresh' && api.data_freshness.instruments.some(row => row.affects_group_freshness !== false && (row.is_stale || !row.latest_date))) throw new Error('False fresh source label');
    if (await page.locator('.history-chart .score-panel').count() !== (api.regime_v2 ? 3 : 4)) throw new Error('Missing small multiples');
    if ((await page.locator('.signal-value').allTextContents()).some(value => /\.\d{4,}/.test(value))) throw new Error('Unformatted signal values');
    await page.screenshot({ path: new URL(`${name}-overview.png`, directory).pathname });
    if (api.regime_v2) {
      await page.locator('.bottom-line').screenshot({ path: new URL(`${name}-bottom-line.png`, directory).pathname });
      if (!(await page.locator('.bottom-line').textContent()).includes(api.regime_v2.headline)) throw new Error('Headline does not match API');
    }
    await page.locator('.regime-panel').screenshot({ path: new URL(`${name}-scores.png`, directory).pathname });
    await page.locator('.signal-table-panel').screenshot({ path: new URL(`${name}-signals.png`, directory).pathname });
    const history = page.locator('.history-panel');
    if (await history.count()) {
      await history.screenshot({ path: new URL(`${name}-history.png`, directory).pathname });
      const slider = page.getByRole('slider', { name: 'Historical regime date' });
      await slider.focus();
      await slider.press('Home');
      const first = await slider.getAttribute('aria-valuetext');
      await slider.press('ArrowRight');
      const second = await slider.getAttribute('aria-valuetext');
      if (!first || first === second) throw new Error('Keyboard date inspection failed');
      const svg = page.getByRole('img', { name: 'Historical regime scores chart' });
      await svg.scrollIntoViewIfNeeded();
      const bounds = await svg.boundingBox();
      await page.mouse.move(bounds.x + bounds.width * .5, bounds.y + 12);
      await page.mouse.down();
      await page.mouse.move(bounds.x + bounds.width * .75, bounds.y + 12, { steps: 5 });
      await page.mouse.up();
      if (name === 'mobile') {
        await page.touchscreen.tap(bounds.x + bounds.width * .3, bounds.y + 12);
        const tapped = await slider.inputValue();
        const touch = await page.context().newCDPSession(page);
        await touch.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: bounds.x + bounds.width * .3, y: bounds.y + 12 }] });
        for (const ratio of [.4, .5, .6]) await touch.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: bounds.x + bounds.width * ratio, y: bounds.y + 12 }] });
        await touch.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
        if (await slider.inputValue() === tapped) throw new Error('Touch drag did not update the synchronized inspector');
      }
      if (await slider.inputValue() === '1') throw new Error('Ribbon pointer inspection failed');
      const inspector = await page.locator('.history-tooltip').textContent();
      const toggle = page.getByRole('checkbox', { name: '5-day smoothing' });
      if (await toggle.count()) {
        await toggle.check();
        if (await page.locator('.history-tooltip').textContent() !== inspector) throw new Error('Smoothing changed raw inspector');
        await history.screenshot({ path: new URL(`${name}-history-smoothed.png`, directory).pathname });
        await toggle.uncheck();
      }
    }
    await page.screenshot({ path: new URL(`${name}-full.png`, directory).pathname, fullPage: true });
    const result = { name, renderMs, settledMs, historyPoints: (api.historical_regimes_v2?.length || api.historical_regimes.length), ...state, errors };
    results.push(result);
    console.log(JSON.stringify({ ...result, text: undefined }));
    if (state.overflow || errors.length || /demo_seed/.test(state.text)) throw new Error(`${name} browser check failed`);
    await page.close();
  }
} finally {
  await writeFile(new URL('browser-results.json', directory), JSON.stringify(results, null, 2));
  await browser.close();
}

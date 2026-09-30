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
    const page = await browser.newPage({ viewport: { width, height }, reducedMotion: 'reduce' });
    const errors = [];
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
    const started = Date.now();
    await page.goto(origin, { waitUntil: 'domcontentloaded' });
    await page.getByLabel('Market overview', { exact: true }).waitFor({ timeout: 30_000 });
    const renderMs = Date.now() - started;
    await page.locator('[aria-label="Market overview"][aria-busy="false"]').waitFor({ timeout: 30_000 });
    const state = await page.evaluate(() => ({
      visibility: document.visibilityState,
      overflow: document.documentElement.scrollWidth > innerWidth,
      title: document.title,
      header: document.querySelector('.refresh-status')?.textContent,
      text: document.body.innerText,
    }));
    await page.screenshot({ path: new URL(`${name}-overview.png`, directory).pathname });
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
      const bounds = await svg.boundingBox();
      await page.mouse.move(bounds.x + bounds.width * .5, bounds.y + 12);
      await page.mouse.down();
      await page.mouse.move(bounds.x + bounds.width * .75, bounds.y + 12, { steps: 5 });
      await page.mouse.up();
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
    const result = { name, renderMs, ...state, errors };
    results.push(result);
    console.log(JSON.stringify({ ...result, text: undefined }));
    if (state.overflow || errors.length || /demo_seed/.test(state.text)) throw new Error(`${name} browser check failed`);
    await page.close();
  }
} finally {
  await writeFile(new URL('browser-results.json', directory), JSON.stringify(results, null, 2));
  await browser.close();
}

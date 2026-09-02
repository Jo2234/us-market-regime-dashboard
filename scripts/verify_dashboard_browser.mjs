// Run with: node scripts/verify_dashboard_browser.mjs [origin]
import { chromium } from '../frontend/node_modules/playwright/index.mjs';
import { mkdir, writeFile } from 'node:fs/promises';
const origin = process.argv[2] || 'https://market-regime-dashboard-mu.vercel.app';
const directory = new URL('../artifacts/production-review/', import.meta.url);
await mkdir(directory, { recursive: true });
const browser = await chromium.launch({ headless: true });
const results = [];
try {
  for (const [name, width, height] of [['desktop', 1440, 900], ['mobile', 375, 812]]) {
    const page = await browser.newPage({ viewport: { width, height }, reducedMotion: 'reduce' });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
    await page.addInitScript(() => {
      Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'hidden' });
      Object.defineProperty(document, 'hidden', { configurable: true, get: () => true });
    });
    const started = Date.now();
    await page.goto(origin, { waitUntil: 'domcontentloaded' });
    await page.getByLabel('Market overview', { exact: true }).waitFor({ timeout: 30_000 });
    await page.waitForFunction(() => !document.querySelector('.refresh-spinner'), { timeout: 30_000 });
    const renderMs = Date.now() - started;
    const state = await page.evaluate(() => ({
      visibility: document.visibilityState,
      overflow: document.documentElement.scrollWidth > innerWidth,
      title: document.title,
      header: document.querySelector('.refresh-status')?.textContent,
      text: document.body.innerText,
    }));
    await page.screenshot({ path: new URL(`${name}-overview.png`, directory).pathname });
    const history = page.locator('.history-panel');
    if (await history.count()) await history.screenshot({ path: new URL(`${name}-history.png`, directory).pathname });
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

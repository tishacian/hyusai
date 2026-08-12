/**
 * Two remaining close-ups: the chat overlay opened from the title bar (the
 * drawer variant of the chat panel, distinct from the /chat page) and the NAWA
 * catalogue maturity badges, which use the client theme rather than the cockpit
 * status tones.
 */
import { chromium } from '@playwright/test';
import { mkdirSync } from 'node:fs';

const BASE = process.env.BASE ?? 'http://localhost:4200';
const OUT = 'e2e/qa-visual';
mkdirSync(OUT, { recursive: true });

const ME = { id: 'u-qa', email: 'qa@local.test', name: 'QA Local', roles: ['admin', 'owner'] };
const WS = {
  id: 'ws-qa',
  slug: 'nawa',
  name: 'NAWA',
  settings: { features: { voice: true }, voice: { enabled: true, provider: 'openai' } },
};
const payload = (p) =>
  /\/auth\/me|\/users\/me|\/me$/.test(p)
    ? ME
    : /\/workspaces\/?$/.test(p)
      ? [WS]
      : /\/workspaces\/[^/]+\/?$/.test(p)
        ? WS
        : /\/(skills|systems|capabilities|runs|collections|apps|presets)(\/)?$/.test(p)
          ? []
          : { items: [], results: [], total: 0 };

const browser = await chromium.launch();

for (const theme of ['light', 'dark']) {
  for (const locale of ['fr', 'en']) {
    const ctx = await browser.newContext({
      viewport: { width: 1600, height: 1000 },
      deviceScaleFactor: 2,
    });
    await ctx.addInitScript(
      ({ theme, locale }) => {
        localStorage.setItem('agentium_token', 'Bearer qa-local-token');
        localStorage.setItem('agentium_workspace_slug', 'nawa');
        localStorage.setItem('agentium_theme', theme);
        localStorage.setItem('agentium_locale', locale);
      },
      { theme, locale },
    );
    const page = await ctx.newPage();
    await page.route('**/api/**', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(payload(new URL(route.request().url()).pathname)),
      }),
    );
    await page.route(/https:\/\/fonts\./, (route) => route.abort());

    // --- chat overlay from the title bar ---------------------------------
    await page.goto(`${BASE}/hypervisor`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(3000);
    const trigger = page
      .locator('header button, app-title-bar button')
      .filter({ hasText: '' })
      .last();
    const chatBtn = page
      .locator('button[title*="hat" i], button[aria-label*="hat" i], button[title*="ssistant" i]')
      .first();
    const btn = (await chatBtn.count()) ? chatBtn : trigger;
    await btn.click().catch(() => {});
    await page.waitForTimeout(2200);
    await page.screenshot({ path: `${OUT}/overlay-chat-${theme}-${locale}.png` });
    const opened = await page.evaluate(
      () => !!document.querySelector('app-chat-overlay, app-chat-panel'),
    );
    console.log(`overlay-chat-${theme}-${locale}: panel in DOM = ${opened}`);

    // --- NAWA catalogue badges ------------------------------------------
    await page.goto(`${BASE}/nawa/itsd`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2600);
    await page.screenshot({
      path: `${OUT}/nawa-badges-${theme}-${locale}.png`,
      clip: { x: 0, y: 80, width: 1600, height: 300 },
    });
    console.log(`nawa-badges-${theme}-${locale}: ok`);
    await ctx.close();
  }
}

await browser.close();

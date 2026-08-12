/**
 * Close-up on the maturity badges: the new "preview" (violet) tone used for
 * beta connectors/apps must read against the cyan ready/available tone in both
 * themes. The two beta connectors are feature-gated, so the fake workspace
 * enables them here.
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
  settings: { features: { sap_hana_connector: true, rpa_bridge: true, model_portal: true } },
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
  for (const locale of ['en', 'fr']) {
    const ctx = await browser.newContext({
      viewport: { width: 1600, height: 1200 },
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

    // --- connectors page: data & storage category holds both beta cards ----
    await page.goto(`${BASE}/connectors`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2600);
    const beta = page.locator('text=SAP HANA').first();
    if (await beta.count()) {
      await beta.scrollIntoViewIfNeeded();
      await page.waitForTimeout(400);
      const box = await beta.evaluate((el) => {
        const card = el.closest('article, [class*="ck-card"], div');
        const r = (card ?? el).getBoundingClientRect();
        return { x: r.x, y: r.y, width: r.width, height: r.height };
      });
      await page.screenshot({
        path: `${OUT}/badges-connectors-${theme}-${locale}.png`,
        clip: {
          x: Math.max(0, box.x - 20),
          y: Math.max(0, box.y - 120),
          width: Math.min(1560, box.width + 700),
          height: 420,
        },
      });
      console.log(`connectors badges ${theme}-${locale}: captured`);
    } else {
      console.log(`connectors badges ${theme}-${locale}: SAP HANA card not found`);
    }

    // --- token values for the preview trio vs the info trio ---------------
    const tones = await page.evaluate(() => {
      const cs = getComputedStyle(document.documentElement);
      const g = (n) => cs.getPropertyValue(n).trim();
      return ['preview', 'info', 'ok', 'warn'].map((t) => ({
        tone: t,
        fg: g(`--ck-status-${t}-fg`),
        bg: g(`--ck-status-${t}-bg`),
        line: g(`--ck-status-${t}-line`),
      }));
    });
    console.log(`  tones (${theme}):`, JSON.stringify(tones));

    // --- resources > connectors tab: the ck-pill "Beta" variant -----------
    await page.goto(`${BASE}/resources?tab=connectors`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2600);
    const pill = page.locator('.ck-tone-preview').first();
    if (await pill.count()) {
      await pill.scrollIntoViewIfNeeded();
      await page.waitForTimeout(400);
      const r = await pill.evaluate((el) => {
        const b = el.getBoundingClientRect();
        return { x: b.x, y: b.y };
      });
      await page.screenshot({
        path: `${OUT}/badges-resources-${theme}-${locale}.png`,
        clip: { x: 0, y: Math.max(0, r.y - 260), width: 1600, height: 560 },
      });
      console.log(`resources badges ${theme}-${locale}: captured`);
    } else {
      console.log(`resources badges ${theme}-${locale}: no .ck-tone-preview rendered`);
    }
    await ctx.close();
  }
}

await browser.close();

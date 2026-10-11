/**
 * 2x element close-ups. Downscaled full-page shots hide small-type problems
 * (accents on 10px uppercase labels, hairline contrast), so anything suspicious
 * gets re-shot here at device scale 2, clipped to the element.
 */
import { chromium } from '@playwright/test';
import { mkdirSync } from 'node:fs';

const BASE = process.env.BASE ?? 'http://localhost:4200';
const OUT = 'e2e/qa-visual';
mkdirSync(OUT, { recursive: true });

const ME = { id: 'u-qa', email: 'qa@local.test', name: 'QA Local', roles: ['admin', 'owner'] };
const WS = { id: 'ws-qa', slug: 'nawa', name: 'NAWA', settings: { features: {} } };
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

// name, route, selector
const TARGETS = [
  ['flow-checklist', '/orchestration', '[class*="checklist"], .ck-surface:has-text("task_no_skill")'],
  ['flow-canvas', '/orchestration', 'f-canvas, [class*="flow-canvas"], main'],
  ['flow-palette', '/orchestration', 'aside, [class*="palette"]'],
  ['titlebar', '/hypervisor', 'app-title-bar, header'],
  ['breadcrumb', '/skills', 'app-semantic-zoom-breadcrumb, nav'],
];

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

    let current = '';
    for (const [name, route, selector] of TARGETS) {
      if (current !== route) {
        await page.goto(BASE + route, { waitUntil: 'domcontentloaded' });
        await page.waitForTimeout(3000);
        current = route;
      }
      const el = page.locator(selector).first();
      if (!(await el.count())) {
        console.log(`${name}-${theme}-${locale}: selector miss (${selector})`);
        continue;
      }
      try {
        await el.screenshot({ path: `${OUT}/zoom-${name}-${theme}-${locale}.png` });
        console.log(`zoom-${name}-${theme}-${locale}: ok`);
      } catch (e) {
        console.log(`${name}-${theme}-${locale}: ${e.message.split('\n')[0]}`);
      }
    }
    await ctx.close();
  }
}

await browser.close();

/**
 * Visual check of the tenant emblem in the title bar, light and dark.
 *
 * Same fake session + `/api/**` stub as qa-visual.mjs, with one addition that
 * is the whole point of the run: the stubbed workspace declares a
 * `platform_brand` carrying `emblem_light`, so the title bar has a light
 * variant to pick up. The `nolight` cell drops that key to show what every
 * tenant that declares no variant still gets.
 */
import { chromium } from '@playwright/test';
import { mkdirSync } from 'node:fs';

const BASE = process.env.BASE ?? 'http://localhost:4200';
const OUT = process.env.OUT ?? 'e2e/qa-brand';
mkdirSync(OUT, { recursive: true });

const ME = {
  id: 'u-qa',
  email: 'qa@local.test',
  name: 'QA Local',
  roles: ['admin', 'owner'],
  workspaces: [{ id: 'ws-qa', slug: 'nawa', name: 'NAWA' }],
};

const BRAND = {
  label: 'NAWA',
  emblem: '/assets/nawa/nawa-logo.png',
  emblem_light: '/assets/nawa/nawa-logo-transparent.png',
  home: '/nawa/itsd',
};

function workspace(withLightVariant) {
  const brand = { ...BRAND };
  if (!withLightVariant) delete brand.emblem_light;
  return {
    id: 'ws-qa',
    slug: 'nawa',
    name: 'NAWA',
    settings: { features: {}, platform_brand: brand },
  };
}

function body(path, ws) {
  if (/\/auth\/me|\/users\/me|\/me$/.test(path)) return ME;
  if (/\/workspaces\/?$/.test(path)) return [ws];
  if (/\/workspaces\/[^/]+\/?$/.test(path)) return ws;
  if (path.includes('/help')) return { items: [] };
  if (/\/(skills|systems|capabilities|flows|runs|collections|apps|presets|use-cases|sessions|documents|connectors)(\/)?$/.test(path)) {
    return [];
  }
  return { items: [], results: [], total: 0, count: 0 };
}

const browser = await chromium.launch();

for (const [tag, withLightVariant] of [['brand', true], ['nolight', false]]) {
  const ws = workspace(withLightVariant);
  for (const theme of ['light', 'dark']) {
    const ctx = await browser.newContext({ viewport: { width: 1600, height: 400 } });
    await ctx.addInitScript(
      ({ theme }) => {
        localStorage.setItem('agentium_token', 'Bearer qa-local-token');
        localStorage.setItem('agentium_workspace_slug', 'nawa');
        localStorage.setItem('agentium_theme', theme);
        localStorage.setItem('agentium_locale', 'en');
        localStorage.removeItem('agentium_business_theme');
      },
      { theme },
    );
    const page = await ctx.newPage();
    await page.route('**/api/**', async (route) => {
      const url = new URL(route.request().url());
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(body(url.pathname, ws)),
      });
    });
    await page.route(/https:\/\/fonts\./, (route) => route.abort());
    await page.goto(`${BASE}/hypervisor`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2600);

    const img = page.locator('.tb-emblem-brand').first();
    const shown = await img.evaluate((el) => ({
      src: new URL(el.getAttribute('src'), location.origin).pathname,
      radius: getComputedStyle(el).borderTopLeftRadius,
      naturalWidth: el.naturalWidth,
    }));
    console.log(`${tag}-${theme}`.padEnd(16), JSON.stringify(shown));

    await page.screenshot({ path: `${OUT}/${tag}-${theme}-titlebar.png`, clip: { x: 0, y: 0, width: 460, height: 48 } });
    await page.screenshot({ path: `${OUT}/${tag}-${theme}-full.png` });
    await ctx.close();
  }
}

await browser.close();
console.log(`\nwrote ${OUT}/`);

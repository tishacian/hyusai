/**
 * Throwaway QA harness for the light/dark x FR/EN matrix.
 *
 * Keycloak is not runnable locally, so this fakes the client-side session the
 * same way e2e/tests/16 does (a token in localStorage) and answers every
 * `/api/v1/**` call with a minimal, well-formed payload. That renders each
 * screen's chrome, empty states and copy — which is what theme and wording QA
 * needs. It does NOT exercise data-dense states; anything that only appears
 * with real rows is out of reach here and must be said so in the report.
 */
import { chromium } from '@playwright/test';
import { mkdirSync, writeFileSync } from 'node:fs';

const BASE = process.env.BASE ?? 'http://localhost:4200';
const OUT = 'e2e/qa-out';
mkdirSync(OUT, { recursive: true });

const SCREENS = [
  ['hypervisor', '/hypervisor'],
  ['skills', '/skills'],
  ['systems', '/systems'],
  ['client360', '/client360'],
  ['capture', '/knowledge'],
  ['flows', '/flows'],
  ['nawa', '/nawa/itsd'],
];

const ME = {
  id: 'u-qa',
  email: 'qa@local.test',
  name: 'QA Local',
  roles: ['admin'],
  workspaces: [{ id: 'ws-qa', slug: 'qa', name: 'QA workspace' }],
};

function body(path) {
  if (path.includes('/auth/me') || path.endsWith('/me')) return ME;
  if (path.includes('/workspaces')) return [ME.workspaces[0]];
  if (/\/(skills|systems|capabilities|flows|runs|collections|apps|presets|use-cases)(\/)?$/.test(path)) {
    return [];
  }
  if (path.includes('/help')) return { items: [] };
  return { items: [], results: [], total: 0, count: 0 };
}

const browser = await chromium.launch();
const report = [];

for (const theme of ['light', 'dark']) {
  for (const locale of ['en', 'fr']) {
    const ctx = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
    await ctx.addInitScript(
      ({ theme, locale }) => {
        localStorage.setItem('agentium_token', 'Bearer qa-local-token');
        localStorage.setItem('agentium_workspace_slug', 'qa');
        localStorage.setItem('agentium_theme', theme);
        localStorage.setItem('agentium_locale', locale);
        localStorage.removeItem('agentium_business_theme');
      },
      { theme, locale },
    );
    const page = await ctx.newPage();
    await page.route('**/api/v1/**', async (route) => {
      const url = new URL(route.request().url());
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(body(url.pathname)),
      });
    });
    await page.route(/https:\/\/fonts\./, (route) => route.abort());

    for (const [name, path] of SCREENS) {
      await page.goto(BASE + path, { waitUntil: 'domcontentloaded' });
      await page.waitForTimeout(2200);
      const info = await page.evaluate(() => ({
        path: location.pathname,
        theme: document.documentElement.getAttribute('data-theme'),
        text: (document.body.innerText || '').replace(/\n{2,}/g, '\n'),
      }));
      const tag = `${name}-${theme}-${locale}`;
      report.push(`\n===== ${tag} (landed on ${info.path}, data-theme=${info.theme}) =====\n${info.text}`);
      if (locale === 'en' || theme === 'light') {
        await page.screenshot({ path: `${OUT}/${tag}.png` });
      }
      console.log(`${tag.padEnd(28)} -> ${info.path.padEnd(22)} ${info.text.length} chars`);
    }
    await ctx.close();
  }
}

writeFileSync(`${OUT}/matrix.txt`, report.join('\n'));
await browser.close();
console.log(`\nwrote ${OUT}/matrix.txt`);

/**
 * Visual QA sweep: light/dark x fr/en over the screens touched by the
 * UI/UX polish work. Same fake session + API stub approach as qa-matrix.mjs,
 * but screenshots every cell of the matrix (full page) and dumps rendered text
 * so language leaks and raw i18n keys can be grepped afterwards.
 */
import { chromium } from '@playwright/test';
import { mkdirSync, writeFileSync } from 'node:fs';

const BASE = process.env.BASE ?? 'http://localhost:4200';
const OUT = process.env.OUT ?? 'e2e/qa-visual';
mkdirSync(OUT, { recursive: true });

const SCREENS = (process.env.ONLY ?? '').trim()
  ? (process.env.ONLY).split(',').map((s) => s.trim()).map((s) => s.split('='))
  : [
      ['hypervisor', '/hypervisor'],
      ['skills', '/skills'],
      ['systems', '/systems'],
      ['system-new', '/systems/new'],
      ['flow', '/orchestration'],
      ['connectors', '/connectors'],
      ['resources', '/resources'],
      ['knowledge', '/knowledge'],
      ['capture', '/knowledge/capture'],
      ['chat', '/chat'],
      ['runs', '/runs'],
      ['client360', '/client360'],
      ['nawa', '/nawa/itsd'],
    ];

const ME = {
  id: 'u-qa',
  email: 'qa@local.test',
  name: 'QA Local',
  roles: ['admin', 'owner'],
  workspaces: [{ id: 'ws-qa', slug: 'nawa', name: 'NAWA' }],
};

const WS = {
  id: 'ws-qa',
  slug: 'nawa',
  name: 'NAWA',
  settings: {
    features: { voice: true, voice_realtime: true, capture_experience: 'fil' },
    voice: { enabled: true, provider: 'openai', transport: 'livekit' },
    voice_loop: { enabled: true },
    voice_output: { enabled: true },
  },
};

function body(path) {
  if (/\/auth\/me|\/users\/me|\/me$/.test(path)) return ME;
  if (/\/workspaces\/?$/.test(path)) return [WS];
  if (/\/workspaces\/[^/]+\/?$/.test(path)) return WS;
  if (path.includes('/help')) return { items: [] };
  if (/\/(skills|systems|capabilities|flows|runs|collections|apps|presets|use-cases|sessions|documents|connectors)(\/)?$/.test(path)) {
    return [];
  }
  return { items: [], results: [], total: 0, count: 0 };
}

async function makeContext(browser, theme, locale) {
  const ctx = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
  await ctx.addInitScript(
    ({ theme, locale }) => {
      localStorage.setItem('agentium_token', 'Bearer qa-local-token');
      localStorage.setItem('agentium_workspace_slug', 'nawa');
      localStorage.setItem('agentium_theme', theme);
      localStorage.setItem('agentium_locale', locale);
      localStorage.removeItem('agentium_business_theme');
    },
    { theme, locale },
  );
  const page = await ctx.newPage();
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(body(url.pathname)),
    });
  });
  await page.route(/https:\/\/fonts\./, (route) => route.abort());
  return { ctx, page };
}

const browser = await chromium.launch();
const report = [];

for (const theme of ['light', 'dark']) {
  for (const locale of ['fr', 'en']) {
    const { ctx, page } = await makeContext(browser, theme, locale);
    for (const [name, path] of SCREENS) {
      try {
        await page.goto(BASE + path, { waitUntil: 'domcontentloaded' });
        await page.waitForTimeout(2600);
      } catch (e) {
        report.push(`\n===== ${name}-${theme}-${locale} NAV FAILED: ${e.message}`);
        continue;
      }
      const info = await page.evaluate(() => ({
        path: location.pathname,
        theme: document.documentElement.getAttribute('data-theme'),
        dark: document.documentElement.classList.contains('dark'),
        text: (document.body.innerText || '').replace(/\n{2,}/g, '\n'),
      }));
      const tag = `${name}-${theme}-${locale}`;
      await page.screenshot({ path: `${OUT}/${tag}.png`, fullPage: true });
      report.push(
        `\n===== ${tag} (landed ${info.path}, data-theme=${info.theme}, dark=${info.dark}) =====\n${info.text}`,
      );
      console.log(`${tag.padEnd(30)} -> ${info.path.padEnd(24)} ${info.text.length} chars`);
    }
    await ctx.close();
  }
}

writeFileSync(`${OUT}/text.txt`, report.join('\n'));
await browser.close();
console.log(`\nwrote ${OUT}/text.txt`);

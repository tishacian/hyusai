/**
 * Theme checkpoints that need a booted shell (ThemeService is `providedIn:
 * 'root'`, so it does not exist until a screen injects it — the sign-in page
 * never does). Same fake session as qa-matrix.mjs.
 */
import { chromium } from '@playwright/test';
import { mkdirSync } from 'node:fs';

const BASE = process.env.BASE ?? 'http://localhost:4200';
const OUT = 'e2e/qa-out';
mkdirSync(OUT, { recursive: true });

const ME = { id: 'u-qa', email: 'qa@local.test', name: 'QA Local', roles: ['admin'] };
const payload = (p) =>
  /\/(skills|systems|capabilities|runs|collections|apps|presets)(\/)?$/.test(p)
    ? []
    : p.includes('/me')
      ? ME
      : { items: [], results: [], total: 0 };

async function session(browser, { theme, locale, legacy, colorScheme }) {
  const ctx = await browser.newContext({
    viewport: { width: 1600, height: 1000 },
    ...(colorScheme ? { colorScheme } : {}),
  });
  await ctx.addInitScript(
    ({ theme, locale, legacy }) => {
      localStorage.setItem('agentium_token', 'Bearer qa-local-token');
      localStorage.setItem('agentium_workspace_slug', 'qa');
      localStorage.setItem('agentium_locale', locale);
      if (theme === null) localStorage.removeItem('agentium_theme');
      else localStorage.setItem('agentium_theme', theme);
      if (legacy === null) localStorage.removeItem('agentium_business_theme');
      else localStorage.setItem('agentium_business_theme', legacy);
    },
    { theme, locale, legacy },
  );
  const page = await ctx.newPage();
  await page.route('**/api/v1/**', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(payload(new URL(route.request().url()).pathname)),
    }),
  );
  await page.route(/https:\/\/fonts\./, (route) => route.abort());
  return { ctx, page };
}

const read = (page) =>
  page.evaluate(() => ({
    dataTheme: document.documentElement.getAttribute('data-theme'),
    dark: document.documentElement.classList.contains('dark'),
    stored: localStorage.getItem('agentium_theme'),
    legacy: localStorage.getItem('agentium_business_theme'),
  }));

const browser = await chromium.launch();

// --- Checkpoint 1, on a shell that actually instantiates ThemeService ----
{
  const { ctx, page } = await session(browser, {
    theme: 'dark',
    legacy: 'light',
    locale: 'en',
  });
  await page.goto(`${BASE}/hypervisor`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('[data-testid="titlebar-theme-toggle"]', { timeout: 20000 });
  await page.waitForTimeout(1500);
  console.log('[1] after first render of a real shell ->', JSON.stringify(await read(page)));
  await page.screenshot({ path: `${OUT}/cp1-migration-shell.png` });
  await ctx.close();
}

// --- Checkpoint 6: the toggle cycle, both locales -----------------------
for (const locale of ['en', 'fr']) {
  const { ctx, page } = await session(browser, { theme: 'system', legacy: null, locale });
  await page.goto(`${BASE}/hypervisor`, { waitUntil: 'domcontentloaded' });
  const toggle = page.locator('[data-testid="titlebar-theme-toggle"]');
  await toggle.waitFor({ timeout: 20000 });
  const steps = [];
  for (let i = 0; i < 4; i++) {
    await page.waitForTimeout(350);
    steps.push({
      tooltip: await toggle.getAttribute('title'),
      aria: await toggle.getAttribute('aria-label'),
      icon: await toggle.locator('app-icon').getAttribute('ng-reflect-name').catch(() => null),
      svg: await toggle.locator('svg').getAttribute('class').catch(() => null),
      ...(await read(page)),
    });
    if (i < 3) await toggle.click();
  }
  console.log(`[6] cycle (${locale}) ->`);
  for (const s of steps) console.log('    ', JSON.stringify(s));
  await ctx.close();
}

// --- Checkpoint 7: OS flip with mode=system, app open -------------------
{
  const { ctx, page } = await session(browser, {
    theme: 'system',
    legacy: null,
    locale: 'en',
    colorScheme: 'light',
  });
  await page.goto(`${BASE}/hypervisor`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('[data-testid="titlebar-theme-toggle"]', { timeout: 20000 });
  await page.waitForTimeout(1200);
  console.log('[7] OS light ->', JSON.stringify(await read(page)));
  await page.emulateMedia({ colorScheme: 'dark' });
  await page.waitForTimeout(800);
  console.log('[7] OS -> dark, no reload ->', JSON.stringify(await read(page)));
  await page.emulateMedia({ colorScheme: 'light' });
  await page.waitForTimeout(800);
  console.log('[7] OS -> light again ->', JSON.stringify(await read(page)));
  await ctx.close();
}

// --- Checkpoint 3 + 4: chat panel in light, and the status pills --------
for (const theme of ['light', 'dark']) {
  const { ctx, page } = await session(browser, { theme, legacy: null, locale: 'en' });
  await page.goto(`${BASE}/hypervisor`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('[data-testid="titlebar-theme-toggle"]', { timeout: 20000 });
  await page.waitForTimeout(1200);
  // Probe the four status trios against the surface they sit on.
  const pills = await page.evaluate(() => {
    const cs = getComputedStyle(document.documentElement);
    const g = (n) => cs.getPropertyValue(n).trim();
    return ['ok', 'warn', 'neg', 'info', 'neutral'].map((t) => ({
      tone: t,
      fg: g(`--ck-status-${t}-fg`),
      bg: g(`--ck-status-${t}-bg`),
      line: g(`--ck-status-${t}-line`),
    }));
  });
  console.log(`[4] status trios (${theme}) ->`, JSON.stringify(pills));

  const chatButton = page.locator('button[title*="Chat"], button[aria-label*="Chat"]').first();
  if (await chatButton.count()) {
    await chatButton.click();
    await page.waitForTimeout(1500);
    await page.screenshot({ path: `${OUT}/cp3-chat-${theme}.png` });
    console.log(`[3] chat overlay screenshot taken (${theme})`);
  } else {
    console.log(`[3] no chat trigger found in the title bar (${theme})`);
  }
  await ctx.close();
}

await browser.close();

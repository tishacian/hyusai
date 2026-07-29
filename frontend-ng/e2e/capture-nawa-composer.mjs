#!/usr/bin/env node
/**
 * Photograph the WE assistant's composer and header in all three themes, plus
 * the listening state. Run from frontend-ng:
 *   E2E_USERNAME=... E2E_PASSWORD=... node e2e/capture-nawa-composer.mjs
 *
 * The fake media device flags grant the microphone without a prompt, which is
 * what makes the listening state reachable without a human at the keyboard.
 */
import { chromium } from 'playwright';

const BASE = process.env.E2E_BASE_URL ?? 'https://agentium.papai.ai';
const USER = process.env.E2E_USERNAME;
const PASS = process.env.E2E_PASSWORD;
// Playwright ships no browser here; point at any local Chrome or Chromium.
const EXECUTABLE =
  process.env.E2E_CHROMIUM_EXECUTABLE ??
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';

if (!USER || !PASS) {
  console.error('Set E2E_USERNAME and E2E_PASSWORD');
  process.exit(1);
}

const browser = await chromium.launch({
  executablePath: EXECUTABLE,
  args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream'],
});
const context = await browser.newContext({
  viewport: { width: 1280, height: 860 },
  deviceScaleFactor: 2,
  permissions: ['microphone'],
});
const page = await context.newPage();
page.on('console', (message) => {
  if (message.type() === 'error') console.log('CONSOLE ERROR:', message.text().slice(0, 200));
});

await page.goto(`${BASE}/auth/signin`, { waitUntil: 'domcontentloaded' });
const login = await page.evaluate(
  async ({ username, password }) => {
    const res = await fetch('/api/v1/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: username, password, remember_me: false }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok || !body.token) return { ok: false, status: res.status };
    localStorage.setItem('agentium_token', `Bearer ${body.token}`);
    if (body.refresh_token) localStorage.setItem('agentium_refresh_token', body.refresh_token);
    localStorage.setItem('agentium_workspace_slug', 'nawa');
    return { ok: true };
  },
  { username: USER, password: PASS },
);
if (!login.ok) throw new Error(`connexion refusée : ${JSON.stringify(login)}`);
console.log('connecté');

await page.goto(`${BASE}/nawa/itsd/assistant`, { waitUntil: 'domcontentloaded' });
await page.waitForSelector('.as-composer', { timeout: 60000 });
await page.waitForTimeout(1500);

const composer = page.locator('.as-composer');
const header = page.locator('.nawa-header');

// Le sélecteur est un bouton unique qui cycle Auto → Light → Dark.
const themeButton = page.locator('app-nawa-theme-toggle button');
for (let i = 0; i < 3; i += 1) {
  const label = (await themeButton.textContent()).trim().toLowerCase();
  await composer.screenshot({ path: `/tmp/nawa-shot-composer-${label}.png` });
  await header.screenshot({ path: `/tmp/nawa-shot-header-${label}.png` });
  console.log(`capturé : ${label}`);
  await themeButton.click();
  await page.waitForTimeout(600);
}

await page.screenshot({ path: '/tmp/nawa-shot-page-dark.png' });

// L'état d'écoute, avec le micro simulé de Chrome.
const speak = page.locator('.as-mic');
if (await speak.count()) {
  await speak.click();
  await page.waitForTimeout(1200);
  await composer.screenshot({ path: '/tmp/nawa-shot-composer-listening.png' });
  console.log('capturé : écoute');
}

await browser.close();

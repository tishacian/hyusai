#!/usr/bin/env node
/**
 * Capture Agentium UI screenshots for the PIH alignment deck.
 * Run from frontend-ng:
 *   E2E_USERNAME=... E2E_PASSWORD=... node e2e/capture-pih-screenshots.mjs
 */
import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.join(__dirname, '../../docs/render/assets/screenshots');
const BASE = process.env.E2E_BASE_URL ?? 'https://agentium.papai.ai';

const USER = process.env.E2E_USERNAME;
const PASS = process.env.E2E_PASSWORD;
const WORKSPACE =
  process.env.E2E_WORKSPACE_SLUG ?? 'agentium-showcase';

if (!USER || !PASS) {
  console.error('Set E2E_USERNAME and E2E_PASSWORD');
  process.exit(1);
}

fs.mkdirSync(OUT, { recursive: true });

async function login(page) {
  await page.goto(`${BASE}/auth/signin`, { waitUntil: 'networkidle' });
  const login = await page.evaluate(
    async ({ username, password }) => {
      const res = await fetch('/api/v1/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: username, password, remember_me: false }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok || !body.token) {
        return { ok: false, status: res.status, body };
      }
      localStorage.setItem('agentium_token', `Bearer ${body.token}`);
      if (body.refresh_token) {
        localStorage.setItem('agentium_refresh_token', body.refresh_token);
      }
      return { ok: true, workspace_slug: body.workspace_slug, workspaces: body.workspaces };
    },
    { username: USER, password: PASS },
  );
  await page.evaluate((slug) => {
    localStorage.setItem('agentium_workspace_slug', slug);
  }, WORKSPACE);
  if (!login.ok) {
    throw new Error(`Login failed: ${JSON.stringify(login)}`);
  }
  console.log('Logged in. Workspace:', login.workspace_slug ?? '(default)');
  return login;
}

async function shot(page, name, url, opts = {}) {
  const { waitMs = 2500, selector, fullPage = false } = opts;
  console.log(`→ ${name}: ${url}`);
  await page.goto(`${BASE}${url}`, { waitUntil: 'networkidle', timeout: 60_000 });
  if (selector) {
    await page.locator(selector).first().waitFor({ state: 'visible', timeout: 20_000 }).catch(() => {});
  }
  await page.waitForTimeout(waitMs);
  const file = path.join(OUT, `${name}.png`);
  await page.screenshot({ path: file, fullPage });
  console.log(`  saved ${file}`);
  return file;
}

async function main() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 2,
    ignoreHTTPSErrors: true,
  });
  const page = await context.newPage();

  try {
    await login(page);
    console.log('Workspace slug:', WORKSPACE);

    const targets = [
      ['01_hypervisor', '/hypervisor', { waitMs: 4000 }],
      ['02_steering', '/steering', { waitMs: 3500 }],
      ['03_governance_audit', '/governance/audit', { waitMs: 3500 }],
      ['04_systems', '/systems', { waitMs: 3500 }],
      ['05_observability', '/observability', { waitMs: 3500 }],
      ['06_chat', '/chat', { waitMs: 3500 }],
      ['07_access_roles', '/governance/access', { waitMs: 3500 }],
    ];

    for (const [name, url, opts] of targets) {
      try {
        await shot(page, name, url, opts);
      } catch (err) {
        console.warn(`  skip ${name}: ${err.message}`);
      }
    }

    try {
      const runId = await page.evaluate(async () => {
        const res = await fetch('/api/v1/runs?limit=1', {
          headers: { Authorization: localStorage.getItem('agentium_token') ?? '' },
        });
        const body = await res.json();
        return body?.runs?.[0]?.id ?? null;
      });
      if (runId) {
        await shot(page, '08_run_detail', `/runs/${runId}`, { waitMs: 4500 });
      }
    } catch (err) {
      console.warn(`  skip run detail: ${err.message}`);
    }

    try {
      await shot(page, '09_evaluation', '/evaluation', { waitMs: 3500 });
    } catch (err) {
      console.warn(`  skip evaluation: ${err.message}`);
    }

    console.log('\nDone. Screenshots in:', OUT);
  } finally {
    await browser.close();
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});

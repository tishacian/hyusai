#!/usr/bin/env node
/**
 * Films the Nawa data/ML demo — the seven beats of
 * `docs/demo-runs/2026-08-25-nawa-data-ml/DEMO-SCRIPT.md`, in order, against a
 * live deployment.
 *
 * Committed rather than improvised because the recording is evidence: a video
 * whose script lives in somebody's shell history cannot be re-shot when the
 * copy changes, and "the demo looks right" is a claim that has to be
 * re-checkable at the next revision.
 *
 * The browser is deliberately configured for **French** (`--browser-locale`,
 * `fr-FR` by default) while the workspace declares `presentation.locale = en`.
 * That is not a detail: it is the whole point of the recording. A video shot in
 * an English browser would prove nothing about what the room's laptop will do.
 *
 * Usage:
 *   AGENTIUM_EMAIL=… AGENTIUM_PASSWORD=… \
 *   node scripts/playwright/nawa_data_ml_demo.mjs \
 *     --host=https://agentium.papai.ai --workspace=nawa --out=/tmp/nawa-demo
 *
 * Environment:
 *   AGENTIUM_EMAIL / AGENTIUM_PASSWORD   credentials, never committed
 *   NAWA_CHURN_SYSTEM / NAWA_RADIO_SYSTEM  optional System name overrides
 */
import { chromium } from 'playwright';
import { mkdir, readdir, rename, writeFile } from 'node:fs/promises';
import path from 'node:path';

function arg(name, fallback = null) {
  const prefix = `--${name}=`;
  const found = process.argv.find((item) => item.startsWith(prefix));
  return found ? found.slice(prefix.length) : fallback;
}

const HOST = (arg('host', process.env.AGENTIUM_HOST || 'https://agentium.papai.ai')).replace(/\/$/, '');
const WORKSPACE = arg('workspace', process.env.NAWA_WORKSPACE_SLUG || 'nawa');
const OUT = arg('out', '/tmp/nawa-data-ml-demo');
const BROWSER_LOCALE = arg('browser-locale', 'fr-FR');
const CHURN_SYSTEM = process.env.NAWA_CHURN_SYSTEM || 'Churn Radar';
const RADIO_SYSTEM = process.env.NAWA_RADIO_SYSTEM || 'Radio Watch';
const EMAIL = process.env.AGENTIUM_EMAIL || '';
const PASSWORD = process.env.AGENTIUM_PASSWORD || '';

const notes = [];

function note(beat, message) {
  const line = `[beat ${beat}] ${message}`;
  notes.push(line);
  console.log(line);
}

/** A pause long enough to read what just appeared. */
const beat = (page, ms = 1400) => page.waitForTimeout(ms);

async function api(page, pathname) {
  return page.evaluate(
    async ({ url, workspace }) => {
      const token = localStorage.getItem('agentium_token') || '';
      const res = await fetch(url, {
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: token } : {}),
          'X-Workspace-Slug': workspace,
        },
      });
      return { status: res.status, body: await res.json().catch(() => null) };
    },
    { url: `${HOST}${pathname}`, workspace: WORKSPACE },
  );
}

/**
 * Scrolls an element into the middle of the viewport before it is talked about.
 * `scrollIntoViewIfNeeded` parks a target at the very edge, which reads badly on
 * a recording — the thing being discussed should be where the eye already is.
 */
async function centre(locator) {
  await locator.scrollIntoViewIfNeeded().catch(() => {});
  await locator.evaluate((node) => node.scrollIntoView({ block: 'center', behavior: 'smooth' })).catch(() => {});
}

async function login(context) {
  const page = await context.newPage();
  await page.goto(`${HOST}/auth/signin`, { waitUntil: 'domcontentloaded', timeout: 90_000 });
  const result = await page.evaluate(
    async ({ email, password, workspace }) => {
      const res = await fetch('/api/v1/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password, remember_me: false }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok || !body.token) return { ok: false, status: res.status };
      localStorage.setItem('agentium_token', `Bearer ${body.token}`);
      if (body.refresh_token) localStorage.setItem('agentium_refresh_token', body.refresh_token);
      localStorage.setItem('agentium_workspace_slug', workspace);
      // Deliberately NOT setting `agentium_locale`: the recording is about the
      // workspace's declared language winning on an unconfigured browser.
      return { ok: true };
    },
    { email: EMAIL, password: PASSWORD, workspace: WORKSPACE },
  );
  if (!result.ok) throw new Error(`login failed: ${JSON.stringify(result)}`);
  await page.close();
}

async function main() {
  if (!EMAIL || !PASSWORD) throw new Error('AGENTIUM_EMAIL and AGENTIUM_PASSWORD are required');
  await mkdir(OUT, { recursive: true });

  const browser = await chromium.launch({ args: ['--force-device-scale-factor=1'] });
  const authContext = await browser.newContext({ locale: BROWSER_LOCALE, ignoreHTTPSErrors: true });
  await login(authContext);
  const state = await authContext.storageState();
  await authContext.close();

  const context = await browser.newContext({
    storageState: state,
    locale: BROWSER_LOCALE,
    viewport: { width: 1600, height: 900 },
    recordVideo: { dir: path.join(OUT, 'video'), size: { width: 1600, height: 900 } },
    ignoreHTTPSErrors: true,
  });
  const page = await context.newPage();

  try {
    // ---------------------------------------------------------------------
    // Beat 1 — the export arrives dirty
    // ---------------------------------------------------------------------
    await page.goto(`${HOST}/data`, { waitUntil: 'domcontentloaded', timeout: 90_000 });
    await page.waitForSelector('text=/Subscriber base/i', { timeout: 60_000 });
    await beat(page, 2200);

    const lang = await page.evaluate(() => document.documentElement.lang);
    note(0, `browser asked for ${BROWSER_LOCALE}; the workspace opened <html lang="${lang}">`);
    if (lang !== 'en') throw new Error(`expected the workspace to open English, got lang="${lang}"`);

    const datasets = await api(page, '/api/v1/datasets?limit=50');
    const rows = datasets.body?.items || datasets.body?.datasets || datasets.body || [];
    const names = rows.map((r) => r.name).filter(Boolean);
    note(1, `Data lists ${rows.length} datasets: ${names.join(' · ')}`);
    const french = names.filter((n) => /[\u00c0-\u017f]|Base clients|cellules/i.test(n));
    if (french.length) throw new Error(`French dataset names still present: ${french.join(', ')}`);

    const raw = rows.find((r) => /raw export/i.test(r.name || ''));
    if (!raw) throw new Error('the raw export dataset was not found');
    await page.click(`text=${raw.name}`);
    await page.waitForURL(/\/data\/[0-9a-f-]{36}/, { timeout: 30_000 });
    await beat(page, 2200);
    note(1, `${raw.name}: ${raw.row_count} rows, ${raw.column_count} columns`);

    // The column profile: click a header to open its popover of statistics.
    const header = page.locator('th', { hasText: 'region' }).first();
    if (await header.count()) {
      await centre(header);
      await header.click();
      await beat(page, 2600);
      await page.keyboard.press('Escape');
    }
    // Then the profile panel proper, which is what the beat is really about.
    const schemaTab = page.locator('button', { hasText: /^Schema$/ }).first();
    if (await schemaTab.count()) {
      await schemaTab.click();
      await beat(page, 2400);
      await page.mouse.wheel(0, 600);
      await beat(page, 1800);
    }

    // ---------------------------------------------------------------------
    // Beats 2, 3, 4 — the canvas, the SQL workshop, the Polars node
    // ---------------------------------------------------------------------
    const systems = await api(page, '/api/v1/systems');
    const systemRows = systems.body?.items || systems.body?.systems || systems.body || [];
    const churn = systemRows.find((s) => (s.name || '').trim() === CHURN_SYSTEM);
    const radio = systemRows.find((s) => (s.name || '').trim() === RADIO_SYSTEM);
    if (!churn) throw new Error(`System "${CHURN_SYSTEM}" not found`);

    await page.goto(`${HOST}/systems/${churn.id}/flow`, { waitUntil: 'domcontentloaded', timeout: 90_000 });
    await page.waitForSelector('text=/SQL cleanup/i', { timeout: 60_000 });
    await beat(page, 3000);
    const labels = await page.locator('text=/SQL cleanup|Polars features|Churn training|Score the base|Retention brief/').allTextContents();
    note(2, `canvas node labels: ${[...new Set(labels.map((l) => l.trim()))].join(' · ')}`);

    for (const [label, hold] of [['SQL cleanup', 3400], ['Polars features', 2800], ['Churn training', 2800]]) {
      const node = page.locator(`text=${label}`).first();
      if (!(await node.count())) continue;
      await centre(node);
      await node.click();
      await beat(page, hold);
    }

    // ---------------------------------------------------------------------
    // Beats 4 and 5 — the model card, then the comparison
    // ---------------------------------------------------------------------
    await page.goto(`${HOST}/models`, { waitUntil: 'domcontentloaded', timeout: 90_000 });
    await page.waitForSelector('text=/Churn Radar/i', { timeout: 60_000 });
    await beat(page, 2400);

    const models = await api(page, '/api/v1/ml-models?limit=50');
    const modelRows = models.body?.items || models.body?.models || models.body || [];
    const ranked = modelRows
      .filter((m) => /Churn Radar/i.test(m.name || ''))
      .sort((a, b) => (a.version || 0) - (b.version || 0));
    note(4, ranked.map((m) => `v${m.version} ${m.algo} ${m.metrics_json?.primary?.value ?? '?'}${m.is_champion ? ' ←serving' : ''}`).join(' · '));

    const best = ranked.find((m) => !m.is_champion && m.status === 'ready') || ranked[0];
    await page.goto(`${HOST}/models/${best.id}`, { waitUntil: 'domcontentloaded', timeout: 90_000 });
    await page.waitForSelector('text=/Churn Radar/i', { timeout: 60_000 });
    await beat(page, 3000);
    // Down the card: tiles, then the curves, then the confusion heatmap and the
    // importances. Slowly, because this is the beat that has to be readable.
    for (let i = 0; i < 5; i += 1) {
      await page.mouse.wheel(0, 460);
      await beat(page, 1500);
    }

    for (const [tab, hold] of [['Comparison', 4200], ['Input contract', 2600], ['Versions', 2600]]) {
      const button = page.locator('button', { hasText: new RegExp(`^${tab}$`) }).first();
      if (!(await button.count())) {
        note(5, `tab "${tab}" not present`);
        continue;
      }
      await button.click();
      await beat(page, hold);
      if (tab === 'Comparison') {
        const compare = page.locator('button', { hasText: /same rows|Re-evaluate|Compare/i }).first();
        if (await compare.count()) {
          await compare.click();
          await beat(page, 6000);
        }
      }
    }

    // ---------------------------------------------------------------------
    // Beat 6 — the Playground
    // ---------------------------------------------------------------------
    const serving = ranked.find((m) => m.is_champion) || ranked[0];
    await page.goto(`${HOST}/models/${serving.id}`, { waitUntil: 'domcontentloaded', timeout: 90_000 });
    await page.waitForSelector('text=/Churn Radar/i', { timeout: 60_000 });
    const predictTab = page.locator('button', { hasText: /^Predict$/ }).first();
    if (await predictTab.count()) {
      await predictTab.click();
      await beat(page, 2600);
      const tickets = page.locator('input[type="number"]').nth(3);
      if (await tickets.count()) {
        await centre(tickets);
        await tickets.fill('3');
        await beat(page, 900);
      }
      const go = page.locator('button', { hasText: /Predict|Run/i }).last();
      if (await go.count()) {
        await go.click();
        await beat(page, 7000);
      }
      note(6, 'Playground answered');
    }

    // The published skill and its provenance chip.
    await page.goto(`${HOST}/skills`, { waitUntil: 'domcontentloaded', timeout: 90_000 });
    await beat(page, 2000);
    const chip = page.locator('text=/Churn Radar v[0-9]/').first();
    if (await chip.count()) {
      await centre(chip);
      note(6, `skill provenance chip: ${(await chip.textContent())?.trim()}`);
      await beat(page, 2600);
    }

    // ---------------------------------------------------------------------
    // Beat 7 — the dbt pipeline and its watchlist
    // ---------------------------------------------------------------------
    if (radio) {
      await page.goto(`${HOST}/systems/${radio.id}/flow`, { waitUntil: 'domcontentloaded', timeout: 90_000 });
      await page.waitForSelector('text=/cells at risk/i', { timeout: 60_000 });
      await beat(page, 2800);
      const dbtNode = page.locator('text=/dbt — cells at risk/').first();
      if (await dbtNode.count()) {
        await centre(dbtNode);
        await dbtNode.click();
        await beat(page, 3600);
      }
      note(7, 'Radio Watch canvas and its dbt node');
    }

    const watchlist = rows.find((r) => /cells at risk/i.test(r.name || ''));
    if (watchlist) {
      await page.goto(`${HOST}/data/${watchlist.id}`, { waitUntil: 'domcontentloaded', timeout: 90_000 });
      await beat(page, 3200);
      await page.mouse.wheel(0, 400);
      await beat(page, 2600);
      note(7, `${watchlist.name}: ${watchlist.row_count} rows, ${watchlist.column_count} columns`);
    }

    await beat(page, 1200);
  } finally {
    await context.close();
    const dir = path.join(OUT, 'video');
    const files = await readdir(dir).catch(() => []);
    const webm = files.find((f) => f.endsWith('.webm'));
    if (webm) {
      await rename(path.join(dir, webm), path.join(OUT, 'nawa-data-ml-demo.webm'));
      console.log(`video: ${path.join(OUT, 'nawa-data-ml-demo.webm')}`);
    }
    await writeFile(path.join(OUT, 'notes.txt'), `${notes.join('\n')}\n`, 'utf8');
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});

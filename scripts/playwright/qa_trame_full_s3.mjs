/**
 * QA UI — Trame démo unifiée SENTINEL-CI (S1 + S2 + S3 + V21)
 *
 * Single browser session, single login — enchaîne S1.1→S1.8, S2, S3.1→S3.6, V21.
 *
 * Usage: node scripts/playwright/qa_trame_full_s3.mjs
 * Env:   AGENTIUM_HOST, AGENTIUM_EMAIL, AGENTIUM_PASSWORD, OUT_DIR
 */
import { chromium } from 'playwright';
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import {
  HOST,
  WORKSPACE,
  createHarnessState,
  log,
  login,
  summarizeResults,
} from './qa_trame_shared.mjs';
import { runTrameFullSteps } from './qa_trame_full.mjs';
import { runS3SecuritySteps } from './qa_s3_security.mjs';

const OUT_DIR =
  process.env.OUT_DIR ||
  `/Users/thib/Developer/PAPAI/omnirag/docs/status-screenshots/${new Date().toISOString().slice(0, 10)}-qa-gate`;

async function main() {
  await mkdir(OUT_DIR, { recursive: true });
  const state = createHarnessState();
  log(state, `QA trame S1+S2+S3 -> ${HOST}, OUT=${OUT_DIR}`);

  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({
    viewport: { width: 1920, height: 1080 },
    locale: 'fr-FR',
    timezoneId: 'Africa/Abidjan',
  });
  const page = await ctx.newPage();
  page.setDefaultTimeout(30_000);
  page.on('console', (m) => {
    if (m.type() === 'error') state.consoleErrors.push(m.text().slice(0, 200));
  });
  page.on('pageerror', (e) => state.consoleErrors.push(`pageerror: ${e.message}`));

  try {
    await login(page, state, OUT_DIR);
    await runTrameFullSteps(page, state, OUT_DIR);
    await runS3SecuritySteps(page, state, OUT_DIR, { includeV21: true });
  } finally {
    await ctx.close();
    await browser.close();
  }

  const { pass, partial, fail, total } = summarizeResults(state);
  const summary = {
    host: HOST,
    workspace: WORKSPACE,
    scope: 'S1+S2+S3+V21',
    runAt: new Date().toISOString(),
    durationSec: ((Date.now() - state.startedAt) / 1000).toFixed(1),
    pass,
    partial,
    fail,
    total,
    results: state.results,
    consoleErrors: state.consoleErrors.slice(0, 30),
    windowEvents: state.windowEvents.slice(0, 50),
    sseActionEffects: state.sseChunks
      .filter((c) => c.chunk_type === 'action_effect')
      .slice(0, 30),
  };
  await writeFile(join(OUT_DIR, 'qa-trame-full-s3-results.json'), JSON.stringify(summary, null, 2), 'utf8');
  log(state, `Done. ${total} steps. JSON -> ${join(OUT_DIR, 'qa-trame-full-s3-results.json')}`);
  log(state, `PASS=${pass} PARTIAL=${partial} FAIL=${fail}`);
  process.exit(fail > 0 ? 1 : 0);
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((e) => {
    console.error('[FATAL]', e.message, e.stack);
    process.exit(2);
  });
}

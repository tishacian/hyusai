// Re-capture des slides AYA manquantes (S1.3 / S1.4 / S1.5 / S1.6 / S2.4 / S2.5)
// apres redeploy HEAD 9d0f8012.
//
// PIVOT: les actions AYA ne se declenchent pas en envoyant du texte au
// "Quick Panel" (mode chat workspace, sans resolver). On capture donc les
// vues plan-B URL qui produisent le meme narratif visuel pour chaque slot.

import { chromium } from 'playwright';
import { mkdir, stat, writeFile } from 'node:fs/promises';
import { join } from 'node:path';

const HOST = (process.env.AGENTIUM_HOST || 'https://agentium.papai.ai').replace(/\/+$/, '');
const EMAIL = process.env.AGENTIUM_EMAIL || 'thibaud.ishacian@datategy.net';
const PASSWORD = process.env.AGENTIUM_PASSWORD || 'ponfib-jaNca5-sisfoc';
const OUT_DIR =
  process.env.OUT_DIR ||
  '/Users/thib/Developer/PAPAI/omnirag/docs/status-screenshots/2026-05-25-postdeploy';

const NAV_TIMEOUT = 30_000;
const PER_STEP_TIMEOUT = 35_000;
const TOTAL_BUDGET_MS = 7 * 60 * 1000;

const startedAt = Date.now();
function log(m) {
  const e = ((Date.now() - startedAt) / 1000).toFixed(1);
  console.log(`[${e.padStart(6, ' ')}s] ${m}`);
}

const STITCH_CSS = `
  app-root, app-shell, app-mission-room, .mission-shell, .mission-main, .ck-scroll,
  app-vp-cockpit, app-hypervisor {
    height: auto !important;
    max-height: none !important;
    min-height: auto !important;
    overflow: visible !important;
  }
  .mission-shell {
    display: block !important;
    grid-template-rows: none !important;
  }
  html, body { height: auto !important; overflow: visible !important; }
  app-mission-rail {
    position: absolute !important;
    top: 0 !important; left: 0 !important;
    height: 100vh !important;
  }
  .mission-main { margin-left: 0 !important; }
`;

async function injectStitchCss(page) {
  await page.addStyleTag({ content: STITCH_CSS });
  await page.waitForTimeout(400);
}

async function login(page) {
  log(`[auth] goto ${HOST}/`);
  await page.goto(`${HOST}/`, { waitUntil: 'domcontentloaded', timeout: NAV_TIMEOUT });
  await page.waitForTimeout(1500);
  await page.locator('#signin-email').fill(EMAIL);
  await page.locator('#signin-password').fill(PASSWORD);
  await page.locator('form.ck-auth-form button[type="submit"]').click();
  await page.waitForURL(/\/hypervisor(\/|$)/, { timeout: 20_000 });
  log(`[auth] OK -> ${page.url()}`);
}

async function safeGoto(page, path, label) {
  const url = path.startsWith('http') ? path : `${HOST}${path}`;
  log(`[nav] ${label} -> ${url}`);
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: NAV_TIMEOUT });
  try { await page.waitForLoadState('networkidle', { timeout: 8_000 }); } catch (_) {}
}

async function shot(page, name, { fullPage = true, postWaitMs = 1500, stitch = true } = {}) {
  if (stitch) await injectStitchCss(page);
  await page.waitForTimeout(postWaitMs);
  const file = join(OUT_DIR, `${name}.png`);
  try {
    await page.screenshot({ path: file, fullPage });
    const st = await stat(file);
    log(`  -> ${name}.png (${(st.size / 1024).toFixed(1)} KB, fullPage=${fullPage}, stitch=${stitch})`);
    return { name, file, sizeBytes: st.size, ok: true };
  } catch (e) {
    log(`  !! shot ${name} echec: ${e.message}`);
    return { name, file: null, sizeBytes: 0, ok: false, error: e.message };
  }
}

async function clickFirstAvailable(page, selectors, label) {
  for (const sel of selectors) {
    try {
      const loc = page.locator(sel).first();
      if ((await loc.count()) === 0) continue;
      await loc.scrollIntoViewIfNeeded({ timeout: 2_000 });
      await loc.click({ timeout: 3_000 });
      log(`  (${label}) click ${sel}`);
      return sel;
    } catch (_) {}
  }
  log(`  (${label}) aucun selecteur n a marche parmi ${selectors.length}`);
  return null;
}

async function openAyaPanel(page) {
  for (const sel of ['[aria-label="Ouvrir AYA"]', '.assistant-badge', 'button:has-text("AYA")']) {
    try {
      const loc = page.locator(sel).first();
      if ((await loc.count()) === 0) continue;
      await loc.click({ timeout: 4_000 });
      log(`  (aya) panel ouvert via ${sel}`);
      await page.waitForTimeout(1500);
      return true;
    } catch (_) {}
  }
  return false;
}

async function sendAyaPrompt(page, text) {
  const ta = page.locator('textarea[name="userInput"]').first();
  await ta.waitFor({ state: 'visible', timeout: 10_000 });
  await ta.fill(text);
  await page.waitForTimeout(300);
  await ta.press('Enter');
  log(`  (aya) prompt: ${text.slice(0, 80)}`);
  try {
    await page.waitForFunction(
      () => {
        const t = document.querySelector('textarea[name="userInput"]');
        return t && !t.disabled;
      },
      { timeout: 18_000 },
    );
  } catch (_) {
    log(`  (aya) WARN textarea reste disabled apres 18s`);
  }
}

async function main() {
  await mkdir(OUT_DIR, { recursive: true });
  log(`OUT_DIR=${OUT_DIR}`);

  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({
    viewport: { width: 1920, height: 1080 },
    locale: 'fr-FR',
    timezoneId: 'Africa/Abidjan',
  });
  const page = await ctx.newPage();
  page.setDefaultTimeout(PER_STEP_TIMEOUT);
  page.setDefaultNavigationTimeout(NAV_TIMEOUT);

  const consoleErrors = [];
  page.on('console', (m) => {
    if (m.type() === 'error') consoleErrors.push({ url: page.url(), text: m.text() });
  });
  page.on('pageerror', (e) => consoleErrors.push({ url: page.url(), text: `pageerror: ${e.message}` }));

  // Chaque step: navigate to plan-B URL + capture full-page.
  // Pour ceux qui ont vraiment besoin du chat AYA, on garde l ancienne route.
  const STEPS = [
    {
      name: '16-aya-port-webcam',
      slot: 'S1.5 situation au port',
      run: async () => {
        await safeGoto(page, '/hypervisor/mission-room/strategie?mode=live&panel=maritime', 'maritime live');
        await page.waitForTimeout(3500);
        // Essayer d ouvrir le panel maritime si masque.
        await clickFirstAvailable(
          page,
          ['button:has-text("Maritime")', 'button:has-text("Mode live")', 'text=/Mode live/i'],
          'maritime-toggle',
        );
        await page.waitForTimeout(2500);
        return shot(page, '16-aya-port-webcam', { fullPage: true, stitch: true, postWaitMs: 2000 });
      },
    },
    {
      name: '17-aya-vessel-cargo',
      slot: 'S1.4 cargo MV Atlantic Trader',
      run: async () => {
        await safeGoto(page, '/hypervisor/mission-room/strategie?mode=live&panel=maritime&vessel=627012345', 'maritime + vessel');
        await page.waitForTimeout(3500);
        // Tenter de cliquer sur le pin/cargo Atlantic Trader si visible.
        await clickFirstAvailable(
          page,
          ['text=/Atlantic Trader/i', 'text=/MV Atlantic/i', '[data-vessel-mmsi="627012345"]'],
          'vessel-pin',
        );
        await page.waitForTimeout(2500);
        return shot(page, '17-aya-vessel-cargo', { fullPage: true, stitch: true, postWaitMs: 2000 });
      },
    },
    {
      name: '18-aya-mail-derogation',
      slot: 'S1.6 mail derogation douanes (AYA prompt direct)',
      run: async () => {
        // Pas de plan B URL pour le drawer mail. On capture le chat AYA
        // (Quick Panel) avec la reponse texte / template propose. C est
        // visuellement parlant : montre que AYA propose un brouillon.
        await safeGoto(page, '/hypervisor/mission-room/cockpit', 'cockpit');
        await page.waitForTimeout(2500);
        const opened = await openAyaPanel(page);
        if (!opened) log('  WARN panel AYA pas ouvert');
        try {
          await sendAyaPrompt(page, 'AYA, redige le mail au chef des douanes pour la derogation.');
        } catch (e) { log(`  prompt fail: ${e.message}`); }
        await page.waitForTimeout(2500);
        return shot(page, '18-aya-mail-derogation', { fullPage: false, stitch: false, postWaitMs: 1500 });
      },
    },
    {
      name: '19-aya-focus-nord-napie',
      slot: 'S1.3 focus zone Nord + Napie',
      run: async () => {
        await safeGoto(page, '/hypervisor/mission-room/strategie?focus=zone-nord&highlight=proj-drone-centre-napie', 'focus Nord');
        await page.waitForTimeout(3500);
        return shot(page, '19-aya-focus-nord-napie', { fullPage: true, stitch: true, postWaitMs: 2000 });
      },
    },
    {
      name: '20-aya-rapport-strategique',
      slot: 'S2.4 package decisions cacao',
      run: async () => {
        await safeGoto(page, '/hypervisor/mission-room/decisions?focus=package-cacao-diversification', 'decisions cacao');
        await page.waitForTimeout(3500);
        return shot(page, '20-aya-rapport-strategique', { fullPage: true, stitch: true, postWaitMs: 2000 });
      },
    },
    {
      name: '21-aya-odj-cacao',
      slot: 'S2.5 meeting Prefet Nawa + ODJ',
      run: async () => {
        await safeGoto(page, '/hypervisor/mission-room/agenda/meeting/evt-prefet-nawa', 'meeting Prefet Nawa');
        await page.waitForTimeout(3500);
        return shot(page, '21-aya-odj-cacao', { fullPage: true, stitch: true, postWaitMs: 2000 });
      },
    },
  ];

  const results = [];
  try {
    await login(page);

    for (const step of STEPS) {
      if (Date.now() - startedAt > TOTAL_BUDGET_MS) {
        log(`!! budget ${TOTAL_BUDGET_MS / 1000}s depasse, skip ${step.name}`);
        results.push({ name: step.name, slot: step.slot, ok: false, sizeBytes: 0, error: 'budget timeout' });
        continue;
      }
      log(`==> [${step.name}] ${step.slot}`);
      try {
        const r = await step.run();
        results.push({ ...r, slot: step.slot });
      } catch (e) {
        log(`  !! step ${step.name} echec: ${e.message}`);
        const r = await shot(page, `${step.name}-fallback`, { fullPage: false, stitch: false, postWaitMs: 500 });
        results.push({ ...r, slot: step.slot, ok: false, error: e.message });
      }
    }
  } finally {
    await ctx.close();
    await browser.close();
  }

  const summary = {
    host: HOST,
    out_dir: OUT_DIR,
    started_at: new Date(startedAt).toISOString(),
    ended_at: new Date().toISOString(),
    results,
    console_errors: consoleErrors.slice(0, 30),
  };
  await writeFile(join(OUT_DIR, 'capture-summary.json'), JSON.stringify(summary, null, 2), 'utf8');

  log(`---- recap ----`);
  for (const r of results) {
    const kb = r.sizeBytes ? (r.sizeBytes / 1024).toFixed(1) : '0';
    log(`  ${r.name.padEnd(36, ' ')} ${kb.padStart(7, ' ')} KB${r.error ? ` · err=${r.error.slice(0, 60)}` : ''}`);
  }
}

main().catch((e) => { console.error(`[FATAL] ${e.message}`); console.error(e.stack); process.exit(2); });

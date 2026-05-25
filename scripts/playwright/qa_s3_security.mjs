/**
 * QA UI — Trame démo SENTINEL-CI Scénario 3 (Posture sécuritaire dual-axis)
 *
 * Rejoue S3.1 → S3.6 contre une instance frontend Agentium :
 *   S3.1 — `aya.show_security_posture` (cockpit, bloc Posture sécuritaire)
 *   S3.2 — `aya.show_social_pulse`     (strategie, drawer pulsation sociale)
 *   S3.3 — `aya.trace_rumor_origin`    (strategie, drawer trace OSINT + proposition)
 *   S3.4 — `aya.show_troops_movement`  (strategie, drawer ADS-B advisory)
 *   S3.5 — `aya.show_reputation_drill` (reputation, 2 positifs + 1 critique)
 *   S3.6 — `aya.draft_security_communique` (drawer brouillon communiqué)
 *
 * Pour chaque étape : capture d'écran + lecture des SSE chunks (action_effect,
 * map_command, assistant-draft-open) + heuristiques DOM. Toutes les sondes
 * sont demo-safe (aucune écriture en base, aucune modification de workspace).
 *
 * Usage : node scripts/playwright/qa_s3_security.mjs
 * Env   : AGENTIUM_HOST, AGENTIUM_EMAIL, AGENTIUM_PASSWORD, OUT_DIR
 */
import { chromium } from 'playwright';
import { mkdir, writeFile, stat } from 'node:fs/promises';
import { join } from 'node:path';

const HOST = (process.env.AGENTIUM_HOST || 'https://agentium.papai.ai').replace(/\/+$/, '');
const EMAIL = process.env.AGENTIUM_EMAIL || 'thibaud.ishacian@datategy.net';
const PASSWORD = process.env.AGENTIUM_PASSWORD || 'ponfib-jaNca5-sisfoc';
const OUT_DIR =
  process.env.OUT_DIR ||
  '/Users/thib/Developer/PAPAI/omnirag/docs/status-screenshots/2026-05-25-qa-s3-trame';
const WORKSPACE = 'sentinel-ci';

const NAV_TIMEOUT = 45_000;
const AYA_WAIT_MS = 18_000;
const startedAt = Date.now();

const results = [];
const consoleErrors = [];
const windowEvents = [];
const sseChunks = [];

function log(m) {
  const e = ((Date.now() - startedAt) / 1000).toFixed(1);
  console.log(`[${e.padStart(6, ' ')}s] ${m}`);
}

function record(step, { status, observation, fix, priority = 'P1', screenshot = null, extra = {} }) {
  const r = { step, status, observation, fix, priority, screenshot, ...extra };
  results.push(r);
  log(`  [${status}] ${step}: ${observation.slice(0, 140)}`);
  return r;
}

async function shot(page, name) {
  const file = join(OUT_DIR, `${name}.png`);
  try {
    await page.waitForTimeout(800);
    await page.screenshot({ path: file, fullPage: false });
    const st = await stat(file);
    return { file, sizeBytes: st.size, ok: st.size > 5000 };
  } catch (e) {
    return { file: null, sizeBytes: 0, ok: false, error: e.message };
  }
}

async function login(page) {
  await page.goto(`${HOST}/`, { waitUntil: 'domcontentloaded', timeout: NAV_TIMEOUT });
  await page.waitForTimeout(1500);
  const emailSel = page.locator('#signin-email, input[type=email]').first();
  await emailSel.waitFor({ state: 'visible', timeout: 15_000 });
  await emailSel.fill(EMAIL);
  await page.locator('#signin-password, input[type=password]').first().fill(PASSWORD);
  await page
    .locator('form.ck-auth-form button[type="submit"], button[type="submit"]')
    .first()
    .click();
  try {
    await page.waitForURL(/\/hypervisor(\/|$)/, { timeout: 25_000 });
  } catch {
    await shot(page, '00-login-failed');
    throw new Error(`Login failed url=${page.url()}`);
  }
  await page.evaluate((slug) => {
    try {
      localStorage.setItem('agentium_workspace_slug', slug);
    } catch {}
  }, WORKSPACE);
}

async function installProbes(page) {
  await page.exposeFunction('__report_event', (e) => windowEvents.push(e));
  await page.exposeFunction('__report_chunk', (c) => sseChunks.push(c));
  await page.evaluate(() => {
    for (const n of [
      'agentium:assistant-navigate',
      'agentium:assistant-propose',
      'agentium:assistant-show-webcam',
      'agentium:assistant-draft-open',
      'agentium:map-command',
    ]) {
      window.addEventListener(n, (ev) => {
        try {
          window.__report_event({ event: n, detail: ev.detail });
        } catch {}
      });
    }
    const origFetch = window.fetch.bind(window);
    window.fetch = async (input, init) => {
      const url = typeof input === 'string' ? input : input.url;
      const isStream = url && url.includes('/chat/stream');
      const res = await origFetch(input, init);
      if (isStream && res.body) {
        const orig = res.clone();
        (async () => {
          const reader = orig.body.getReader();
          const dec = new TextDecoder();
          let buf = '';
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buf += dec.decode(value, { stream: true });
            const lines = buf.split('\n');
            buf = lines.pop() || '';
            for (const line of lines) {
              if (line.startsWith('data:')) {
                const data = line.slice(5).trim();
                if (!data) continue;
                try {
                  window.__report_chunk(JSON.parse(data));
                } catch {}
              }
            }
          }
        })();
      }
      return res;
    };
  });
}

async function openAyaPanel(page) {
  for (const sel of [
    'button.action-button:has-text("AYA")',
    '[aria-label="Ouvrir AYA"]',
    '.assistant-badge',
    'button:has-text("AYA")',
  ]) {
    try {
      const loc = page.locator(sel).first();
      if ((await loc.count()) === 0) continue;
      await loc.click({ timeout: 4000 });
      await page.waitForTimeout(1000);
      if (
        await page
          .locator('textarea[name="userInput"]')
          .first()
          .isVisible()
          .catch(() => false)
      )
        return true;
    } catch {}
  }
  await page.keyboard.press('Meta+j').catch(() => {});
  await page.waitForTimeout(800);
  if (
    await page
      .locator('textarea[name="userInput"]')
      .first()
      .isVisible()
      .catch(() => false)
  )
    return true;
  await page.keyboard.press('Control+j').catch(() => {});
  await page.waitForTimeout(800);
  return page
    .locator('textarea[name="userInput"]')
    .first()
    .isVisible()
    .catch(() => false);
}

async function sendAya(page, text, waitMs = AYA_WAIT_MS) {
  const ta = page.locator('textarea[name="userInput"]').first();
  await ta.waitFor({ state: 'visible', timeout: 10_000 });
  await ta.fill(text);
  await page.waitForTimeout(200);
  const beforeChunks = sseChunks.length;
  await ta.press('Enter');
  await page.waitForTimeout(waitMs);
  try {
    await page.waitForFunction(
      () => {
        const t = document.querySelector('textarea[name="userInput"]');
        return t && !t.disabled;
      },
      { timeout: waitMs },
    );
  } catch {}
  await page.waitForTimeout(1500);
  return { newChunks: sseChunks.slice(beforeChunks) };
}

async function drawerState(page) {
  return page.evaluate(() => {
    const drawer = document.querySelector(
      'app-assistant-draft-drawer, .draft-drawer, [data-testid="assistant-draft-drawer"]',
    );
    if (!drawer) return { open: false, title: '', body: '' };
    const title = drawer.querySelector('h2, h3, .drawer-title')?.textContent?.trim() || '';
    const body = drawer.querySelector('.draft-body, pre, .doc-preview')?.textContent?.trim() || '';
    const kind = drawer.querySelector('.eyebrow')?.textContent?.trim() || '';
    return { open: true, title: title.slice(0, 160), body: body.slice(0, 400), kind };
  });
}

async function goto(page, path) {
  const url = path.startsWith('http') ? path : `${HOST}${path}`;
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: NAV_TIMEOUT });
  try {
    await page.waitForLoadState('networkidle', { timeout: 10_000 });
  } catch {}
  await page.waitForTimeout(2000);
}

function hasAction(chunks, actionPattern) {
  return chunks.some((c) => {
    const text = JSON.stringify(c);
    return actionPattern.test(text);
  });
}

async function main() {
  await mkdir(OUT_DIR, { recursive: true });
  log(`QA S3 -> ${HOST}, OUT=${OUT_DIR}`);

  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({
    viewport: { width: 1920, height: 1080 },
    locale: 'fr-FR',
    timezoneId: 'Africa/Abidjan',
  });
  const page = await ctx.newPage();
  page.setDefaultTimeout(30_000);
  page.on('console', (m) => {
    if (m.type() === 'error') consoleErrors.push(m.text().slice(0, 200));
  });
  page.on('pageerror', (e) => consoleErrors.push(`pageerror: ${e.message}`));

  try {
    await login(page);
    await goto(page, '/hypervisor/mission-room/cockpit?workspace=sentinel-ci');
    await installProbes(page);

    // ── S3.1 — Posture sécuritaire ─────────────────────────────────────────
    const opened = await openAyaPanel(page);
    if (!opened) {
      record('S3.1 AYA panel ouverture', {
        status: 'FAIL',
        observation: 'Quick Panel AYA ne s\'ouvre pas (bouton + Cmd/Ctrl+K)',
        fix: 'Vérifier ouverture chat-overlay / icônes lucide',
        priority: 'P0',
        screenshot: (await shot(page, 'S3.1-aya-panel-fail')).file,
      });
    } else {
      const { newChunks } = await sendAya(page, 'AYA, montre-moi la posture sécuritaire du jour.');
      const s1 = await shot(page, 'S3.1-posture-securite');
      const navAction = hasAction(newChunks, /show_security_posture|security_posture|posture/i);
      const cockpitText = await page.evaluate(() =>
        /Posture s[eé]curitaire|Conseil D[eé]fense|dual.axis|Sahel/i.test(document.body.innerText),
      );
      record('S3.1 AYA posture sécuritaire dual-axis', {
        status: navAction && cockpitText ? 'PASS' : cockpitText ? 'PARTIAL' : 'FAIL',
        observation: `action=${navAction}, bloc Posture sécuritaire visible=${cockpitText}`,
        fix: !navAction
          ? 'Vérifier pack sentinel_ci_aya_security_v1 + aya.show_security_posture'
          : '—',
        priority: cockpitText ? 'P2' : 'P0',
        screenshot: s1.file,
      });
    }

    // ── S3.2 — Pulsation sociale Abidjan ───────────────────────────────────
    await openAyaPanel(page);
    const { newChunks: c2 } = await sendAya(page, 'AYA, montre la pulsation sociale à Abidjan.');
    await page.waitForTimeout(3000);
    const s2 = await shot(page, 'S3.2-pulsation-sociale');
    const d2 = await drawerState(page);
    const mapCmd2 = hasAction(c2, /social.geo|social_pulse|set_layers/i);
    const draftEvt2 = windowEvents.some(
      (e) =>
        e.event === 'agentium:assistant-draft-open' &&
        /social_pulse_snapshot|social.snapshot/i.test(JSON.stringify(e.detail || {})),
    );
    record('S3.2 AYA pulsation sociale + drawer tweets', {
      status: draftEvt2 && d2.open ? 'PASS' : mapCmd2 ? 'PARTIAL' : 'FAIL',
      observation: `map_command=${mapCmd2}, draft_open=${draftEvt2}, drawer="${d2.title}"`,
      fix: !draftEvt2
        ? 'Vérifier aya.show_social_pulse + emit assistant-draft-open(social_pulse_snapshot)'
        : '—',
      priority: draftEvt2 ? 'P2' : 'P0',
      screenshot: s2.file,
    });

    // ── S3.3 — Rumeur frontière Nord ───────────────────────────────────────
    await openAyaPanel(page);
    const { newChunks: c3 } = await sendAya(page, "AYA, d'où vient la rumeur frontière Nord ?");
    await page.waitForTimeout(3000);
    const s3file = await shot(page, 'S3.3-rumeur-frontiere');
    const d3 = await drawerState(page);
    const traceAction = hasAction(c3, /trace_rumor_origin|rumor_trace|border.tension|border_tension/i);
    const proposeEvt = windowEvents.some(
      (e) =>
        e.event === 'agentium:assistant-propose' &&
        /security_communique|propose-security/i.test(JSON.stringify(e.detail || {})),
    );
    const chainText = await page.evaluate(() =>
      /Telegram|d[eé]menti|Bouna|FANCI|11h42|13h45/i.test(document.body.innerText),
    );
    record('S3.3 AYA trace rumeur OSINT + proposition communiqué', {
      status: traceAction && chainText ? 'PASS' : chainText ? 'PARTIAL' : 'FAIL',
      observation: `action=${traceAction}, propose=${proposeEvt}, chaîne visible=${chainText}, drawer="${d3.title}"`,
      fix: !traceAction ? 'Vérifier aya.trace_rumor_origin + map_command border-tension' : '—',
      priority: chainText ? 'P2' : 'P0',
      screenshot: s3file.file,
    });

    // ── S3.4 — Mouvements de troupes Sahel ─────────────────────────────────
    await openAyaPanel(page);
    const { newChunks: c4 } = await sendAya(page, 'AYA, montre les mouvements de troupes au Sahel.');
    await page.waitForTimeout(3000);
    const s4 = await shot(page, 'S3.4-troupes-sahel');
    const d4 = await drawerState(page);
    const troopsAction = hasAction(c4, /show_troops_movement|troops_sahel|military.air|military_air/i);
    const adsbText = await page.evaluate(() =>
      /ADS.B|advisory|Bamako|Ouaga|Niamey|CEDEAO/i.test(document.body.innerText),
    );
    record('S3.4 AYA snapshot ADS-B advisory Sahel', {
      status: troopsAction && (d4.open || adsbText) ? 'PASS' : adsbText ? 'PARTIAL' : 'FAIL',
      observation: `action=${troopsAction}, drawer="${d4.title}", ADS-B visible=${adsbText}`,
      fix: !troopsAction
        ? 'Vérifier aya.show_troops_movement + map_command military-air + draft snapshot'
        : '—',
      priority: adsbText ? 'P2' : 'P0',
      screenshot: s4.file,
    });

    // ── S3.5 — Drill réputation 2+/1- ──────────────────────────────────────
    await openAyaPanel(page);
    const { newChunks: c5 } = await sendAya(
      page,
      'AYA, montre le drill de réputation 2 positifs et 1 critique.',
    );
    await page.waitForTimeout(3000);
    const s5 = await shot(page, 'S3.5-drill-reputation');
    const reputationUrl = page.url();
    const reputationAction = hasAction(c5, /show_reputation_drill|reputation|reputation_drill/i);
    const drillVisible = await page.evaluate(
      () =>
        /Jeune Afrique|Fraternit[eé] Matin|L'Inter|72\s*\/\s*100|Drill du sentiment|Positif|Critique/i.test(
          document.body.innerText,
        ),
    );
    record('S3.5 AYA drill réputation 2+/1-', {
      status: reputationAction && drillVisible ? 'PASS' : drillVisible ? 'PARTIAL' : 'FAIL',
      observation: `action=${reputationAction}, drill visible=${drillVisible}, url=${reputationUrl.split('?')[0]}`,
      fix: !reputationAction
        ? 'Vérifier aya.show_reputation_drill + reputation.items dans cockpit payload'
        : '—',
      priority: drillVisible ? 'P2' : 'P0',
      screenshot: s5.file,
    });

    // ── S3.6 — Brouillon communiqué sécurité ──────────────────────────────
    await openAyaPanel(page);
    const { newChunks: c6 } = await sendAya(
      page,
      'AYA, prépare un communiqué de sécurité sur la rumeur frontière Nord.',
    );
    await page.waitForTimeout(3500);
    const s6 = await shot(page, 'S3.6-communique-securite');
    const d6 = await drawerState(page);
    const draftAction = hasAction(
      c6,
      /draft_security_communique|security_communique|draft_response_email/i,
    );
    const draftEvt6 = windowEvents.some(
      (e) =>
        e.event === 'agentium:assistant-draft-open' &&
        /security_communique|communique/i.test(JSON.stringify(e.detail || {})),
    );
    record('S3.6 AYA brouillon communiqué sécurité', {
      status: draftAction && (d6.open || draftEvt6) ? 'PASS' : draftEvt6 ? 'PARTIAL' : 'FAIL',
      observation: `action=${draftAction}, draft_open=${draftEvt6}, drawer="${d6.title}"`,
      fix: !draftAction
        ? 'Vérifier aya.draft_security_communique + skill draft_response_email_v1 ou fallback'
        : '—',
      priority: draftEvt6 ? 'P2' : 'P0',
      screenshot: s6.file,
    });
  } finally {
    await ctx.close();
    await browser.close();
  }

  const summary = {
    host: HOST,
    workspace: WORKSPACE,
    runAt: new Date().toISOString(),
    durationSec: ((Date.now() - startedAt) / 1000).toFixed(1),
    results,
    consoleErrors: consoleErrors.slice(0, 30),
    windowEvents: windowEvents.slice(0, 50),
    sseActionEffects: sseChunks
      .filter((c) => c.chunk_type === 'action_effect')
      .slice(0, 30),
  };
  await writeFile(
    join(OUT_DIR, 'qa-s3-results.json'),
    JSON.stringify(summary, null, 2),
    'utf8',
  );
  log(`Done. ${results.length} steps. JSON -> ${join(OUT_DIR, 'qa-s3-results.json')}`);

  const pass = results.filter((r) => r.status === 'PASS').length;
  const partial = results.filter((r) => r.status === 'PARTIAL').length;
  const fail = results.filter((r) => r.status === 'FAIL').length;
  log(`PASS=${pass} PARTIAL=${partial} FAIL=${fail}`);
  process.exit(fail > 2 ? 1 : 0);
}

main().catch((e) => {
  console.error('[FATAL]', e.message, e.stack);
  process.exit(2);
});

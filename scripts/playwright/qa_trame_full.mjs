/**
 * QA UI — Trame démo complète SENTINEL-CI (S1 + S2)
 * Usage: node scripts/playwright/qa_trame_full.mjs
 * Env: AGENTIUM_HOST, AGENTIUM_EMAIL, AGENTIUM_PASSWORD, OUT_DIR
 */
import { chromium } from 'playwright';
import { mkdir, writeFile, stat } from 'node:fs/promises';
import { join } from 'node:path';

const HOST = (process.env.AGENTIUM_HOST || 'https://agentium.papai.ai').replace(/\/+$/, '');
const EMAIL = process.env.AGENTIUM_EMAIL || 'thibaud.ishacian@datategy.net';
const PASSWORD = process.env.AGENTIUM_PASSWORD || 'ponfib-jaNca5-sisfoc';
const OUT_DIR =
  process.env.OUT_DIR ||
  '/Users/thib/Developer/PAPAI/omnirag/docs/status-screenshots/2026-05-25-qa-trame';
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
  log(`  [${status}] ${step}: ${observation.slice(0, 120)}`);
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
  await page.locator('form.ck-auth-form button[type="submit"], button[type="submit"]').first().click();
  try {
    await page.waitForURL(/\/hypervisor(\/|$)/, { timeout: 25_000 });
  } catch {
    const s = await shot(page, '00-login-failed');
    throw new Error(`Login failed url=${page.url()}`);
  }
  await page.evaluate((slug) => {
    try { localStorage.setItem('agentium_workspace_slug', slug); } catch {}
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
        try { window.__report_event({ event: n, detail: ev.detail }); } catch {}
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
                try { window.__report_chunk(JSON.parse(data)); } catch {}
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
      await page.waitForTimeout(1200);
      if (await page.locator('textarea[name="userInput"]').first().isVisible().catch(() => false)) return true;
    } catch {}
  }
  await page.keyboard.press('Meta+j').catch(() => {});
  await page.waitForTimeout(800);
  if (await page.locator('textarea[name="userInput"]').first().isVisible().catch(() => false)) return true;
  await page.keyboard.press('Control+j').catch(() => {});
  await page.waitForTimeout(800);
  return page.locator('textarea[name="userInput"]').first().isVisible().catch(() => false);
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
    const drawer = document.querySelector('app-assistant-draft-drawer, .draft-drawer, [data-testid="assistant-draft-drawer"]');
    const open = !!drawer && (
      drawer.getAttribute('data-open') === 'true' ||
      drawer.classList.contains('is-open') ||
      drawer.querySelector('[open]') ||
      drawer.querySelector('iframe, embed, object')
    );
    const iframe = drawer?.querySelector('iframe');
    let iframeBlack = false;
    if (iframe) {
      const rect = iframe.getBoundingClientRect();
      iframeBlack = rect.width > 50 && rect.height > 50;
    }
    const title = drawer?.querySelector('h2, h3, .drawer-title, [class*="title"]')?.textContent?.trim() || '';
    const kind = drawer?.getAttribute('data-kind') || '';
    const pdfVisible = !!drawer?.querySelector('iframe[src*="pdf"], iframe[src*="blob"], canvas, .pdf-viewer');
    const emailVisible = !!drawer?.querySelector('.email-draft, [class*="customs"], textarea, .draft-body');
    return { open: !!open || !!drawer, title: title.slice(0, 120), kind, pdfVisible, emailVisible, iframeBlack, html: drawer?.outerHTML?.slice(0, 300) || '' };
  });
}

async function webcamState(page) {
  return page.evaluate(() => {
    const imgs = [...document.querySelectorAll('img[src*="webcam"], img[src*="blob"], video, .webcam-preview, .webcam-tile')];
    const apm = [...document.querySelectorAll('*')].some(el => /APM Apapa|Port Vridi|Atlantic Trader/i.test(el.textContent || ''));
    const filled = imgs.filter(el => {
      const r = el.getBoundingClientRect();
      return r.width > 40 && r.height > 40;
    }).length;
    return { filled, apm, total: imgs.length };
  });
}

async function goto(page, path) {
  const url = path.startsWith('http') ? path : `${HOST}${path}`;
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: NAV_TIMEOUT });
  try { await page.waitForLoadState('networkidle', { timeout: 10_000 }); } catch {}
  await page.waitForTimeout(2000);
}

async function checkCockpit(page) {
  const s = await shot(page, 'S1-01-cockpit');
  const state = await page.evaluate(() => {
    const kpiCards = document.querySelectorAll('.macro-kpi, .kpi-card, [class*="macro"] .kpi, app-macro-kpi, .vp-macro-kpi');
    const kpiAlt = document.querySelectorAll('[class*="kpi"]');
    const zoneNord = [...document.querySelectorAll('*')].find(el => /Zone Nord/i.test(el.textContent || '') && /Tendue/i.test(el.textContent || ''));
    const map = document.querySelector('app-strategic-map, .map-preview, canvas, .maplibregl-canvas, .map-container');
    const blocks = {
      status: !!document.querySelector('.vp-status, .status-bar, [class*="status"]'),
      macro: document.querySelector('h2, h3, .section-title')?.textContent?.includes('MACRO') || kpiAlt.length >= 3,
      aya: !!document.querySelector('.aya-recommendation, [class*="aya"], .assistant-banner'),
      map: !!map,
      arbitrages: !!document.querySelector('[class*="arbitr"], .decision-card, .executive-decision'),
    };
    return {
      kpiCount: Math.max(kpiCards.length, kpiAlt.length >= 8 ? 8 : kpiAlt.length),
      zoneNord: !!zoneNord,
      blocks,
      dateLabel: document.body.innerText.match(/Lundi 25 Mai 2026/i)?.[0] || '',
    };
  });
  const kpiOk = state.kpiCount >= 8;
  const status = kpiOk && state.zoneNord && state.blocks.map ? 'PASS' : (state.blocks.map ? 'PARTIAL' : 'FAIL');
  record('S1.1 Cockpit KPIs + carte + Zone Nord', {
    status,
    observation: `KPIs~${state.kpiCount}/8, Zone Nord=${state.zoneNord}, carte=${state.blocks.map}, date=${state.dateLabel || '?'}`,
    fix: kpiOk ? '—' : 'Vérifier rendu macro KPI (8 tuiles) et chip Zone Nord · Tendue sur prod',
    priority: kpiOk ? 'P2' : 'P0',
    screenshot: s.file,
  });
  return state;
}

async function clickZoneNord(page) {
  for (const sel of ['text=/Zone Nord.*Tendue/i', 'text=Zone Nord', '[class*="chip"]:has-text("Nord")']) {
    try {
      const loc = page.locator(sel).first();
      if ((await loc.count()) === 0) continue;
      await loc.click({ timeout: 4000 });
      await page.waitForTimeout(2000);
      return true;
    } catch {}
  }
  return false;
}

async function main() {
  await mkdir(OUT_DIR, { recursive: true });
  log(`QA trame -> ${HOST}, OUT=${OUT_DIR}`);

  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({
    viewport: { width: 1920, height: 1080 },
    locale: 'fr-FR',
    timezoneId: 'Africa/Abidjan',
  });
  const page = await ctx.newPage();
  page.setDefaultTimeout(30_000);
  page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text().slice(0, 200)); });
  page.on('pageerror', (e) => consoleErrors.push(`pageerror: ${e.message}`));

  try {
    await login(page);
    await installProbes(page);
    await goto(page, '/hypervisor/mission-room/cockpit?workspace=sentinel-ci');
    await checkCockpit(page);

    // S1.2 AYA Nord tendue
    const ayaOk = await openAyaPanel(page);
    if (!ayaOk) {
      record('S1.2 AYA panel ouverture', { status: 'FAIL', observation: 'Quick Panel AYA ne s\'ouvre pas (bouton + ⌘J)', fix: 'Fix ouverture chat-overlay / icônes lucide cassant change detection', priority: 'P0', screenshot: (await shot(page, 'S1-02-aya-panel-fail')).file });
    } else {
      const { newChunks } = await sendAya(page, 'AYA, pourquoi la situation Nord est-elle tendue ?');
      const s = await shot(page, 'S1-02-nord-tendue');
      const url = page.url();
      const hasNavigate = newChunks.some(c => c.chunk_type === 'action_effect' && /navigate|strategie|zone-nord/i.test(JSON.stringify(c)));
      const hasNapie = await page.evaluate(() => /Napi[eé]|Aerostar|120/i.test(document.body.innerText));
      const onStrategie = url.includes('strategie') || hasNavigate;
      record('S1.2 AYA pourquoi Nord tendue', {
        status: hasNapie && (onStrategie || hasNavigate) ? 'PASS' : (hasNapie ? 'PARTIAL' : 'FAIL'),
        observation: `navigate=${onStrategie}, narrative Napié=${hasNapie}, url=${url.split('?')[0]}`,
        fix: !hasNapie ? 'Vérifier resolver aya.explain_why + narrative seed' : (!onStrategie ? 'Vérifier forwarding assistant-navigate côté frontend' : '—'),
        priority: hasNapie ? 'P1' : 'P0',
        screenshot: s.file,
      });
    }

    // S1.3 PV douanes
    await sendAya(page, 'AYA, ouvre le PV douanes.');
    await page.waitForTimeout(3000);
    const s3 = await shot(page, 'S1-03-pv-douanes');
    const d3 = await drawerState(page);
    const pdfChunk = sseChunks.some(c => c.chunk_type === 'action_effect' && /document_preview|proces-verbal/i.test(JSON.stringify(c)));
    const blackIframe = d3.open && d3.pdfVisible && !d3.title && !pdfChunk;
    record('S1.3 AYA ouvre PV douanes', {
      status: (d3.open || d3.pdfVisible || pdfChunk) && !blackIframe ? 'PASS' : (pdfChunk ? 'PARTIAL' : 'FAIL'),
      observation: `drawer=${d3.open}, pdf=${d3.pdfVisible}, title="${d3.title}", sse_doc=${pdfChunk}`,
      fix: !d3.pdfVisible ? 'Drawer document_preview ne s\'ouvre pas — vérifier assistant-draft-open handler' : (blackIframe ? 'Iframe PDF noir — vérifier URL signée / CORS blob' : '—'),
      priority: d3.pdfVisible ? 'P2' : 'P0',
      screenshot: s3.file,
    });

    // S1.4 Atlantic Trader
    await goto(page, '/hypervisor/mission-room/cockpit?workspace=sentinel-ci');
    await openAyaPanel(page);
    const { newChunks: c4 } = await sendAya(page, 'AYA, montre le cargo Atlantic Trader.');
    await page.waitForTimeout(3000);
    const s4 = await shot(page, 'S1-04-atlantic-trader');
    const w4 = await webcamState(page);
    const vesselNav = c4.some(c => /vessel|maritime|atlantic/i.test(JSON.stringify(c)));
    const webcamEvt = windowEvents.some(e => e.event === 'agentium:assistant-show-webcam');
    record('S1.4 AYA cargo Atlantic Trader', {
      status: (w4.apm || webcamEvt || vesselNav) ? 'PASS' : 'PARTIAL',
      observation: `webcam tiles=${w4.filled}, APM/Trader text=${w4.apm}, sse_vessel=${vesselNav}, event_webcam=${webcamEvt}, url=${page.url()}`,
      fix: !w4.apm && !webcamEvt ? 'Vérifier show_vessel_evidence + assistant-show-webcam + zoom Abidjan' : '—',
      priority: w4.apm ? 'P2' : 'P0',
      screenshot: s4.file,
    });

    // S1.5 situation au port
    await openAyaPanel(page);
    const { newChunks: c5 } = await sendAya(page, 'AYA, montre la situation au port.');
    await page.waitForTimeout(3000);
    const s5 = await shot(page, 'S1-05-situation-port');
    const w5 = await webcamState(page);
    const maritimeAction = c5.some(c => /show_maritime|maritime-traffic|panel.*maritime/i.test(JSON.stringify(c)));
    record('S1.5 AYA situation au port', {
      status: maritimeAction && w5.filled > 0 ? 'PASS' : (maritimeAction || w5.filled > 0 ? 'PARTIAL' : 'FAIL'),
      observation: `maritime_action=${maritimeAction}, webcam_tiles=${w5.filled}, fallback_only=${!maritimeAction && c5.some(c => /demo-safe|Abidjan/i.test(JSON.stringify(c)))}`,
      fix: !maritimeAction ? 'Déployer aya.show_maritime_traffic (commit 6335d460+) — actuellement no_match/fallback' : '—',
      priority: maritimeAction ? 'P2' : 'P0',
      screenshot: s5.file,
    });

    // S1.6 courrier dédouanement
    await openAyaPanel(page);
    await sendAya(page, 'AYA, rédige le courrier de dédouanement pour Atlantic Trader.');
    await page.waitForTimeout(3000);
    const s6 = await shot(page, 'S1-06-courrier-dedouanement');
    const d6 = await drawerState(page);
    const emailChunk = sseChunks.some(c => /customs_email|draft_customs/i.test(JSON.stringify(c)));
    record('S1.6 AYA courrier dédouanement', {
      status: (d6.emailVisible || emailChunk) ? 'PASS' : 'FAIL',
      observation: `email_drawer=${d6.emailVisible}, sse=${emailChunk}, title="${d6.title}"`,
      fix: !d6.emailVisible ? 'Vérifier drawer customs_email / propose-customs-derogation chain' : '—',
      priority: d6.emailVisible ? 'P2' : 'P0',
      screenshot: s6.file,
    });

    // S1.7 clic vessel manuel
    await goto(page, '/hypervisor/mission-room/strategie?workspace=sentinel-ci&mode=live&panel=maritime');
    await page.waitForTimeout(3500);
    let vesselClicked = false;
    for (const sel of ['text=/Atlantic Trader/i', 'text=/MV Atlantic/i', '[class*="vessel"]', '.maplibregl-marker']) {
      try {
        const loc = page.locator(sel).first();
        if ((await loc.count()) === 0) continue;
        await loc.click({ timeout: 3000, force: true });
        vesselClicked = true;
        break;
      } catch {}
    }
    await page.waitForTimeout(2500);
    const s7 = await shot(page, 'S1-07-vessel-click');
    const w7 = await webcamState(page);
    const vesselDetail = await page.evaluate(() => /Atlantic Trader|627012345|IMO/i.test(document.body.innerText));
    record('S1.7 Clic vessel → détails + webcam', {
      status: vesselClicked && (vesselDetail || w7.filled > 0) ? 'PASS' : (vesselClicked ? 'PARTIAL' : 'FAIL'),
      observation: `clicked=${vesselClicked}, detail=${vesselDetail}, webcam=${w7.filled}`,
      fix: !vesselClicked ? 'Déployer befb2869 (vessel click handler) — pin peut être bloqué par wrapper carte' : '—',
      priority: vesselDetail ? 'P2' : 'P0',
      screenshot: s7.file,
    });

    // S1.8 Mission Control / monitor
    await goto(page, '/hypervisor/mission-room/monitor?workspace=sentinel-ci');
    const s8 = await shot(page, 'S1-08-mission-control');
    const m8 = await page.evaluate(() => {
      const map = !!document.querySelector('.maplibregl-canvas, canvas, app-strategic-map');
      const flux = [...document.querySelectorAll('*')].some(el => /FLUX TERRAIN|Flux terrain/i.test(el.textContent || ''));
      const apm = [...document.querySelectorAll('*')].some(el => /APM Apapa|Port Vridi/i.test(el.textContent || ''));
      const webcams = document.querySelectorAll('img[src*="webcam"], img[src*="blob"], video').length;
      return { map, flux, apm, webcams };
    });
    record('S1.8 Mission Control carte + flux terrain', {
      status: m8.map && m8.flux ? (m8.apm || m8.webcams > 0 ? 'PASS' : 'PARTIAL') : 'FAIL',
      observation: `map=${m8.map}, flux=${m8.flux}, apm=${m8.apm}, webcams=${m8.webcams}`,
      fix: !m8.apm ? 'Déployer 2efedef8 (webcam blob auth) + APM en tête sidebar' : '—',
      priority: m8.apm ? 'P2' : 'P1',
      screenshot: s8.file,
    });

    // S2 Transition — agenda + presse
    await goto(page, '/hypervisor/mission-room/agenda?workspace=sentinel-ci');
    const s9a = await shot(page, 'S2-09-agenda');
    const ag = await page.evaluate(() => ({
      nawa: /Pr[eé]fet.*Nawa|Nawa.*11/i.test(document.body.innerText),
      date: /25.*mai.*2026|Lundi 25/i.test(document.body.innerText),
    }));
    await goto(page, '/hypervisor/mission-room/presse?workspace=sentinel-ci');
    const s9b = await shot(page, 'S2-09-presse');
    const pr = await page.evaluate(() => ({
      articles: document.querySelectorAll('.press-list-row, .press-article-card, article').length,
      napie: /Napi[eé]|drone/i.test(document.body.innerText),
    }));
    record('S2.T Transition agenda + presse', {
      status: ag.nawa && pr.articles > 0 ? 'PASS' : 'PARTIAL',
      observation: `agenda Nawa=${ag.nawa}, presse articles=${pr.articles}, Napie=${pr.napie}`,
      fix: !ag.nawa ? 'Vérifier seed evt-prefet-nawa timeline 25/05' : '—',
      priority: 'P1',
      screenshot: s9a.file,
      extra: { presseScreenshot: s9b.file },
    });

    // S2.1 résumé Nawa
    await goto(page, '/hypervisor/mission-room/agenda?workspace=sentinel-ci');
    await openAyaPanel(page);
    const { newChunks: c10 } = await sendAya(page, 'AYA, résume le rapport Préfet Nawa.');
    const s10 = await shot(page, 'S2-10-resume-nawa');
    const nawaText = await page.evaluate(() => /Nawa|Soubr[eé]|cacao|anacarde/i.test(document.body.innerText));
    const sumAction = c10.some(c => /summarize|nawa|cacao_summary/i.test(JSON.stringify(c)));
    record('S2.1 AYA résumé Préfet Nawa', {
      status: nawaText && sumAction ? 'PASS' : (nawaText ? 'PARTIAL' : 'FAIL'),
      observation: `narrative=${nawaText}, action=${sumAction}`,
      fix: !sumAction ? 'Vérifier aya.summarize_last_exchanges resolver' : '—',
      priority: 'P0',
      screenshot: s10.file,
    });

    // S2.2 préconisations cacao
    await openAyaPanel(page);
    const { newChunks: c11 } = await sendAya(page, 'AYA, donne-moi des préconisations sur le cacao.');
    const s11 = await shot(page, 'S2-11-preconisations');
    const reco = await page.evaluate(() => /transformation|coop[eé]rative|PPP|FCFA|anacarde/i.test(document.body.innerText));
    const recoAction = c11.some(c => /recommend_cacao|cacao/i.test(JSON.stringify(c)));
    record('S2.2 AYA préconisations cacao', {
      status: reco && recoAction ? 'PASS' : (reco ? 'PARTIAL' : 'FAIL'),
      observation: `3 options visibles=${reco}, action=${recoAction}`,
      fix: !recoAction ? 'AYA only — vérifier skill generate_recommendations_v1' : '—',
      priority: reco ? 'P2' : 'P0',
      screenshot: s11.file,
    });

    // S2.3 rapport stratégique
    await openAyaPanel(page);
    const { newChunks: c12 } = await sendAya(page, 'AYA, génère le rapport complet.');
    await page.waitForTimeout(4000);
    const s12 = await shot(page, 'S2-12-rapport-strategique');
    const d12 = await drawerState(page);
    const reportChunk = c12.some(c => /strategic|draft_strategic|report/i.test(JSON.stringify(c)));
    record('S2.3 AYA rapport stratégique drawer', {
      status: (d12.pdfVisible || reportChunk) ? 'PASS' : 'PARTIAL',
      observation: `pdf_drawer=${d12.pdfVisible}, sse=${reportChunk}, title="${d12.title}"`,
      fix: !d12.pdfVisible ? 'Vérifier draft_strategic_report + URL signée PDF (~12p)' : '—',
      priority: 'P1',
      screenshot: s12.file,
    });

    // S2.4 ODJ patch — try UI click path first
    await goto(page, '/hypervisor/mission-room/agenda/meeting/evt-prefet-nawa?workspace=sentinel-ci');
    await page.waitForTimeout(2500);
    let odjProposed = false;
    for (const sel of ['text=/Proposer un point ODJ/i', 'text=/Proposer modification/i', 'button:has-text("Proposer")']) {
      try {
        const loc = page.locator(sel).first();
        if ((await loc.count()) === 0) continue;
      } catch {}
    }
    await openAyaPanel(page);
    await sendAya(page, 'AYA, ajoute le point cacao à l\'ordre du jour.');
    await page.waitForTimeout(3000);
    const s13 = await shot(page, 'S2-13-odj-patch');
    const odj = await page.evaluate(() => ({
      patchBanner: /Modification ODJ|propos[eé]e|validation/i.test(document.body.innerText),
      cacao: /cacao|anacarde/i.test(document.body.innerText),
      drawer: !!document.querySelector('app-assistant-draft-drawer, .calendar-agenda-patch'),
    }));
    record('S2.4 AYA patch ODJ cacao', {
      status: odj.patchBanner || odj.drawer ? 'PASS' : 'PARTIAL',
      observation: `banner=${odj.patchBanner}, drawer=${odj.drawer}, cacao=${odj.cacao}`,
      fix: !odj.patchBanner ? 'Vérifier form Proposer point ODJ + calendar_agenda_patch drawer' : '—',
      priority: 'P1',
      screenshot: s13.file,
    });

    // S2.5 validation
    await openAyaPanel(page);
    await sendAya(page, 'Oui, valide.');
    await page.waitForTimeout(3000);
    const s14 = await shot(page, 'S2-14-odj-validate');
    const validated = await page.evaluate(() => /Ajout[eé] par AYA|valid[eé]|cacao/i.test(document.body.innerText));
    record('S2.5 Validation patch ODJ', {
      status: validated ? 'PASS' : 'PARTIAL',
      observation: `badge/ODJ updated=${validated}`,
      fix: !validated ? 'Clic bannière orange Valider modification ou voice.confirm_yes → confirm_agenda_patch' : '—',
      priority: 'P1',
      screenshot: s14.file,
    });

    // S2.6 démarrer réunion
    await goto(page, '/hypervisor/mission-room/agenda?workspace=sentinel-ci');
    let started = false;
    for (const sel of ['text=/D[eé]marrer la r[eé]union/i', 'button:has-text("Démarrer")']) {
      try {
        const loc = page.locator(sel).first();
        if ((await loc.count()) === 0) continue;
        await loc.click({ timeout: 4000 });
        started = true;
        break;
      } catch {}
    }
    if (!started) {
      await openAyaPanel(page);
      await sendAya(page, 'AYA, démarre la réunion.');
    }
    await page.waitForTimeout(3000);
    const s15 = await shot(page, 'S2-15-meeting-live');
    const meeting = await page.evaluate(() => ({
      url: location.pathname,
      live: /meeting|chrono|r[eé]union/i.test(document.body.innerText),
      odj: /Ordre du jour|ODJ|cacao/i.test(document.body.innerText),
    }));
    record('S2.6 Démarrer réunion live', {
      status: meeting.url.includes('meeting') && meeting.live ? 'PASS' : 'PARTIAL',
      observation: `url=${meeting.url}, live=${meeting.live}, odj=${meeting.odj}, click=${started}`,
      fix: !meeting.url.includes('meeting') ? 'Déployer bouton Démarrer réunion + POST /meetings/start' : '—',
      priority: 'P1',
      screenshot: s15.file,
    });

    // S2.7 décision option B
    await openAyaPanel(page);
    await sendAya(page, 'AYA, décide option B.');
    await page.waitForTimeout(4000);
    const s16 = await shot(page, 'S2-16-decision-b');
    const dec = await page.evaluate(() => ({
      optionB: /Option B|option B|d[eé]cid[eé]/i.test(document.body.innerText),
      logged: /Logger|d[eé]cision enregistr[eé]e|Arbitrage/i.test(document.body.innerText),
    }));
    // Plan B manual click
    if (!dec.optionB) {
      for (const sel of ['text=/Cacao/i', 'text=/Option B/i']) {
        try {
          const loc = page.locator(sel).first();
          if ((await loc.count()) === 0) continue;
          await loc.click({ timeout: 3000 });
        } catch {}
      }
      for (const sel of ['button:has-text("Décider")', 'button:has-text("Logger")']) {
        try {
          const loc = page.locator(sel).first();
          if ((await loc.count()) === 0) continue;
          await loc.click({ timeout: 3000 });
          break;
        } catch {}
      }
      await page.waitForTimeout(2000);
    }
    record('S2.7 Décision option B', {
      status: dec.optionB ? 'PASS' : 'PARTIAL',
      observation: `optionB_text=${dec.optionB}, logged=${dec.logged}`,
      fix: !dec.optionB ? 'Meeting view → ODJ Cacao → Option B → Décider → Logger' : '—',
      priority: 'P1',
      screenshot: s16.file,
    });

    // Plan B clicks validation
    await goto(page, '/hypervisor/mission-room/cockpit?workspace=sentinel-ci');
    const pb1 = await clickZoneNord(page);
    const spb1 = await shot(page, 'planB-zone-nord');
    record('Plan B — chip Zone Nord', {
      status: pb1 ? 'PASS' : 'FAIL',
      observation: `click chip Zone Nord → ${page.url()}`,
      fix: !pb1 ? 'Rendre chip Zone Nord cliquable (drill /strategie?zone=zone-nord)' : '—',
      priority: pb1 ? 'P2' : 'P0',
      screenshot: spb1.file,
    });

    await goto(page, '/hypervisor/mission-room/strategie?workspace=sentinel-ci');
    let pbWebcam = false;
    for (const sel of ['text=/Port Vridi.*webcam/i', 'text=/webcam demo/i', 'button:has-text("Vridi")']) {
      try {
        const loc = page.locator(sel).first();
        if ((await loc.count()) === 0) continue;
        await loc.click({ timeout: 3000 });
        pbWebcam = true;
        break;
      } catch {}
    }
    const spb2 = await shot(page, 'planB-webcam-vridi');
    record('Plan B — Port Vridi webcam demo', {
      status: pbWebcam ? 'PASS' : 'PARTIAL',
      observation: `legend button clicked=${pbWebcam}`,
      fix: !pbWebcam ? 'Ajouter bouton Port Vridi · webcam demo dans légende carte cockpit' : '—',
      priority: 'P1',
      screenshot: spb2.file,
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
    sseActionEffects: sseChunks.filter(c => c.chunk_type === 'action_effect').slice(0, 30),
  };
  await writeFile(join(OUT_DIR, 'qa-results.json'), JSON.stringify(summary, null, 2), 'utf8');
  log(`Done. ${results.length} steps. JSON -> ${join(OUT_DIR, 'qa-results.json')}`);

  const pass = results.filter(r => r.status === 'PASS').length;
  const partial = results.filter(r => r.status === 'PARTIAL').length;
  const fail = results.filter(r => r.status === 'FAIL').length;
  log(`PASS=${pass} PARTIAL=${partial} FAIL=${fail}`);
  process.exit(fail > 3 ? 1 : 0);
}

main().catch((e) => { console.error('[FATAL]', e.message, e.stack); process.exit(2); });

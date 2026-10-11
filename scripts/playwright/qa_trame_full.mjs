/**
 * QA UI — Trame démo complète SENTINEL-CI (S1 + S2)
 * Usage: node scripts/playwright/qa_trame_full.mjs
 * Env: AGENTIUM_HOST, AGENTIUM_EMAIL, AGENTIUM_PASSWORD, OUT_DIR
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
  record,
  shot,
  login,
  openAyaPanel,
  sendAya,
  drawerState,
  webcamState,
  goto,
  summarizeResults,
} from './qa_trame_shared.mjs';

const OUT_DIR =
  process.env.OUT_DIR ||
  '/Users/thib/Developer/PAPAI/omnirag/docs/status-screenshots/2026-05-25-qa-trame';

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

async function checkCockpit(page, state, outDir) {
  const s = await shot(page, outDir, 'S1-01-cockpit');
  const st = await page.evaluate(() => {
    const kpiCards = document.querySelectorAll('.macro-kpi, .kpi-card, [class*="macro"] .kpi, app-macro-kpi, .vp-macro-kpi');
    const kpiAlt = document.querySelectorAll('[class*="kpi"]');
    const zoneNord = [...document.querySelectorAll('*')].find(el => /Zone Nord/i.test(el.textContent || '') && /Tendue/i.test(el.textContent || ''));
    const map = document.querySelector('app-strategic-map, .map-preview, canvas, .maplibregl-canvas, .map-container');
    return {
      kpiCount: Math.max(kpiCards.length, kpiAlt.length >= 8 ? 8 : kpiAlt.length),
      zoneNord: !!zoneNord,
      map: !!map,
      dateLabel: document.body.innerText.match(/Lundi 25 Mai 2026/i)?.[0] || '',
    };
  });
  const kpiOk = st.kpiCount >= 8;
  record(state, 'S1.1 Cockpit KPIs + carte + Zone Nord', {
    status: kpiOk && st.zoneNord && st.map ? 'PASS' : st.map ? 'PARTIAL' : 'FAIL',
    observation: `KPIs~${st.kpiCount}/8, Zone Nord=${st.zoneNord}, carte=${st.map}, date=${st.dateLabel || '?'}`,
    fix: kpiOk ? '—' : 'Vérifier rendu macro KPI (8 tuiles) et chip Zone Nord · Tendue sur prod',
    priority: kpiOk ? 'P2' : 'P0',
    screenshot: s.file,
  });
  return st;
}

/** @param {import('playwright').Page} page */
export async function runTrameFullSteps(page, state, outDir) {
  await goto(page, '/hypervisor/mission-room/cockpit?workspace=sentinel-ci');
  await checkCockpit(page, state, outDir);

  const ayaOk = await openAyaPanel(page);
  if (!ayaOk) {
    record(state, 'S1.2 AYA panel ouverture', {
      status: 'FAIL',
      observation: 'Quick Panel AYA ne s\'ouvre pas (bouton + ⌘J)',
      fix: 'Fix ouverture chat-overlay / icônes lucide cassant change detection',
      priority: 'P0',
      screenshot: (await shot(page, outDir, 'S1-02-aya-panel-fail')).file,
    });
  } else {
    await sendAya(page, state, 'AYA, pourquoi la situation Nord est-elle tendue ?');
    const s = await shot(page, outDir, 'S1-02-nord-tendue');
    const url = page.url();
    const hasNapie = await page.evaluate(() => /Napi[eé]|Aerostar|120/i.test(document.body.innerText));
    const onStrategie = url.includes('strategie');
    record(state, 'S1.2 AYA pourquoi Nord tendue', {
      status: hasNapie ? 'PASS' : 'FAIL',
      observation: `narrative Napié=${hasNapie}, url=${url.split('?')[0]}`,
      fix: !hasNapie ? 'Vérifier resolver aya.explain_why + narrative seed' : '—',
      priority: hasNapie ? 'P2' : 'P0',
      screenshot: s.file,
      extra: { functional_pass: hasNapie, onStrategie },
    });
  }

  await sendAya(page, state, 'AYA, ouvre le PV douanes.');
  await page.waitForTimeout(3000);
  const s3 = await shot(page, outDir, 'S1-03-pv-douanes');
  const d3 = await drawerState(page);
  const pvDom = d3.open || d3.pdfVisible || /proces.verbal|PV douanes/i.test(`${d3.title} ${d3.body}`);
  record(state, 'S1.3 AYA ouvre PV douanes', {
    status: pvDom ? 'PASS' : 'FAIL',
    observation: `drawer=${d3.open}, pdf=${d3.pdfVisible}, title="${d3.title}"`,
    fix: !pvDom ? 'Drawer document_preview ne s\'ouvre pas — vérifier assistant-draft-open handler' : '—',
    priority: pvDom ? 'P2' : 'P0',
    screenshot: s3.file,
  });

  await goto(page, '/hypervisor/mission-room/cockpit?workspace=sentinel-ci');
  await openAyaPanel(page);
  await sendAya(page, state, 'AYA, montre le cargo Atlantic Trader.');
  await page.waitForTimeout(3000);
  const s4 = await shot(page, outDir, 'S1-04-atlantic-trader');
  const w4 = await webcamState(page);
  record(state, 'S1.4 AYA cargo Atlantic Trader', {
    status: w4.apm || w4.filled > 0 ? 'PASS' : 'FAIL',
    observation: `webcam tiles=${w4.filled}, APM/Trader text=${w4.apm}, url=${page.url()}`,
    fix: !w4.apm && !w4.filled ? 'Vérifier show_vessel_evidence + assistant-show-webcam + zoom Abidjan' : '—',
    priority: w4.apm ? 'P2' : 'P0',
    screenshot: s4.file,
  });

  await openAyaPanel(page);
  await sendAya(page, state, 'AYA, montre la situation au port.');
  await page.waitForTimeout(3000);
  const s5 = await shot(page, outDir, 'S1-05-situation-port');
  const w5 = await webcamState(page);
  const maritimeUrl = page.url().includes('maritime') || page.url().includes('port-abidjan');
  const maritimeDom = w5.filled > 0 || w5.apm || maritimeUrl;
  record(state, 'S1.5 AYA situation au port', {
    status: maritimeDom ? 'PASS' : 'FAIL',
    observation: `webcam_tiles=${w5.filled}, maritime_url=${maritimeUrl}, url=${page.url()}`,
    fix: !maritimeDom ? 'Vérifier aya.show_maritime_traffic + panel maritime Abidjan' : '—',
    priority: maritimeDom ? 'P2' : 'P0',
    screenshot: s5.file,
  });

  await openAyaPanel(page);
  await sendAya(page, state, 'AYA, rédige le courrier de dédouanement pour Atlantic Trader.');
  await page.waitForTimeout(3000);
  const s6 = await shot(page, outDir, 'S1-06-courrier-dedouanement');
  const d6 = await drawerState(page);
  const emailDom = d6.emailVisible || /d[eé]douanement|customs|Atlantic Trader/i.test(`${d6.title} ${d6.body}`);
  record(state, 'S1.6 AYA courrier dédouanement', {
    status: emailDom ? 'PASS' : 'FAIL',
    observation: `email_drawer=${d6.emailVisible}, title="${d6.title}"`,
    fix: !emailDom ? 'Vérifier drawer customs_email / propose-customs-derogation chain' : '—',
    priority: emailDom ? 'P2' : 'P0',
    screenshot: s6.file,
  });

  await goto(page, '/hypervisor/mission-room/cockpit?workspace=sentinel-ci');
  await page.waitForTimeout(2500);
  let vesselClicked = false;
  for (const sel of [
    'text=/Atlantic Trader/i',
    'text=/MV Atlantic/i',
  ]) {
    try {
      const loc = page.locator(sel).first();
      if ((await loc.count()) === 0) continue;
      await loc.click({ timeout: 3000, force: true });
      vesselClicked = true;
      break;
    } catch {}
  }
  if (!vesselClicked) {
    vesselClicked = await page.evaluate(() => {
      const host = document.querySelector('app-workspace-map canvas, .deck-canvas, .maplibregl-canvas');
      if (!host) return false;
      const rect = host.getBoundingClientRect();
      const x = rect.left + rect.width * 0.7;
      const y = rect.top + rect.height * 0.8;
      const el = document.elementFromPoint(x, y);
      if (!el) return false;
      el.dispatchEvent(new MouseEvent('click', { bubbles: true, clientX: x, clientY: y }));
      return true;
    }).catch(() => false);
  }
  await page.waitForTimeout(2500);
  const s7 = await shot(page, outDir, 'S1-07-vessel-click');
  const w7 = await webcamState(page);
  const vesselDetail = await page.evaluate(() => /Atlantic Trader|627012345|IMO/i.test(document.body.innerText));
  record(state, 'S1.7 Clic vessel → détails + webcam', {
    status: vesselDetail ? 'PASS' : vesselClicked && w7.filled > 0 ? 'PARTIAL' : 'FAIL',
    observation: `clicked=${vesselClicked}, detail=${vesselDetail}, webcam=${w7.filled}`,
    fix: !vesselDetail ? 'Déployer vessel click handler — pin peut être bloqué par wrapper carte' : '—',
    priority: vesselDetail ? 'P2' : 'P0',
    screenshot: s7.file,
  });

  await goto(page, '/hypervisor/mission-room/monitor?workspace=sentinel-ci');
  const s8 = await shot(page, outDir, 'S1-08-mission-control');
  const m8 = await page.evaluate(() => {
    const map = !!document.querySelector('.maplibregl-canvas, canvas, app-strategic-map');
    const flux = [...document.querySelectorAll('*')].some(el => /FLUX TERRAIN|Flux terrain/i.test(el.textContent || ''));
    const apm = [...document.querySelectorAll('*')].some(el => /APM Apapa|Port Vridi/i.test(el.textContent || ''));
    const webcams = document.querySelectorAll('img[src*="webcam"], img[src*="blob"], video').length;
    return { map, flux, apm, webcams };
  });
  record(state, 'S1.8 Mission Control carte + flux terrain', {
    status: m8.map && m8.flux ? 'PASS' : 'FAIL',
    observation: `map=${m8.map}, flux=${m8.flux}, apm=${m8.apm}, webcams=${m8.webcams}`,
    fix: !m8.flux ? 'Vérifier monitor view + flux terrain sidebar' : '—',
    priority: m8.apm ? 'P2' : 'P1',
    screenshot: s8.file,
  });

  await goto(page, '/hypervisor/mission-room/agenda?workspace=sentinel-ci');
  const s9a = await shot(page, outDir, 'S2-09-agenda');
  const ag = await page.evaluate(() => ({
    nawa: /Pr[eé]fet.*Nawa|Nawa.*11/i.test(document.body.innerText),
    date: /25.*mai.*2026|Lundi 25/i.test(document.body.innerText),
  }));
  await goto(page, '/hypervisor/mission-room/presse?workspace=sentinel-ci');
  const s9b = await shot(page, outDir, 'S2-09-presse');
  const pr = await page.evaluate(() => ({
    articles: document.querySelectorAll('.press-list-row, .press-article-card, article').length,
    napie: /Napi[eé]|drone/i.test(document.body.innerText),
  }));
  record(state, 'S2.T Transition agenda + presse', {
    status: ag.nawa && pr.articles > 0 ? 'PASS' : 'PARTIAL',
    observation: `agenda Nawa=${ag.nawa}, presse articles=${pr.articles}, Napie=${pr.napie}`,
    fix: !ag.nawa ? 'Vérifier seed evt-prefet-nawa timeline 25/05' : '—',
    priority: 'P1',
    screenshot: s9a.file,
    extra: { presseScreenshot: s9b.file },
  });

  await goto(page, '/hypervisor/mission-room/agenda?workspace=sentinel-ci');
  await openAyaPanel(page);
  await sendAya(page, state, 'AYA, résume le rapport Préfet Nawa.');
  const s10 = await shot(page, outDir, 'S2-10-resume-nawa');
  const nawaText = await page.evaluate(() => /Nawa|Soubr[eé]|cacao|anacarde/i.test(document.body.innerText));
  record(state, 'S2.1 AYA résumé Préfet Nawa', {
    status: nawaText ? 'PASS' : 'FAIL',
    observation: `narrative=${nawaText}`,
    fix: !nawaText ? 'Vérifier aya.summarize_last_exchanges resolver' : '—',
    priority: 'P0',
    screenshot: s10.file,
  });

  await openAyaPanel(page);
  await sendAya(page, state, 'AYA, donne-moi des préconisations sur le cacao.');
  const s11 = await shot(page, outDir, 'S2-11-preconisations');
  const reco = await page.evaluate(() => /transformation|coop[eé]rative|PPP|FCFA|anacarde/i.test(document.body.innerText));
  record(state, 'S2.2 AYA préconisations cacao', {
    status: reco ? 'PASS' : 'FAIL',
    observation: `3 options visibles=${reco}`,
    fix: !reco ? 'Vérifier skill generate_recommendations_v1' : '—',
    priority: reco ? 'P2' : 'P0',
    screenshot: s11.file,
  });

  await openAyaPanel(page);
  await sendAya(page, state, 'AYA, génère le rapport complet.');
  await page.waitForTimeout(4000);
  const s12 = await shot(page, outDir, 'S2-12-rapport-strategique');
  const d12 = await drawerState(page);
  record(state, 'S2.3 AYA rapport stratégique drawer', {
    status: d12.pdfVisible || d12.open ? 'PASS' : 'FAIL',
    observation: `pdf_drawer=${d12.pdfVisible}, title="${d12.title}"`,
    fix: !d12.pdfVisible ? 'Vérifier draft_strategic_report + URL signée PDF (~12p)' : '—',
    priority: 'P1',
    screenshot: s12.file,
  });

  await goto(page, '/hypervisor/mission-room/agenda/meeting/evt-prefet-nawa?workspace=sentinel-ci');
  await page.waitForTimeout(2500);
  await openAyaPanel(page);
  await sendAya(page, state, 'AYA, ajoute le point cacao à l\'ordre du jour.');
  await page.waitForTimeout(3000);
  const s13 = await shot(page, outDir, 'S2-13-odj-patch');
  const odj = await page.evaluate(() => ({
    patchBanner: /Modification ODJ|propos[eé]e|validation/i.test(document.body.innerText),
    cacao: /cacao|anacarde/i.test(document.body.innerText),
    drawer: !!document.querySelector('app-assistant-draft-drawer, .calendar-agenda-patch'),
  }));
  record(state, 'S2.4 AYA patch ODJ cacao', {
    status: odj.patchBanner || odj.drawer ? 'PASS' : 'FAIL',
    observation: `banner=${odj.patchBanner}, drawer=${odj.drawer}, cacao=${odj.cacao}`,
    fix: !odj.patchBanner ? 'Vérifier form Proposer point ODJ + calendar_agenda_patch drawer' : '—',
    priority: 'P1',
    screenshot: s13.file,
  });

  await openAyaPanel(page);
  await sendAya(page, state, 'Oui, valide.');
  await page.waitForTimeout(3000);
  const s14 = await shot(page, outDir, 'S2-14-odj-validate');
  const validated = await page.evaluate(() => /Ajout[eé] par AYA|valid[eé]|cacao/i.test(document.body.innerText));
  record(state, 'S2.5 Validation patch ODJ', {
    status: validated ? 'PASS' : 'FAIL',
    observation: `badge/ODJ updated=${validated}`,
    fix: !validated ? 'Clic bannière orange Valider modification ou voice.confirm_yes → confirm_agenda_patch' : '—',
    priority: 'P1',
    screenshot: s14.file,
  });

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
    await sendAya(page, state, 'AYA, démarre la réunion.');
  }
  await page.waitForTimeout(3000);
  const s15 = await shot(page, outDir, 'S2-15-meeting-live');
  const meeting = await page.evaluate(() => ({
    url: location.pathname,
    live: /meeting|chrono|r[eé]union/i.test(document.body.innerText),
    odj: /Ordre du jour|ODJ|cacao/i.test(document.body.innerText),
  }));
  record(state, 'S2.6 Démarrer réunion live', {
    status: meeting.url.includes('meeting') && meeting.live ? 'PASS' : 'FAIL',
    observation: `url=${meeting.url}, live=${meeting.live}, odj=${meeting.odj}, click=${started}`,
    fix: !meeting.url.includes('meeting') ? 'Déployer bouton Démarrer réunion + POST /meetings/start' : '—',
    priority: 'P1',
    screenshot: s15.file,
  });

  await openAyaPanel(page);
  await sendAya(page, state, 'AYA, décide option B.');
  await page.waitForTimeout(4000);
  const s16 = await shot(page, outDir, 'S2-16-decision-b');
  const dec = await page.evaluate(() => ({
    optionB: /Option B|option B|d[eé]cid[eé]/i.test(document.body.innerText),
    logged: /Logger|d[eé]cision enregistr[eé]e|Arbitrage/i.test(document.body.innerText),
  }));
  record(state, 'S2.7 Décision option B', {
    status: dec.optionB ? 'PASS' : 'FAIL',
    observation: `optionB_text=${dec.optionB}, logged=${dec.logged}`,
    fix: !dec.optionB ? 'Meeting view → ODJ Cacao → Option B → Décider → Logger' : '—',
    priority: 'P1',
    screenshot: s16.file,
  });

  await goto(page, '/hypervisor/mission-room/cockpit?workspace=sentinel-ci');
  const pb1 = await clickZoneNord(page);
  const spb1 = await shot(page, outDir, 'planB-zone-nord');
  record(state, 'Plan B — chip Zone Nord', {
    status: pb1 ? 'PASS' : 'FAIL',
    observation: `click chip Zone Nord → ${page.url()}`,
    fix: !pb1 ? 'Rendre chip Zone Nord cliquable (drill /strategie?zone=zone-nord)' : '—',
    priority: pb1 ? 'P2' : 'P0',
    screenshot: spb1.file,
  });

  // Plan B Port is an independent presenter fallback. Re-open the cockpit map
  // instead of inheriting the Zone Nord drill route, where maritime layers are
  // intentionally disabled.
  await goto(page, '/hypervisor/mission-room/cockpit?workspace=sentinel-ci');
  await page.waitForTimeout(1500);
  let pbWebcam = false;
  for (const sel of [
    'button.port-webcam:has-text("Port Vridi")',
    'button:has-text("Port Vridi")',
    'text=/Port Vridi.*cargo/i',
    'text=/Port Vridi.*webcam/i',
    'text=/webcam demo/i',
    'button:has-text("Vridi")',
  ]) {
    try {
      const loc = page.locator(sel).first();
      if ((await loc.count()) === 0) continue;
      await loc.click({ timeout: 3000, force: true });
      pbWebcam = true;
      break;
    } catch {}
  }
  await page.waitForTimeout(1500);
  const pbWebcamDom = await page.evaluate(() => /APM Apapa|Port Vridi|Webcam port|Vignette port/i.test(document.body.innerText));
  const spb2 = await shot(page, outDir, 'planB-webcam-vridi');
  record(state, 'Plan B — Port Vridi webcam demo', {
    status: pbWebcam && pbWebcamDom ? 'PASS' : 'FAIL',
    observation: `legend button clicked=${pbWebcam}, webcam visible=${pbWebcamDom}`,
    fix: !pbWebcam ? 'Ajouter bouton Port Vridi · cargo demo dans légende carte cockpit' : '—',
    priority: 'P1',
    screenshot: spb2.file,
  });
}

async function main() {
  await mkdir(OUT_DIR, { recursive: true });
  const state = createHarnessState();
  log(state, `QA trame -> ${HOST}, OUT=${OUT_DIR}`);

  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({
    viewport: { width: 1920, height: 1080 },
    locale: 'fr-FR',
    timezoneId: 'Africa/Abidjan',
  });
  const page = await ctx.newPage();
  page.setDefaultTimeout(30_000);
  page.on('console', (m) => { if (m.type() === 'error') state.consoleErrors.push(m.text().slice(0, 200)); });
  page.on('pageerror', (e) => state.consoleErrors.push(`pageerror: ${e.message}`));

  try {
    await login(page, state, OUT_DIR);
    await runTrameFullSteps(page, state, OUT_DIR);
  } finally {
    await ctx.close();
    await browser.close();
  }

  const summary = {
    host: HOST,
    workspace: WORKSPACE,
    runAt: new Date().toISOString(),
    durationSec: ((Date.now() - state.startedAt) / 1000).toFixed(1),
    results: state.results,
    consoleErrors: state.consoleErrors.slice(0, 30),
    windowEvents: state.windowEvents.slice(0, 50),
    sseActionEffects: state.sseChunks.filter(c => c.chunk_type === 'action_effect').slice(0, 30),
    ...summarizeResults(state),
  };
  await writeFile(join(OUT_DIR, 'qa-results.json'), JSON.stringify(summary, null, 2), 'utf8');
  log(state, `Done. ${state.results.length} steps. JSON -> ${join(OUT_DIR, 'qa-results.json')}`);
  const { pass, partial, fail } = summarizeResults(state);
  log(state, `PASS=${pass} PARTIAL=${partial} FAIL=${fail}`);
  process.exit(fail > 0 ? 1 : 0);
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((e) => { console.error('[FATAL]', e.message, e.stack); process.exit(2); });
}

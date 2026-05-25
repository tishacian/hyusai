/**
 * QA UI — Trame démo SENTINEL-CI Scénario 3 (Posture sécuritaire dual-axis)
 *
 * Rejoue S3.1 → S3.6 + surfaces V21 contre une instance frontend Agentium.
 * Critère primaire : effet DOM (drawer titre, URL, bloc visible) — SSE optionnel.
 *
 * Usage : node scripts/playwright/qa_s3_security.mjs
 * Env   : AGENTIUM_HOST, AGENTIUM_EMAIL, AGENTIUM_PASSWORD, OUT_DIR
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
  goto,
  hasAction,
  summarizeResults,
} from './qa_trame_shared.mjs';

const OUT_DIR =
  process.env.OUT_DIR ||
  '/Users/thib/Developer/PAPAI/omnirag/docs/status-screenshots/2026-05-25-qa-s3-trame';

/** @param {import('playwright').Page} page */
export async function runS3SecuritySteps(page, state, outDir, { includeV21 = true } = {}) {
  if (includeV21) {
    await goto(page, '/hypervisor/mission-room/cockpit?workspace=sentinel-ci');

    const navItems = await page.evaluate(() =>
      Array.from(document.querySelectorAll('app-mission-rail button, app-mission-rail a'))
        .map((el) => el.textContent?.trim() || '')
        .filter(Boolean),
    );
    const sV21Nav = await shot(page, outDir, 'V21-01-nav-rail');
    record(state, 'V21.1 Rail Securite + Reputation visible', {
      status: navItems.some((t) => /S[eé]curit/i.test(t)) && navItems.some((t) => /R[eé]putation/i.test(t))
        ? 'PASS'
        : 'FAIL',
      observation: `nav items: ${navItems.join(' · ')}`,
      fix: 'Verifier NAVIGATION_ITEMS + primaryRailKeys mission-room',
      priority: 'P1',
      screenshot: sV21Nav.file,
    });

    await goto(page, '/hypervisor/mission-room/securite?workspace=sentinel-ci');
    const sV21Sec = await shot(page, outDir, 'V21-02-securite-shell');
    const securiteShell = await page.evaluate(() =>
      /Posture s[eé]curitaire|Conseil D[eé]fense|Th[eé][aâ]tre Sahel|Dossier rumeur/i.test(document.body.innerText),
    );
    record(state, 'V21.1 Onglet Securite shell agregé', {
      status: securiteShell ? 'PASS' : 'FAIL',
      observation: `shell securite visible=${securiteShell}, url=${page.url()}`,
      fix: 'Verifier #securiteView + embedded drawers',
      priority: 'P1',
      screenshot: sV21Sec.file,
    });

    await goto(page, '/hypervisor/mission-room/securite/monitor?workspace=sentinel-ci');
    const sV21Mon = await shot(page, outDir, 'V21-03-security-monitor');
    const monitorVisible = await page.evaluate(() =>
      /Security Monitor|ADS-B|CACHE BASELINE|Theatre Sahel/i.test(document.body.innerText),
    );
    record(state, 'V21.2 Security Monitor plein ecran', {
      status: monitorVisible ? 'PASS' : 'FAIL',
      observation: `monitor visible=${monitorVisible}, url=${page.url()}`,
      fix: 'Verifier security-monitor.component + GET /security-monitor',
      priority: 'P1',
      screenshot: sV21Mon.file,
    });

    await goto(page, '/hypervisor/mission-room/veille-sociale?workspace=sentinel-ci');
    const sV21Soc = await shot(page, outDir, 'V21-04-veille-sociale');
    const socialPage = await page.evaluate(() =>
      /Pulsation sociale|Veille sociale|Export CSV|officiel/i.test(document.body.innerText),
    );
    record(state, 'V21.4 Page Veille sociale standalone', {
      status: socialPage ? 'PASS' : 'FAIL',
      observation: `page sociale visible=${socialPage}, url=${page.url()}`,
      fix: 'Verifier social-pulse-page.component + route /veille-sociale',
      priority: 'P1',
      screenshot: sV21Soc.file,
    });

    await goto(page, '/hypervisor/mission-room/cockpit?workspace=sentinel-ci');
  }

  const opened = await openAyaPanel(page);
  if (!opened) {
    record(state, 'S3.1 AYA panel ouverture', {
      status: 'FAIL',
      observation: 'Quick Panel AYA ne s\'ouvre pas (bouton + Cmd/Ctrl+K)',
      fix: 'Vérifier ouverture chat-overlay / icônes lucide',
      priority: 'P0',
      screenshot: (await shot(page, outDir, 'S3.1-aya-panel-fail')).file,
    });
  } else {
    const { newChunks } = await sendAya(page, state, 'AYA, montre-moi la posture sécuritaire du jour.');
    const s1 = await shot(page, outDir, 'S3.1-posture-securite');
    const navAction = hasAction(newChunks, /show_security_posture|security_posture|posture/i);
    const securiteRoute = state.windowEvents.some(
      (e) =>
        e.event === 'agentium:assistant-navigate'
        && /\/securite/i.test(JSON.stringify(e.detail || {})),
    );
    const cockpitText = await page.evaluate(() =>
      /Posture s[eé]curitaire|Conseil D[eé]fense|dual.axis|Sahel/i.test(document.body.innerText),
    );
    const domOk = cockpitText || securiteRoute || page.url().includes('/securite');
    record(state, 'S3.1 AYA posture sécuritaire dual-axis', {
      status: domOk ? 'PASS' : 'FAIL',
      observation: `action=${navAction}, route_securite=${securiteRoute}, bloc Posture visible=${cockpitText}`,
      fix: !domOk ? 'Vérifier pack sentinel_ci_aya_security_v1 + aya.show_security_posture' : '—',
      priority: domOk ? 'P2' : 'P0',
      screenshot: s1.file,
      extra: { functional_pass: domOk, telemetry_pass: navAction },
    });
  }

  await openAyaPanel(page);
  await sendAya(page, state, 'AYA, montre la pulsation sociale à Abidjan.');
  await page.waitForTimeout(3000);
  const s2 = await shot(page, outDir, 'S3.2-pulsation-sociale');
  const d2 = await drawerState(page);
  const socialDrawer = d2.open && /pulsation|sociale|signaux|Abidjan/i.test(`${d2.title} ${d2.body}`);
  record(state, 'S3.2 AYA pulsation sociale + drawer tweets', {
    status: socialDrawer ? 'PASS' : 'FAIL',
    observation: `drawer_open=${d2.open}, drawer="${d2.title}"`,
    fix: !socialDrawer ? 'Vérifier aya.show_social_pulse + emit assistant-draft-open(social_pulse_snapshot)' : '—',
    priority: socialDrawer ? 'P2' : 'P0',
    screenshot: s2.file,
  });

  await openAyaPanel(page);
  await sendAya(page, state, "AYA, d'où vient la rumeur frontière Nord ?");
  await page.waitForTimeout(3000);
  const s3file = await shot(page, outDir, 'S3.3-rumeur-frontiere');
  const d3 = await drawerState(page);
  const chainText = await page.evaluate(() =>
    /Telegram|d[eé]menti|Bouna|FANCI|11h42|13h45|rumeur/i.test(document.body.innerText),
  );
  const rumorDrawer = d3.open && /rumeur|fronti[eè]re|OSINT/i.test(`${d3.title} ${d3.body}`);
  record(state, 'S3.3 AYA trace rumeur OSINT + proposition communiqué', {
    status: chainText || rumorDrawer ? 'PASS' : 'FAIL',
    observation: `chaîne visible=${chainText}, drawer="${d3.title}"`,
    fix: !chainText ? 'Vérifier aya.trace_rumor_origin + map_command border-tension' : '—',
    priority: chainText ? 'P2' : 'P0',
    screenshot: s3file.file,
  });

  await openAyaPanel(page);
  await sendAya(page, state, 'AYA, montre les mouvements de troupes au Sahel.');
  await page.waitForTimeout(3000);
  const s4 = await shot(page, outDir, 'S3.4-troupes-sahel');
  const d4 = await drawerState(page);
  const adsbText = await page.evaluate(() =>
    /ADS.B|advisory|Bamako|Ouaga|Niamey|CEDEAO|Sahel/i.test(document.body.innerText),
  );
  const troopsDrawer = d4.open && /ADS|Sahel|troupes|Th[eé][aâ]tre/i.test(`${d4.title} ${d4.body}`);
  record(state, 'S3.4 AYA snapshot ADS-B advisory Sahel', {
    status: adsbText || troopsDrawer ? 'PASS' : 'FAIL',
    observation: `drawer="${d4.title}", ADS-B visible=${adsbText}`,
    fix: !adsbText ? 'Vérifier aya.show_troops_movement + map_command military-air + draft snapshot' : '—',
    priority: adsbText ? 'P2' : 'P0',
    screenshot: s4.file,
  });

  await openAyaPanel(page);
  await sendAya(page, state, 'AYA, montre le drill de réputation 2 positifs et 1 critique.');
  try {
    await page.waitForURL(/\/reputation/i, { timeout: 14_000 });
  } catch {}
  await page.waitForTimeout(2000);
  const s5 = await shot(page, outDir, 'S3.5-drill-reputation');
  const reputationUrl = page.url();
  const drillVisible = await page.evaluate(
    () =>
      /Jeune Afrique|Fraternit[eé] Matin|L'Inter|72\s*\/\s*100|Drill du sentiment|Positif|Critique|r[eé]putation/i.test(
        document.body.innerText,
      ),
  );
  const onReputation = /\/reputation/i.test(reputationUrl);
  record(state, 'S3.5 AYA drill réputation 2+/1-', {
    status: drillVisible && onReputation ? 'PASS' : 'FAIL',
    observation: `drill visible=${drillVisible}, on_reputation=${onReputation}, url=${reputationUrl.split('?')[0]}`,
    fix: !onReputation
      ? 'Vérifier route /hypervisor/mission-room/reputation + assistant-navigate depuis effet SSE'
      : (!drillVisible ? 'Vérifier aya.show_reputation_drill + reputation.items dans cockpit payload' : '—'),
    priority: drillVisible && onReputation ? 'P2' : 'P0',
    screenshot: s5.file,
    extra: { onReputationRoute: onReputation },
  });

  await openAyaPanel(page);
  await sendAya(page, state, 'AYA, prépare un communiqué de sécurité sur la rumeur frontière Nord.');
  await page.waitForTimeout(3500);
  const s6 = await shot(page, outDir, 'S3.6-communique-securite');
  const d6 = await drawerState(page);
  const communiqueDrawer = d6.open && /communiqu[eé]|s[eé]curit[eé]|rumeur|advisory/i.test(`${d6.title} ${d6.body}`);
  record(state, 'S3.6 AYA brouillon communiqué sécurité', {
    status: communiqueDrawer ? 'PASS' : 'FAIL',
    observation: `drawer="${d6.title}"`,
    fix: !communiqueDrawer ? 'Vérifier aya.draft_security_communique + skill draft_response_email_v1 ou fallback' : '—',
    priority: communiqueDrawer ? 'P2' : 'P0',
    screenshot: s6.file,
  });
}

async function main() {
  await mkdir(OUT_DIR, { recursive: true });
  const state = createHarnessState();
  log(state, `QA S3 -> ${HOST}, OUT=${OUT_DIR}`);

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
    await runS3SecuritySteps(page, state, OUT_DIR);
  } finally {
    await ctx.close();
    await browser.close();
  }

  const { pass, partial, fail } = summarizeResults(state);
  const summary = {
    host: HOST,
    workspace: WORKSPACE,
    runAt: new Date().toISOString(),
    durationSec: ((Date.now() - state.startedAt) / 1000).toFixed(1),
    results: state.results,
    pass,
    partial,
    fail,
    consoleErrors: state.consoleErrors.slice(0, 30),
    windowEvents: state.windowEvents.slice(0, 50),
    sseActionEffects: state.sseChunks
      .filter((c) => c.chunk_type === 'action_effect')
      .slice(0, 30),
  };
  await writeFile(join(OUT_DIR, 'qa-s3-results.json'), JSON.stringify(summary, null, 2), 'utf8');
  log(state, `Done. ${state.results.length} steps. JSON -> ${join(OUT_DIR, 'qa-s3-results.json')}`);
  log(state, `PASS=${pass} PARTIAL=${partial} FAIL=${fail}`);
  process.exit(fail > 0 ? 1 : 0);
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((e) => {
    console.error('[FATAL]', e.message, e.stack);
    process.exit(2);
  });
}

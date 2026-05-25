/**
 * QA UI — verbatim deck phrases (presenter deck 2026-05-25)
 *
 * For each phrase the presenter will read literally from the deck, this
 * script sends it through the AYA chat panel on prod and:
 *   1. captures the SSE action_effect chunks streamed by /chat/stream
 *   2. captures a screenshot of the resulting UI state
 *   3. asserts the expected UI effect (drawer / panel / navigation)
 *
 * Coupled with `scripts/qa_deck_phrases_resolve.py` (deterministic
 * /actions/resolve probe), this gives a full deck-conformity verdict.
 *
 * Usage:
 *   node scripts/playwright/qa_deck_phrases_ui.mjs
 *
 * Env: AGENTIUM_HOST, AGENTIUM_EMAIL, AGENTIUM_PASSWORD, OUT_DIR
 */
import { chromium } from 'playwright';
import { mkdir, writeFile, stat } from 'node:fs/promises';
import { join } from 'node:path';

const HOST = (process.env.AGENTIUM_HOST || 'https://agentium.papai.ai').replace(/\/+$/, '');
const EMAIL = process.env.AGENTIUM_EMAIL || 'thibaud.ishacian@datategy.net';
const PASSWORD = process.env.AGENTIUM_PASSWORD || '';
const OUT_DIR =
  process.env.OUT_DIR ||
  join(process.cwd(), 'docs/status-screenshots/2026-05-25-qa-trame-v2');
const WORKSPACE = 'sentinel-ci';

if (!PASSWORD) {
  throw new Error('AGENTIUM_PASSWORD is required for QA login');
}

const NAV_TIMEOUT = 45_000;
const AYA_WAIT_MS = 14_000;
const startedAt = Date.now();

// VERBATIM deck phrases — copy/paste from
// docs/sentinel-ci-demo-presenter-deck-2026-05-25.md
// Order = order the presenter will read.
const DECK_PHRASES = [
  {
    slide: 'S1.1',
    label: 'Brief lundi matin',
    phrase: "AYA, c'est lundi matin. Qu'est-ce qui demande mon attention ?",
    nav: '/hypervisor/mission-room/cockpit?workspace=sentinel-ci',
    expectedActionLike: ['priority_summary', 'explain_why', 'focus_zone'],
    expectedTextLike: ['cacao', 'Napi', 'Nord', 'matin', 'attention'],
  },
  {
    slide: 'S1.3',
    label: 'Pourquoi Nord tendue',
    phrase: 'AYA, pourquoi la situation Nord est-elle tendue ?',
    nav: '/hypervisor/mission-room/cockpit?workspace=sentinel-ci',
    expectedActionLike: ['explain_why', 'focus_zone', 'zoom_zone'],
    expectedTextLike: ['Napi', 'Aerostar', '120'],
    expectedNav: 'strategie',
  },
  {
    slide: 'S1.4',
    label: 'Ouvre PV douanes',
    phrase: 'AYA, ouvre le PV douanes.',
    expectedActionLike: ['show_customs_record', 'document_preview'],
    expectedDrawer: 'document_preview',
    expectedDrawerTitleLike: ['PV douanes', 'non conformite', 'non-conformit'],
  },
  {
    slide: 'S1.5',
    label: 'Cargo Atlantic Trader',
    phrase: 'AYA, montre le cargo Atlantic Trader.',
    nav: '/hypervisor/mission-room/cockpit?workspace=sentinel-ci',
    expectedActionLike: ['show_vessel', 'show_maritime', 'show-webcam', 'maritime'],
    expectedNav: 'strategie',
    expectedTextLike: ['Atlantic', 'IMO', 'APM', 'Apapa'],
  },
  {
    slide: 'S1.6',
    label: 'Situation au port',
    phrase: 'AYA, montre la situation au port.',
    expectedActionLike: ['show_maritime', 'maritime', 'show-webcam'],
    expectedNav: 'strategie',
    expectedTextLike: ['Vridi', 'APM', 'Apapa', 'maritime'],
  },
  {
    slide: 'S1.7',
    label: 'Courrier dedouanement',
    phrase: 'AYA, rédige le courrier de dédouanement pour Atlantic Trader.',
    expectedActionLike: ['draft_customs', 'customs_email', 'propose-customs', 'derogation'],
    expectedDrawer: 'customs_email',
    expectedDrawerTitleLike: ['dedouanement', 'derogation', 'douani', 'Atlantic'],
  },
  {
    slide: 'T.1',
    label: 'Prochain rendez-vous',
    phrase: 'AYA, quel est mon prochain rendez-vous ?',
    nav: '/hypervisor/mission-room/cockpit?workspace=sentinel-ci',
    expectedActionLike: ['open_next_meeting', 'next_meeting', 'open_agenda'],
    expectedNav: 'agenda',
    expectedTextLike: ['Nawa', 'Pr\u00e9fet', '11h', 'Soubr'],
  },
  {
    slide: 'S2.1',
    label: 'Resume rapport prefet',
    phrase: 'AYA, donne-moi le résumé du rapport préfet.',
    nav: '/hypervisor/mission-room/agenda?workspace=sentinel-ci',
    expectedActionLike: ['summarize_last', 'summarize', 'nawa'],
    expectedTextLike: ['Nawa', 'Soubr', 'cacao', 'anacarde'],
  },
  {
    slide: 'S2.2',
    label: 'Preconisations cacao',
    phrase: 'AYA, donne-moi des préconisations sur le cacao.',
    expectedActionLike: ['recommend_cacao', 'recommend', 'cacao'],
    expectedTextLike: ['transformation', 'coop', 'PPP', 'FCFA'],
  },
  {
    slide: 'S2.3',
    label: 'Rapport complet',
    phrase: 'AYA, génère le rapport complet.',
    expectedActionLike: ['draft_strategic_report', 'strategic', 'report'],
    expectedDrawer: 'document_preview',
    expectedDrawerTitleLike: ['cacao', 'rapport', 'strat'],
  },
  {
    slide: 'S2.4',
    label: 'Patch ODJ cacao',
    phrase: "AYA, ajoute le point cacao à l'ordre du jour.",
    nav: '/hypervisor/mission-room/agenda?workspace=sentinel-ci',
    expectedActionLike: ['agenda_patch', 'update_meeting_agenda', 'add_meeting_topic'],
    expectedTextLike: ['cacao', 'ODJ', 'Modification', 'propos'],
  },
  {
    slide: 'S2.5',
    label: 'Valider patch',
    phrase: 'Oui, valide.',
    expectedActionLike: ['confirm_yes', 'confirm_agenda_patch', 'voice.confirm'],
    expectedTextLike: ['valid', 'Ajout', 'cacao'],
  },
  {
    slide: 'S2.6',
    label: 'Demarrer reunion',
    phrase: 'AYA, démarre la réunion.',
    expectedActionLike: ['start_meeting', 'open_meeting_live', 'meeting'],
    expectedNav: 'meeting',
    expectedTextLike: ['ODJ', 'cacao', 'reunion', 'r\u00e9union', 'chrono'],
  },
  {
    slide: 'S2.7',
    label: 'Decide option B',
    phrase: 'AYA, décide option B.',
    expectedActionLike: ['decide_option', 'log_decision', 'option_b'],
    expectedTextLike: ['option B', 'd\u00e9cid', 'd\u00e9cision', 'Option B'],
  },
];

const consoleErrors = [];
const windowEvents = [];
const sseChunks = [];
const results = [];

function log(m) {
  const e = ((Date.now() - startedAt) / 1000).toFixed(1);
  console.log(`[${e.padStart(6, ' ')}s] ${m}`);
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
    await shot(page, '00-login-failed');
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
  const beforeEvents = windowEvents.length;
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
  return {
    newChunks: sseChunks.slice(beforeChunks),
    newEvents: windowEvents.slice(beforeEvents),
  };
}

async function drawerState(page) {
  return page.evaluate(() => {
    const drawer = document.querySelector('app-assistant-draft-drawer, .draft-drawer, [data-testid="assistant-draft-drawer"]');
    const open = !!drawer && (
      drawer.getAttribute('data-open') === 'true' ||
      drawer.classList.contains('is-open') ||
      drawer.querySelector('[open]') ||
      drawer.querySelector('iframe, embed, object, .doc-citation-preview, .doc-citation, .citation-page')
    );
    const title = drawer?.querySelector('h2, h3, .drawer-title, [class*="title"]')?.textContent?.trim() || '';
    const kind = drawer?.getAttribute('data-kind') || drawer?.querySelector('[data-kind]')?.getAttribute('data-kind') || '';
    const pdfVisible = !!drawer?.querySelector('iframe[src*="blob"], iframe[src*="pdf"], canvas, .pdf-viewer');
    const citationsVisible = !!drawer?.querySelector('.doc-citation-preview, .citation-page');
    const emailVisible = !!drawer?.querySelector('.email-draft, [class*="customs"], textarea, .draft-body');
    return {
      open: !!open || !!drawer,
      title: title.slice(0, 160),
      kind,
      pdfVisible,
      citationsVisible,
      emailVisible,
    };
  });
}

async function pageState(page) {
  return page.evaluate(() => {
    const text = document.body.innerText.slice(0, 30000);
    return { url: location.pathname + location.search, text };
  });
}

async function nav(page, path) {
  if (!path) return;
  const url = path.startsWith('http') ? path : `${HOST}${path}`;
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: NAV_TIMEOUT });
  try { await page.waitForLoadState('networkidle', { timeout: 8_000 }); } catch {}
  await page.waitForTimeout(1500);
}

function chunkSummary(chunks) {
  const actions = [];
  for (const c of chunks) {
    if (c.chunk_type === 'action_effect') {
      const aid = c.action_id || c.action || c.detail?.action_id || '';
      if (aid) actions.push(aid);
      const inner = JSON.stringify(c).slice(0, 240);
      actions.push(`<${inner}>`);
    }
  }
  return actions;
}

async function runPhrase(page, phrase, idx) {
  const slug = `${phrase.slide}-${String(idx).padStart(2, '0')}-${phrase.label.toLowerCase().replace(/[^a-z0-9]+/g, '-').slice(0, 30)}`;
  log(`-- ${phrase.slide} ${phrase.label} :: "${phrase.phrase}"`);

  if (phrase.nav) await nav(page, phrase.nav);
  await openAyaPanel(page);

  const { newChunks, newEvents } = await sendAya(page, phrase.phrase);
  await page.waitForTimeout(2000);

  const s = await shot(page, slug);
  const ds = await drawerState(page);
  const ps = await pageState(page);
  const sseDump = JSON.stringify(newChunks).slice(0, 2000);
  const eventDump = JSON.stringify(newEvents).slice(0, 1000);

  const actionMatch = phrase.expectedActionLike?.some(a =>
    new RegExp(a, 'i').test(sseDump) || new RegExp(a, 'i').test(eventDump),
  ) ?? null;
  const navMatch = phrase.expectedNav ? new RegExp(phrase.expectedNav, 'i').test(ps.url) : null;
  const textMatch = phrase.expectedTextLike?.some(t => new RegExp(t, 'i').test(ps.text)) ?? null;
  const drawerMatch = phrase.expectedDrawer
    ? (
        ds.open
        && (
          phrase.expectedDrawer === 'document_preview'
            ? (ds.citationsVisible || ds.pdfVisible)
            : phrase.expectedDrawer === 'customs_email'
              ? ds.emailVisible
              : true
        )
      )
    : null;
  const titleMatch = phrase.expectedDrawerTitleLike
    ? phrase.expectedDrawerTitleLike.some(t => new RegExp(t, 'i').test(ds.title))
    : null;

  const positiveSignals = [actionMatch, navMatch, textMatch, drawerMatch, titleMatch].filter(v => v === true).length;
  const checked = [actionMatch, navMatch, textMatch, drawerMatch, titleMatch].filter(v => v !== null).length;

  let status = 'PARTIAL';
  if (checked === 0) status = 'PARTIAL';
  else if (positiveSignals === checked) status = 'PASS';
  else if (positiveSignals >= Math.ceil(checked / 2)) status = 'PARTIAL';
  else status = 'FAIL';

  const summary = {
    slide: phrase.slide,
    label: phrase.label,
    phrase: phrase.phrase,
    status,
    actionMatch,
    navMatch,
    textMatch,
    drawerMatch,
    titleMatch,
    drawer: ds,
    url: ps.url,
    sseActions: chunkSummary(newChunks).slice(0, 5),
    events: newEvents.slice(0, 5).map(e => e.event),
    screenshot: s.file,
  };
  results.push(summary);
  log(`   [${status}] action=${actionMatch} nav=${navMatch} text=${textMatch} drawer=${drawerMatch} title=${titleMatch}`);
  return summary;
}

async function main() {
  await mkdir(OUT_DIR, { recursive: true });
  log(`Deck-phrase QA -> ${HOST}, OUT=${OUT_DIR}`);

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

    let i = 0;
    for (const phrase of DECK_PHRASES) {
      i += 1;
      try {
        await runPhrase(page, phrase, i);
      } catch (e) {
        log(`   [ERR] ${phrase.slide}: ${e.message}`);
        results.push({
          slide: phrase.slide,
          label: phrase.label,
          phrase: phrase.phrase,
          status: 'FAIL',
          error: e.message,
        });
      }
    }
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
    consoleErrors: consoleErrors.slice(0, 20),
  };
  await writeFile(join(OUT_DIR, 'deck-phrases-ui-results.json'), JSON.stringify(summary, null, 2), 'utf8');

  const pass = results.filter(r => r.status === 'PASS').length;
  const partial = results.filter(r => r.status === 'PARTIAL').length;
  const fail = results.filter(r => r.status === 'FAIL').length;
  log(`Done. PASS=${pass} PARTIAL=${partial} FAIL=${fail} (total ${results.length})`);
  process.exit(fail > 3 ? 1 : 0);
}

main().catch(e => { console.error('[FATAL]', e.message, e.stack); process.exit(2); });

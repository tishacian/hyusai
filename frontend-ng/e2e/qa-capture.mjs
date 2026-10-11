/**
 * Capture-fil surfaces (prep / plan / finalize / review / publish). The shell
 * gates its tab strip on engine state, so the stub seeds one completed session
 * plus an accepted proposal: opening the session lands on Review and unlocks
 * Publication. Runs on /knowledge/interventions so the FSE template is bound —
 * that is the branch that renders `capture.publish.template_intro`, the merged
 * sentence we need to eyeball.
 */
import { chromium } from '@playwright/test';
import { mkdirSync, writeFileSync } from 'node:fs';

const BASE = process.env.BASE ?? 'http://localhost:4200';
const OUT = 'e2e/qa-visual';
mkdirSync(OUT, { recursive: true });

const ME = { id: 'u-qa', email: 'qa@local.test', name: 'QA Local', roles: ['admin', 'owner'] };
const WS = { id: 'ws-qa', slug: 'nawa', name: 'NAWA', settings: { features: {} } };

const SESSION = {
  id: 'sess-qa-1',
  status: 'completed',
  title: 'Reprise pompe P-204 — vibration palier',
  domain: 'maintenance',
  expert_name: 'Karim B.',
  created_at: '2026-08-10T09:00:00Z',
  updated_at: '2026-08-10T10:20:00Z',
  turns_count: 24,
  facts_count: 11,
};

const PROPOSAL = {
  id: 'prop-qa-1',
  status: 'accepted',
  session_id: 'sess-qa-1',
  proposal: {
    title: 'Reprise pompe P-204 — vibration palier',
    objective: 'Documenter le diagnostic et la remise en service de la pompe P-204.',
    captured_facts: [
      { id: 'f1', statement: 'Le palier côté accouplement chauffe au-delà de 78 °C.', confidence: 0.9 },
      { id: 'f2', statement: 'Le jeu radial mesuré est de 0,42 mm, hors tolérance.', confidence: 0.8 },
    ],
    open_questions: [{ id: 'q1', question: 'La référence du roulement de rechange est-elle homologuée ?' }],
    report_markdown: '# Reprise pompe P-204\n\nDiagnostic vibratoire et remise en service.\n',
    publication: { destination: 'interventions-fse', source_type: 'intervention_fse', suggested: true },
  },
};

const FEED = {
  feed: [
    { id: 'e1', kind: 'turn', channel: 'voice', speaker: 'expert', text: 'On a relevé une vibration sur le palier.', ts_ms: 1754812800000, seq: 1, turn_id: 't1' },
    { id: 'e2', kind: 'turn', channel: 'voice', speaker: 'assistant', text: 'À quelle fréquence apparaît-elle ?', ts_ms: 1754812830000, seq: 2, turn_id: 't2' },
  ],
};

function payload(p, method) {
  if (/\/auth\/me|\/users\/me|\/me$/.test(p)) return ME;
  if (/\/workspaces\/?$/.test(p)) return [WS];
  if (/\/workspaces\/[^/]+\/?$/.test(p)) return WS;
  if (p.endsWith('/knowledge-capture/sessions')) return { sessions: [SESSION] };
  if (p.endsWith('/knowledge-capture/proposals')) return { proposals: [PROPOSAL] };
  if (/\/knowledge-capture\/sessions\/[^/]+\/feed$/.test(p)) return FEED;
  if (/\/knowledge-capture\/sessions\/[^/]+\/documents$/.test(p)) return { documents: [] };
  if (/\/knowledge-capture\/sessions\/[^/]+\/closure-sheet$/.test(p)) return { checklist: [], ready: true };
  if (/\/knowledge-capture\/sessions\/[^/]+\/quality-backlog$/.test(p)) return { items: [] };
  if (/\/knowledge-capture\/sessions\/[^/]+\/hint-queue$/.test(p)) return { hints: [] };
  if (p.endsWith('/documents/collections')) return { collections: ['interventions-fse', 'methodes-geotechnique'] };
  if (p.endsWith('/knowledge-capture/fiches')) return { fiches: [] };
  if (/\/(skills|systems|capabilities|runs|collections|apps|presets)(\/)?$/.test(p)) return [];
  return { items: [], results: [], total: 0, sessions: [], proposals: [] };
}

const browser = await chromium.launch();
const log = [];

for (const theme of ['light', 'dark']) {
  for (const locale of ['fr', 'en']) {
    const ctx = await browser.newContext({ viewport: { width: 1600, height: 1100 } });
    await ctx.addInitScript(
      ({ theme, locale }) => {
        localStorage.setItem('agentium_token', 'Bearer qa-local-token');
        localStorage.setItem('agentium_workspace_slug', 'nawa');
        localStorage.setItem('agentium_theme', theme);
        localStorage.setItem('agentium_locale', locale);
      },
      { theme, locale },
    );
    const page = await ctx.newPage();
    await page.route('**/api/**', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(payload(new URL(route.request().url()).pathname, route.request().method())),
      }),
    );
    await page.route(/https:\/\/fonts\./, (route) => route.abort());

    const shot = async (label) => {
      const tag = `capture-${label}-${theme}-${locale}`;
      await page.screenshot({ path: `${OUT}/${tag}.png`, fullPage: true });
      const text = await page.evaluate(() => (document.body.innerText || '').replace(/\n{2,}/g, '\n'));
      log.push(`\n===== ${tag} =====\n${text}`);
      console.log(`${tag.padEnd(34)} ${text.length} chars`);
    };

    await page.goto(`${BASE}/knowledge/interventions`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(3000);
    await shot('dashboard');

    // Preparation surface: reachable straight from the tab strip.
    const tab = (name) => page.locator(`nav button:has-text("${name}")`).first();
    for (const [label, fr, en] of [['prep', 'PRÉPARATION', 'PREPARATION']]) {
      const btn = tab(locale === 'fr' ? fr : en);
      if (await btn.count()) {
        await btn.click();
        await page.waitForTimeout(1600);
        await shot(label);
      } else {
        console.log(`  ${label}: tab not found`);
      }
    }

    // Open the seeded completed session -> Review, which unlocks Publication.
    await page.goto(`${BASE}/knowledge/interventions`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2800);
    const row = page.locator(`text=${SESSION.title}`).first();
    if (await row.count()) {
      await row.click();
      await page.waitForTimeout(2600);
      await shot('review');
      const enabled = await page.evaluate(() =>
        [...document.querySelectorAll('nav button')].map((b) => ({
          label: b.textContent.trim(),
          disabled: b.disabled,
        })),
      );
      console.log('  tabs:', JSON.stringify(enabled));
      for (const [label, fr, en] of [
        ['finalize', 'FINALISATION', 'WRAP-UP'],
        ['publish', 'PUBLICATION', 'PUBLICATION'],
        ['plan', 'PLAN', 'PLAN'],
      ]) {
        const btn = tab(locale === 'fr' ? fr : en);
        if ((await btn.count()) && !(await btn.isDisabled())) {
          await btn.click();
          await page.waitForTimeout(1800);
          await shot(label);
        } else {
          console.log(`  ${label}: unreachable (missing or disabled)`);
        }
      }
    } else {
      console.log('  session row not rendered — dashboard stub rejected');
    }
    await ctx.close();
  }
}

writeFileSync(`${OUT}/capture-text.txt`, log.join('\n'));
await browser.close();

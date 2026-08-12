/**
 * Skill authoring wizard + flow inspector, from a builder's seat. The create
 * affordance is gated on `GET /skills/executors` returning `editable: true`, so
 * the stub serves a small but realistic executor catalog and walks the four
 * steps of the dialog, shooting each one in both themes and both locales.
 */
import { chromium } from '@playwright/test';
import { mkdirSync, writeFileSync } from 'node:fs';

const BASE = process.env.BASE ?? 'http://localhost:4200';
const OUT = 'e2e/qa-visual';
mkdirSync(OUT, { recursive: true });

const ME = { id: 'u-qa', email: 'qa@local.test', name: 'QA Local', roles: ['admin', 'owner'] };
const WS = { id: 'ws-qa', slug: 'nawa', name: 'NAWA', settings: { features: {} } };

const EXECUTORS = {
  editable: true,
  categories: ['retrieval', 'generation', 'integration', 'analysis'],
  executors: [
    {
      kind: 'http_request',
      summary: 'Call an external HTTP endpoint and return the parsed body.',
      params_schema: {
        type: 'object',
        required: ['url', 'method'],
        properties: {
          url: { type: 'string', minLength: 8 },
          method: { type: 'string', enum: ['GET', 'POST', 'PUT'] },
          timeout_s: { type: 'number' },
        },
      },
    },
    {
      kind: 'sql_query',
      summary: 'Run a parameterised SQL query against a configured connector.',
      params_schema: {
        type: 'object',
        required: ['connector', 'query'],
        properties: {
          connector: { type: 'string', enum: ['postgres', 'sap_hana'] },
          query: { type: 'string', minLength: 4 },
        },
      },
    },
  ],
};

const CAPABILITIES = [
  { id: 'cap-1', name: 'ITSD triage', slug: 'itsd-triage', description: 'Route and answer service desk tickets.' },
  { id: 'cap-2', name: 'Maintenance advisor', slug: 'maintenance-advisor', description: 'Support field maintenance.' },
];

function payload(p) {
  if (/\/auth\/me|\/users\/me|\/me$/.test(p)) return ME;
  if (/\/workspaces\/?$/.test(p)) return [WS];
  if (/\/workspaces\/[^/]+\/?$/.test(p)) return WS;
  if (p.endsWith('/skills/executors')) return EXECUTORS;
  if (p.endsWith('/capabilities')) return CAPABILITIES;
  if (/\/(skills|systems|runs|collections|apps|presets)(\/)?$/.test(p)) return [];
  return { items: [], results: [], total: 0 };
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
        body: JSON.stringify(payload(new URL(route.request().url()).pathname)),
      }),
    );
    await page.route(/https:\/\/fonts\./, (route) => route.abort());

    const shot = async (label) => {
      const tag = `skill-${label}-${theme}-${locale}`;
      await page.screenshot({ path: `${OUT}/${tag}.png`, fullPage: true });
      const text = await page.evaluate(() => (document.body.innerText || '').replace(/\n{2,}/g, '\n'));
      log.push(`\n===== ${tag} =====\n${text}`);
      console.log(`${tag.padEnd(32)} ${text.length} chars`);
    };

    await page.goto(`${BASE}/skills`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(3000);
    await shot('registry');

    // The create affordance lives in the page-frame actions.
    const trigger = page
      .locator('button')
      .filter({ hasText: /nouvelle skill|nouveau skill|new skill|créer un skill|create skill/i })
      .first();
    if (!(await trigger.count())) {
      const labels = await page.evaluate(() =>
        [...document.querySelectorAll('button')].map((b) => b.textContent.trim()).filter(Boolean),
      );
      console.log(`  no create trigger; buttons: ${JSON.stringify(labels.slice(0, 40))}`);
      await ctx.close();
      continue;
    }
    await trigger.click();
    await page.waitForTimeout(1400);
    await shot('wizard-step1');

    // Step 1: identity. The dialog labels its fields above the control rather
    // than with placeholders, so fill positionally: local name, display name,
    // description.
    const dialog = page.locator('div').filter({ hasText: /INTENT|INTENTION/ }).last();
    const texts = page.locator('input[type=text], input:not([type]), textarea');
    const values = ['sla_lookup', 'Lookup ticket SLA', 'Returns the contractual SLA of an ITSD ticket.'];
    const total = await texts.count();
    for (let i = 0; i < Math.min(total, values.length); i++) {
      try {
        await texts.nth(i).fill(values[i], { timeout: 3000 });
      } catch {}
    }
    // Pick the first real executor so the "how the work gets done" gate clears.
    const selects = page.locator('select');
    for (let i = 0; i < (await selects.count()); i++) {
      const opts = await selects.nth(i).locator('option').allTextContents();
      const real = opts.findIndex((o) => /http_request|sql_query/.test(o));
      if (real >= 0) await selects.nth(i).selectOption({ index: real });
    }
    await page.waitForTimeout(600);
    await shot('wizard-step1-filled');

    for (let step = 2; step <= 4; step++) {
      const next = page
        .locator('button')
        .filter({ hasText: /\b(suivant|next|continuer|continue)\b/i })
        .first();
      if (!(await next.count())) {
        console.log(`  wizard: no next button before step ${step}`);
        break;
      }
      if (await next.isDisabled()) {
        console.log(`  wizard: next disabled before step ${step} (gates unmet)`);
        break;
      }
      await next.click();
      await page.waitForTimeout(1200);
      await shot(`wizard-step${step}`);
    }
    await ctx.close();
  }
}

writeFileSync(`${OUT}/skill-text.txt`, log.join('\n'));
await browser.close();

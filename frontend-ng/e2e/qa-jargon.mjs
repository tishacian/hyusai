/**
 * Close-ups for the two jargon fixes: the flow builder checklist strip (codes
 * out of the readable surface, messages in the reader's language) and the
 * skill wizard steps (plain question first, requirements document second).
 *
 * Same stubbing as qa-skill.mjs / qa-zoom.mjs, element-clipped at device scale
 * 2 because both surfaces are 9–11px type, in light/dark × FR/EN.
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
        },
      },
    },
  ],
};

const CAPABILITIES = [
  { id: 'cap-1', name: 'ITSD triage', slug: 'itsd-triage', description: 'Route and answer service desk tickets.' },
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
    const ctx = await browser.newContext({
      viewport: { width: 1600, height: 1100 },
      deviceScaleFactor: 2,
    });
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

    const shoot = async (label, locator) => {
      const tag = `jargon-${label}-${theme}-${locale}`;
      if (!(await locator.count())) {
        console.log(`${tag}: selector miss`);
        return;
      }
      await locator.screenshot({ path: `${OUT}/${tag}.png` });
      const text = (await locator.innerText()).replace(/\n{2,}/g, '\n');
      const attrs = await locator.evaluate((root) =>
        [...root.querySelectorAll('[data-code]')].map(
          (el) => `${el.dataset.code} | ${el.title}`,
        ),
      );
      log.push(`\n===== ${tag} =====\n${text}${attrs.length ? `\n-- data-code --\n${attrs.join('\n')}` : ''}`);
      console.log(`${tag}: ok`);
    };

    // ---- flow builder checklist -----------------------------------------
    await page.goto(`${BASE}/orchestration`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(3500);
    await shoot('checklist', page.locator('app-flow-validation-strip .ck-vstrip').first());

    // ---- skill wizard ----------------------------------------------------
    await page.goto(`${BASE}/skills`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(3000);
    const trigger = page
      .locator('button')
      .filter({ hasText: /nouvelle skill|new skill/i })
      .first();
    if (!(await trigger.count())) {
      console.log(`wizard-${theme}-${locale}: no create trigger`);
      await ctx.close();
      continue;
    }
    await trigger.click();
    await page.waitForTimeout(1200);
    const dialog = page.locator('app-new-skill-dialog > div > div').last();
    await shoot('wizard-step1', dialog);

    const texts = page.locator('input[type=text], input:not([type]), textarea');
    const values = ['sla_lookup', 'Lookup ticket SLA', 'Returns the contractual SLA of an ITSD ticket.'];
    for (let i = 0; i < Math.min(await texts.count(), values.length); i++) {
      try {
        await texts.nth(i).fill(values[i], { timeout: 3000 });
      } catch {}
    }
    await page.waitForTimeout(400);
    await shoot('wizard-step1-filled', dialog);

    // The step tabs navigate directly, so a gate on the Next button cannot
    // hide the later steps from the shoot.
    for (let step = 2; step <= 4; step++) {
      const tab = page.locator('[role=tab]').nth(step - 1);
      if (!(await tab.count())) {
        console.log(`wizard: cannot reach step ${step}`);
        break;
      }
      await tab.click();
      await page.waitForTimeout(900);
      await shoot(`wizard-step${step}`, dialog);
    }
    await ctx.close();
  }
}

writeFileSync(`${OUT}/jargon-text.txt`, log.join('\n'));
await browser.close();

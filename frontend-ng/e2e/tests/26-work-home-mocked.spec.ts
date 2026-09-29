import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page, type Route } from '@playwright/test';

/**
 * L33 — the Work home « À faire », fully mocked.
 *
 * Opt-in, with no backend (same flag as the chrome safety net):
 *
 *   E2E_CHROME_V2_MOCKED=1 E2E_BASE_URL=http://127.0.0.1:4238
 *   npx playwright test e2e/tests/26-work-home-mocked.spec.ts --trace=off
 *
 * `GET /work/_home` is answered as the backend composes it; the PR to PO
 * decision is enriched from its Run, shaped like the L32 fixture (25-…).
 */

const enabled = process.env['E2E_CHROME_V2_MOCKED'] === '1';
const SHOT_DIR = process.env['E2E_SHOT_DIR'] ?? 'test-results/l33-home-shots';

test.use({ serviceWorkers: 'block', video: 'off', viewport: { width: 1440, height: 900 } });

function json(route: Route, body: unknown, status = 200): Promise<void> {
  return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
}

const WORKSPACE = {
  id: 'ws-l33',
  name: 'NAWA',
  slug: 'nawa-l33',
  role: 'member',
  role_template: 'workspace_contributor',
  settings: { features: { experience_v1: true, adoption_experience_v1: true } },
};

const USER = {
  id: 'user-l33',
  email: 'ada@example.test',
  role: 'user',
  is_active: true,
  mfa_enabled: false,
  first_name: 'Ada',
  last_name: 'Lovelace',
  workspaces: [WORKSPACE],
};

/** Naive UTC, as the backend serialises its stamps. */
const ago = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString().replace('Z', '');

const PR_RUN = 'run-l33-atex';
const PR = {
  PurchaseRequisition: '2000276559',
  PurchaseRequisitionItem: '10',
  PurchaseRequisitionItemText: 'ATEX Services',
  RequestedQuantity: '61.000',
  BaseUnit: 'NO',
  PurchaseRequisitionPrice: '10.00',
  PurReqnItemCurrency: 'QAR',
  Plant: '1000',
};

function inv(nodeId: string, slug: string, output: Record<string, unknown>) {
  return { id: `inv-${nodeId}`, skill_slug: slug, status: 'completed', latency_ms: 100, input_ref: {}, output_ref: output, trace: { node_id: nodeId } };
}

function mcp(server: string, tool: string, extra: Record<string, unknown>) {
  return { ok: true, server_id: server, tool, contract_tool: tool, ...extra };
}

function prRun(): Record<string, unknown> {
  const nodes = ['task.list_prs', 'task.select_pr', 'task.budget', 'task.justification', 'task.hikma', 'task.majority'];
  const checkpoints: Array<Record<string, unknown>> = [{ kind: 'run_start', t: ago(240) }];
  for (const id of nodes) {
    checkpoints.push({ kind: 'node_start', node_id: id, t: ago(240) });
    checkpoints.push({ kind: 'node_end', node_id: id, status: 'completed', t: ago(240) });
  }
  return {
    id: PR_RUN,
    system_id: 'sys-pr',
    status: 'hitl_pending',
    input_ref: { disabled_tools: [] },
    checkpoints,
    hitl: {
      node_id: 'hitl.approve_po',
      decision_id: 'dec-atex',
      decision_status: 'proposed',
      upstream: { pr: PR, pr_id: PR.PurchaseRequisition, price_missing: false, budget: true, budget_reason: 'ok', supplier: '4000004006', vote_count: 5 },
    },
    invocations: [
      inv('task.list_prs', 'sap_list_approved_prs_v1', mcp('sap', 'get_A_PurchaseRequisitionItem', { prs: [PR] })),
      inv('task.select_pr', 'python_recipe_v1', { pr_id: PR.PurchaseRequisition, pr: PR, price_missing: false }),
      inv('task.budget', 'sap_check_budget_v1', mcp('sap', 'fi_Validate', { pr_id: PR.PurchaseRequisition, budget_ok: true, reason: 'ok' })),
      inv('task.justification', 'sap_get_justification_v1', mcp('sap', 'get_A_PurchaseRequisitionItem_by_key', { justification: 'Maintenance ATEX.' })),
      inv('task.hikma', 'hikma_list_pos_by_type_v1', mcp('hikma', 'get_A_PurchaseOrder', { pos: [{}], pr_type: 'ZNPR' })),
      inv('task.majority', 'python_recipe_v1', { supplier: '4000004006', vote_count: 5 }),
    ],
  };
}

const PR_APP = { kind: 'app', slug: 'pr-to-po', name: 'PR to PO' };
const OPS_APP = { kind: 'app', slug: 'operational-analysis', name: 'Operational Analysis' };
const NIGHTLY = { kind: 'automation', system_id: 'sys-nightly', name: 'Relance fournisseurs' };

function catalogue(): Record<string, unknown> {
  const app = (slug: string, name: string, pattern: string, channel: string) => ({
    experience: { id: `exp-${slug}`, name, slug, pattern, deployments: [{ channel }] },
    channel,
    release: { id: `rel-${slug}`, renderer_version: 'certified-components-0.2.0', identity_snapshot: { name, slug, pattern } },
    pending_decisions: { count: 0, oldest_at: null },
  });
  return {
    experiences: [
      app('pr-to-po', 'PR to PO', 'approval', 'live'),
      app('operational-analysis', 'Operational Analysis', 'form_result', 'live'),
      app('spark-grading', 'SPARK grading', 'queue', 'pilot'),
    ],
    automation_jobs: [
      { job: { system_id: 'sys-nightly', name: 'Relance fournisseurs' }, objective: { text: 'Relancer les fournisseurs en retard.' }, convention: {}, gap: {}, proof: null },
    ],
  };
}

function busyHome(): Record<string, unknown> {
  return {
    window_days: 7,
    decisions: {
      count: 2,
      oldest_at: ago(245),
      items: [
        { run_id: 'run-l33-late', title: 'Confirmer la livraison partielle', started_at: ago(30), source: PR_APP },
        { run_id: PR_RUN, decision_id: 'dec-atex', title: 'Valider la commande ATEX Services', started_at: ago(245), source: PR_APP },
      ],
    },
    reviews: {
      count: 1,
      oldest_at: ago(60 * 26),
      items: [{ decision_id: 'rev-spark', run_id: '95f2e6e5-1c2d', title: 'Compléter le grade proposé', created_at: ago(60 * 26), source: OPS_APP }],
    },
    results: {
      items: [
        { run_id: 'e2d7e8ce-aa01', completed_at: ago(90), source: NIGHTLY, receipt: { steps: 4, agent_ms: 6200, write: null, passages_read: null, passages_cited: null } },
      ],
    },
    agent_work: {
      items: [
        { run_id: '827e12b7-0001', completed_at: ago(50), source: PR_APP, receipt: { steps: 8, agent_ms: 18_000, write: 'sealed', passages_read: null, passages_cited: null } },
        { run_id: '5b1c0f3a-0002', completed_at: ago(80), source: OPS_APP, receipt: { steps: null, agent_ms: null, write: null, passages_read: 3, passages_cited: 2 } },
        { run_id: 'e2d7e8ce-aa01', completed_at: ago(90), source: NIGHTLY, receipt: { steps: 4, agent_ms: 6200, write: null, passages_read: null, passages_cited: null } },
      ],
    },
  };
}

function quietHome(): Record<string, unknown> {
  return {
    window_days: 7,
    decisions: { count: 0, oldest_at: null, items: [] },
    reviews: null,
    results: { items: [] },
    agent_work: { items: [] },
  };
}

async function installHome(page: Page, theme: 'dark' | 'light', home: Record<string, unknown>): Promise<void> {
  await page.addInitScript(({ slug, theme }) => {
    localStorage.setItem('agentium_token', 'Bearer mocked-l33');
    localStorage.setItem('agentium_workspace_slug', slug);
    localStorage.setItem('agentium_theme', theme);
    localStorage.setItem('agentium_locale', 'fr');
  }, { slug: WORKSPACE.slug, theme });

  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const apiPath = new URL(request.url()).pathname.replace(/^\/api\/v1/, '');
    const method = request.method();
    if (apiPath === '/auth/validate' && method === 'POST') {
      return json(route, { valid: true, user_id: USER.id, email: USER.email, role: USER.role });
    }
    if (apiPath === '/auth/workspaces') return json(route, [WORKSPACE]);
    if (apiPath === `/auth/workspaces/${WORKSPACE.slug}`) return json(route, WORKSPACE);
    if (apiPath === `/auth/workspaces/${WORKSPACE.slug}/me/experience`) {
      return json(route, { version: 1, persona: 'operator', journey: 'northforge_sources', completed_steps: [], dismissed: false, example_available: true });
    }
    if (apiPath === '/auth/me') return json(route, USER);
    if (apiPath === '/help-content') return json(route, { version: 'local', personas: [], languages: [], items: [] });
    if (apiPath === '/work') return json(route, catalogue());
    if (apiPath === '/work/_home') return json(route, home);
    if (apiPath === `/runs/${PR_RUN}` && method === 'GET') return json(route, prRun());
    if (apiPath === '/work/pr-to-po/validations') return json(route, { runs: [] });
    if (method === 'GET') {
      if (apiPath.endsWith('s') || apiPath.includes('items')) return json(route, []);
      return json(route, {});
    }
    return json(route, { ok: true });
  });
}

async function expectNoAxeViolations(page: Page): Promise<void> {
  // The compact onboarding card is lot L34's (content and styles ship there).
  const results = await new AxeBuilder({ page })
    .include('app-work-launcher')
    .exclude('app-adoption-journey')
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
    .analyze();
  expect(results.violations, results.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`).join('\n')).toEqual([]);
}

test.describe('L33 — Work home « À faire »', () => {
  test.skip(!enabled, 'Set E2E_CHROME_V2_MOCKED=1 to run the mocked chrome safety net');

  for (const theme of ['light', 'dark'] as const) {
    test(`home with items, receipts and a keyboard path to the first decision (${theme})`, async ({ page }) => {
      const errors: string[] = [];
      page.on('pageerror', (error) => errors.push(error.message));
      await installHome(page, theme, busyHome());
      await page.goto('/work');

      const home = page.locator('app-work-launcher');
      await expect(home.getByRole('heading', { level: 1 })).toHaveText('4 choses vous attendent', { timeout: 20_000 });
      await expect(home.locator('.xp-home-eyebrow')).toHaveText('Accueil');

      // Three tiles; only the first actionable one is filled.
      const tiles = home.locator('.xp-home-tiles > li');
      await expect(tiles).toHaveCount(3);
      await expect(tiles.nth(0)).toContainText('2');
      await expect(tiles.nth(0)).toContainText('décisions attendues');
      await expect(tiles.nth(0)).toContainText('La plus ancienne attend depuis 4 h.');
      await expect(tiles.nth(1)).toContainText('réponse à relire');
      await expect(tiles.nth(2)).toContainText('applications prêtes');
      await expect(tiles.nth(2)).toContainText('2 en service · 1 en pilote.');
      await expect(home.locator('.xp-home-tile-lead')).toHaveCount(1);
      await expect(tiles.nth(0).locator('a')).toHaveClass(/xp-home-tile-lead/);

      // Prioritised list: oldest decision first, then the review, then the result.
      const rows = home.locator('.xp-home-list > li');
      await expect(rows).toHaveCount(4);
      await expect(rows.nth(0)).toContainText('Valider la commande ATEX Services');
      await expect(rows.nth(1)).toContainText('Confirmer la livraison partielle');
      await expect(rows.nth(2)).toContainText('Compléter le grade proposé');
      await expect(rows.nth(3)).toContainText('Relance fournisseurs');
      // The L32 receipt, read from the Run: amount, budget check, SAP reads.
      const firstMeta = rows.nth(0).locator('.xp-home-meta');
      await expect(firstMeta).toContainText('610,00 QAR');
      await expect(firstMeta).toContainText('contrôle budgétaire OK');
      await expect(firstMeta).toContainText('3 lectures SAP');
      await expect(rows.nth(0).locator('.xp-home-chip')).toHaveText('Votre accord');
      await expect(rows.nth(2).locator('.xp-home-chip')).toHaveText('À relire');
      await expect(rows.nth(3).locator('.xp-home-chip')).toHaveText('Prêt');
      await expect(rows.nth(3)).toContainText('4 étapes · 6,2 s');

      // Agent work this week, with one receipt line each and a mono reference.
      const work = home.locator('.xp-home-work > li');
      await expect(work).toHaveCount(3);
      await expect(work.nth(0)).toContainText('8 étapes · 18 s · écriture scellée');
      await expect(work.nth(1)).toContainText('3 passages lus · 2 cités');
      await expect(work.nth(0).locator('a.xp-home-id')).toHaveText('827e12b7');
      await expect(home.locator('.xp-home-rail app-adoption-journey')).toHaveCount(1);
      // No designer note, no letter-spaced capitals.
      await expect(home).not.toContainText('Un utilisateur est activé');
      await page.screenshot({ path: `${SHOT_DIR}/work-home-${theme}.png`, fullPage: true });
      const spaced = await home.evaluate((root) =>
        [...root.querySelectorAll<HTMLElement>('.xp-home *')].filter((el) => {
          const style = getComputedStyle(el);
          return style.textTransform === 'uppercase' && parseFloat(style.letterSpacing) > 0.5 && el.textContent?.trim();
        }).map((el) => el.outerHTML.slice(0, 160)),
      );
      expect(spaced).toEqual([]);
      await expectNoAxeViolations(page);

      // Keyboard: Tab to « Traiter » on the first decision, then Enter.
      const target = 'Traiter : Valider la commande ATEX Services';
      await page.locator('body').click({ position: { x: 5, y: 5 } });
      let reached = false;
      for (let i = 0; i < 40 && !reached; i++) {
        await page.keyboard.press('Tab');
        reached = (await page.evaluate(() => document.activeElement?.getAttribute('aria-label'))) === target;
      }
      expect(reached).toBe(true);
      const box = await page.evaluate(() => document.activeElement!.getBoundingClientRect().height);
      expect(box).toBeGreaterThanOrEqual(24);
      // Phone width: one column, no horizontal scroll.
      await page.setViewportSize({ width: 390, height: 844 });
      await expect(home.locator('.xp-home-list > li').first()).toBeVisible();
      expect(await page.evaluate(() => document.scrollingElement!.scrollWidth)).toBeLessThanOrEqual(390);
      await page.screenshot({ path: `${SHOT_DIR}/work-home-mobile-${theme}.png`, fullPage: true });
      await page.setViewportSize({ width: 1440, height: 900 });

      // The home itself raised nothing; the gate page behind it is not mocked here.
      expect(errors).toEqual([]);
      await page.keyboard.press('Enter');
      await expect(page).toHaveURL(/\/work\/pr-to-po\/validations/);
    });

    test(`empty week: fixed title, no fabricated count, next useful action (${theme})`, async ({ page }) => {
      await installHome(page, theme, quietHome());
      await page.goto('/work');
      const home = page.locator('app-work-launcher');
      await expect(home.getByRole('heading', { level: 1 })).toHaveText('Vos applications', { timeout: 20_000 });
      const tiles = home.locator('.xp-home-tiles > li');
      // Reviews are unknown for this reader: no tile, not a zero.
      await expect(tiles).toHaveCount(2);
      await expect(tiles.nth(0)).toContainText("Rien à valider pour l'instant.");
      await expect(tiles.nth(0)).toContainText('décision attendue');
      await expect(home.locator('.xp-home-tile-lead')).toHaveCount(0);
      await expect(home.locator('.xp-home-queue')).toContainText("Rien à traiter pour l'instant.");
      const rail = home.locator('.xp-home-agents');
      await expect(rail).toContainText("Aucun travail d'agent terminé cette semaine.");
      await rail.getByRole('link', { name: 'Voir vos applications' }).click();
      await expect(home.locator('#work-all-apps')).toBeFocused();
      await expect(home.locator('.xp-work-grid').first()).toBeVisible();
      await page.screenshot({ path: `${SHOT_DIR}/work-home-empty-${theme}.png`, fullPage: true });
      await expectNoAxeViolations(page);
    });
  }
});

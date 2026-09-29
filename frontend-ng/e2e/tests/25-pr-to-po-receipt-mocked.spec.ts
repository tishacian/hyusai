import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page, type Route } from '@playwright/test';

/**
 * L32 — the work receipt of the PR to PO Studio, fully mocked.
 *
 * Opt-in, with no backend (same flag as the chrome safety net):
 *
 *   E2E_CHROME_V2_MOCKED=1 E2E_BASE_URL=http://127.0.0.1:4235
 *   npx playwright test e2e/tests/25-pr-to-po-receipt-mocked.spec.ts
 *
 * The Studio opens on a gate left pending (`/work/pr-to-po/validations`), so
 * nothing is launched. The Run below is shaped like the walker writes it:
 * naive-UTC `t` on every checkpoint, one invocation per task node.
 */

const enabled = process.env['E2E_CHROME_V2_MOCKED'] === '1';
const SHOT_DIR = process.env['E2E_SHOT_DIR'] ?? 'test-results/l32-receipt-shots';

test.use({ serviceWorkers: 'block', video: 'off', viewport: { width: 1440, height: 900 } });

function json(route: Route, body: unknown, status = 200): Promise<void> {
  return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
}

const WORKSPACE = {
  id: 'ws-l32',
  name: 'NAWA',
  slug: 'nawa-l32',
  role: 'admin',
  role_template: 'workspace_admin',
  settings: { features: { experience_v1: true, mcp_connector: true } },
};

const USER = {
  id: 'user-l32',
  email: 'ada@example.test',
  role: 'admin',
  is_active: true,
  mfa_enabled: false,
  first_name: 'Ada',
  last_name: 'Lovelace',
  workspaces: [WORKSPACE],
};

const RUN_ID = 'run-l32';
const T0 = Date.parse('2026-09-28T10:00:00Z');
const at = (ms: number) => new Date(T0 + ms).toISOString().replace('Z', '');

const PR = {
  PurchaseRequisition: '2000276559',
  PurchaseRequisitionItem: '10',
  PurchaseRequisitionItemText: 'DE-09-F Desk 140 X 80 X 75 H',
  RequestedQuantity: '61.000',
  BaseUnit: 'NO',
  PurchaseRequisitionPrice: '10.00',
  PurReqnItemCurrency: 'QAR',
  Plant: '1000',
};

const WALK: Array<[string, number, number, Record<string, unknown>]> = [
  ['task.list_prs', 100, 1400, {}],
  ['task.select_pr', 1400, 1500, {}],
  ['task.budget', 1500, 2300, {}],
  ['task.justification', 2300, 2700, {}],
  ['task.reject', 2700, 2700, { status: 'skipped', skipped_reason: 'all_inputs_dead' }],
  ['task.hikma', 2700, 15300, {}],
  ['task.majority', 15300, 15400, {}],
  ['task.format_dossier', 15400, 15600, {}],
  ['task.summarise', 15600, 18000, {}],
];

function inv(nodeId: string, slug: string, output: Record<string, unknown>) {
  return { id: `inv-${nodeId}`, skill_slug: slug, status: 'completed', latency_ms: 100, input_ref: {}, output_ref: output, trace: { node_id: nodeId } };
}

function mcp(server: string, tool: string, extra: Record<string, unknown>) {
  return { ok: true, server_id: server, tool, contract_tool: tool, ...extra };
}

const INVOCATIONS = [
  inv('task.list_prs', 'sap_list_approved_prs_v1', mcp('sap', 'get_A_PurchaseRequisitionItem', { prs: [PR], duration_ms: 1235 })),
  inv('task.select_pr', 'python_recipe_v1', { pr_id: PR.PurchaseRequisition, pr: PR, price_missing: false, candidates: [PR.PurchaseRequisition], total_open: 1 }),
  inv('task.budget', 'sap_check_budget_v1', mcp('sap', 'fi_Validate', { pr_id: PR.PurchaseRequisition, budget_ok: true, reason: 'ok', duration_ms: 763 })),
  inv('task.justification', 'sap_get_justification_v1', mcp('sap', 'get_A_PurchaseRequisitionItem_by_key', { pr_id: PR.PurchaseRequisition, justification: 'Finance floor refresh.' })),
  inv('task.hikma', 'hikma_list_pos_by_type_v1', mcp('hikma', 'get_A_PurchaseOrder', { pos: [{}, {}, {}, {}, {}], pr_type: 'ZNPR', duration_ms: 12619 })),
  inv('task.majority', 'python_recipe_v1', { supplier: '4000004006', vote_count: 5, payment_terms: 'ZAD7', incoterms: 'DDP', format: 'ZLPO', purch_group: '100' }),
  inv('task.format_dossier', 'python_recipe_v1', { formatted: '| PR | Supplier |\n| 2000276559 | 4000004006 |' }),
  inv('task.summarise', 'azure_llm_v1', { completion: 'Bureaux pour le nouvel étage finance.' }),
];

function gateCheckpoints() {
  const rows: Array<Record<string, unknown>> = [{ kind: 'run_start', t: at(0) }];
  for (const [id, start, end, extra] of WALK) {
    rows.push({ kind: 'node_start', node_id: id, t: at(start) });
    rows.push({ kind: 'node_end', node_id: id, status: 'completed', ...extra, t: at(end) });
  }
  rows.push({ kind: 'node_start', node_id: 'hitl.approve_po', node_kind: 'hitl', t: at(18100) });
  rows.push({ kind: 'node_end', node_id: 'hitl.approve_po', node_kind: 'hitl', pause: true, t: at(18200) });
  return rows;
}

function pendingRun(): Record<string, unknown> {
  return {
    id: RUN_ID,
    system_id: 'sys-l32',
    status: 'hitl_pending',
    input_ref: { disabled_tools: [] },
    checkpoints: gateCheckpoints(),
    hitl: {
      node_id: 'hitl.approve_po',
      decision_id: 'dec-l32',
      decision_status: 'proposed',
      upstream: {
        pr: PR,
        pr_id: PR.PurchaseRequisition,
        PurchaseRequisitionItem: '10',
        price_missing: false,
        candidates: [PR.PurchaseRequisition],
        total_open: 1,
        budget: true,
        budget_reason: 'ok',
        vote_count: 5,
        purch_group: '100',
        payment_terms: 'ZAD7',
        incoterms: 'DDP',
        supplier: '4000004006',
        format: 'ZLPO',
        justification_summary: 'Bureaux pour le nouvel étage finance.',
        formatted: '| PR | Supplier |\n| 2000276559 | 4000004006 |',
      },
    },
    invocations: INVOCATIONS,
  };
}

function rejectedRun(): Record<string, unknown> {
  const base = pendingRun();
  return {
    ...base,
    status: 'completed',
    hitl: { ...(base['hitl'] as Record<string, unknown>), decision_status: 'rejected' },
    checkpoints: [
      ...gateCheckpoints(),
      { kind: 'hitl_resume', node_id: 'hitl.approve_po', decision_status: 'rejected', t: at(300_000) },
      { kind: 'node_start', node_id: 'task.create_po', t: at(300_100) },
      { kind: 'node_end', node_id: 'task.create_po', status: 'skipped', skipped_reason: 'all_inputs_dead', t: at(300_100) },
      { kind: 'node_start', node_id: 'task.handle_rejection', t: at(300_100) },
      { kind: 'node_end', node_id: 'task.handle_rejection', status: 'completed', t: at(300_900) },
      { kind: 'node_start', node_id: 'task.audit', t: at(300_900) },
      { kind: 'node_end', node_id: 'task.audit', status: 'completed', t: at(301_100) },
      { kind: 'run_end', t: at(301_200) },
    ],
    invocations: [
      ...INVOCATIONS,
      inv('task.handle_rejection', 'sap_handle_rejection_v1', { sealed: true, called: false, blocked: false, server_id: 'sap', tool: 'fi_DiscardFromPurchasing' }),
      inv('task.audit', 'audit_log_v1', { ok: true }),
    ],
  };
}

interface Studio {
  hitlPosts: Array<Record<string, unknown>>;
}

async function installStudio(page: Page, theme: 'dark' | 'light'): Promise<Studio> {
  const studio: Studio = { hitlPosts: [] };
  let run = pendingRun();
  await page.addInitScript(({ slug, theme }) => {
    localStorage.setItem('agentium_token', 'Bearer mocked-l32');
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
    if (apiPath === '/auth/me') return json(route, USER);
    if (apiPath === '/help-content') return json(route, { version: 'local', personas: [], languages: [], items: [] });
    if (apiPath === '/work/pr-to-po/validations') return json(route, { runs: [run] });
    if (apiPath === `/runs/${RUN_ID}` && method === 'GET') return json(route, run);
    if (apiPath === `/runs/${RUN_ID}/hitl` && method === 'POST') {
      const body = request.postDataJSON() as Record<string, unknown>;
      studio.hitlPosts.push(body);
      run = body['action'] === 'reject' ? rejectedRun() : run;
      return json(route, { ...pendingRun(), hitl: { ...(pendingRun()['hitl'] as Record<string, unknown>), decision_status: 'rejected' } });
    }
    if (apiPath === '/mcp/servers') {
      return json(route, {
        servers: [
          { id: 'sap', label: 'SAP S/4HANA', configured: true, enabled: true },
          { id: 'hikma', label: 'Hikma', configured: true, enabled: true },
          { id: 'bapi_po', label: 'SAP BAPI', configured: true, enabled: true },
        ],
      });
    }
    if (apiPath.startsWith('/system-bindings/')) return json(route, {});
    if (method === 'GET') {
      if (apiPath.endsWith('s') || apiPath.includes('items')) return json(route, []);
      return json(route, {});
    }
    return json(route, { ok: true });
  });
  return studio;
}

test.describe('L32 — PR to PO work receipt', () => {
  test.skip(!enabled, 'Set E2E_CHROME_V2_MOCKED=1 to run the mocked chrome safety net');

  for (const theme of ['dark', 'light'] as const) {
    test(`receipt line, keyboard chronology, gate card and a refusal that needs a reason (${theme})`, async ({ page }) => {
      const studio = await installStudio(page, theme);
      await page.goto('/work/pr-to-po');

      // The receipt: real events only — 8 settled steps, the reads the server
      // made, the budget verdict, the agent time up to the gate (18.1 s).
      const receipt = page.getByTestId('work-receipt');
      await expect(receipt).toBeVisible({ timeout: 20_000 });
      if (theme === 'light') {
        // The Studio ships dark (pinned by client-applications.spec). This pass
        // checks that the receipt and the gate hold on the light v2 tokens.
        await page.locator('.xp-work.xp-studio').evaluate((el) => el.setAttribute('data-theme', 'light'));
      }
      const line = receipt.locator('.xp-receipt-line');
      await expect(line).toContainText('8 étapes');
      await expect(line).toContainText('3 lectures SAP');
      await expect(line).toContainText('1 lecture Hikma');
      await expect(line).toContainText('contrôle budgétaire OK');
      await expect(line).toContainText('18 s');
      await expect(receipt.getByRole('status')).toHaveText('Le dossier attend votre décision.');

      // One orb on the screen, on the step in progress: the gate.
      await expect(page.locator('ck-thinking-orb')).toHaveCount(1);
      await expect(page.locator('.xp-gate-eyebrow ck-thinking-orb')).toHaveCount(1);

      // Chronology: closed, then opened from the keyboard.
      const toggle = receipt.getByRole('button', { name: 'Voir la chronologie' });
      await expect(toggle).toHaveAttribute('aria-expanded', 'false');
      await expect(page.locator('#xp-receipt-chronology')).toBeHidden();
      await toggle.focus();
      await page.keyboard.press('Enter');
      await expect(receipt.getByRole('button', { name: 'Masquer la chronologie' })).toHaveAttribute('aria-expanded', 'true');
      const rows = page.locator('#xp-receipt-chronology .xp-studio-nodes > li');
      await expect(rows).toHaveCount(10);
      const budget = page.locator('.xp-studio-nodes > li[data-node="budget"]');
      await expect(budget).toContainText('Contrôle budgétaire');
      await expect(budget).toContainText('fi_Validate');
      await expect(budget).toContainText('800 ms');
      await expect(budget.getByRole('link', { name: 'Invocation : Contrôle budgétaire' }))
        .toHaveAttribute('href', `/runs/${RUN_ID}/invocations/inv-task.budget`);
      await expect(page.locator('.xp-studio-nodes > li[data-node="gate"]')).toContainText('Votre décision');

      // Tab lands in the first step; Enter opens its calls.
      await page.keyboard.press('Tab');
      const firstHead = rows.first().locator('.xp-studio-node-head');
      await expect(firstHead).toBeFocused();
      await page.keyboard.press('Enter');
      await expect(firstHead).toHaveAttribute('aria-expanded', 'true');
      await expect(rows.first().locator('.xp-studio-node-detail')).toBeVisible();
      await expect(rows.first().locator('.xp-studio-call summary code')).toContainText('get_A_PurchaseRequisitionItem');
      await page.keyboard.press('Enter');
      await expect(firstHead).toHaveAttribute('aria-expanded', 'false');

      // The gate card: what you decide on, what was checked, what follows.
      const card = page.locator('.xp-gate');
      await expect(card.locator('.xp-gate-amount strong')).toHaveText('610,00 QAR');
      const terms = card.locator('.xp-gate-terms');
      await expect(terms).toContainText('4000004006');
      await expect(terms).toContainText('ZAD7');
      await expect(terms).toContainText('DDP');
      await expect(terms).toContainText('ZLPO');
      await expect(card.locator('.xp-gate-lines tbody tr')).toHaveCount(1);
      await expect(card.locator('.xp-gate-lines tbody tr')).toContainText('61 NO');
      await expect(card.locator('.xp-gate-lines tbody tr')).toContainText('10,00 QAR');
      const checked = card.locator('section', { has: page.getByRole('heading', { name: 'Ce que l’agent a vérifié' }) });
      await expect(checked).toContainText('Contrôle budgétaire SAP : conforme.');
      await expect(checked).toContainText('Prix net repris de la demande 2000276559');
      const triggers = card.locator('section', { has: page.getByRole('heading', { name: 'Ce que votre accord déclenche' }) });
      await expect(triggers).toContainText('L’écriture SAP est scellée');
      await expect(triggers).toContainText('journal d’audit Agentium');
      await expect(page.getByRole('button', { name: 'Approuver et poster la commande de la demande 2000276559' })).toBeEnabled();

      await page.screenshot({ path: `${SHOT_DIR}/l32-gate-${theme}.png`, fullPage: true });
      const gateAxe = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa']).analyze();
      expect(gateAxe.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`)).toEqual([]);

      // Refuse without a reason: blocked, the field says why, nothing is sent.
      await page.getByRole('button', { name: 'Refuser la commande de la demande 2000276559' }).click();
      const reason = page.getByLabel('Motif du refus');
      await expect(reason).toBeFocused();
      await page.getByRole('button', { name: 'Confirmer le refus' }).click();
      await expect(page.getByRole('alert')).toHaveText('Indiquez un motif pour refuser.');
      await expect(reason).toHaveAttribute('aria-invalid', 'true');
      await expect(reason).toBeFocused();
      expect(studio.hitlPosts).toEqual([]);
      await page.screenshot({ path: `${SHOT_DIR}/l32-reject-blocked-${theme}.png`, fullPage: true });

      // With a reason: the canonical decision carries it; the outcome follows.
      await reason.fill('Fournisseur hors contrat cadre');
      await page.getByRole('button', { name: 'Confirmer le refus' }).click();
      await expect.poll(() => studio.hitlPosts.length).toBe(1);
      expect(studio.hitlPosts[0]['action']).toBe('reject');
      expect(String(studio.hitlPosts[0]['note'])).toContain('Fournisseur hors contrat cadre');
      const after = card.locator('.xp-gate-after');
      await expect(after.getByRole('status')).toContainText('Refus enregistré.', { timeout: 10_000 });
      await expect(after).toContainText('Motif : Fournisseur hors contrat cadre');
      await expect(after).toContainText('Écarter sur refus humain');
      await expect(after).toContainText('écart scellé pour 2000276559');
      await expect(after).toContainText('Journal d’audit');
      await expect(receipt.getByRole('status')).toHaveText('Exécution terminée.');
      await expect(page.locator('ck-thinking-orb')).toHaveCount(0);

      await page.screenshot({ path: `${SHOT_DIR}/l32-rejected-${theme}.png`, fullPage: true });
      const afterAxe = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa']).analyze();
      expect(afterAxe.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`)).toEqual([]);
    });
  }
});

import { expect, test, type Page } from '@playwright/test';

import {
  api,
  assertDeployedRevision,
  bindWorkspace,
  expectedSha,
  login,
  logout,
  sha256,
  writeEvidence,
} from '../fixtures/experience-canary';

/**
 * NAWA Agent Studio — behavioural contract of the PR to PO demo.
 *
 * This is the freeze contract of the post-audit realignment (H0): whatever
 * the implementation does underneath, the demo must keep behaving like this.
 *
 *   1. `/work/pr-to-po/desk` lands on the Studio (`/work/pr-to-po`).
 *   2. Run flow: one click starts the published agent, the read nodes turn
 *      green, the human gate opens with a proposal (supplier, terms, amount).
 *   3. Approve: the write verdict comes back from the server gate. With the
 *      `BAPI_PO_CREATE1` guardrail off the create is refused before the
 *      network; with the guardrail on the PO is either sealed (envelope shown)
 *      or created and committed (PO number shown) depending on the workspace
 *      flag `sap_write_unsealed`.
 *   4. The browser never talks to an MCP server itself: zero request to
 *      `/mcp/servers/{id}/invoke` during the whole scenario.
 *   5. Chat: "Create the order" opens the write dialogue in the thread,
 *      Cancel writes nothing and leaves the package at the gate, Confirm with
 *      the guardrail off ends in the refusal bubble.
 *
 * Opt-in: `E2E_NAWA_STUDIO=1`. The default run keeps `BAPI_PO_CREATE1` off in
 * the guardrails so nothing reaches SAP even when the workspace is unsealed.
 * `E2E_NAWA_STUDIO_WRITE=1` approves with the guardrail on — one real PO per
 * run when the flag is on; only the chat path stays blocked in that mode.
 * `E2E_NAWA_STUDIO_RECORD=1` keeps the video of the passing run (ops journal).
 */

const studioCanaryEnabled = process.env['E2E_NAWA_STUDIO'] === '1';
const workspaceSlug = process.env['E2E_NAWA_WORKSPACE_SLUG'] ?? 'nawa';
const allowWrite = process.env['E2E_NAWA_STUDIO_WRITE'] === '1';
const evidencePath = process.env['E2E_NAWA_STUDIO_EVIDENCE'];
const recordRun = process.env['E2E_NAWA_STUDIO_RECORD'] === '1';

const STUDIO_PATH = '/work/pr-to-po';
const BINDING_KEY = 'procurement.pr_to_po.run';
const CREATE_TOOL = 'BAPI_PO_CREATE1';
/** SAP reads, an LLM summary and a BAPI commit: the run needs minutes, not seconds. */
const RUN_TIMEOUT_MS = 240_000;

const BLOCKED = /Blocked by the guardrail|Bloqué par le garde-fou/;
const SEALED = /Write sealed|Écriture scellée/;
const POSTED = /PO (45\d{8}) created and committed|Commande (45\d{8}) créée et validée/;
const PO_NUMBER = /45\d{8}/;

type Verdict = 'blocked' | 'sealed' | 'posted' | 'failed';

interface RunSummary {
  id: string;
  status?: string;
}

interface Traffic {
  mcpInvokes: string[];
  bindingRuns: string[];
  hitlDecisions: string[];
}

function watchTraffic(page: Page): Traffic {
  const traffic: Traffic = { mcpInvokes: [], bindingRuns: [], hitlDecisions: [] };
  page.on('request', (request) => {
    const path = new URL(request.url()).pathname;
    if (/\/api\/v1\/mcp\/servers\/[^/]+\/invoke$/.test(path)) traffic.mcpInvokes.push(path);
  });
  page.on('response', async (response) => {
    const request = response.request();
    if (request.method() !== 'POST') return;
    const path = new URL(response.url()).pathname;
    if (path === `/api/v1/work/pr-to-po/bindings/${encodeURIComponent(BINDING_KEY)}/runs` && response.ok()) {
      const body = await response.json().catch(() => null) as RunSummary | null;
      if (body?.id) traffic.bindingRuns.push(body.id);
    }
    const hitl = path.match(/^\/api\/v1\/runs\/([^/]+)\/hitl$/);
    if (hitl && response.ok()) traffic.hitlDecisions.push(hitl[1]);
  });
  return traffic;
}

function verdictOf(text: string): Verdict {
  if (BLOCKED.test(text)) return 'blocked';
  if (SEALED.test(text)) return 'sealed';
  if (POSTED.test(text)) return 'posted';
  return 'failed';
}

async function pendingGates(page: Page): Promise<RunSummary[]> {
  const result = await api<{ runs?: RunSummary[] }>(page, workspaceSlug, '/work/pr-to-po/validations');
  if (!result.ok) return [];
  return (result.body.runs ?? []).filter((run) => run.status === 'hitl_pending');
}

async function setCreateGuardrail(page: Page, enabled: boolean): Promise<void> {
  const toggle = page.locator('.xp-studio-tools li', { hasText: CREATE_TOOL }).getByRole('switch');
  await expect(toggle).toBeVisible();
  if ((await toggle.getAttribute('aria-checked')) !== String(enabled)) await toggle.click();
  await expect(toggle).toHaveAttribute('aria-checked', String(enabled));
}

async function expandNode(page: Page, nodeId: string): Promise<void> {
  const node = page.locator(`.xp-studio-nodes li[data-node="${nodeId}"]`);
  if (await node.locator('.xp-studio-node-detail').count()) return;
  await node.locator('.xp-studio-node-head').click();
  await expect(node.locator('.xp-studio-node-detail')).toBeVisible();
}

test.use({
  trace: 'off',
  video: recordRun ? { mode: 'on', size: { width: 1440, height: 900 } } : 'off',
  screenshot: 'off',
  viewport: { width: 1440, height: 900 },
});

test.describe('NAWA Agent Studio — PR to PO behavioural contract', () => {
  test.skip(!studioCanaryEnabled, 'Set E2E_NAWA_STUDIO=1 to exercise /work/pr-to-po');

  test('runs the agent to its gate, decides, and keeps every SAP call on the server', async ({ page }, testInfo) => {
    test.setTimeout(3 * RUN_TIMEOUT_MS + 120_000);
    const traffic = watchTraffic(page);
    let leftPending: string[] = [];

    try {
      await assertDeployedRevision(page);
      const memberships = await login(page);
      const workspace = memberships.find((item) => item.slug === workspaceSlug);
      expect(workspace, `the canary principal must belong to workspace "${workspaceSlug}"`).toBeTruthy();
      await bindWorkspace(page, workspaceSlug);
      expect(
        await pendingGates(page),
        'a gate is already open on pr-to-po: settle it before the canary (it would become the run under test)',
      ).toEqual([]);

      // 1. The old desk route lands on the Studio.
      await page.goto(`${STUDIO_PATH}/desk?workspace=${workspaceSlug}&lang=en`);
      await expect.poll(() => new URL(page.url()).pathname).toBe(STUDIO_PATH);
      await expect(page.locator('.xp-studio-bar')).toBeVisible({ timeout: 30_000 });
      await expect(page.locator('.xp-studio-brand h1')).toContainText(/Agent Studio/);
      const badge = page.locator('.xp-studio-badge');
      await expect(badge).toBeVisible();
      const writeUnsealed = (await badge.getAttribute('data-live')) === 'true';
      await expect(page.locator('.xp-studio-servers li[data-configured="true"]').first()).toBeVisible();

      // 2. Guardrail rides the run: the create tool is off unless a real write is requested.
      await setCreateGuardrail(page, allowWrite);
      const runButton = page.locator('.xp-studio-run');
      await expect(runButton).toBeEnabled();
      await runButton.click();
      await expect.poll(() => traffic.bindingRuns.length, { timeout: 30_000 }).toBe(1);
      const runId = traffic.bindingRuns[0];
      await expect(page.locator('.xp-studio-run-link code')).toHaveText(runId.slice(0, 8));

      const gateNode = page.locator('.xp-studio-nodes li[data-node="gate"]');
      await expect(gateNode).toHaveAttribute('data-status', 'waiting', { timeout: RUN_TIMEOUT_MS });
      for (const nodeId of ['requisitions', 'select', 'history', 'derive']) {
        await expect(page.locator(`.xp-studio-nodes li[data-node="${nodeId}"]`))
          .toHaveAttribute('data-status', /^(done|warn)$/);
      }
      await expandNode(page, 'requisitions');
      const readCall = page.locator('.xp-studio-nodes li[data-node="requisitions"] .xp-studio-call').first();
      await expect(readCall).toBeVisible();
      await expect(readCall.locator('summary span[data-kind="read"]')).toBeVisible();
      await expect(readCall.locator('summary code')).toContainText('get_A_PurchaseRequisitionItem');

      const card = page.locator('.xp-studio-card');
      await expect(card).toBeVisible();
      await expect(card).toHaveAttribute('data-decision', 'pending');
      const gateLine = (await card.locator('header p').innerText()).trim();
      expect(gateLine).toMatch(/Requisition 20\d{8} · item \d+ · plant \d+/);
      const prId = gateLine.match(/20\d{8}/)![0];
      const amount = (await card.locator('header strong').innerText()).trim();
      expect(amount).toMatch(/\d/);
      await expect(card.locator('dd').first()).not.toHaveText('—');
      await expect(card.locator('.xp-studio-provenance li').first()).toBeVisible();
      const approve = page.locator('.xp-studio-approve');
      await expect(approve).toBeEnabled();
      await expect(page.locator('.xp-studio-reject')).toBeEnabled();
      expect(traffic.mcpInvokes, 'the Studio must not read SAP from the browser').toEqual([]);

      // 3. Approve: the write verdict is the server's.
      await approve.click();
      await expect.poll(() => traffic.hitlDecisions.length, { timeout: 30_000 }).toBe(1);
      expect(traffic.hitlDecisions[0]).toBe(runId);
      const outcome = page.locator('.xp-studio-outcome');
      await expect(outcome).toBeVisible({ timeout: RUN_TIMEOUT_MS });
      await expect(card).toHaveAttribute('data-decision', 'approved');
      const outcomeText = (await outcome.innerText()).trim();
      const verdict = verdictOf(outcomeText);
      const postNode = page.locator('.xp-studio-nodes li[data-node="post"]');
      await expect(page.locator('.xp-studio-nodes li[data-node="reject"]')).toHaveAttribute('data-status', 'skipped');
      let poNumber: string | null = null;
      if (!allowWrite) {
        expect(verdict, outcomeText).toBe('blocked');
        await expect(postNode).toHaveAttribute('data-status', 'warn');
        await expandNode(page, 'post');
        await expect(postNode.locator('.xp-studio-call[data-blocked="true"]').first()).toBeVisible();
      } else if (writeUnsealed) {
        expect(verdict, outcomeText).toBe('posted');
        poNumber = outcomeText.match(PO_NUMBER)![0];
        await expect(postNode).toHaveAttribute('data-status', 'done');
        await expect(page.locator('.xp-studio-result[data-live="true"]')).toContainText(poNumber);
      } else {
        expect(verdict, outcomeText).toBe('sealed');
        await expandNode(page, 'post');
        await expect(postNode.locator('.xp-studio-call[data-sealed="true"]').first()).toBeVisible();
      }
      await expect(page.locator('.xp-studio-nodes li[data-node="audit"]'))
        .toHaveAttribute('data-status', 'done', { timeout: 60_000 });
      expect(traffic.mcpInvokes, 'the Studio must not write SAP from the browser').toEqual([]);

      // 5. Chat: the write dialogue lives in the thread and rides the same gate.
      await setCreateGuardrail(page, false);
      await page.getByRole('tab', { name: /Chat/ }).click();
      await expect(page.locator('.xp-studio-chips')).toBeVisible();
      await expect(page.locator('.xp-studio-chat header ck-thinking-orb')).toBeVisible();
      const createChip = page.locator('.xp-desk-chip[data-write="true"]');
      await createChip.click();
      const dialogue = page.locator('.xp-studio-dialog');
      await expect(dialogue).toBeVisible();
      await expect(dialogue).toHaveAttribute('data-stage', 'proposing', { timeout: RUN_TIMEOUT_MS });
      await expect.poll(() => traffic.bindingRuns.length).toBe(2);
      const chatRunId = traffic.bindingRuns[1];
      await expect(dialogue.locator('.xp-studio-dialog-user')).toContainText(/Create the order for requisition 20\d{8}/);
      await expect(dialogue.locator('.xp-studio-dialog-agent > p').first())
        .toContainText(/Here is exactly what I would send/);
      await expect(dialogue.locator('.xp-studio-dialog-confirm')).toContainText(/Nothing goes out without your yes/);

      await dialogue.locator('.xp-studio-dialog-no').click();
      await expect(dialogue).toHaveAttribute('data-stage', 'cancelled');
      await expect(dialogue.locator('.xp-studio-dialog-cancelled')).toContainText(/nothing was written/);
      expect(traffic.hitlDecisions).toHaveLength(1);
      expect((await pendingGates(page)).map((run) => run.id)).toContain(chatRunId);

      await createChip.click();
      await expect(dialogue).toHaveAttribute('data-stage', 'proposing');
      await dialogue.locator('.xp-studio-dialog-yes').click();
      await expect.poll(() => traffic.hitlDecisions.length, { timeout: 30_000 }).toBe(2);
      expect(traffic.hitlDecisions[1]).toBe(chatRunId);
      await expect(dialogue).toHaveAttribute('data-stage', 'blocked', { timeout: RUN_TIMEOUT_MS });
      await expect(dialogue.locator('.xp-studio-dialog-blocked')).toContainText(/no call was made/);
      await expect(dialogue.locator('.xp-studio-dialog-calls')).toBeVisible();
      await expect(dialogue.locator('.xp-studio-dialog-calls .xp-studio-call[data-blocked="true"]').first()).toBeVisible();
      expect(traffic.mcpInvokes, 'the chat dialogue must not write SAP from the browser').toEqual([]);
      leftPending = (await pendingGates(page)).map((run) => run.id);
      expect(leftPending, 'the canary settles every gate it opens').toEqual([]);

      const evidence = {
        schema_version: 1,
        kind: 'nawa_agent_studio_canary',
        claim: 'NAWA-STUDIO-SERVER-RUN',
        outcome: 'passed',
        tested_revision: expectedSha || null,
        generated_at: new Date().toISOString(),
        target: {
          workspace_sha256: sha256(workspace!.id),
          run_sha256: sha256(runId),
          chat_run_sha256: sha256(chatRunId),
          requisition_sha256: sha256(prId),
        },
        checks: {
          desk_route_redirects_to_studio: true,
          run_started_through_binding: true,
          gate_opened_with_proposal: true,
          read_calls_visible_verbatim: true,
          decision_is_canonical_hitl: true,
          write_verdict: verdict,
          write_unsealed_flag: writeUnsealed,
          real_write_requested: allowWrite,
          po_created: poNumber !== null,
          browser_mcp_invokes: traffic.mcpInvokes.length,
          chat_dialogue_cancel_writes_nothing: true,
          chat_dialogue_confirm_blocked_by_guardrail: true,
          gates_left_pending: 0,
        },
      };
      writeEvidence(evidencePath, evidence);
      await testInfo.attach('nawa-agent-studio-canary', {
        body: JSON.stringify(evidence, null, 2),
        contentType: 'application/json',
      });
    } finally {
      // A gate the canary opened with the guardrail off can be closed without a
      // write: approving it ends in the blocked verdict. Anything else is reported.
      const stillPending = await pendingGates(page).catch(() => [] as RunSummary[]);
      const mine = stillPending.filter((run) => traffic.bindingRuns.includes(run.id));
      for (const run of mine) {
        const guardrailOff = !allowWrite || run.id !== traffic.bindingRuns[0];
        if (!guardrailOff) {
          testInfo.annotations.push({ type: 'left_pending', description: run.id });
          continue;
        }
        await api(page, workspaceSlug, `/runs/${encodeURIComponent(run.id)}/hitl`, {
          method: 'POST',
          body: { action: 'accept', note: 'canary cleanup — guardrail off, blocked before the network' },
        }).catch(() => undefined);
      }
      await logout(page);
    }
  });
});

import assert from 'node:assert/strict';
import test from 'node:test';

import type { Run } from '@app/core/canonical-api.service';
import {
  agentWorkMs,
  checkpointTime,
  chronology,
  formatReceiptDuration,
  gateChecks,
  gateConsequences,
  readSystemLabel,
  rejectReasonError,
  runDisabledTools,
  stepDurationMs,
  workReceipt,
} from './pr-to-po-receipt';
import { proposalFromRun, studioNodesFromRun } from './pr-to-po-studio';

/**
 * A Run as the walker writes it: naive-UTC `t` on every checkpoint, one
 * invocation per task node with `trace.node_id`, the package on `hitl.upstream`.
 */
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

/** [dag node id, start ms, end ms, end extras] in walker order. */
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

function mcp(server: string, tool: string, extra: Record<string, unknown> = {}) {
  return { ok: true, server_id: server, tool, contract_tool: tool, ...extra };
}

function inv(nodeId: string, slug: string, output: Record<string, unknown>) {
  return { id: `inv-${nodeId}`, skill_slug: slug, status: 'completed', latency_ms: 100, input_ref: {}, output_ref: output, trace: { node_id: nodeId } };
}

const INVOCATIONS = [
  inv('task.list_prs', 'sap_list_approved_prs_v1', mcp('sap', 'get_A_PurchaseRequisitionItem', { prs: [PR] })),
  inv('task.select_pr', 'python_recipe_v1', { pr_id: PR.PurchaseRequisition, pr: PR, price_missing: false, candidates: [PR.PurchaseRequisition] }),
  inv('task.budget', 'sap_check_budget_v1', mcp('sap', 'fi_Validate', { pr_id: PR.PurchaseRequisition, budget_ok: true, reason: 'ok' })),
  inv('task.justification', 'sap_get_justification_v1', mcp('sap', 'get_A_PurchaseRequisitionItem_by_key', { justification: 'Finance floor refresh.' })),
  inv('task.hikma', 'hikma_list_pos_by_type_v1', mcp('hikma', 'get_A_PurchaseOrder', { pos: [{}, {}, {}, {}, {}], pr_type: 'ZNPR' })),
  inv('task.majority', 'python_recipe_v1', { supplier: '4000004006', vote_count: 5, payment_terms: 'ZAD7', incoterms: 'DDP', format: 'ZLPO' }),
  inv('task.format_dossier', 'python_recipe_v1', { formatted: '| PR |' }),
  inv('task.summarise', 'azure_llm_v1', { completion: 'Desks for the new finance floor.' }),
];

function checkpoints(options: { timed?: boolean; upTo?: number; gate?: boolean } = {}) {
  const timed = options.timed !== false;
  const t = (ms: number) => (timed ? { t: at(ms) } : {});
  const rows: Array<Record<string, unknown>> = [{ kind: 'run_start', ...t(0) }];
  for (const [id, start, end, extra] of WALK.slice(0, options.upTo ?? WALK.length)) {
    rows.push({ kind: 'node_start', node_id: id, ...t(start) });
    rows.push({ kind: 'node_end', node_id: id, status: 'completed', ...extra, ...t(end) });
  }
  if (options.gate !== false) {
    rows.push({ kind: 'node_start', node_id: 'hitl.approve_po', node_kind: 'hitl', ...t(18100) });
    rows.push({ kind: 'node_end', node_id: 'hitl.approve_po', node_kind: 'hitl', pause: true, ...t(18200) });
  }
  return rows;
}

function gateRun(overrides: Partial<Run> = {}): Run {
  return {
    id: 'run-receipt',
    system_id: 'sys-1',
    status: 'hitl_pending',
    input_ref: { disabled_tools: [] },
    checkpoints: checkpoints(),
    hitl: {
      node_id: 'hitl.approve_po',
      decision_id: 'dec-1',
      decision_status: 'proposed',
      upstream: { pr: PR, pr_id: PR.PurchaseRequisition, supplier: '4000004006', vote_count: 5, payment_terms: 'ZAD7', incoterms: 'DDP', format: 'ZLPO', budget: true, budget_reason: 'ok' },
    },
    skill_invocations: INVOCATIONS,
    ...overrides,
  } as unknown as Run;
}

test('receipt at the gate counts settled steps, observed SAP reads, the budget verdict and the agent time', () => {
  const run = gateRun();
  const receipt = workReceipt(run, studioNodesFromRun(run));
  // Eight completed steps; the skipped discard and the gate itself do not count.
  assert.equal(receipt.stepsDone, 8);
  assert.equal(receipt.stepsFailed, 0);
  assert.deepEqual(receipt.reads, [
    { server: 'sap', count: 3 },
    { server: 'hikma', count: 1 },
  ]);
  assert.deepEqual(receipt.budget, { ok: true, reason: 'ok' });
  // run_start → the gate opening: the wait for the human is excluded.
  assert.equal(receipt.agentMs, 18100);
  assert.equal(receipt.current, null);
});

test('receipt omits what the Run does not carry: no timestamps, no tool calls, no budget yet', () => {
  const untimed = gateRun({ checkpoints: checkpoints({ timed: false }) });
  assert.equal(workReceipt(untimed, studioNodesFromRun(untimed)).agentMs, null);
  assert.equal(agentWorkMs(untimed), null);
  assert.equal(stepDurationMs(untimed, 'task.budget'), null);

  const noCalls = gateRun({ skill_invocations: [] } as Partial<Run>);
  const receipt = workReceipt(noCalls, studioNodesFromRun(noCalls));
  assert.deepEqual(receipt.reads, []);

  const early = gateRun({ status: 'running', checkpoints: checkpoints({ upTo: 2, gate: false }) });
  const earlyReceipt = workReceipt(early, studioNodesFromRun(early));
  assert.equal(earlyReceipt.budget, null);
  assert.equal(earlyReceipt.stepsDone, 2);
});

test('receipt names the step the walker is on while it runs', () => {
  const rows = checkpoints({ upTo: 2, gate: false });
  rows.push({ kind: 'node_start', node_id: 'task.budget', t: at(1500) });
  const run = gateRun({ status: 'running', checkpoints: rows });
  assert.equal(workReceipt(run, studioNodesFromRun(run)).current, 'budget');
});

test('agent time adds the work after the resume, not the human wait', () => {
  const rows = [
    ...checkpoints(),
    { kind: 'hitl_resume', node_id: 'hitl.approve_po', decision_status: 'accepted', t: at(600_000) },
    { kind: 'node_start', node_id: 'task.create_po', t: at(600_100) },
    { kind: 'node_end', node_id: 'task.create_po', status: 'completed', t: at(602_500) },
    { kind: 'run_end', t: at(603_000) },
  ];
  assert.equal(agentWorkMs(gateRun({ status: 'completed', checkpoints: rows })), 18100 + 3000);
});

test('chronology lists the steps that happened, in walker order, with plain labels, durations and invocation ids', () => {
  const run = gateRun();
  const steps = chronology(run, studioNodesFromRun(run));
  assert.deepEqual(
    steps.map((step) => step.id),
    ['requisitions', 'select', 'budget', 'justification', 'discard', 'history', 'derive', 'dossier', 'summarise', 'gate'],
  );
  // Steps not reached (post, reject, audit) are not events yet.
  assert.ok(!steps.some((step) => step.id === 'post' || step.id === 'audit'));
  const budget = steps.find((step) => step.id === 'budget')!;
  assert.equal(budget.labelKey, 'experience.pr_to_po.studio.node.budget');
  assert.equal(budget.technical, 'fi_Validate');
  assert.equal(budget.durationMs, 800);
  assert.equal(budget.invocationId, 'inv-task.budget');
  const derive = steps.find((step) => step.id === 'derive')!;
  assert.equal(derive.technical, 'python_recipe_v1');
  const gate = steps.find((step) => step.id === 'gate')!;
  assert.equal(gate.status, 'waiting');
  assert.equal(gate.durationMs, null, 'the gate span is the human wait');
  assert.equal(gate.invocationId, null);
  const discard = steps.find((step) => step.id === 'discard')!;
  assert.equal(discard.status, 'skipped');
  assert.equal(discard.durationMs, null, 'a skipped branch did no work');
});

test('what the approval triggers is read off the steps still ahead and the Run conditions', () => {
  const run = gateRun();
  const nodes = studioNodesFromRun(run);
  const pr = PR.PurchaseRequisition;
  const sealed = gateConsequences('approve', nodes, { unsealed: false, disabledTools: new Set(), prId: pr });
  assert.deepEqual(sealed.map((item) => item.key.split('.').pop()), ['post_sealed', 'audit']);
  const live = gateConsequences('approve', nodes, { unsealed: true, disabledTools: new Set(), prId: pr });
  assert.deepEqual(live.map((item) => item.key.split('.').pop()), ['post', 'audit']);
  assert.deepEqual(live[0].tools, ['BAPI_PO_CREATE1', 'BAPI_TRANSACTION_COMMIT']);
  const blocked = gateConsequences('approve', nodes, {
    unsealed: true,
    disabledTools: runDisabledTools(gateRun({ input_ref: { disabled_tools: ['BAPI_PO_CREATE1'] } })),
    prId: pr,
  });
  assert.equal(blocked[0].key.split('.').pop(), 'post_blocked');
  assert.equal(blocked[0].tone, 'blocked');
  const refusal = gateConsequences('reject', nodes, { unsealed: true, disabledTools: new Set(), prId: pr });
  assert.deepEqual(refusal.map((item) => item.key.split('.').pop()), ['reject', 'audit']);
  assert.deepEqual(refusal[0].params, { pr });

  // Once the post ran, it is an outcome, not a consequence.
  const posted = nodes.map((node) => (node.id === 'post' ? { ...node, status: 'done' as const } : node));
  assert.deepEqual(
    gateConsequences('approve', posted, { unsealed: true, disabledTools: new Set(), prId: pr }).map((item) => item.step),
    ['audit'],
  );
});

test('what the agent checked comes from completed steps only, with their verdicts', () => {
  const run = gateRun();
  const nodes = studioNodesFromRun(run);
  const checks = gateChecks(run, nodes, proposalFromRun(run), 'fr');
  assert.deepEqual(checks.map((check) => [check.id, check.ok]), [
    ['budget', true],
    ['price', true],
    ['justification', true],
    ['supplier', true],
  ]);
  assert.equal(checks[0].tool, 'fi_Validate');
  assert.equal(checks[1].params['price'], '10,00 QAR');
  assert.deepEqual(checks[3].params, { votes: 5, type: 'ZNPR', plant: '1000' });

  const refused = gateRun({
    skill_invocations: INVOCATIONS.map((row) =>
      row.trace.node_id === 'task.budget'
        ? { ...row, output_ref: { ...row.output_ref, budget_ok: false, reason: 'imputation fermée' } }
        : row),
  } as Partial<Run>);
  const budget = gateChecks(refused, studioNodesFromRun(refused), proposalFromRun(refused))[0];
  assert.equal(budget.ok, false);
  assert.equal(budget.key, 'experience.pr_to_po.studio.receipt.check.budget_ko');
  assert.equal(budget.params['reason'], 'imputation fermée');

  const early = gateRun({ status: 'running', checkpoints: checkpoints({ upTo: 2, gate: false }) });
  assert.deepEqual(gateChecks(early, studioNodesFromRun(early), proposalFromRun(early)).map((check) => check.id), ['price']);
});

test('a refusal requires a reason; blank is not one', () => {
  assert.equal(rejectReasonError(''), 'experience.pr_to_po.studio.gate.reason_required');
  assert.equal(rejectReasonError('   '), 'experience.pr_to_po.studio.gate.reason_required');
  assert.equal(rejectReasonError(null), 'experience.pr_to_po.studio.gate.reason_required');
  assert.equal(rejectReasonError('Fournisseur hors contrat cadre'), null);
});

test('timestamps, durations and system names read as written', () => {
  assert.equal(checkpointTime('2026-09-28T10:00:01.500000'), T0 + 1500, 'naive walker time is UTC');
  assert.equal(checkpointTime('2026-09-28T12:00:00+02:00'), T0);
  assert.equal(checkpointTime('not a time'), null);
  assert.equal(formatReceiptDuration(763, 'fr'), '763 ms');
  assert.equal(formatReceiptDuration(1234, 'fr'), '1,2 s');
  assert.equal(formatReceiptDuration(1234, 'en'), '1.2 s');
  assert.equal(formatReceiptDuration(42_000, 'fr'), '42 s');
  assert.equal(formatReceiptDuration(64_400, 'en'), '1 min 04 s');
  assert.equal(readSystemLabel('sap'), 'SAP');
  assert.equal(readSystemLabel('hikma'), 'Hikma');
});

import assert from 'node:assert/strict';
import test from 'node:test';

import type { Run } from '@app/core/canonical-api.service';
import {
  STUDIO_CHAT_CHIPS,
  STUDIO_DAG_NODE,
  STUDIO_GUARDRAIL_TOOLS,
  STUDIO_NODE_KIND,
  STUDIO_NODE_ORDER,
  callsFromInvocation,
  chatWriteDialogueFromRun,
  dagNodeStates,
  formatStudioAmount,
  gateDecided,
  initialStudioNodes,
  invocationFor,
  nextCandidates,
  openChatWriteDialogue,
  openRowsFromRun,
  postOutcome,
  proposalFromRun,
  runDecision,
  runIsBusy,
  runIsSettled,
  studioFactSheet,
  studioJson,
  studioNodesFromRun,
  studioRunPayload,
  writeOutcomeFromOutput,
} from './pr-to-po-studio';

/**
 * A Run shaped like the live probe of 2026-09-02 (run reached hitl_pending in
 * ~25 s): checkpoints from the walker, invocations with `trace.node_id`, and
 * the HITL package on `hitl.upstream`.
 */
const PR_ROW = {
  PurchaseRequisition: '2000276559',
  PurchaseRequisitionItem: '10',
  PurchaseRequisitionType: 'ZNPR',
  PurchaseRequisitionItemText: 'DE-09-F Desk 140 X 80 X 75 H',
  Material: '100000662363',
  MaterialGroup: 'S125000',
  RequestedQuantity: '61.000',
  BaseUnit: 'NO',
  PurchaseRequisitionPrice: '10.00',
  PurReqnItemCurrency: 'QAR',
  Plant: '1000',
  DeliveryDate: '/Date(1755043200000)/',
};

const OTHER_ROWS = [
  { ...PR_ROW, PurchaseRequisition: '2000276560', PurchaseRequisitionItemText: 'Chair', PurchaseRequisitionPrice: '4.50' },
  { ...PR_ROW, PurchaseRequisition: '2000276561', PurchaseRequisitionItemText: 'Lamp', PurchaseRequisitionPrice: '0.00' },
];

function invocation(nodeId: string, slug: string, output: Record<string, unknown>, extra: Record<string, unknown> = {}) {
  return {
    id: `inv-${nodeId}`,
    skill_slug: slug,
    status: 'completed' as const,
    latency_ms: 120,
    input_ref: { pr_id: '2000276559' },
    output_ref: output,
    trace: { node_id: nodeId },
    ...extra,
  };
}

function checkpointsUpTo(nodeIds: readonly string[], pauseAt = 'hitl.approve_po') {
  const rows: Array<Record<string, unknown>> = [{ kind: 'run_start', nodes: 18 }];
  for (const id of nodeIds) {
    rows.push({ kind: 'node_start', node_id: id, node_kind: id.startsWith('hitl') ? 'hitl' : 'task' });
    if (id === pauseAt) rows.push({ kind: 'node_end', node_id: id, node_kind: 'hitl', pause: true });
    else if (id === 'task.reject') rows.push({ kind: 'node_end', node_id: id, status: 'skipped', skipped_reason: 'all_inputs_dead' });
    else rows.push({ kind: 'node_end', node_id: id, status: 'completed', latency_ms: 120 });
  }
  return rows;
}

const SELECT_OUTPUT = {
  pr_id: '2000276559',
  pr: PR_ROW,
  pr_type: 'ZNPR',
  MaterialGroup: 'S125000',
  Plant: '1000',
  PurchaseRequisitionItem: '10',
  price_missing: false,
  candidates: ['2000276559', '2000276560', '2000276561'],
  total_open: 3,
  prs: [PR_ROW, ...OTHER_ROWS],
  empty: false,
};

const MAJORITY_OUTPUT = {
  supplier: '4000004006',
  format: 'ZLPO',
  vote_count: 5,
  purch_group: '100',
  payment_terms: 'ZAD7',
  incoterms: 'DDP',
  proposed_po: { pr_id: '2000276559', supplier: '4000004006', format: 'ZLPO', currency: 'QAR', pr_type: 'ZNPR' },
  pos: [],
};

function pendingRun(): Run {
  const up = [
    'src',
    'task.list_prs',
    'task.select_pr',
    'decision.has_pr',
    'task.budget',
    'task.justification',
    'decision.budget',
    'task.reject',
    'task.hikma',
    'task.majority',
    'task.format_dossier',
    'task.summarise',
    'hitl.approve_po',
  ];
  return {
    id: 'run-1',
    system_id: 'sys-1',
    status: 'hitl_pending',
    checkpoints: checkpointsUpTo(up),
    hitl: {
      node_id: 'hitl.approve_po',
      decision_id: 'dec-1',
      decision_status: 'proposed',
      upstream: {
        pr: PR_ROW,
        pr_id: '2000276559',
        PurchaseRequisitionItem: '10',
        price_missing: false,
        candidates: ['2000276559', '2000276560', '2000276561'],
        total_open: 3,
        budget: true,
        budget_reason: 'ok',
        vote_count: 5,
        purch_group: '100',
        payment_terms: 'ZAD7',
        incoterms: 'DDP',
        supplier: '4000004006',
        format: 'ZLPO',
        justification_summary: 'Desks for the new finance floor.',
        formatted: '| PR | Supplier |\n| 2000276559 | 4000004006 |',
        proposed_po: MAJORITY_OUTPUT.proposed_po,
      },
    },
    invocations: [
      invocation('task.list_prs', 'sap_list_approved_prs_v1', {
        prs: [PR_ROW, ...OTHER_ROWS],
        ok: true,
        server_id: 'sap',
        tool: 'get_A_PurchaseRequisitionItem',
        contract_tool: 'get_A_PurchaseRequisitionItem',
        credential_source: 'workspace',
        duration_ms: 1235,
      }),
      invocation('task.select_pr', 'python_recipe_v1', SELECT_OUTPUT),
      invocation('task.budget', 'sap_check_budget_v1', {
        pr_id: '2000276559',
        budget_ok: true,
        reason: 'ok',
        ok: true,
        server_id: 'sap',
        tool: 'fi_Validate',
        contract_tool: 'fi_Validate',
        credential_source: 'workspace',
        duration_ms: 763,
      }),
      invocation('task.justification', 'sap_get_justification_v1', {
        pr_id: '2000276559',
        justification: 'Finance floor refresh.',
        ok: true,
        server_id: 'sap',
        tool: 'get_A_PurchaseRequisitionItem_by_key',
        contract_tool: 'get_A_PurchaseRequisitionItem_by_key',
        credential_source: 'workspace',
        duration_ms: 400,
      }),
      invocation('task.hikma', 'hikma_list_pos_by_type_v1', {
        pos: [{}, {}, {}, {}, {}],
        pr_type: 'ZNPR',
        ok: true,
        server_id: 'hikma',
        tool: 'get_A_PurchaseOrder',
        contract_tool: 'get_A_PurchaseOrder',
        credential_source: 'workspace',
        duration_ms: 12619,
      }),
      invocation('task.majority', 'python_recipe_v1', MAJORITY_OUTPUT),
      invocation('task.format_dossier', 'python_recipe_v1', { formatted: '| PR |', recipe_package: 'tabulate' }),
      invocation('task.summarise', 'azure_llm_v1', { completion: 'Desks for the new finance floor.', model: 'gpt-4o-mini' }),
    ],
  } as unknown as Run;
}

const CREATE_ROW = {
  ok: true,
  sealed: false,
  called: true,
  blocked: false,
  kind: 'write',
  server_id: 'bapi_po',
  tool: 'BAPI_PO_CREATE1',
  arguments: { import: { POHEADER: { DOC_TYPE: 'ZLPO', VENDOR: '4000004006' } }, tables: { POITEM: [{ PREQ_NO: '2000276559' }] } },
  sap_ok: true,
  messages: [{ type: 'W', id: '06', number: '219', message: 'Net price adopted' }],
  po_number: '4500382540',
  rolled_back: false,
  duration_ms: 2100,
  result: { export: { EXPHEADER: { PO_NUMBER: '4500382540' } } },
};

const COMMIT_ROW = {
  ...CREATE_ROW,
  tool: 'BAPI_TRANSACTION_COMMIT',
  arguments: { import: { WAIT: 'X' } },
  messages: [],
  po_number: '',
  duration_ms: 300,
  result: { tables: { RETURN: [] } },
};

function completedRun(postOutput: Record<string, unknown>, status: 'completed' | 'failed' = 'completed'): Run {
  const base = pendingRun();
  const checkpoints = [
    ...(base.checkpoints || []),
    { kind: 'hitl_resume', node_id: 'hitl.approve_po', decision_status: 'accepted' },
    { kind: 'node_start', node_id: 'decision.hitl', node_kind: 'decision' },
    { kind: 'node_end', node_id: 'decision.hitl', node_kind: 'decision', chosen_branch: 'approved' },
    { kind: 'node_start', node_id: 'task.create_po', node_kind: 'task', skill_slug: 'sap_create_po_v1' },
    { kind: 'node_end', node_id: 'task.create_po', node_kind: 'task', status: 'completed' },
    { kind: 'node_start', node_id: 'task.handle_rejection', node_kind: 'task' },
    { kind: 'node_end', node_id: 'task.handle_rejection', node_kind: 'task', status: 'skipped', skipped_reason: 'all_inputs_dead' },
    { kind: 'node_start', node_id: 'task.audit', node_kind: 'task' },
    { kind: 'node_end', node_id: 'task.audit', node_kind: 'task', status: 'completed' },
  ];
  return {
    ...base,
    status,
    checkpoints,
    hitl: { ...base.hitl, decision_status: 'accepted' },
    invocations: [
      ...((base as unknown as { invocations: unknown[] }).invocations),
      invocation('task.create_po', 'sap_create_po_v1', postOutput, { input_ref: { pr_id: '2000276559', supplier: '4000004006' } }),
      invocation('task.audit', 'audit_log_v1', { id: 'audit-1', status: 'recorded' }),
    ],
  } as unknown as Run;
}

const LIVE_POST_OUTPUT = {
  ...CREATE_ROW,
  committed: true,
  calls: [CREATE_ROW, COMMIT_ROW],
  contract_tool: 'BAPI_PO_CREATE1',
  credential_source: 'workspace',
  testrun: false,
};

test('the studio node list mirrors the published DAG, one entry per node', () => {
  assert.equal(STUDIO_NODE_ORDER.length, 13);
  assert.equal(STUDIO_NODE_ORDER[0], 'requisitions');
  assert.equal(STUDIO_NODE_ORDER.at(-1), 'audit');
  assert.equal(STUDIO_DAG_NODE.gate, 'hitl.approve_po');
  assert.equal(STUDIO_DAG_NODE.post, 'task.create_po');
  for (const id of STUDIO_NODE_ORDER) {
    assert.ok(STUDIO_DAG_NODE[id].startsWith('task.') || STUDIO_DAG_NODE[id].startsWith('hitl.'));
    assert.ok(STUDIO_NODE_KIND[id]);
  }
  assert.deepEqual(
    STUDIO_NODE_ORDER.filter((id) => STUDIO_NODE_KIND[id] === 'write'),
    ['discard', 'post', 'reject'],
  );
  assert.deepEqual(STUDIO_GUARDRAIL_TOOLS, ['BAPI_PO_CREATE1', 'BAPI_TRANSACTION_COMMIT', 'fi_DiscardFromPurchasing']);
  assert.equal(STUDIO_CHAT_CHIPS.at(-1), 'create');
  assert.equal(initialStudioNodes().every((node) => node.status === 'idle' && node.calls.length === 0), true);
});

test('the launch payload carries only known guardrails and an optional pin', () => {
  assert.deepEqual(studioRunPayload(new Set()), { disabled_tools: [] });
  assert.deepEqual(
    studioRunPayload(new Set(['BAPI_PO_CREATE1', 'not_a_guardrail']), ' 2000276560 '),
    { disabled_tools: ['BAPI_PO_CREATE1'], pr_id: '2000276560' },
  );
});

test('a paused run projects to running-until-the-gate with the server calls verbatim', () => {
  const run = pendingRun();
  const nodes = studioNodesFromRun(run);
  const byId = new Map(nodes.map((node) => [node.id, node]));
  assert.equal(byId.get('requisitions')?.status, 'done');
  assert.deepEqual(byId.get('requisitions')?.noteParams, { shown: 3, total: 3 });
  assert.equal(byId.get('select')?.noteKey, 'experience.pr_to_po.studio.note.select');
  assert.equal(byId.get('budget')?.status, 'done');
  assert.equal(byId.get('discard')?.status, 'skipped');
  assert.equal(byId.get('gate')?.status, 'waiting');
  assert.equal(byId.get('post')?.status, 'idle');
  assert.equal(byId.get('audit')?.status, 'idle');
  const budgetCall = byId.get('budget')?.calls[0];
  assert.equal(budgetCall?.server, 'sap');
  assert.equal(budgetCall?.tool, 'fi_Validate');
  assert.equal(budgetCall?.write, false);
  assert.equal(budgetCall?.durationMs, 763);
  assert.deepEqual(budgetCall?.request, { pr_id: '2000276559' });
  const recipe = byId.get('derive')?.calls[0];
  assert.equal(recipe?.server, 'agentium');
  assert.equal(recipe?.tool, 'python_recipe_v1');
  assert.equal(byId.get('history')?.noteParams['count'], 5);
  assert.equal(byId.get('derive')?.noteParams['supplier'], '4000004006');
});

test('a failed node reads as error with the walker message, not a silent skip', () => {
  const run = pendingRun();
  const checkpoints = (run.checkpoints || []).map((row) =>
    row['node_id'] === 'task.justification' && row['kind'] === 'node_end'
      ? { ...row, status: 'failed', error: 'named MCP skills do not accept tool, sql, or server_id' }
      : row,
  );
  const failed = { ...run, checkpoints } as Run;
  const node = studioNodesFromRun(failed).find((row) => row.id === 'justification');
  assert.equal(node?.status, 'error');
  assert.match(node?.error || '', /named MCP skills/);
  assert.equal(dagNodeStates(failed).get('task.justification')?.status, 'failed');
});

test('the gate package comes from hitl.upstream and names every source', () => {
  const proposal = proposalFromRun(pendingRun());
  assert.ok(proposal);
  assert.equal(proposal.runId, 'run-1');
  assert.equal(proposal.prId, '2000276559');
  assert.equal(proposal.item, '10');
  assert.equal(proposal.label, 'DE-09-F Desk 140 X 80 X 75 H');
  assert.equal(proposal.quantity, '61.000');
  assert.equal(proposal.netPrice, '10.00');
  assert.equal(proposal.priceMissing, false);
  assert.equal(proposal.amount, 610);
  assert.equal(formatStudioAmount(proposal.amount, proposal.currency), '610.00 QAR');
  assert.equal(proposal.supplier, '4000004006');
  assert.equal(proposal.paymentTerms, 'ZAD7');
  assert.equal(proposal.incoterms, 'DDP');
  assert.equal(proposal.format, 'ZLPO');
  assert.equal(proposal.budgetOk, true);
  assert.equal(proposal.voteCount, 5);
  assert.equal(proposal.justification, 'Desks for the new finance floor.');
  assert.deepEqual(proposal.candidates, ['2000276559', '2000276560', '2000276561']);
  assert.deepEqual(nextCandidates(proposal), ['2000276560', '2000276561']);
  const fields = proposal.provenance.map((row) => row.field);
  assert.deepEqual(fields, ['supplier', 'purch_org', 'currency', 'payment_terms', 'delivery_date', 'net_price']);
  assert.equal(proposal.provenance[0].sourceParams['votes'], 5);
  assert.equal(proposal.provenance.at(-1)?.sourceKey, 'experience.pr_to_po.studio.provenance.price');
});

test('a zero-price package is flagged the way SAP will refuse it (06/215)', () => {
  const run = pendingRun();
  const upstream = { ...(run.hitl?.upstream || {}), price_missing: true, pr: { ...PR_ROW, PurchaseRequisitionPrice: '0.00' } };
  const proposal = proposalFromRun({ ...run, hitl: { ...run.hitl, upstream } } as Run);
  assert.equal(proposal?.priceMissing, true);
  assert.equal(proposal?.amount, 0);
  assert.equal(proposal?.provenance.at(-1)?.sourceKey, 'experience.pr_to_po.studio.provenance.price_missing');
});

test('settled, busy and decided follow the HITL decision, not only the run status', () => {
  const pending = pendingRun();
  assert.equal(runIsSettled(pending), true);
  assert.equal(runIsBusy(pending), false);
  assert.equal(gateDecided(pending), false);
  assert.equal(runDecision(pending), 'pending');
  // The HITL endpoint answers before the background resume flips the status.
  const decided = { ...pending, hitl: { ...pending.hitl, decision_status: 'accepted' } } as Run;
  assert.equal(gateDecided(decided), true);
  assert.equal(runIsSettled(decided), false);
  assert.equal(runIsBusy(decided), true);
  assert.equal(runDecision(decided), 'approved');
  assert.equal(runIsSettled({ ...pending, status: 'running' } as Run), false);
  assert.equal(runIsSettled({ ...pending, status: 'completed' } as Run), true);
});

test('an approved run shows the create + commit pair and the PO number from the gate envelope', () => {
  const run = completedRun(LIVE_POST_OUTPUT);
  assert.equal(runDecision(run), 'approved');
  const outcome = postOutcome(run);
  assert.deepEqual(outcome, {
    sealed: false,
    called: true,
    blocked: false,
    sapOk: true,
    committed: true,
    poNumber: '4500382540',
    rolledBack: false,
    messages: ['W: Net price adopted'],
  });
  const nodes = studioNodesFromRun(run);
  const post = nodes.find((node) => node.id === 'post');
  assert.equal(post?.status, 'done');
  assert.equal(post?.noteKey, 'experience.pr_to_po.studio.note.post_done');
  assert.equal(post?.noteParams['pos'], '4500382540');
  assert.deepEqual(post?.calls.map((call) => call.tool), ['BAPI_PO_CREATE1', 'BAPI_TRANSACTION_COMMIT']);
  assert.deepEqual(post?.calls[1].request, { import: { WAIT: 'X' } });
  assert.equal(post?.calls.every((call) => call.write && call.ok && !call.sealed && !call.blocked), true);
  assert.equal(nodes.find((node) => node.id === 'reject')?.status, 'skipped');
  assert.equal(nodes.find((node) => node.id === 'gate')?.status, 'done');
  assert.equal(nodes.find((node) => node.id === 'audit')?.status, 'done');
});

test('sealed, blocked and refused writes keep their own verdicts', () => {
  const sealed = writeOutcomeFromOutput({
    sealed: true,
    called: false,
    tool: 'BAPI_PO_CREATE1',
    sap_block: 'sap_write_unsealed is off',
    result: { sealed: true, called: false, arguments: { import: {} } },
  });
  assert.equal(sealed?.sealed, true);
  assert.equal(sealed?.committed, false);
  const blocked = writeOutcomeFromOutput({ blocked: true, called: false, sealed: false, reason: 'guardrail_disabled' });
  assert.equal(blocked?.blocked, true);
  const refused = writeOutcomeFromOutput({
    called: true,
    sealed: false,
    sap_ok: false,
    rolled_back: true,
    messages: [{ type: 'E', id: '06', number: '215', message: 'Please enter net price' }],
  });
  assert.equal(refused?.sapOk, false);
  assert.equal(refused?.rolledBack, true);
  assert.deepEqual(refused?.messages, ['E: Please enter net price']);
  assert.equal(writeOutcomeFromOutput({}), null);
  const sealedRun = completedRun({ ...sealed, server_id: 'bapi_po' } as unknown as Record<string, unknown>);
  const post = studioNodesFromRun(sealedRun).find((node) => node.id === 'post');
  assert.equal(post?.status, 'done');
  assert.equal(post?.noteKey, 'experience.pr_to_po.studio.note.post_sealed');
  assert.equal(post?.calls[0].sealed, true);
  const blockedRun = completedRun({ ...blocked, server_id: 'bapi_po', tool: 'BAPI_PO_CREATE1' } as unknown as Record<string, unknown>);
  assert.equal(studioNodesFromRun(blockedRun).find((node) => node.id === 'post')?.status, 'warn');
  const refusedRun = completedRun({ ...refused, server_id: 'bapi_po', tool: 'BAPI_PO_CREATE1', sap_ok: false, called: true, rolled_back: true } as unknown as Record<string, unknown>);
  assert.equal(studioNodesFromRun(refusedRun).find((node) => node.id === 'post')?.status, 'error');
});

test('the chat fact sheet is the run: open rows, majority terms, budget, proposal state', () => {
  const run = pendingRun();
  assert.equal(openRowsFromRun(run).length, 3);
  const facts = studioFactSheet(run);
  assert.match(facts, /open approved ZNPR requisition items: 3 \(showing 3\)/);
  assert.match(facts, /PR 2000276559\/10 "DE-09-F Desk 140 X 80 X 75 H" — 61\.000 NO × 10\.00 QAR, plant 1000/);
  assert.match(facts, /majority of 5 recent orders: supplier 4000004006, terms ZAD7, incoterms DDP, group 100/);
  assert.match(facts, /budget check on PR 2000276559: ok/);
  assert.match(facts, /610\.00 QAR to supplier 4000004006 type ZLPO \(waiting for the human gate\)/);
  assert.match(facts, /next candidates: 2000276559, 2000276560, 2000276561/);
  assert.match(studioFactSheet(completedRun(LIVE_POST_OUTPUT)), /posted as PO 4500382540/);
  assert.equal(studioFactSheet(null), '');
});

test('the chat write dialogue follows the run: preparing → proposing → posting → posted', () => {
  let dialogue = openChatWriteDialogue('', null);
  assert.equal(dialogue.stage, 'preparing');
  const running = { ...pendingRun(), status: 'running', hitl: undefined } as Run;
  dialogue = chatWriteDialogueFromRun({ ...dialogue, runId: 'run-1' }, running);
  assert.equal(dialogue.stage, 'preparing');
  dialogue = chatWriteDialogueFromRun(dialogue, pendingRun());
  assert.equal(dialogue.stage, 'proposing');
  assert.equal(dialogue.proposal?.prId, '2000276559');
  // Human said yes: stays posting while the gate is decided but not resumed.
  dialogue = { ...dialogue, stage: 'posting' };
  const decided = { ...pendingRun(), hitl: { ...pendingRun().hitl, decision_status: 'accepted' } } as Run;
  assert.equal(chatWriteDialogueFromRun(dialogue, decided).stage, 'posting');
  const done = chatWriteDialogueFromRun(dialogue, completedRun(LIVE_POST_OUTPUT));
  assert.equal(done.stage, 'posted');
  assert.equal(done.outcome?.poNumber, '4500382540');
  assert.equal(done.calls.length, 2);
  // A cancelled dialogue never advances, whatever the run does.
  const cancelled = chatWriteDialogueFromRun({ ...dialogue, stage: 'cancelled' }, completedRun(LIVE_POST_OUTPUT));
  assert.equal(cancelled.stage, 'cancelled');
  // Another run's updates are ignored.
  assert.equal(chatWriteDialogueFromRun(dialogue, { ...completedRun(LIVE_POST_OUTPUT), id: 'run-2' } as Run).stage, 'posting');
  // A run that ended without a write is a failure with the walker's reason.
  const noWrite = completedRun(LIVE_POST_OUTPUT);
  const failedRun = { ...noWrite, status: 'failed', error: 'membrane_egress_block', invocations: (noWrite as unknown as { invocations: unknown[] }).invocations.slice(0, 8) } as unknown as Run;
  const failed = chatWriteDialogueFromRun(dialogue, failedRun);
  assert.equal(failed.stage, 'failed');
  assert.deepEqual(failed.outcome?.messages, ['membrane_egress_block']);
});

test('invocation lookup takes the latest row for a node and calls are verbatim JSON', () => {
  const run = completedRun(LIVE_POST_OUTPUT);
  assert.equal(invocationFor(run, 'task.create_po')?.skill_slug, 'sap_create_po_v1');
  assert.equal(invocationFor(run, 'task.nowhere'), null);
  assert.equal(callsFromInvocation(null, 'read').length, 0);
  const text = studioJson({ a: 'x'.repeat(5000) });
  assert.match(text, /chars truncated\)$/);
  assert.equal(studioJson({ ok: true }), '{\n  "ok": true\n}');
});

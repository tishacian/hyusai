import assert from 'node:assert/strict';
import test from 'node:test';

import type { DeskPreview, RecentPoTerms } from './pr-to-po-desk';
import {
  STUDIO_CHAT_CHIPS,
  STUDIO_GUARDRAIL_TOOLS,
  STUDIO_NODE_KIND,
  STUDIO_NODE_ORDER,
  STUDIO_PROPOSAL_CAP,
  STUDIO_WRITE_SERVERS,
  bapiCommitInvokeBody,
  bapiCreateInvokeBody,
  blockedCall,
  buildStudioProposal,
  discardInvokeBody,
  formatStudioAmount,
  guardrailBlocked,
  initialStudioNodes,
  openPrRowsFromPreview,
  outcomeFromInvoke,
  proposalsTotal,
  studioCallFromInvoke,
  studioJson,
  studioPlants,
} from './pr-to-po-studio';

const TERMS: RecentPoTerms = {
  supplier: '1000000018',
  purchGroup: '013',
  paymentTerms: 'ZAPS',
  incoterms: 'DDP',
};

const PR_PREVIEW: DeskPreview = {
  ok: true,
  tool: 'get_A_PurchaseRequisitionItem',
  columns: [
    'PurchaseRequisition',
    'PurchaseRequisitionItem',
    'PurchaseRequisitionItemText',
    'MaterialGroup',
    'RequestedQuantity',
    'OrderedQuantity',
    'BaseUnit',
    'PurchaseRequisitionPrice',
    'PurReqnItemCurrency',
    'Plant',
    'DeliveryDate',
    'PurchaseRequisitionType',
  ],
  rows: [
    ['2000276449', '00020', 'PAPER BAG', 'E032700', '20', '0', 'EA', '4.50', 'QAR', '1000', '20261123', 'ZNPR'],
    ['2000276449', '00030', 'STICKER', 'E032701', '5', '0', 'EA', '2.00', 'QAR', '1000', '20261123', 'ZNPR'],
    ['2000276451', '00010', 'THERMAL ROLL', 'G111190', '40', '0', 'SHT', '954.00', 'QAR', '1000', '20261123', 'ZNPR'],
    ['2000276452', '00010', 'LORX CLEANER', 'G111191', '10', '10', 'EA', '30.00', 'QAR', '2100', '20261123', 'ZNPR'],
    ['2000276453', '00010', 'ARABIC BREAD', 'G111192', '8', '0', 'EA', '12050.00', 'QAR', '2100', '20261123', 'ZNPR'],
  ],
  row_count: 8482,
};

test('the run flow has ten nodes in the demo order, gate before the writes', () => {
  assert.deepEqual(STUDIO_NODE_ORDER, [
    'requisitions',
    'budget',
    'discard',
    'summarise',
    'history',
    'derive',
    'proposal',
    'gate',
    'post',
    'reject',
  ]);
  const nodes = initialStudioNodes();
  assert.equal(nodes.length, 10);
  assert.ok(nodes.every((node) => node.status === 'idle' && node.calls.length === 0));
  assert.equal(STUDIO_NODE_KIND.post, 'write');
  assert.equal(STUDIO_NODE_KIND.discard, 'write');
  assert.equal(STUDIO_NODE_KIND.reject, 'write');
  assert.equal(STUDIO_NODE_KIND.gate, 'gate');
  assert.equal(STUDIO_NODE_KIND.requisitions, 'read');
});

test('proposals pick distinct open PRs, skip consumed items, cap at three', () => {
  const rows = openPrRowsFromPreview(PR_PREVIEW);
  assert.equal(rows.length, STUDIO_PROPOSAL_CAP);
  assert.deepEqual(
    rows.map((row) => row.pr_id),
    ['2000276449', '2000276451', '2000276453'],
  );
  // 2000276452 is fully ordered (20/20 would be, here 10/10) — skipped.
  assert.ok(!rows.some((row) => row.pr_id === '2000276452'));
  assert.equal(rows[0].item, '00020');
  assert.equal(rows[0].label, 'PAPER BAG');
  assert.deepEqual(studioPlants(rows), ['1000', '2100']);
});

test('a proposal carries the sealed BAPI body, provenance and the amount', () => {
  const fields = openPrRowsFromPreview(PR_PREVIEW)[0];
  const proposal = buildStudioProposal(fields, TERMS, '4500382504');
  assert.equal(proposal.prId, '2000276449');
  assert.equal(proposal.supplier, '1000000018');
  assert.equal(proposal.amount, 90);
  assert.equal(proposal.decision, 'pending');
  assert.ok(proposal.post);
  const importBlock = proposal.post!.requestBody['import'] as Record<string, unknown>;
  const tables = proposal.post!.requestBody['tables'] as Record<string, unknown>;
  const header = importBlock['POHEADER'] as Record<string, string>;
  assert.equal(header['DOC_TYPE'], 'ZLPO');
  assert.equal(header['PURCH_ORG'], '1000');
  assert.equal(header['COMP_CODE'], '1000');
  assert.equal(header['INCOTERMS2L'], 'Doha');
  const item = (tables['POITEM'] as Array<Record<string, string>>)[0];
  assert.equal(item['PREQ_NO'], '2000276449');
  assert.equal(item['PREQ_ITEM'], '00020');
  assert.ok(!('TESTRUN' in proposal.post!.requestBody));
  const supplierRow = proposal.provenance.find((row) => row.field === 'supplier');
  assert.equal(supplierRow?.sourceParams['po'], '4500382504');
  const orgRow = proposal.provenance.find((row) => row.field === 'purch_org');
  assert.equal(orgRow?.value, '1000');
  assert.equal(
    formatStudioAmount(proposalsTotal([proposal, proposal]), 'QAR'),
    '180.00 QAR',
  );
});

test('write bodies: create from the sealed post, commit WAIT=X, discard unpadded', () => {
  const fields = openPrRowsFromPreview(PR_PREVIEW)[0];
  const proposal = buildStudioProposal(fields, TERMS);
  const create = bapiCreateInvokeBody(proposal.post!);
  assert.equal(create.tool, 'BAPI_PO_CREATE1');
  assert.ok('tables' in create.arguments);
  const commit = bapiCommitInvokeBody();
  assert.equal(commit.tool, 'BAPI_TRANSACTION_COMMIT');
  assert.deepEqual(commit.arguments, { import: { WAIT: 'X' } });
  const discard = discardInvokeBody('2000276453', '00010');
  assert.equal(discard.tool, 'fi_DiscardFromPurchasing');
  assert.equal(discard.arguments.PurchaseRequisitionItem, '10');
  assert.equal(STUDIO_WRITE_SERVERS['BAPI_PO_CREATE1'], 'bapi_po');
  assert.equal(STUDIO_WRITE_SERVERS['fi_DiscardFromPurchasing'], 'sap');
});

test('the guardrail blocks before the network and the transcript says so', () => {
  const disabled = new Set(['BAPI_PO_CREATE1']);
  assert.equal(guardrailBlocked('BAPI_PO_CREATE1', disabled), true);
  assert.equal(guardrailBlocked('BAPI_TRANSACTION_COMMIT', disabled), false);
  assert.deepEqual(STUDIO_GUARDRAIL_TOOLS, [
    'BAPI_PO_CREATE1',
    'BAPI_TRANSACTION_COMMIT',
    'fi_DiscardFromPurchasing',
  ]);
  const call = blockedCall('bapi_po', 'BAPI_PO_CREATE1', { tool: 'BAPI_PO_CREATE1' });
  assert.equal(call.blocked, true);
  assert.equal(call.ok, false);
  assert.match(studioJson(call.response), /guardrail_disabled/);
});

test('invoke outcomes: sealed envelope, live success, live SAP error', () => {
  const sealed = outcomeFromInvoke({ sealed: true, called: false });
  assert.equal(sealed.sealed, true);
  assert.equal(sealed.called, false);
  const live = outcomeFromInvoke({
    sealed: false,
    called: true,
    sap_ok: true,
    po_number: '4500382517',
    messages: [{ type: 'W', message: 'Net price adopted from last document' }],
  });
  assert.equal(live.sapOk, true);
  assert.equal(live.poNumber, '4500382517');
  assert.match(live.messages[0], /^W: Net price/);
  const failed = outcomeFromInvoke({
    sealed: false,
    called: true,
    sap_ok: false,
    rolled_back: true,
    messages: [{ type: 'E', message: 'Supplier blocked for purchasing organization 1000' }],
  });
  assert.equal(failed.sapOk, false);
  assert.equal(failed.rolledBack, true);
  const call = studioCallFromInvoke('bapi_po', 'BAPI_PO_CREATE1', {}, { sealed: true, called: false });
  assert.equal(call.sealed, true);
  assert.equal(call.ok, true);
  const failedCall = studioCallFromInvoke('bapi_po', 'BAPI_PO_CREATE1', {}, {
    sealed: false,
    called: true,
    sap_ok: false,
  });
  assert.equal(failedCall.ok, false);
});

test('chat chips follow the demo scenario order', () => {
  assert.deepEqual(STUDIO_CHAT_CHIPS, [
    'open_prs',
    'suppliers',
    'why_rejected',
    'would_post',
    'sealed',
  ]);
});

test('studioJson stays verbatim below the cap and says how much was cut above it', () => {
  assert.equal(studioJson({ a: 1 }), '{\n  "a": 1\n}');
  const big = studioJson({ blob: 'x'.repeat(5000) });
  assert.match(big, /chars truncated/);
});

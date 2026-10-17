import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import { claimRunProjection, recordedClaimActions, type ClaimProposal, type ClaimSnapshot } from './claim-run';
import type { Run } from '@app/core/canonical-api.service';

test('only completed claim tools produce financial proposals', () => {
  const run = { id: 'r1', status: 'running', skill_invocations: [
    { id: 'i1', skill_slug: 'decide_next_v1', status: 'completed', output_ref: { action: 'refund', amount: '420' } },
    { id: 'i2', skill_slug: 'ecommerce_resolution_propose_v1', status: 'failed', output_ref: { evidence_kind: 'synthetic_demo', claim_id: 'RC-1042', action: 'refund' } },
  ] } as unknown as Run;
  assert.equal(claimRunProjection(run).proposal, null);
  assert.equal(claimRunProjection(run).steps.length, 1);
});

test('the actual receipt replaces its proposal and retains real citations', () => {
  const proposal = { evidence_kind: 'synthetic_demo', claim_id: 'RC-1043', action: 'refund', citations: [{ document_id: 'real-doc' }] };
  const receipt = { ...proposal, receipt_id: 'real-receipt', status: 'simulated' };
  const run = { skill_invocations: [
    { id: 'i1', skill_slug: 'ecommerce_resolution_propose_v1', status: 'completed', output_ref: proposal },
    { id: 'i2', skill_slug: 'ecommerce_resolution_simulate_v1', status: 'completed', output_ref: receipt },
  ] } as unknown as Run;
  assert.equal(claimRunProjection(run).proposal?.receipt_id, 'real-receipt');
  assert.deepEqual(claimRunProjection(run).proposal?.citations, [{ document_id: 'real-doc' }]);
});

test('recorded actions require settled evidence for the selected order and deduplicate the current run', () => {
  const receipt = { claim_id: 'claim-1', order_id: 'order-1', action: 'refund', evidence_kind: 'synthetic_demo',
    receipt_id: 'receipt-1', status: 'simulated' } as ClaimProposal;
  const snapshot = { data: { context: [{ order_id: 'order-1' }] }, receipts: [
    { ...receipt, receipt_id: 'older-action', claim_id: 'earlier-claim', action: 'carrier_investigation' },
    receipt,
    { ...receipt, receipt_id: 'different-order', order_id: 'order-2' },
    { ...receipt, receipt_id: 'unsettled', status: 'pending' },
    { ...receipt, receipt_id: '', action: 'request_information' },
  ] } as ClaimSnapshot;
  assert.deepEqual(recordedClaimActions(snapshot, receipt).map(r => r.receipt_id), ['receipt-1', 'older-action']);
  assert.deepEqual(recordedClaimActions(snapshot, { ...receipt, receipt_id: undefined }).map(r => r.receipt_id), ['receipt-1', 'older-action']);
  assert.deepEqual(recordedClaimActions(null, receipt), []);
});

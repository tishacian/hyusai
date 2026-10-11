import assert from 'node:assert/strict';
import { test } from 'node:test';
import { summarizeAutomationRun } from './automation-turn';

test('a retrieve cites a passage or says there is none', () => {
  assert.deepEqual(
    summarizeAutomationRun({
      status: 'completed',
      skill_invocations: [{
        skill_slug: 'semantic_search_v1',
        output_ref: { passage: 'The laptop request is approved.', source: 'doc-1' },
      }],
    }),
    { kind: 'retrieve', passage: 'The laptop request is approved.', source: 'doc-1' },
  );
  assert.deepEqual(
    summarizeAutomationRun({
      status: 'completed',
      skill_invocations: [{ skill_slug: 'semantic_search_v1', output_ref: { results: [] } }],
    }),
    { kind: 'retrieve', passage: null, source: null },
  );
});

test('a SAP write without approval stays sealed', () => {
  assert.deepEqual(
    summarizeAutomationRun({
      status: 'completed',
      skill_invocations: [{
        skill_slug: 'sap_create_po_v1',
        output_ref: { sealed: true, called: false },
      }],
    }),
    { kind: 'sap_write', sealed: true, called: false },
  );
});

test('an approval pause is the result shown on the turn', () => {
  const summary = summarizeAutomationRun({
    status: 'hitl_pending',
    checkpoints: [{ kind: 'hitl_pause', prompt: 'Approve this step?', decision_id: 'd1' }],
    skill_invocations: [{
      skill_slug: 'sap_create_po_v1',
      output_ref: { sealed: true, called: false },
    }],
  });
  assert.equal(summary.kind, 'approval_pause');
  assert.equal(summary.decision_id, 'd1');
});

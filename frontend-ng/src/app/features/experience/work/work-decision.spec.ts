import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { Run } from '@app/core/canonical-api.service';
import { workDecisionAvailable, workDecisionDate, workDecisionKey, workDecisionRows } from './work-decision';

const pending: Run = {id:'run-1',system_id:'system-1',status:'hitl_pending',flow_sha256:'version-1',
  hitl:{decision_id:'decision-1',decision_status:'proposed',prompt:'Share this dossier',
    expires_at:'2026-09-17T10:00:00Z',upstream:{recipient:'maintenance',document:{version:3}}}};

test('a review belongs to its decision, document and version, not a reused Run ID', () => {
  for (const updated of [
    {...pending, flow_sha256:'version-2'},
    {...pending, hitl:{...pending.hitl, decision_id:'decision-2'}},
    {...pending, hitl:{...pending.hitl, upstream:{recipient:'another team',document:{version:3}}}},
    {...pending, hitl:{...pending.hitl, upstream:{recipient:'maintenance',document:{version:4}}}},
  ]) assert.notEqual(workDecisionKey(pending), workDecisionKey(updated));
  assert.equal(workDecisionKey(pending), workDecisionKey({...pending, hitl:{...pending.hitl, seconds_remaining:5}}));
});

test('missing, expired, malformed, decided or resumed gates cannot be accepted', () => {
  const now = Date.parse('2026-09-17T09:59:00Z');
  assert.equal(workDecisionAvailable(pending, now), true);
  assert.equal(workDecisionAvailable(pending, Date.parse('2026-09-17T10:00:00Z')), false);
  for (const gate of [
    {...pending, status:'running' as const},
    {...pending, hitl:{...pending.hitl, decision_id:undefined}},
    {...pending, hitl:{...pending.hitl, decision_status:'accepted'}},
    {...pending, hitl:{...pending.hitl, decision_status:null}},
    {...pending, hitl:{...pending.hitl, expires_at:'not a date'}},
  ]) assert.equal(workDecisionAvailable(gate, now), false);
  assert.equal(workDecisionAvailable({...pending,hitl:{...pending.hitl,expires_at:null}}, now), true);
});

test('review shows only the authorised gate payload, never Run input/output fallbacks', () => {
  assert.deepEqual(workDecisionRows({...pending,hitl:undefined,input_ref:{secret:'hidden'},output_ref:{held:'hidden'}}), []);
  assert.deepEqual(workDecisionRows(pending), [
    {label:'recipient',value:'maintenance'}, {label:'document',value:'{"version":3}'},
  ]);
});

test('legacy UTC gate deadlines are not shifted by the viewer timezone', () => {
  assert.equal(workDecisionDate('2026-09-17T10:00:00').getTime(), Date.parse('2026-09-17T10:00:00Z'));
  assert.equal(workDecisionDate('2026-09-17T12:00:00+02:00').getTime(), Date.parse('2026-09-17T10:00:00Z'));
  assert.equal(workDecisionAvailable({...pending, hitl: {...pending.hitl, expires_at:'2026-09-17T10:00:00'}}, Date.parse('2026-09-17T09:59:00Z')), true);
});

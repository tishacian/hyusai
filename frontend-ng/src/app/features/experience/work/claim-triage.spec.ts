import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import type { Run } from '@app/core/canonical-api.service';
import type { ClaimRow } from './claim-run';
import { freshTriage, queueByPriority, selectedAdvice, type ClaimTriage } from './claim-triage';

const now = Date.parse('2026-10-06T20:00:00Z');
const triage: ClaimTriage = {
  status: 'ready', captured_at: new Date(now).toISOString(), rows: [
    { claim_id: 'RC-1042', risk: 0.82, priority: 'high' },
    { claim_id: 'RC-1043', risk: 0.16, priority: 'low' },
  ], model: { id: 'sla-model', version: 1, name: 'SLA' },
};

test('predictive ordering has a business effect and manual sessions retain the original order', () => {
  const rows = [{ claim_id: 'RC-1043' }, { claim_id: 'RC-1042' }] as ClaimRow[];
  assert.deepEqual(queueByPriority(rows, triage, false).map(r => r.claim_id), ['RC-1042', 'RC-1043']);
  assert.equal(queueByPriority(rows, triage, true), rows);
  assert.equal(selectedAdvice(triage, null, 'RC-1042', true, now), null);
  assert.equal(queueByPriority(rows, { ...triage, status: 'stale' }, false), rows);
  assert.equal(freshTriage(triage, now + 3600001)?.status, 'stale');
});

test('confidence in the non-late class cannot become high SLA risk', () => {
  const run = { input_ref: { claim_id: 'RC-1043' }, skill_invocations: [{
    skill_slug: 'ml_predict_v1', status: 'completed', completed_at: new Date(now).toISOString(),
    output_ref: { served: { model_id: 'sla-model', version: 1 }, positive_label: '1', target: 'resolution_over_72h',
                  prediction: '0', confidence: 0.99, score: 0.01 },
  }] } as unknown as Run;
  assert.equal(selectedAdvice(triage, run, 'RC-1043', false, now)?.risk, 0.01);
  assert.equal(selectedAdvice(triage, run, 'RC-1043', false, now)?.priority, 'low');
  run.skill_invocations![0].output_ref!['served'] = { model_id: 'foreign-model', version: 1 };
  assert.equal(selectedAdvice(triage, run, 'RC-1043', false, now)?.risk, 0.16);
  assert.equal(selectedAdvice({ ...triage, status: 'stale' }, run, 'RC-1043', false, now), null);
});

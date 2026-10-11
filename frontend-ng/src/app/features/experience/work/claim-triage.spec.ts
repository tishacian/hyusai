import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import type { Run } from '@app/core/canonical-api.service';
import type { ClaimRow } from './claim-run';
import { caseDatasets, freshTriage, queueByPriority, selectedAdvice, type ClaimTriage } from './claim-triage';

const now = Date.parse('2026-10-06T20:00:00Z');
const triage: ClaimTriage = {
  prediction_contract: {
    schema_version: 1, model_id: 'sla-model', model_version: 1, task: 'classification',
    target: 'resolution_over_72h', positive_label: '1', label: 'SLA', unit: 'probability',
    value_column: 'prediction', score_column: 'score_1', max_age_seconds: 3600,
    order: 'descending', bands: [{ key: 'low', label: 'Low', min: 0 }, { key: 'medium', label: 'Medium', min: .35 }, { key: 'high', label: 'High', min: .6 }],
  },
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

test('a composed inquiry exposes only its own fresh, pinned-model dataset artifacts', () => {
  const output = {
    claim_id: 'RC-1042', served: { model_id: 'sla-model', version: 1 }, positive_label: '1',
    target: 'resolution_over_72h', score: 0.7,
    prepared_dataset: { id: 'case-prepared', name: 'Prepared', version: 2, rows: 1 },
    scored_dataset: { id: 'case-score', name: 'Scored', version: 2, rows: 1 },
  };
  const run = { input_ref: { claim_id: 'RC-1042' }, skill_invocations: [{
    skill_slug: 'ecommerce_sav_context_v1', status: 'completed', completed_at: new Date(now).toISOString(), output_ref: output,
  }] } as unknown as Run;
  assert.equal(selectedAdvice(triage, run, 'RC-1042', false, now)?.risk, 0.7);
  assert.equal(caseDatasets(triage, run, 'RC-1042', false, now)?.prepared.id, 'case-prepared');
  assert.equal(caseDatasets(triage, run, 'RC-1042', true, now), null);
  assert.equal(caseDatasets(triage, run, 'RC-1043', false, now), null);
  assert.equal(caseDatasets(triage, run, 'RC-1042', false, now + 3600001), null);
  output.scored_dataset.rows = 23;
  assert.equal(caseDatasets(triage, run, 'RC-1042', false, now), null);
  output.scored_dataset.rows = 1;
  output.served.version = 2;
  assert.equal(caseDatasets(triage, run, 'RC-1042', false, now), null);
  assert.equal(selectedAdvice(triage, run, 'RC-1042', false, now)?.risk, 0.82);
});

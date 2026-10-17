import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { Run } from '@app/core/canonical-api.service';
import { runQualityReviews } from './run-quality-review';

const output = { schema_version: 2, evaluation_id: 'evaluation-1', status: 'partial', quality_status: 'unassessed', coverage: {}, answers: {
  policy: { status: 'abstained', value: null, reason: 'insufficient_evidence', explanation: 'Policy missing', evidence: [], confidence: null },
}, confidence: null, disposition: 'review' };
const run = (status: string, invocationStatus: string, outputRef: unknown = output) => ({ status, skill_invocations: [{ id: 'call-1', skill_slug: 'evaluate_v2', status: invocationStatus, output_ref: outputRef }] }) as unknown as Run;

test('shows typed abstention without converting it to a score or approval', () => {
  const review = runQualityReviews(run('hitl_pending', 'completed'))[0];
  assert.equal(review.state, 'result');
  assert.equal(review.result?.answers['policy'].value, null);
  assert.equal(review.result?.disposition, 'review');
  assert.equal(review.result?.confidence, null);
});

test('pending, failed and malformed evaluations remain distinct and hide raw errors', () => {
  assert.equal(runQualityReviews(run('running', 'running'))[0].state, 'pending');
  assert.equal(runQualityReviews(run('failed', 'running'))[0].state, 'unavailable');
  assert.equal(runQualityReviews(run('hitl_pending', 'failed'))[0].result, null);
  assert.equal(runQualityReviews(run('hitl_pending', 'completed', { error: 'private-diagnostic' }))[0].state, 'unavailable');
  assert.equal(runQualityReviews(run('hitl_pending', 'completed', { composite_score: 99 }))[0].result, null);
});

test('no quality result is invented when no v2 invocation exists', () => {
  assert.deepEqual(runQualityReviews(null), []);
  assert.deepEqual(runQualityReviews({ skill_invocations: [{ skill_slug: 'evaluate_v1', status: 'completed', output_ref: { composite_score: 100 } }] } as unknown as Run), []);
});

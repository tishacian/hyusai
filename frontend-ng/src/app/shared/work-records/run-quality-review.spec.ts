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

test('two evaluations retain distinct recorded engines and invocation identities', () => {
  const reviews = runQualityReviews({id: 'run-1', status: 'hitl_pending', skill_invocations: [
    { id: 'jev-call', skill_slug: 'evaluate_v2', status: 'completed', output_ref: output,
      trace: {node_id: 'review.second_opinion', node_label: 'Independent decision', model_execution: {provider: 'typesafe', model: 'jev-1.13.0'}} },
    { id: 'gpt-call', skill_slug: 'evaluate_v2', status: 'completed', output_ref: output,
      trace: {node_id: 'review.evidence', model_execution: {provider: 'openai', model: 'gpt-5', returned_model: 'gpt-5-2025-08-07'}} },
  ]} as Run);
  assert.deepEqual(reviews.map(({invocationId, node, model}) => ({invocationId, node, model})), [
    {invocationId: 'jev-call', node: 'Independent decision', model: 'typesafe · jev-1.13.0'},
    {invocationId: 'gpt-call', node: 'review.evidence', model: 'openai · gpt-5-2025-08-07'},
  ]);
  // Readers see the step's label; a bare node id stays technical evidence.
  assert.deepEqual(reviews.map(({nodeLabel}) => nodeLabel), ['Independent decision', null]);
});

test('review identity never falls back to a planned model or mutable output claims', () => {
  const review = runQualityReviews({status: 'hitl_pending', skill_invocations: [{id: 'call-1', skill_slug: 'evaluate_v2', status: 'completed',
    output_ref: {...output, model_execution: {provider: 'unverified', model: 'unverified'}},
    trace: {node_label: {private: 'never shown'}, model_resolution: {provider: 'planned', model: 'planned'}},
  }]} as unknown as Run)[0];
  assert.equal(review.model, null);
  assert.equal(review.node, null);
});

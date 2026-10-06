import assert from 'node:assert/strict';
import { test } from 'node:test';
import { FLOW_EN, FLOW_FR } from '@app/core/i18n/flow.dict';
import { laterResults, reviewRefusalKey, reviewStep } from './review-loop.vm';

const runs = [
  { id: 'run-3', status: 'completed' },
  { id: 'run-2', status: 'failed' },
  { id: 'run-1', status: 'completed' },
  { id: 'run-0', status: 'completed' },
];

test('only results newer than the reserved one can be compared', () => {
  assert.deepEqual(laterResults(runs, 'run-1').map((run) => run.id), ['run-3', 'run-2']);
  assert.deepEqual(laterResults(runs, 'run-3'), []);
});

test('a reserved result outside the recent list leaves every other result', () => {
  assert.deepEqual(laterResults(runs, 'run-old').map((run) => run.id), ['run-3', 'run-2', 'run-1', 'run-0']);
});

test('a refusal a person can act on names what to do, in both languages', () => {
  for (const code of ['unchanged_draft', 'stale_reread', 'not_later']) {
    const key = reviewRefusalKey(code) as keyof typeof FLOW_EN;
    assert.equal(key, `flow.review.refused.${code}`);
    assert.ok(FLOW_EN[key]?.trim() && FLOW_FR[key]?.trim(), `${key} resolves to copy`);
  }
  assert.equal(reviewRefusalKey('object_lost'), 'flow.review.error');
  assert.equal(reviewRefusalKey(undefined), 'flow.review.error');
});

test('a reservation walks through raise, reread, confirm and compare', () => {
  assert.equal(reviewStep(null), 1);
  assert.equal(reviewStep({}), 2, 'raised, the corrected draft is still to reread');
  assert.equal(reviewStep({ draft_hash: 'a' }), 3);
  assert.equal(reviewStep({ draft_hash: 'a', correction_hash: 'b' }), 4);
  assert.equal(reviewStep({ draft_hash: 'a', correction_hash: 'b', same_object: true }), 5);
  assert.equal(reviewStep({ correction_hash: null, draft_hash: null }), 2, 'a reread resets the confirmation');
});

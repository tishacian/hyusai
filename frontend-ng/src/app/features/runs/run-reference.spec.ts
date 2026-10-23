import assert from 'node:assert/strict';
import { test } from 'node:test';
import { isShortRunReference, shortReferenceOutcome } from './run-reference';

test('only a hexadecimal prefix of at least 8 characters is a short reference', () => {
  assert.equal(isShortRunReference('f0f481fb'), true);
  assert.equal(isShortRunReference('F0F481FB-24cb'), true);
  assert.equal(isShortRunReference('f0f481'), false);
  assert.equal(isShortRunReference('f0f481fb-24cb-4cab-9d65-9d624157b1ff'), false);
  assert.equal(isShortRunReference('run-name'), false);
  assert.equal(isShortRunReference(null), false);
});

test('a unique match opens, several are ambiguous, none says so', () => {
  assert.deepEqual(shortReferenceOutcome({ run_ids: ['full-id'], ambiguous: false }), { kind: 'open', runId: 'full-id' });
  assert.deepEqual(shortReferenceOutcome({ run_ids: ['a', 'b'], ambiguous: true }), { kind: 'ambiguous' });
  assert.deepEqual(shortReferenceOutcome({ run_ids: [] }), { kind: 'none' });
  assert.deepEqual(shortReferenceOutcome(null), { kind: 'none' });
});

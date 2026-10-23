import assert from 'node:assert/strict';
import { test } from 'node:test';
import { columnChoices } from './prep-columns';

test('configured columns stay visible without a preview schema', () => {
  assert.deepEqual(columnChoices([], ['claim_id', 'amount']), ['claim_id', 'amount']);
  assert.deepEqual(columnChoices([], 'claim_id'), ['claim_id']);
});

test('preview columns come first and configured ones are added once', () => {
  assert.deepEqual(columnChoices(['a', 'b'], ['b', 'c'], 'c', ['d']), ['a', 'b', 'c', 'd']);
  assert.deepEqual(columnChoices(['a'], undefined, null, '', [1, 'b']), ['a', 'b']);
});

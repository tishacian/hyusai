import assert from 'node:assert/strict';
import { test } from 'node:test';
import { collectionIndexPresentation } from './knowledge-facets';

test('knowledge-base never labels a queued collection as indexed', () => {
  const queued = collectionIndexPresentation('queued');
  assert.notEqual(queued.labelKey, 'knowledge.collections.indexed');
  assert.equal(queued.labelKey, 'knowledge.collections.indexing');
  assert.equal(collectionIndexPresentation('ready').labelKey, 'knowledge.collections.indexed');
});

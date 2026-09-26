import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  KNOWLEDGE_FACETS,
  collectionIndexPresentation,
  contentPanelFromLegacy,
  isKnowledgeFacet,
  normalizeKnowledgeFacet,
} from './knowledge-facets';

test('L19 collection exposes exactly five facets', () => {
  assert.deepEqual([...KNOWLEDGE_FACETS], [
    'overview',
    'documents',
    'content',
    'usage',
    'graph',
  ]);
});

test('legacy tabs rewrite to the five facets', () => {
  assert.equal(normalizeKnowledgeFacet('sources'), 'documents');
  assert.equal(normalizeKnowledgeFacet('diagnostics'), 'overview');
  assert.equal(normalizeKnowledgeFacet('chunks'), 'content');
  assert.equal(normalizeKnowledgeFacet('table-facts'), 'content');
  assert.equal(normalizeKnowledgeFacet('guides'), 'usage');
  assert.equal(normalizeKnowledgeFacet('bindings'), 'usage');
  assert.equal(normalizeKnowledgeFacet('graph'), 'graph');
  assert.equal(normalizeKnowledgeFacet('bogus'), 'overview');
  assert.equal(contentPanelFromLegacy('ocr'), 'ocr');
  assert.equal(contentPanelFromLegacy('sources'), null);
  assert.equal(isKnowledgeFacet('content'), true);
  assert.equal(isKnowledgeFacet('sources'), false);
});

test('indexing status never presents as indexed while queued', () => {
  assert.equal(collectionIndexPresentation('queued').labelKey, 'knowledge.collections.indexing');
  assert.equal(collectionIndexPresentation('queued').tone, 'warning');
  assert.equal(collectionIndexPresentation('ready').labelKey, 'knowledge.collections.indexed');
  assert.equal(collectionIndexPresentation('error').tone, 'danger');
  assert.equal(collectionIndexPresentation('created').labelKey, 'knowledge.collections.not_indexed');
});

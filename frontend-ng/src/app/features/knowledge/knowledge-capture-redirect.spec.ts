import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  collectionCaptureFacetUrl,
  knowledgeCaptureRedirectUrl,
  systemCaptureFacetUrl,
} from './knowledge-capture-redirect';

test('system capture facet URL', () => {
  assert.equal(systemCaptureFacetUrl('sys-1'), '/systems/sys-1?facet=capture');
});

test('collection capture facet keeps documents facet', () => {
  assert.equal(
    collectionCaptureFacetUrl('manuals'),
    '/knowledge/manuals?facet=documents&capture=1',
  );
});

test('legacy /knowledge/capture query resolves to facets', () => {
  assert.equal(
    knowledgeCaptureRedirectUrl({ systemId: 'sys-9' }),
    '/systems/sys-9?facet=capture',
  );
  assert.equal(
    knowledgeCaptureRedirectUrl({ collection: 'docs' }),
    '/knowledge/docs?facet=documents&capture=1',
  );
  assert.equal(knowledgeCaptureRedirectUrl({}), null);
});

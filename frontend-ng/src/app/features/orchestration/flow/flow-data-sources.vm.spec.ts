import assert from 'node:assert/strict';
import { test } from 'node:test';
import { connectorSourceItems, collectionSourceItems, sourceResources } from './flow-data-sources.vm';
import { paletteItemSlug, searchPaletteItems } from './flow-palette.vm';
import { paletteItemToNode } from './flow.types';

test('configured sources seed references and never persist connection values', () => {
  const items = connectorSourceItems([
    { id: 'postgresql', configured: true, values: { database: 'Luma', host: 'internal.example.test', password: 'must-not-leak' } },
    { id: 's3', configured: false, values: {} },
    { id: 'planned-provider', configured: true, values: {} },
  ]);
  assert.equal(items.length, 1);
  assert.equal(paletteItemSlug(items[0]), 'postgresql');
  const node = paletteItemToNode(items[0]);
  assert.deepEqual(node.config, { connector_id: 'postgresql', read_mode: 'live', resources: [] });
  assert.equal(node.kind, 'asset');
  assert.equal(JSON.stringify(node).includes('must-not-leak'), false);
  assert.equal(JSON.stringify(node).includes('internal.example.test'), false);
});

test('collections retain unique palette/search identities and bound source names', () => {
  const items = collectionSourceItems(['luma-preuves', 'luma-regles', 'luma-preuves']);
  assert.deepEqual(items.map(paletteItemSlug), ['luma-preuves', 'luma-regles']);
  assert.equal(searchPaletteItems(items, 'luma-preuves')[0].label, 'luma-preuves');
  assert.deepEqual(paletteItemToNode(items[1]).config, { collection_slug: 'luma-regles', workspace_scoped: true });
});

test('resource projection preserves quoted identifiers and discards non-reference values', () => {
  assert.deepEqual(sourceResources({ id: 'pg', type: 'source.connector', kind: 'asset', config: { resources: [
    { schema: 'Sales Data', table: 'Order "Items"', password: 'discard' }, { schema: 1, table: 'invalid' },
  ] } }), [{ schema: 'Sales Data', table: 'Order "Items"' }]);
});

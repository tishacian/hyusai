import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import {
  CATALOG_0_2_RENDERER_VERSION,
  CERTIFIED_RENDERER_VERSION,
  followUpRecordRef,
  localizeDocument,
  recordFollowUpConfig,
  renderableComponents,
  resolveCatalogType,
} from './model';
import { followUpBindings, followUpProps } from '../studio/studio-model';

const FIXTURES = 'src/app/features/experience/runtime/fixtures';

/**
 * Réclamations as published (catalog 0.2.0). The expected rendering was
 * recorded with the code before catalog 0.3.0 existed: the pinned renderer
 * must read the release exactly as before.
 */
test('a published 0.2.0 release (Réclamations) reads exactly as before catalog 0.3.0', () => {
  const raw = JSON.parse(readFileSync(`${FIXTURES}/claims-release-v0_2.json`, 'utf8'));
  const expected = JSON.parse(readFileSync(`${FIXTURES}/claims-release-v0_2.expected.json`, 'utf8'));
  for (const locale of ['fr', 'en']) {
    const doc = localizeDocument(raw, locale);
    const rendered = doc.pages.map((page) => renderableComponents(page.components)
      .map((node) => ({ id: node.id, resolution: resolveCatalogType(node.type, CATALOG_0_2_RENDERER_VERSION) })));
    assert.deepEqual(JSON.parse(JSON.stringify({ document: doc, rendered })), expected[locale]);
  }
});

test('only catalog 0.3.0 renders the follow-up block; 0.2.0 keeps its fallback', () => {
  assert.deepEqual(resolveCatalogType('record_follow_up', CERTIFIED_RENDERER_VERSION), { kind: 'ok', type: 'record_follow_up' });
  assert.deepEqual(resolveCatalogType('record_follow_up', CATALOG_0_2_RENDERER_VERSION), { kind: 'fallback', type: 'record_follow_up' });
  assert.deepEqual(resolveCatalogType('form', CATALOG_0_2_RENDERER_VERSION), { kind: 'ok', type: 'form' });
});

test('the block reads its record from the page address or from the followed action', () => {
  const byUrl = recordFollowUpConfig({ type: 'record_follow_up', props: { followBindingKey: 'k', recordField: 'claim_id', recordSource: { kind: 'url' } } });
  const byAction = recordFollowUpConfig({ type: 'record_follow_up', props: { followBindingKey: 'k', recordField: 'claim_id', recordSource: { kind: 'action', componentId: 'investigation' } } });
  assert.deepEqual(byAction?.source, { kind: 'action', componentId: 'investigation' });
  assert.equal(followUpRecordRef(byUrl, { queryRecord: ' RC-1042 ' }), 'RC-1042');
  assert.equal(followUpRecordRef(byUrl, { runInput: { claim_id: 'RC-9' } }), null);
  assert.equal(followUpRecordRef(byAction, { runInput: { claim_id: 'RC-1043' }, lastPayload: { claim_id: 'RC-1' } }), 'RC-1043');
  assert.equal(followUpRecordRef(byAction, { lastPayload: { claim_id: 'RC-1044' } }), 'RC-1044');
  assert.equal(followUpRecordRef(byAction, {}), null);
  // An incomplete or free-form configuration renders as "not linked yet".
  assert.equal(recordFollowUpConfig({ type: 'record_follow_up', props: { followBindingKey: 'k', recordField: 'claim_id', recordSource: { kind: 'json' } } }), null);
  assert.equal(recordFollowUpConfig({ type: 'record_follow_up', props: {} }), null);
});

test('the builder offers the app’s own actions, their fields and sources, by selection', () => {
  const raw = JSON.parse(readFileSync(`${FIXTURES}/claims-release-v0_2.json`, 'utf8'));
  const doc = localizeDocument(raw, 'fr');
  const bindings = followUpBindings(doc);
  const investigate = bindings.find((row) => row.bindingKey === 'showcase.claims.investigate');
  assert.deepEqual(investigate, { bindingKey: 'showcase.claims.investigate', fields: ['claim_id'], actions: ['investigation'] });
  // Choosing the service picks its only field and the page address as source.
  assert.deepEqual(followUpProps({}, { bindingKey: 'showcase.claims.investigate' }, doc), {
    followBindingKey: 'showcase.claims.investigate', recordField: 'claim_id', recordSource: { kind: 'url' },
  });
  const sourced = followUpProps({ followBindingKey: 'showcase.claims.investigate', recordField: 'claim_id' }, { source: 'investigation' }, doc);
  assert.deepEqual(sourced['recordSource'], { kind: 'action', componentId: 'investigation' });
  // A fixed-input action without fields leaves the key to choose.
  assert.equal(followUpProps({}, { bindingKey: 'showcase.claims.refresh_queue' }, doc)['recordField'], '');
});

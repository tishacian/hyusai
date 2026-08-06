/**
 * Integration tests for `FlowStore` — exercised headless through a real
 * Angular `Injector` (ngrx `signalStore` + JIT compiler), no browser/zone.
 *
 * Covers two plan §4 acceptance criteria at the source-of-truth layer:
 *   - **Panel navigation determinism.** `setSelection(id)` makes
 *     `selectedNode()` reflect the new node synchronously (same tick = within
 *     one frame), which is what makes the docked inspector update
 *     deterministically off the `selectedNode` computed.
 *   - **Two-way wiring round-trip.** A manifest edit to the exact
 *     `runtime_read_path` (`nodes.runtime.settings_budget.data.retrieval_defaults.top_k`)
 *     writes that precise nested path, marks the graph dirty, and is re-read
 *     identically after `snapshot()` → `load()` (the persist/reload cycle),
 *     with dirty cleared on reload. Also asserts the skill param home
 *     (`config.params.<key>`, PART A.4) round-trips.
 *
 * `@angular/compiler` is imported first so ngrx's partially-compiled
 * `signalStore` can JIT-compile in Node. Run with `npm run test:unit`.
 */
import '@angular/compiler';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { Injector } from '@angular/core';
import { FlowSerializerService, type CanonicalFlow } from '@app/core/flow-serializer.service';
import { FlowStore } from './flow.store';

type Store = InstanceType<typeof FlowStore>;

function makeStore(): Store {
  const injector = Injector.create({
    providers: [FlowSerializerService, FlowStore as never],
  });
  return injector.get(FlowStore) as Store;
}

function budgetFlow(topK = 5): CanonicalFlow {
  return {
    source: 'flow',
    schema_version: 2,
    nodes: [
      {
        id: 'runtime.settings_budget',
        type: 'runtime',
        kind: 'task',
        label: 'Budget',
        data: { retrieval_defaults: { top_k: topK } },
        config: {},
      },
      {
        id: 'flow.retrieve',
        type: 'skill',
        kind: 'task',
        label: 'Retrieve',
        config: { skill_slug: 'fast_retrieval', params: { top_k: 4 } },
      },
    ],
    edges: [{ from: 'runtime.settings_budget', to: 'flow.retrieve', kind: 'data' }],
  };
}

test('selection is deterministic and synchronous (inspector updates within one frame)', () => {
  const store = makeStore();
  store.load(budgetFlow());
  assert.equal(store.selectedNode(), null);

  store.setSelection('runtime.settings_budget');
  assert.equal(store.selectedNode()?.id, 'runtime.settings_budget', 'selectedNode reflects immediately');

  store.setSelection('flow.retrieve');
  assert.equal(store.selectedNode()?.id, 'flow.retrieve', 'switching selection is immediate');

  store.setSelection(null);
  assert.equal(store.selectedNode(), null);
});

test('load resets dirty; a manifest write marks dirty; markSaved clears it', () => {
  const store = makeStore();
  store.load(budgetFlow());
  assert.equal(store.dirty(), false, 'loaded graph is the saved baseline');

  store.updateNodeData('runtime.settings_budget', 'retrieval_defaults.top_k', 9);
  assert.equal(store.dirty(), true, 'editing a field marks dirty');

  store.markSaved();
  assert.equal(store.dirty(), false, 'markSaved clears dirty (save success path)');
});

test('revision is monotone and a stale save acknowledgement cannot clean a newer edit', () => {
  const store = makeStore();
  assert.equal(store.revision(), 0);

  store.load(budgetFlow());
  const loadedRevision = store.revision();
  assert.equal(loadedRevision, 1, 'baseline load increments the persistable revision');

  store.setSelection('flow.retrieve');
  assert.equal(store.revision(), loadedRevision, 'selection is not persisted');

  store.setSource('form');
  assert.equal(store.revision(), loadedRevision + 1, 'metadata mutation increments revision');

  store.updateNodeData('runtime.settings_budget', 'retrieval_defaults.top_k', 8);
  const requestRevision = store.revision();
  assert.equal(requestRevision, loadedRevision + 2);

  store.updateNodeData('runtime.settings_budget', 'retrieval_defaults.top_k', 13);
  assert.equal(store.revision(), requestRevision + 1);
  assert.equal(store.markSaved(requestRevision), false, 'stale response is rejected');
  assert.equal(store.dirty(), true, 'newer edit remains dirty');

  assert.equal(store.markSaved(store.revision()), true);
  assert.equal(store.dirty(), false);
});

test('load and snapshot preserve known and unknown top-level sidecars without graph duplication', () => {
  const store = makeStore();
  const source = {
    ...budgetFlow(),
    variable_namespaces: ['case', 'ticket'],
    future_runtime_contract: {
      mode: 'authoritative',
      nested: { keep: ['all', 'values'] },
    },
  } as CanonicalFlow & Record<string, unknown>;

  store.load(source);
  const snapshot = store.snapshot() as CanonicalFlow & Record<string, unknown>;

  assert.deepEqual(snapshot.variable_namespaces, ['case', 'ticket']);
  assert.deepEqual(snapshot['future_runtime_contract'], {
    mode: 'authoritative',
    nested: { keep: ['all', 'values'] },
  });
  assert.equal(snapshot.nodes.length, source.nodes.length);
  assert.equal(snapshot.edges.length, source.edges.length);

  // Meta is cloned at both boundaries rather than aliasing imported JSON.
  (source['future_runtime_contract'] as any).nested.keep.push('mutated-after-load');
  assert.deepEqual((store.snapshot() as any).future_runtime_contract.nested.keep, [
    'all',
    'values',
  ]);
});

test('replaceAsEdit is dirty and undo/redo restores the complete metadata sidecar', () => {
  const store = makeStore();
  const baseline = {
    ...budgetFlow(),
    variable_namespaces: ['baseline'],
    opaque: { owner: 'baseline' },
  } as CanonicalFlow & Record<string, unknown>;
  const imported = {
    schema_version: 3,
    io_mode: 'strict',
    variable_namespaces: ['imported'],
    opaque: { owner: 'imported' },
    nodes: [{ id: 'imported', type: 'task', label: 'Imported' }],
    edges: [],
  } as CanonicalFlow & Record<string, unknown>;

  store.load(baseline);
  const afterLoad = store.revision();
  store.replaceAsEdit(imported);

  assert.equal(store.dirty(), true);
  assert.equal(store.canUndo(), true);
  assert.equal(store.revision(), afterLoad + 1);
  assert.deepEqual(store.snapshot().variable_namespaces, ['imported']);
  assert.deepEqual((store.snapshot() as any).opaque, { owner: 'imported' });

  store.undo();
  assert.equal(store.revision(), afterLoad + 2);
  assert.deepEqual(store.snapshot().variable_namespaces, ['baseline']);
  assert.deepEqual((store.snapshot() as any).opaque, { owner: 'baseline' });
  assert.equal(store.snapshot().nodes[0].id, 'runtime.settings_budget');

  store.redo();
  assert.equal(store.revision(), afterLoad + 3);
  assert.deepEqual(store.snapshot().variable_namespaces, ['imported']);
  assert.deepEqual((store.snapshot() as any).opaque, { owner: 'imported' });
  assert.equal(store.snapshot().nodes[0].id, 'imported');
});

test('clear is idempotent for an already empty graph', () => {
  const store = makeStore();
  const empty: CanonicalFlow = { schema_version: 3, nodes: [], edges: [] };
  store.load(empty);
  const revision = store.revision();

  store.clear();

  assert.equal(store.revision(), revision);
  assert.equal(store.dirty(), false);
  assert.equal(store.canUndo(), false);
});

test('TWO-WAY WIRING: top_k edit writes the exact nested path and round-trips on reload', () => {
  const store = makeStore();
  store.load(budgetFlow(5));
  store.setSelection('runtime.settings_budget');

  // Mirrors manifest-fields write-back for a `node.data` field with
  // key `retrieval_defaults.top_k` → updateNodeData(id, key).
  store.updateNodeData('runtime.settings_budget', 'retrieval_defaults.top_k', 12);

  const node = store.selectedNode();
  assert.equal(
    (node!.data as any)['retrieval_defaults']['top_k'],
    12,
    'value lands at nodes.runtime.settings_budget.data.retrieval_defaults.top_k',
  );
  // Sibling key under the same parent is preserved (immutable set-path).
  assert.equal(store.dirty(), true);

  // Persist → reload cycle (what saveSystemFlow + reload-from-System do).
  const snapshot = store.snapshot();
  assert.equal(
    (snapshot.nodes.find((n) => n.id === 'runtime.settings_budget')!.data as any)['retrieval_defaults']['top_k'],
    12,
    'snapshot carries the edit',
  );

  const reopened = makeStore();
  reopened.load(snapshot);
  assert.equal(reopened.dirty(), false, 'reloaded graph is clean');
  const reloaded = reopened.snapshot().nodes.find((n) => n.id === 'runtime.settings_budget');
  assert.equal(
    (reloaded!.data as any)['retrieval_defaults']['top_k'],
    12,
    'edit is re-read identically after reload',
  );
});

test('skill param home: config.params.<key> writes + round-trips (PART A.4)', () => {
  const store = makeStore();
  store.load(budgetFlow());

  // P2 manifest-fields write for source 'skill.input_schema' →
  // updateNodeConfig(id, 'params.' + key).
  store.updateNodeConfig('flow.retrieve', 'params.top_k', 7);
  const cfg = store.snapshot().nodes.find((n) => n.id === 'flow.retrieve')!.config as any;
  assert.equal(cfg['params']['top_k'], 7, 'inspector edit writes config.params.<key>');
  assert.equal(cfg['skill_slug'], 'fast_retrieval', 'binding is preserved alongside params');

  const reopened = makeStore();
  reopened.load(store.snapshot());
  const cfg2 = reopened.snapshot().nodes.find((n) => n.id === 'flow.retrieve')!.config as any;
  assert.equal(cfg2['params']['top_k'], 7, 'config.params survives reload');
});

test('undo/redo + connect/disconnect behave as single steps', () => {
  const store = makeStore();
  store.load(budgetFlow());
  assert.equal(store.canUndo(), false);

  store.connect({ from: 'flow.retrieve', to: 'runtime.settings_budget', kind: 'data' });
  assert.equal(store.edgeCount(), 2);
  assert.equal(store.canUndo(), true);

  store.undo();
  assert.equal(store.edgeCount(), 1, 'undo removes the new edge');
  store.redo();
  assert.equal(store.edgeCount(), 2, 'redo re-adds it');

  store.disconnect({ from: 'flow.retrieve', to: 'runtime.settings_budget', kind: 'data' });
  assert.equal(store.edgeCount(), 1);
});

test('clear is one revision and undo restores the graph', () => {
  const store = makeStore();
  store.load(budgetFlow());
  const loadedRevision = store.revision();

  store.clear();
  assert.equal(store.nodeCount(), 0);
  assert.equal(store.edgeCount(), 0);
  assert.equal(store.revision(), loadedRevision + 1);

  store.undo();
  assert.equal(store.nodeCount(), 2);
  assert.equal(store.edgeCount(), 1);
  assert.equal(store.revision(), loadedRevision + 2);
});

import '@angular/compiler';
import { Injector, signal } from '@angular/core';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { FlowSerializerService } from '@app/core/flow-serializer.service';
import { FlowInspectorComponent } from './flow-inspector.component';
import { FlowStore } from './flow.store';

function harness() {
  const injector = Injector.create({ providers: [FlowSerializerService, FlowStore as never] });
  const store = injector.get(FlowStore) as InstanceType<typeof FlowStore>;
  const config = {
    skill_slug: 'evaluate_v2',
    inputs_map: { claim: 'nodes.investigation.claim' },
    passthrough_inputs: ['case_id'],
    typed_evaluation: { questions: [{ key: 'verdict', requires_evidence: true }] },
    params: { context_key: 'claim' },
  };
  store.load({ source: 'flow', runtime_mode: 'dag_overlay', nodes: [
    { id: 'judge', type: 'skill', kind: 'task', config },
    { id: 'source', type: 'source', kind: 'source', config: {} },
  ], edges: [] });
  store.setSelection('judge');
  const locked = signal(false);
  const published = signal(false);
  const inspector = Object.assign(Object.create(FlowInspectorComponent.prototype), {
    store, node: store.selectedNode, editingLocked: locked, publishedReading: published,
  }) as FlowInspectorComponent;
  const change = (value: string) => inspector.onTaskInputMode({ target: { value } } as unknown as Event);
  return { injector, store, config, inspector, locked, published, change };
}

test('input isolation round-trips without rewriting mappings, evidence or defaults', () => {
  const h = harness();
  try {
    const initial = h.store.snapshot();
    assert.equal(h.inspector.taskInputMode(h.store.selectedNode()!), 'inherit');
    h.change('inherit');
    assert.deepEqual(h.store.snapshot(), initial);
    assert.equal(h.store.dirty(), false);
    h.change('mapped');
    assert.deepEqual(h.store.selectedNode()!.config, { ...h.config, input_mode: 'mapped' });
    h.store.load(h.store.snapshot());
    h.store.setSelection('judge');
    assert.equal(h.inspector.taskInputMode(h.store.selectedNode()!), 'mapped');
    h.change('inherit');
    assert.deepEqual(h.store.selectedNode()!.config, { ...h.config, input_mode: 'inherit' });
  } finally { h.injector.destroy(); }
});

test('input isolation rejects unsupported modes, non-task nodes and locked or published edits', () => {
  const h = harness();
  try {
    const initial = h.store.snapshot();
    h.change('all');
    h.locked.set(true);
    h.change('mapped');
    h.locked.set(false);
    h.published.set(true);
    h.change('mapped');
    h.published.set(false);
    h.store.setSelection('source');
    h.change('mapped');
    assert.deepEqual(h.store.snapshot(), initial);
    assert.equal(h.store.dirty(), false);
  } finally { h.injector.destroy(); }
});

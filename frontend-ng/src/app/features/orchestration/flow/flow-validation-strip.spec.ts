/**
 * Integration tests for `FlowValidationStripComponent` — exercised headless
 * through a real Angular `Injector` (the strip injects the component-scoped
 * `FlowStore` + the root `FlowSerializerService`; `serverIssues` is a signal
 * input that defaults to `[]`).
 *
 * Covers the P2 checklist wiring:
 *   - client `validateFlow` diagnostics flow into the strip's `vm()` reactively;
 *   - clicking a node-scoped row calls `store.setSelection(node_id)` (so the
 *     inspector opens on it) and emits `(focusNode)` for canvas recentring;
 *   - graph-level rows (no node id) are inert.
 *
 * `@angular/compiler` is imported first so the `@Component` JITs in Node.
 * Run with `npm run test:unit`.
 */
import '@angular/compiler';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { Injector, runInInjectionContext } from '@angular/core';
import {
  FlowSerializerService,
  type CanonicalFlow,
} from '@app/core/flow-serializer.service';
import { FlowStore } from './flow.store';
import { FlowValidationStripComponent } from './flow-validation-strip.component';

type Store = InstanceType<typeof FlowStore>;

function setup(flow: CanonicalFlow): {
  store: Store;
  strip: FlowValidationStripComponent;
} {
  const injector = Injector.create({
    providers: [FlowSerializerService, FlowStore as never],
  });
  const store = injector.get(FlowStore) as Store;
  store.load(flow);
  const strip = runInInjectionContext(
    injector,
    () => new FlowValidationStripComponent(),
  );
  return { store, strip };
}

// A task node with no Skill bound → validateFlow warns `task_no_skill` on it;
// a stray cycle → graph-level `cycle_detected` (no node id).
function flawedFlow(): CanonicalFlow {
  return {
    source: 'flow',
    schema_version: 3,
    nodes: [
      { id: 'n1', type: 'custom', kind: 'task', config: {} },
      { id: 'n2', type: 'custom', kind: 'task', config: {} },
    ],
    edges: [
      { from: 'n1', to: 'n2', kind: 'data' },
      { from: 'n2', to: 'n1', kind: 'data' },
    ],
  };
}

test('client diagnostics map into the strip vm with node ids', () => {
  const { strip } = setup(flawedFlow());
  const vm = strip.vm();
  assert.equal(vm.clean, false);
  assert.ok(vm.errorCount >= 1, 'cycle is an error');
  const taskRow = vm.rows.find((r) => r.code === 'task_no_skill' && r.nodeId === 'n1');
  assert.ok(taskRow, 'node-scoped warning carries its node id');
  assert.ok(vm.rows.some((r) => r.code === 'cycle_detected' && r.nodeId === null));
});

test('clicking a node-scoped row selects the node and emits focusNode', () => {
  const { store, strip } = setup(flawedFlow());
  assert.equal(store.selectedNodeId(), null);

  let focused: string | null = null;
  strip.focusNode.subscribe((id) => (focused = id));

  const row = strip.vm().rows.find((r) => r.nodeId === 'n1')!;
  strip.onSelect(row);

  assert.equal(store.selectedNodeId(), 'n1', 'click → store.setSelection(node_id)');
  assert.equal(focused, 'n1', 'click → (focusNode) emits the node id');
});

test('clicking a graph-level row (no node id) is inert', () => {
  const { store, strip } = setup(flawedFlow());
  let emitted = false;
  strip.focusNode.subscribe(() => (emitted = true));

  const graphRow = strip.vm().rows.find((r) => r.nodeId === null)!;
  strip.onSelect(graphRow);

  assert.equal(store.selectedNodeId(), null, 'no selection for graph-level issues');
  assert.equal(emitted, false, 'no focus emitted');
});

test('vm reacts to graph edits (resolving the cycle drops the error)', () => {
  const { store, strip } = setup(flawedFlow());
  assert.ok(strip.vm().rows.some((r) => r.code === 'cycle_detected'));

  // Remove the back-edge that forms the cycle.
  store.disconnect({ from: 'n2', to: 'n1', kind: 'data' });
  assert.ok(
    !strip.vm().rows.some((r) => r.code === 'cycle_detected'),
    'cycle error clears after the back-edge is removed',
  );
});

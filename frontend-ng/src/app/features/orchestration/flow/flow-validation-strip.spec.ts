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
import { Injector, runInInjectionContext, signal } from '@angular/core';
import {
  FlowSerializerService,
  type CanonicalFlow,
} from '@app/core/flow-serializer.service';
import { I18nService } from '@app/core/i18n.service';
import { FLOW_EN } from '@app/core/i18n/flow.dict';
import { FlowStore } from './flow.store';
import { FlowValidationStripComponent } from './flow-validation-strip.component';

type Store = InstanceType<typeof FlowStore>;

/**
 * Resolves real EN copy so the assertions below keep reading the words an
 * operator sees, now that they live in the dictionary rather than the template.
 */
function i18nStub() {
  return {
    locale: signal('en' as const),
    setLocale: () => undefined,
    t: (key: string, params?: Record<string, string | number>) => {
      const value = (FLOW_EN as Record<string, string>)[key] ?? key;
      return params
        ? value.replace(/\{(\w+)\}/g, (match, name: string) =>
            name in params ? String(params[name]) : match,
          )
        : value;
    },
  };
}

function setup(flow: CanonicalFlow): {
  store: Store;
  strip: FlowValidationStripComponent;
} {
  const injector = Injector.create({
    providers: [
      FlowSerializerService,
      FlowStore as never,
      { provide: I18nService, useValue: i18nStub() },
    ],
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
      { id: 'n1', type: 'custom', kind: 'task', label: 'Retrieve', config: {} },
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

test('a known code reads as a sentence naming the node, not as the code', () => {
  const { strip } = setup(flawedFlow());
  const row = strip.vm().rows.find((r) => r.code === 'task_no_skill' && r.nodeId === 'n1')!;

  const message = strip.message(row);
  assert.equal(message, FLOW_EN['flow.checklist.code.task_no_skill'].replace('{name}', 'Retrieve'));
  assert.ok(!message.includes('task_no_skill'), 'the code never reaches the readable surface');
  assert.ok(!message.includes('{name}'), 'the node name is interpolated, not left as a placeholder');

  // The code and the analyser's own wording stay available for support.
  const title = strip.diagnostic(row);
  assert.ok(title.includes('task_no_skill'), 'the code stays in the row title');
  assert.ok(title.includes(row.message), 'the raw diagnostic stays in the row title');
});

test('an unknown server code falls back to the server sentence, never to a key', () => {
  const { strip } = setup(flawedFlow());
  const message = strip.message({
    level: 'error',
    code: 'code_from_a_newer_server',
    message: 'Something the server knows and this build does not.',
    nodeId: null,
    origin: 'server',
  });
  assert.equal(message, 'Something the server knows and this build does not.');
  assert.ok(!message.startsWith('flow.checklist.'), 'no unresolved i18n key on screen');
});

test('a node-scoped message with no node falls back rather than showing {name}', () => {
  const { strip } = setup(flawedFlow());
  const message = strip.message({
    level: 'warn',
    code: 'task_no_skill',
    message: 'Task node has no Skill bound.',
    nodeId: null,
    origin: 'server',
  });
  assert.equal(message, 'Task node has no Skill bound.');
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

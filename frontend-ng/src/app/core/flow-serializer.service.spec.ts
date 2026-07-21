/**
 * Unit tests for `FlowSerializerService` — the CanonicalFlow pivot.
 *
 * Focus areas for the cleanup phase:
 *   - **Two-way wiring round-trip (persistence half).** `FlowStore.load()`
 *     runs `normalize()` and `FlowStore.snapshot()` clones the graph; the
 *     save path runs `annotateSidecars()`. So the property "a manifest edit
 *     to the exact `runtime_read_path` is re-read identically on reload" hinges
 *     on `normalize`/`annotateSidecars` NOT dropping node `data`/`config`.
 *     We assert the canonical example
 *     `nodes.runtime.settings_budget.data.retrieval_defaults.top_k` survives.
 *   - **Skill param home (PART A.4).** Confirms `config.params.<key>` (where
 *     P3 seeds and P2 writes) round-trips through normalize untouched.
 *   - Validation + topo-sort sanity (unchanged behaviour, guards the cleanup).
 *
 * Pure logic: the `@Injectable` decorator is stubbed at bundle time, so the
 * service is exercised as a plain class. Run with `npm run test:unit`.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  FlowSerializerService,
  variableRefValidationError,
  type CanonicalFlow,
} from './flow-serializer.service';

function svc(): FlowSerializerService {
  return new FlowSerializerService();
}

function budgetFlow(topK: number): CanonicalFlow {
  return {
    source: 'flow',
    schema_version: 2,
    nodes: [
      {
        id: 'runtime.settings_budget',
        type: 'runtime',
        kind: 'task',
        label: 'Budget',
        data: { retrieval_defaults: { top_k: topK, mode: 'hybrid' } },
        config: {},
      },
    ],
    edges: [],
  };
}

test('round-trip: nodes.<id>.data.retrieval_defaults.top_k survives normalize (load)', () => {
  const s = svc();
  const loaded = s.normalize(budgetFlow(8));
  const node = loaded.nodes.find((n) => n.id === 'runtime.settings_budget');
  assert.ok(node);
  const data = node!.data as Record<string, any>;
  assert.equal(data['retrieval_defaults']['top_k'], 8, 'top_k must be preserved on load');
  assert.equal(data['retrieval_defaults']['mode'], 'hybrid');
});

test('round-trip: annotateSidecars (save path) does not drop node data/config', () => {
  const s = svc();
  const annotated = s.annotateSidecars(budgetFlow(13));
  const node = annotated.nodes.find((n) => n.id === 'runtime.settings_budget');
  assert.equal((node!.data as any)['retrieval_defaults']['top_k'], 13);
});

test('normalize is idempotent for the budget flow (load → snapshot → load fidelity)', () => {
  const s = svc();
  const once = s.normalize(budgetFlow(5));
  const twice = s.normalize(JSON.parse(JSON.stringify(once)) as CanonicalFlow);
  assert.deepEqual(
    (twice.nodes[0].data as any)['retrieval_defaults'],
    (once.nodes[0].data as any)['retrieval_defaults'],
  );
});

test('PART A.4: skill config.params.<key> is the shared home and round-trips', () => {
  const s = svc();
  const flow: CanonicalFlow = {
    source: 'flow',
    schema_version: 2,
    nodes: [
      {
        id: 'flow.retrieve',
        type: 'skill',
        kind: 'task',
        label: 'Retrieve',
        // P3 seeds typed defaults here; P2 manifest-fields write here too
        // (updateNodeConfig(id, 'params.<key>')).
        config: { skill_slug: 'fast_retrieval', skill_id: 's1', params: { top_k: 4 } },
      },
    ],
    edges: [],
  };
  const loaded = s.normalize(flow);
  const cfg = loaded.nodes[0].config as Record<string, any>;
  assert.equal(cfg['params']['top_k'], 4, 'config.params.<key> must survive normalize');
  assert.equal(cfg['skill_slug'], 'fast_retrieval');
});

test('validateFlow flags a task node with no skill bound', () => {
  const s = svc();
  const flow: CanonicalFlow = {
    schema_version: 2,
    nodes: [{ id: 'n1', type: 'custom', kind: 'task', config: {} }],
    edges: [],
  };
  const issues = s.validateFlow(flow);
  assert.ok(issues.some((i) => i.code === 'task_no_skill' && i.node_id === 'n1'));
});

test('validateFlow accepts a bound skill task with no warnings for it', () => {
  const s = svc();
  const flow: CanonicalFlow = {
    schema_version: 2,
    nodes: [{ id: 'n1', type: 'skill', kind: 'task', config: { skill_slug: 'x' } }],
    edges: [],
  };
  const issues = s.validateFlow(flow);
  assert.ok(!issues.some((i) => i.code === 'task_no_skill'));
});

test('normalize backfills schema_version 3 idempotently (v2 -> v3)', () => {
  const s = svc();
  const once = s.normalize(budgetFlow(8));
  assert.equal(once.schema_version, 3, 'v2 input is lifted to v3');
  const twice = s.normalize(JSON.parse(JSON.stringify(once)) as CanonicalFlow);
  assert.equal(twice.schema_version, 3, 'second pass stays v3 (idempotent)');
  // A higher version is preserved, never downgraded.
  const v4 = s.normalize({ schema_version: 4, nodes: [], edges: [] });
  assert.equal(v4.schema_version, 4);
});

test('normalize infers typed ports from data edges that name a port (idempotent)', () => {
  const s = svc();
  const flow: CanonicalFlow = {
    schema_version: 2,
    nodes: [
      { id: 'a', type: 'source', kind: 'source' },
      { id: 'b', type: 'task', kind: 'task', config: { skill_slug: 'x' } },
    ],
    edges: [{ from: 'a', to: 'b', kind: 'data', from_port: 'out', to_port: 'in' }],
  };
  const once = s.normalize(flow);
  const a = once.nodes.find((n) => n.id === 'a')!;
  const b = once.nodes.find((n) => n.id === 'b')!;
  assert.deepEqual(a.outputs, [{ name: 'out', schema: 'object' }]);
  assert.deepEqual(b.inputs, [{ name: 'in', schema: 'object' }]);
  // Idempotent: declared ports are not re-inferred or duplicated.
  const twice = s.normalize(JSON.parse(JSON.stringify(once)) as CanonicalFlow);
  assert.deepEqual(twice.nodes.find((n) => n.id === 'a')!.outputs, a.outputs);
  assert.deepEqual(twice.nodes.find((n) => n.id === 'b')!.inputs, b.inputs);
});

test('normalize leaves legacy inputs_map dot-path strings intact', () => {
  const s = svc();
  const flow: CanonicalFlow = {
    schema_version: 2,
    nodes: [
      {
        id: 'n1',
        type: 'skill',
        kind: 'task',
        config: { skill_slug: 'x', inputs_map: { objective: 'session.objective' } },
      },
    ],
    edges: [],
  };
  const cfg = s.normalize(flow).nodes[0].config as Record<string, any>;
  assert.equal(cfg['inputs_map']['objective'], 'session.objective');
});

test('validateFlow: port_type_mismatch warns on incompatible primitives only', () => {
  const s = svc();
  const flow: CanonicalFlow = {
    schema_version: 3,
    nodes: [
      { id: 'a', type: 'source', kind: 'source', outputs: [{ name: 'out', schema: 'string' }] },
      {
        id: 'b',
        type: 'task',
        kind: 'task',
        config: { skill_slug: 'x' },
        inputs: [{ name: 'in', schema: 'number' }],
      },
    ],
    edges: [{ from: 'a', to: 'b', kind: 'data', from_port: 'out', to_port: 'in' }],
  };
  const issues = s.validateFlow(flow);
  assert.ok(issues.some((i) => i.code === 'port_type_mismatch' && i.level === 'warn'));
  assert.ok(!issues.some((i) => i.level === 'error'));
});

test('validateFlow: port_type_mismatch silent on numeric widening + portless edges', () => {
  const s = svc();
  const widening: CanonicalFlow = {
    schema_version: 3,
    nodes: [
      { id: 'a', type: 'source', kind: 'source', outputs: [{ name: 'out', schema: 'integer' }] },
      { id: 'b', type: 'task', kind: 'task', config: { skill_slug: 'x' }, inputs: [{ name: 'in', schema: 'number' }] },
    ],
    edges: [{ from: 'a', to: 'b', kind: 'data', from_port: 'out', to_port: 'in' }],
  };
  assert.ok(!s.validateFlow(widening).some((i) => i.code === 'port_type_mismatch'));

  const portless: CanonicalFlow = {
    schema_version: 3,
    nodes: [
      { id: 'a', type: 'source', kind: 'source', outputs: [{ name: 'out', schema: 'string' }] },
      { id: 'b', type: 'task', kind: 'task', config: { skill_slug: 'x' }, inputs: [{ name: 'in', schema: 'number' }] },
    ],
    edges: [{ from: 'a', to: 'b', kind: 'data' }],
  };
  assert.ok(!s.validateFlow(portless).some((i) => i.code === 'port_type_mismatch'));
});

test('validateFlow: variable_unresolved warns on unknown/non-upstream refs, silent for reserved + legacy', () => {
  const s = svc();
  const bad: CanonicalFlow = {
    schema_version: 3,
    nodes: [
      {
        id: 'b',
        type: 'task',
        kind: 'task',
        config: { skill_slug: 'x', inputs_map: { q: { node_id: 'ghost', path: ['v'] } } },
      },
    ],
    edges: [],
  };
  assert.ok(bad ? s.validateFlow(bad).some((i) => i.code === 'variable_unresolved') : false);

  const good: CanonicalFlow = {
    schema_version: 3,
    nodes: [
      { id: 'a', type: 'source', kind: 'source', outputs: [{ name: 'goal', schema: 'string' }] },
      {
        id: 'b',
        type: 'task',
        kind: 'task',
        config: {
          skill_slug: 'x',
          inputs_map: {
            ws: { node_id: 'workspace', path: ['settings'] },
            goal: { node_id: 'a', path: ['goal'] },
            legacy: 'session.objective',
          },
        },
      },
    ],
    edges: [{ from: 'a', to: 'b', kind: 'data' }],
  };
  assert.ok(!s.validateFlow(good).some((i) => i.code === 'variable_unresolved'));
});

test('VariableRef JSON shape matches the backend strict contract', () => {
  assert.equal(variableRefValidationError({ node_id: 'run', path: [] }), null);
  assert.equal(variableRefValidationError({ node_id: 'run', path: [], required: false }), null);
  assert.equal(
    variableRefValidationError({ node_id: ' ', path: [] }),
    'node_id_must_be_non_empty_string',
  );
  assert.equal(
    variableRefValidationError({ node_id: 'run', path: ['query', 0] }),
    'path_must_be_string_array',
  );
  assert.equal(variableRefValidationError({ node_id: 'run' }), 'path_must_be_string_array');
  assert.equal(
    variableRefValidationError({ node_id: 'run', path: [], required: 'false' }),
    'required_must_be_boolean',
  );
});

test('validateFlow rejects the same malformed VariableRefs as the backend', () => {
  const flow = {
    schema_version: 3,
    io_mode: 'strict',
    nodes: [
      { id: 'source', type: 'source', kind: 'source' },
      {
        id: 'consumer',
        type: 'task',
        kind: 'task',
        config: {
          skill_slug: 'x',
          inputs_map: {
            blank_owner: { node_id: ' ', path: [] },
            mixed_path: { node_id: 'run', path: ['query', 0] },
            bad_required: { node_id: 'run', path: ['query'], required: 'false' },
          },
        },
      },
    ],
    edges: [{ from: 'source', to: 'consumer', kind: 'data' }],
  } as unknown as CanonicalFlow;
  const invalid = svc()
    .validateFlow(flow)
    .filter(
      (issue) => issue.code === 'variable_contract_invalid' && issue.node_id === 'consumer',
    );
  assert.equal(invalid.length, 3);
  assert.ok(invalid.every((issue) => issue.level === 'error'));
});

test('strict dot-path conversion refuses empty path segments', () => {
  const flow: CanonicalFlow = {
    schema_version: 3,
    io_mode: 'strict',
    variable_namespaces: ['session'],
    nodes: [
      {
        id: 'consumer',
        type: 'task',
        kind: 'task',
        config: { skill_slug: 'x', inputs_map: { q: 'session..objective' } },
      },
    ],
    edges: [],
  };
  assert.equal(svc().dotPathToVariableRef('session..objective', flow), null);
  const nodeFlow: CanonicalFlow = {
    ...flow,
    nodes: [
      { id: 'task.primary', type: 'source', kind: 'source' },
      ...flow.nodes,
    ],
  };
  assert.equal(svc().dotPathToVariableRef('task.primary.', nodeFlow), null);
  assert.ok(svc().validateFlow(flow).some((issue) => issue.code === 'variable_unresolved'));
});

test('topoSort returns an order for a DAG and null for a cycle', () => {
  const s = svc();
  const dag: CanonicalFlow = {
    schema_version: 2,
    nodes: [
      { id: 'a', type: 'source', kind: 'source' },
      { id: 'b', type: 'task', kind: 'task' },
      { id: 'c', type: 'sink', kind: 'sink' },
    ],
    edges: [
      { from: 'a', to: 'b' },
      { from: 'b', to: 'c' },
    ],
  };
  const order = s.topoSort(dag);
  assert.ok(order);
  assert.ok(order!.indexOf('a') < order!.indexOf('b'));
  assert.ok(order!.indexOf('b') < order!.indexOf('c'));

  const cyclic: CanonicalFlow = {
    schema_version: 2,
    nodes: [
      { id: 'a', type: 'task', kind: 'task' },
      { id: 'b', type: 'task', kind: 'task' },
    ],
    edges: [
      { from: 'a', to: 'b' },
      { from: 'b', to: 'a' },
    ],
  };
  assert.equal(s.topoSort(cyclic), null);
});

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
  canonicalEdgeIdentity,
  decisionConditionValidationError,
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

test('strict label review ports are derived on normalization and cannot be forged by a draft', () => {
  const s = svc();
  const flow: CanonicalFlow = { source: 'flow', schema_version: 3, io_mode: 'strict', nodes: [
    { id: 'source', type: 'source', kind: 'source', outputs: [{ name: 'dataset_id', schema: 'string' }] },
    { id: 'review', type: 'hitl', kind: 'hitl', outputs: [{ name: 'approved', schema: 'boolean' }],
      config: { prompt: 'Review labels', prompt_kind: 'review_dataset_labels',
        inputs_map: { dataset_id: { node_id: 'source', path: ['dataset_id'], required: true } } } },
    { id: 'sink', type: 'sink', kind: 'sink', inputs: [{ name: 'dataset_id', schema: 'string' }],
      config: { inputs_map: { dataset_id: { node_id: 'review', path: ['dataset_id'], required: true } } } },
  ], edges: [{ from: 'source', to: 'review' }, { from: 'review', to: 'sink' }] };
  assert.deepEqual(s.validateFlow(flow).filter(issue => issue.level === 'error'), []);
  const normalized = s.normalize(flow);
  assert.ok(normalized.nodes[1].outputs?.some(port => port.name === 'dataset_id'));
  assert.deepEqual(s.normalize(normalized), normalized);
  flow.nodes[1].config = { ...flow.nodes[1].config, prompt_kind: 'approve_write' };
  flow.nodes[1].outputs = [{ name: 'dataset_id', schema: 'string' }];
  assert.ok(s.validateFlow(flow).some(issue => issue.code === 'variable_unresolved' && issue.level === 'error'));
});

test('normalizing HITL preserves authored context and only fixes the reviewed dataset type', () => {
  const s = svc();
  const inputs = [
    { name: 'in', schema: 'string', required: true, description: 'Automation approval text' },
    { name: 'custom', schema: 'object', description: 'Authored context' },
    { name: 'dataset_id', schema: 'integer', required: true },
  ];
  const gate = { id: 'gate', type: 'hitl', kind: 'hitl' as const, inputs, config: { prompt_kind: 'approve_write' } };
  assert.deepEqual(s.normalizeNode(gate).inputs, inputs);
  const review = s.normalizeNode({ ...gate, config: { prompt_kind: 'review_dataset_labels' } });
  assert.deepEqual(review.inputs, [inputs[0], inputs[1], { ...inputs[2], schema: 'string' }]);
  assert.equal(inputs[2].schema, 'integer', 'normalization does not mutate the imported graph');
  assert.deepEqual(s.normalizeNode(review), review);
});

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

test('error routing requires an explicit policy and a real error edge', () => {
  const valid: CanonicalFlow = {
    schema_version: 3,
    nodes: [
      { id: 'task', type: 'skill', kind: 'task', config: { skill_slug: 'x', on_error: 'route' } },
      { id: 'handler', type: 'skill', kind: 'task', config: { skill_slug: 'audit_log_v1' } },
    ],
    edges: [{ from: 'task', to: 'handler', kind: 'error', from_port: 'error' }],
  };
  const missing: CanonicalFlow = {
    schema_version: 3,
    nodes: [
      { id: 'task', type: 'skill', kind: 'task', config: { skill_slug: 'x', on_error: 'route' } },
    ],
    edges: [],
  };
  const invalid: CanonicalFlow = {
    schema_version: 3,
    nodes: [
      { id: 'task', type: 'skill', kind: 'task', config: { skill_slug: 'x', on_error: 'ignore' } },
    ],
    edges: [],
  };

  assert.ok(!svc().validateFlow(valid).some((issue) => issue.code.startsWith('on_error_')));
  assert.ok(svc().validateFlow(missing).some((issue) => issue.code === 'on_error_route_missing'));
  assert.ok(svc().validateFlow(invalid).some((issue) => issue.code === 'on_error_invalid'));
});

test('join quorum is bounded by its incoming branches', () => {
  const flow: CanonicalFlow = {
    schema_version: 3,
    nodes: [
      { id: 'join', type: 'join', kind: 'join', config: { strategy: 'all', min_success: 2 } },
    ],
    edges: [],
  };

  assert.ok(svc().validateFlow(flow).some((issue) => issue.code === 'join_min_success_invalid'));
});

test('validateFlow rejects duplicate node ids before ambiguous map construction', () => {
  const flow: CanonicalFlow = {
    nodes: [
      { id: 'same', type: 'source', kind: 'source' },
      { id: 'same', type: 'sink', kind: 'sink' },
    ],
    edges: [],
  };

  const issues = svc().validateFlow(flow);
  assert.deepEqual(issues.map((issue) => issue.code), ['node_id_duplicate']);
  assert.equal(issues[0]?.node_id, 'same');
  assert.equal(issues[0]?.level, 'error');
});

test('edge identity is structured, collision-free and rejects true duplicates', () => {
  const first = { from: 'a|b', to: 'c', kind: 'data' as const };
  const delimiterCollision = { from: 'a', to: 'b|c', kind: 'data' as const };
  assert.notEqual(canonicalEdgeIdentity(first), canonicalEdgeIdentity(delimiterCollision));

  const flow: CanonicalFlow = {
    nodes: [
      { id: 'a|b', type: 'source', kind: 'source' },
      { id: 'a', type: 'source', kind: 'source' },
      { id: 'c', type: 'sink', kind: 'sink' },
      { id: 'b|c', type: 'sink', kind: 'sink' },
    ],
    edges: [first, delimiterCollision],
  };
  assert.ok(!svc().validateFlow(flow).some((issue) => issue.code === 'edge_duplicate'));

  flow.edges.push({ ...first });
  const duplicates = svc().validateFlow(flow)
    .filter((issue) => issue.code === 'edge_duplicate');
  assert.equal(duplicates.length, 1);
  assert.equal(duplicates[0]?.edge_index, 2);
  assert.equal(duplicates[0]?.level, 'error');
});

test('strict Flow requires exactly one explicit output sink', () => {
  const missing: CanonicalFlow = {
    schema_version: 3,
    io_mode: 'strict',
    nodes: [{ id: 'source', type: 'source', kind: 'source' }],
    edges: [],
  };
  assert.ok(svc().validateFlow(missing).some(
    (issue) => issue.code === 'flow_output_sink_required' && issue.level === 'error',
  ));

  const ambiguous: CanonicalFlow = {
    schema_version: 3,
    io_mode: 'strict',
    nodes: [
      { id: 'source', type: 'source', kind: 'source' },
      { id: 'first', type: 'sink', kind: 'sink' },
      { id: 'second', type: 'sink', kind: 'sink' },
    ],
    edges: [
      { from: 'source', to: 'first' },
      { from: 'source', to: 'second' },
    ],
  };
  assert.ok(svc().validateFlow(ambiguous).some(
    (issue) => issue.code === 'flow_output_sink_ambiguous' && issue.level === 'error',
  ));

  const exact: CanonicalFlow = {
    schema_version: 3,
    io_mode: 'strict',
    nodes: [
      { id: 'source', type: 'source', kind: 'source' },
      { id: 'result', type: 'sink', kind: 'sink' },
    ],
    edges: [{ from: 'source', to: 'result' }],
  };
  assert.deepEqual(svc().validateFlow(exact), []);
});

test('Decision condition structural validation accepts the runtime DSL and rejects unsafe syntax', () => {
  for (const expression of [
    'value == True',
    "scenario == 'nominal' and human_approved != False",
    "'password_reset' in intent",
    '(score >= 50 or context_count == 0) and not failed',
    'run.approved == True',
    'sub_queries != [] and sub_queries != None',
  ]) {
    assert.equal(decisionConditionValidationError(expression), null, expression);
  }
  assert.equal(decisionConditionValidationError(''), 'condition_empty');
  assert.equal(decisionConditionValidationError("__import__('os')"), 'condition_unsupported');
  assert.equal(decisionConditionValidationError('ctx.deep.value == 1'), 'condition_unsupported');
  assert.equal(decisionConditionValidationError('items[0] == 1'), 'condition_unsupported');
  assert.equal(decisionConditionValidationError('value = True'), 'condition_syntax_error');
});

test('validateFlow accepts a fully wired Decision contract', () => {
  const flow: CanonicalFlow = {
    schema_version: 3,
    nodes: [
      {
        id: 'decision',
        type: 'decision',
        kind: 'decision',
        config: {
          branches: [
            { label: 'yes', condition: 'value == True' },
            { label: 'no', condition: 'value == False' },
          ],
          default_branch: 'no',
        },
      },
      { id: 'yes', type: 'sink', kind: 'sink' },
      { id: 'no', type: 'sink', kind: 'sink' },
    ],
    edges: [
      { from: 'decision', to: 'yes', kind: 'branch', branch_label: 'yes' },
      { from: 'decision', to: 'no', kind: 'branch', branch_label: 'no' },
    ],
  };
  assert.deepEqual(svc().validateFlow(flow), []);
});

test('validateFlow mirrors Decision contract diagnostics', () => {
  const flow: CanonicalFlow = {
    schema_version: 3,
    nodes: [
      {
        id: 'decision',
        type: 'decision',
        kind: 'decision',
        config: {
          branches: [
            { label: 'duplicate', condition: '' },
            { label: 'duplicate', condition: "__import__('os')" },
          ],
          default_branch: 'missing',
        },
      },
      { id: 'sink', type: 'sink', kind: 'sink' },
    ],
    edges: [
      { from: 'decision', to: 'sink', kind: 'branch', branch_label: 'duplicate' },
    ],
  };
  const codes = new Set(svc().validateFlow(flow).map((issue) => issue.code));
  assert.ok(codes.has('decision_condition_invalid'));
  assert.ok(codes.has('decision_branch_duplicate'));
  assert.ok(codes.has('decision_default_invalid'));
});

test('validateFlow reports unwired Decision routes and foreign branch edges', () => {
  const flow: CanonicalFlow = {
    schema_version: 3,
    nodes: [
      {
        id: 'decision',
        type: 'decision',
        kind: 'decision',
        config: {
          branches: [
            { label: 'yes', condition: 'True' },
            { label: 'no', condition: 'False' },
          ],
        },
      },
      { id: 'source', type: 'source', kind: 'source' },
      { id: 'sink', type: 'sink', kind: 'sink' },
    ],
    edges: [
      { from: 'decision', to: 'sink', kind: 'branch', branch_label: 'yes' },
      { from: 'source', to: 'sink', kind: 'branch', branch_label: 'no' },
    ],
  };
  const codes = new Set(svc().validateFlow(flow).map((issue) => issue.code));
  assert.ok(codes.has('decision_branch_unwired'));
  assert.ok(codes.has('branch_edge_invalid'));
});

test('validateFlow pairs fork/join by real reconvergence, not global counts', () => {
  const flow: CanonicalFlow = {
    schema_version: 3,
    nodes: [
      { id: 'fork', type: 'fork', kind: 'fork', config: { branches: ['a', 'b'] } },
      { id: 'a', type: 'sink', kind: 'sink' },
      { id: 'b', type: 'sink', kind: 'sink' },
      { id: 'left', type: 'source', kind: 'source' },
      { id: 'right', type: 'source', kind: 'source' },
      { id: 'join', type: 'join', kind: 'join', config: { strategy: 'all' } },
    ],
    edges: [
      { from: 'fork', to: 'a', kind: 'data', from_port: 'a' },
      { from: 'fork', to: 'b', kind: 'data', from_port: 'b' },
      { from: 'left', to: 'join', kind: 'data' },
      { from: 'right', to: 'join', kind: 'data' },
    ],
  };
  const issues = svc().validateFlow(flow);
  assert.ok(issues.some((issue) => issue.code === 'fork_unjoined'));
  assert.ok(issues.some((issue) => issue.code === 'join_without_matching_fork'));
  assert.ok(issues.filter((issue) => issue.code === 'fork_unjoined').every((issue) => issue.level === 'warn'));

  flow.io_mode = 'strict';
  assert.ok(
    svc().validateFlow(flow).some(
      (issue) => issue.code === 'fork_unjoined' && issue.level === 'error',
    ),
  );
});

test('validateFlow accepts a labelled fork whose lanes post-dominate at a join', () => {
  const flow: CanonicalFlow = {
    schema_version: 3,
    nodes: [
      { id: 'fork', type: 'fork', kind: 'fork', config: { branches: ['a', 'b'] } },
      { id: 'a', type: 'task', kind: 'task', config: { skill_slug: 'a' } },
      { id: 'b', type: 'task', kind: 'task', config: { skill_slug: 'b' } },
      { id: 'join', type: 'join', kind: 'join', config: { strategy: 'all' } },
      { id: 'sink', type: 'sink', kind: 'sink' },
    ],
    edges: [
      { from: 'fork', to: 'a', kind: 'data', from_port: 'a' },
      { from: 'fork', to: 'b', kind: 'data', from_port: 'b' },
      { from: 'a', to: 'join', kind: 'data' },
      { from: 'b', to: 'join', kind: 'data' },
      { from: 'join', to: 'sink', kind: 'data' },
    ],
  };
  const topologyCodes = new Set([
    'fork_fanout_invalid',
    'fork_unjoined',
    'join_fanin_invalid',
    'join_without_matching_fork',
    'branch_label_invalid',
    'join_strategy_invalid',
  ]);
  assert.ok(!svc().validateFlow(flow).some((issue) => topologyCodes.has(issue.code)));
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

test('ingress kind typos and inbound source nodes are blocking', () => {
  const typo: CanonicalFlow = {
    schema_version: 3,
    nodes: [
      {
        id: 'webhook',
        type: 'source.webhook',
        kind: 'source',
        config: { ingress_kind: 'htp' },
      },
    ],
    edges: [],
  };
  const inbound: CanonicalFlow = {
    schema_version: 3,
    nodes: [
      { id: 'entry', type: 'source', kind: 'source' },
      { id: 'nested', type: 'source', kind: 'source' },
    ],
    edges: [{ from: 'entry', to: 'nested', kind: 'data' }],
  };

  assert.ok(
    svc().validateFlow(typo).some((issue) => issue.code === 'ingress_kind_invalid'),
  );
  assert.ok(
    svc()
      .validateFlow(inbound)
      .some((issue) => issue.code === 'ingress_source_not_root'),
  );
});

test('agent loop requires a turn budget and a compact allowlist', () => {
  const flow: CanonicalFlow = {
    schema_version: 3,
    nodes: [
      {
        id: 'loop.itsd',
        type: 'agent_loop',
        kind: 'agent_loop',
        config: { budget: { max_turns: 0 }, skill_allowlist: [] },
      },
    ],
    edges: [],
  };
  const codes = svc().validateFlow(flow).map((issue) => issue.code);
  assert.ok(codes.includes('agent_loop_no_budget'));
  assert.ok(codes.includes('agent_loop_allowlist'));
});

test('loop and retry budgets must be finite positive integers', () => {
  for (const [kind, field] of [
    ['loop', 'max_iterations'],
    ['retry', 'max_attempts'],
  ] as const) {
    for (const value of [true, 1.5, Number.NaN]) {
      const flow: CanonicalFlow = {
        schema_version: 3,
        nodes: [
          {
            id: `${kind}.node`,
            type: kind,
            kind,
            config: { [field]: value },
          },
        ],
        edges: [],
      };
      const code = kind === 'loop' ? 'loop_no_budget' : 'retry_no_target';
      assert.ok(svc().validateFlow(flow).some((issue) => issue.code === code));
    }
  }
});


test('strict retraining approval preserves proposal wiring and derives its portable verdict output', () => {
  const s = svc();
  const flow: CanonicalFlow = {source:'flow',schema_version:3,io_mode:'strict',nodes:[
    {id:'source',type:'source',kind:'source',outputs:[{name:'proposal_id',schema:'string'}]},
    {id:'review',type:'hitl',kind:'hitl',inputs:[{name:'proposal_id',schema:'string'}],outputs:[{name:'approved',schema:'boolean'}],config:{prompt_kind:'approve_model_retraining',inputs_map:{proposal_id:{node_id:'source',path:['proposal_id'],required:true}}}},
    {id:'sink',type:'sink',kind:'sink',inputs:[{name:'proposal_id',schema:'string'}],config:{inputs_map:{proposal_id:{node_id:'review',path:['proposal_id'],required:true}}}},
  ],edges:[{from:'source',to:'review'},{from:'review',to:'sink'}]};
  assert.deepEqual(s.validateFlow(flow).filter(issue => issue.level === 'error'), []);
  const normalized = s.normalize(flow);
  assert.deepEqual(normalized.nodes[1].inputs, flow.nodes[1].inputs);
  assert.ok(normalized.nodes[1].outputs?.some(port => port.name === 'proposal_id' && port.schema === 'string'));
  assert.deepEqual(s.normalize(normalized), normalized);
  flow.nodes[1].config = {...flow.nodes[1].config,prompt_kind:'approve_write'};
  assert.ok(s.validateFlow(flow).some(issue => issue.code === 'variable_unresolved' && issue.level === 'error'));
});

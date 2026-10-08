/**
 * Unit tests for the variable-membrane catalog (`flow-variable.service.ts`).
 *
 * Covers the two P2 picker guarantees:
 *   - **upstream-only**: `upstreamOutputs` returns the output ports of graph
 *     ancestors of the selected node, never of self, downstream, or parallel
 *     branches — matching `validateFlow`'s upstream definition.
 *   - **type filtering**: `filterCompatibleCandidates` keeps exactly what the
 *     primitive-compat rule accepts (number/integer compatible; unknown /
 *     `ref:` / object-vs-object kept; cross-primitive dropped).
 *
 * Pure logic: `@angular/core` is stubbed at bundle time. Run with
 * `npm run test:unit`.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { FlowSerializerService } from '@app/core/flow-serializer.service';
import type {
  CanonicalFlowEdge,
  CanonicalFlowNode,
} from '@app/core/flow-serializer.service';
import {
  decodeCandidateValue,
  encodeCandidateValue,
  filterCompatibleCandidates,
  upstreamOutputs,
  variableRefFor,
  type VariableCandidate,
} from './flow-variable.service';

// a → b → c (linear); d is a parallel sibling feeding c only.
function graph(): { nodes: CanonicalFlowNode[]; edges: CanonicalFlowEdge[] } {
  const nodes: CanonicalFlowNode[] = [
    { id: 'a', type: 'source', kind: 'source', label: 'Objective', outputs: [{ name: 'goal', schema: 'string' }] },
    {
      id: 'b',
      type: 'task',
      kind: 'task',
      label: 'Retrieve',
      inputs: [{ name: 'query', schema: 'string' }],
      outputs: [
        { name: 'context', schema: 'object' },
        { name: 'score', schema: 'number' },
      ],
    },
    { id: 'c', type: 'task', kind: 'task', label: 'Generate', inputs: [{ name: 'ctx', schema: 'object' }] },
    { id: 'd', type: 'task', kind: 'task', label: 'Side', outputs: [{ name: 'note', schema: 'string' }] },
  ];
  const edges: CanonicalFlowEdge[] = [
    { from: 'a', to: 'b', kind: 'data' },
    { from: 'b', to: 'c', kind: 'data' },
    { from: 'd', to: 'c', kind: 'data' },
  ];
  return { nodes, edges };
}

test('upstreamOutputs returns only ancestors of the selected node', () => {
  const { nodes, edges } = graph();
  // For c, ancestors are a, b, d → all their output ports.
  const forC = upstreamOutputs('c', nodes, edges);
  const labels = forC.map((x) => `${x.node_id}.${x.port}`).sort();
  assert.deepEqual(labels, ['a.goal', 'b.context', 'b.score', 'd.note']);
});

test('review dataset can be selected from a legacy HITL declaration without trusting forged ports', () => {
  const nodes: CanonicalFlowNode[] = [
    { id: 'review', type: 'hitl', kind: 'hitl', config: { prompt_kind: 'review_dataset_labels' },
      outputs: [{ name: 'approved', schema: 'boolean' }, { name: 'forged', schema: 'string' }] },
    { id: 'train', type: 'task', kind: 'task' },
  ];
  const candidates = upstreamOutputs('train', nodes, [{ from: 'review', to: 'train' }]);
  assert.ok(candidates.some(candidate => candidate.port === 'dataset_id' && candidate.schema === 'string'));
  assert.ok(!candidates.some(candidate => candidate.port === 'forged'));
  nodes[0].config = { prompt_kind: 'approve_write' };
  assert.ok(!upstreamOutputs('train', nodes, [{ from: 'review', to: 'train' }]).some(candidate => candidate.port === 'dataset_id'));
});

test('automation approval still offers upstream text after loading in the Flow editor', () => {
  const serializer = new FlowSerializerService();
  const nodes: CanonicalFlowNode[] = [
    { id: 'agent', type: 'task', kind: 'task', outputs: [{ name: 'completion', schema: 'string' }] },
    serializer.normalizeNode({ id: 'gate', type: 'hitl', kind: 'hitl',
      config: { prompt_kind: 'approve_write' }, inputs: [{ name: 'in', schema: 'string' }] }),
  ];
  const candidates = upstreamOutputs('gate', nodes, [{ from: 'agent', to: 'gate' }]);
  const compatible = filterCompatibleCandidates(candidates, nodes[1].inputs![0].schema);
  assert.equal(compatible.length, 1);
  assert.equal(compatible[0].port, 'completion');
});

test('upstreamOutputs excludes self, downstream and parallel non-ancestors', () => {
  const { nodes, edges } = graph();
  // For b, the only ancestor is a; c is downstream and d is a parallel branch.
  const forB = upstreamOutputs('b', nodes, edges);
  assert.deepEqual(forB.map((x) => x.node_id), ['a']);
  assert.ok(!forB.some((x) => x.node_id === 'b'), 'never reads from self');
  assert.ok(!forB.some((x) => x.node_id === 'c'), 'never reads downstream');
  assert.ok(!forB.some((x) => x.node_id === 'd'), 'never reads a parallel branch');
});

test('upstreamOutputs returns [] for a root node and for unknown selection', () => {
  const { nodes, edges } = graph();
  assert.deepEqual(upstreamOutputs('a', nodes, edges), []);
  assert.deepEqual(upstreamOutputs('ghost', nodes, edges), []);
  assert.deepEqual(upstreamOutputs(null, nodes, edges), []);
});

test('upstreamOutputs enriches portless nodes from the manifest output_schema', () => {
  const nodes: CanonicalFlowNode[] = [
    { id: 'a', type: 'task', kind: 'task', label: 'Fetch' }, // no declared outputs
    { id: 'b', type: 'task', kind: 'task', label: 'Use' },
  ];
  const edges: CanonicalFlowEdge[] = [{ from: 'a', to: 'b', kind: 'data' }];
  const candidates = upstreamOutputs('b', nodes, edges, {
    outputSchemaFor: (id) =>
      id === 'a'
        ? { properties: { answer: { type: 'string' }, hits: { type: 'integer' } } }
        : null,
  });
  const byPort = candidates.map((c) => `${c.port}:${c.schema}`).sort();
  assert.deepEqual(byPort, ['answer:string', 'hits:integer']);
});

test('upstreamOutputs orders candidates by the supplied topological order', () => {
  const { nodes, edges } = graph();
  // Reverse topo order → d before b before a; candidates follow node position.
  const ordered = upstreamOutputs('c', nodes, edges, { order: ['d', 'b', 'a'] });
  const firstNode = ordered[0].node_id;
  assert.equal(firstNode, 'd', 'first candidate follows the provided order');
});

test('filterCompatibleCandidates reuses the primitive-compat rule', () => {
  const candidates: VariableCandidate[] = [
    { node_id: 'a', port: 'goal', schema: 'string', label: 'a · goal' },
    { node_id: 'b', port: 'score', schema: 'number', label: 'b · score' },
    { node_id: 'b', port: 'count', schema: 'integer', label: 'b · count' },
    { node_id: 'b', port: 'ctx', schema: 'object', label: 'b · ctx' },
    { node_id: 'b', port: 'ref', schema: 'ref:run.input', label: 'b · ref' },
  ];

  // target number → number + integer (numeric widening) + unknown ref kept;
  // string + object dropped.
  const forNumber = filterCompatibleCandidates(candidates, 'number').map((c) => c.port).sort();
  assert.deepEqual(forNumber, ['count', 'ref', 'score']);

  // target string → string + unknown ref kept; number/integer/object dropped.
  const forString = filterCompatibleCandidates(candidates, 'string').map((c) => c.port).sort();
  assert.deepEqual(forString, ['goal', 'ref']);
});

test('encode/decode round-trips and variableRefFor builds a typed selector', () => {
  const v = encodeCandidateValue('b', 'context');
  assert.deepEqual(decodeCandidateValue(v), { node_id: 'b', port: 'context' });
  assert.equal(decodeCandidateValue('no-separator'), null);
  assert.deepEqual(variableRefFor('b', 'context'), { node_id: 'b', path: ['context'] });
});

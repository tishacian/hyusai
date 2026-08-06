/**
 * Unit tests for the engine boundary (`flow-foblex.adapter.ts`).
 *
 * These cover the plan §4 acceptance criterion **edge/link stability**: a
 * link stays attached to its ports across node move / zoom / pan / resize
 * with NO manual redraw. The proof is structural and engine-agnostic — the
 * adapter derives every Foblex connector id from `(nodeId, portName)` only,
 * never from a pixel position or the viewport transform. So moving a node
 * (changing `position`) or zooming/panning/resizing (which are not even part
 * of the model) cannot change a connector id; Foblex re-anchors the path to
 * the same connector automatically. That is exactly what replaces the old
 * Drawflow `redrawStableConnectionPaths()` hack.
 *
 * Run with: `npm run test:unit` (esbuild bundle → `node --test`).
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import type {
  CanonicalFlowEdge,
  CanonicalFlowNode,
} from '@app/core/flow-serializer.service';
import {
  connectorsToEdge,
  inputConnectorId,
  outputConnectorId,
  parseConnectorId,
  toConnectionViews,
  toNodeViews,
} from './flow-foblex.adapter';

function graph(): { nodes: CanonicalFlowNode[]; edges: CanonicalFlowEdge[] } {
  const nodes: CanonicalFlowNode[] = [
    {
      id: 'flow.start',
      type: 'source',
      kind: 'source',
      label: 'Objective',
      outputs: [{ name: 'goal', schema: 'string' }],
      position: { x: 80, y: 160 },
    },
    {
      id: 'flow.retrieve',
      type: 'retrieve',
      kind: 'task',
      label: 'Retrieve',
      inputs: [{ name: 'query', schema: 'string' }],
      outputs: [{ name: 'context', schema: 'object' }],
      position: { x: 380, y: 160 },
    },
    {
      id: 'flow.output',
      type: 'sink',
      kind: 'sink',
      label: 'Output',
      inputs: [{ name: 'result', schema: 'object' }],
      position: { x: 680, y: 160 },
    },
  ];
  const edges: CanonicalFlowEdge[] = [
    { from: 'flow.start', to: 'flow.retrieve', kind: 'data', from_port: 'goal', to_port: 'query' },
    { from: 'flow.retrieve', to: 'flow.output', kind: 'data', from_port: 'context', to_port: 'result' },
  ];
  return { nodes, edges };
}

test('connector ids are derived from (nodeId, port), not coordinates', () => {
  assert.equal(outputConnectorId('n1', 'goal'), 'n1::out::goal');
  assert.equal(inputConnectorId('n1', 'query'), 'n1::in::query');
  // Default (implicit) port uses the sentinel and round-trips to undefined.
  assert.equal(outputConnectorId('n1'), 'n1::out::_');
  assert.deepEqual(parseConnectorId('n1::out::_'), { nodeId: 'n1', direction: 'out', port: undefined });
  assert.deepEqual(parseConnectorId('n1::in::query'), { nodeId: 'n1', direction: 'in', port: 'query' });
});

test('source renders no input connector; sink renders no output connector', () => {
  const [start, , output] = toNodeViews(graph().nodes);
  assert.equal(start.inputs.length, 0, 'source has no inputs');
  assert.equal(start.outputs.length, 1);
  assert.equal(output.outputs.length, 0, 'sink has no outputs');
  assert.equal(output.inputs.length, 1);
});

test('EDGE STABILITY: connector source/target ids are invariant under node move / zoom / pan / resize', () => {
  const { nodes, edges } = graph();
  const before = toConnectionViews(edges, nodes).map((c) => ({ source: c.source, target: c.target }));

  // Simulate a drag (move) — only `position` changes. Zoom/pan/resize never
  // touch the model at all, so a position change is the strongest mutation.
  const moved = nodes.map((n) => ({ ...n, position: { x: n.position!.x + 999, y: n.position!.y - 540 } }));
  const after = toConnectionViews(edges, moved).map((c) => ({ source: c.source, target: c.target }));

  assert.deepEqual(after, before, 'links must stay attached to the same connectors after a move');
  // And no connector id leaks a coordinate — proving anchors are port-based.
  for (const c of before) {
    assert.match(c.source, /::out::/);
    assert.match(c.target, /::in::/);
    assert.doesNotMatch(c.source + c.target, /\d{3,}/, 'no pixel coordinates in connector ids');
  }
});

test('toConnectionViews resolves to connectors the node actually renders (never dangles)', () => {
  const { nodes } = graph();
  // Edge references a from_port that does not exist on the source node.
  const bogus: CanonicalFlowEdge[] = [
    { from: 'flow.retrieve', to: 'flow.output', from_port: 'does-not-exist', to_port: 'nope' },
  ];
  const [conn] = toConnectionViews(bogus, nodes);
  // Falls back to the first real port on each side, so the path still attaches.
  assert.equal(conn.source, 'flow.retrieve::out::context');
  assert.equal(conn.target, 'flow.output::in::result');
});

test('connectorsToEdge round-trips and is order-defensive', () => {
  const out = outputConnectorId('a', 'context');
  const inp = inputConnectorId('b', 'result');

  const forward = connectorsToEdge(out, inp);
  assert.deepEqual(forward, { from: 'a', to: 'b', kind: 'data', from_port: 'context', to_port: 'result' });

  // Foblex may hand (output, input) in either order — adapter normalizes it.
  const reversed = connectorsToEdge(inp, out);
  assert.deepEqual(reversed, forward, 'reversed connector pair yields the same edge');

  // Two outputs (or two inputs) is not a valid connection.
  assert.equal(connectorsToEdge(out, outputConnectorId('c', 'x')), null);
});

test('view → connection → edge round-trip preserves endpoints', () => {
  const { nodes, edges } = graph();
  const views = toConnectionViews(edges, nodes);
  for (const v of views) {
    const edge = connectorsToEdge(v.source, v.target);
    assert.ok(edge, 'connection must reproduce a valid edge');
    assert.equal(edge!.from, v.edge.from);
    assert.equal(edge!.to, v.edge.to);
  }
});

test('Decision route handles create canonical branch edges and preserve labels', () => {
  const decision: CanonicalFlowNode = {
    id: 'decision.approve',
    type: 'decision',
    kind: 'decision',
    inputs: [{ name: 'value', schema: 'object' }],
    outputs: [
      { name: 'yes', schema: 'object' },
      { name: 'no', schema: 'object' },
    ],
    config: {
      branches: [
        { label: 'yes', condition: 'value == True' },
        { label: 'no', condition: 'value == False' },
      ],
      default_branch: 'no',
    },
  };
  const sink: CanonicalFlowNode = {
    id: 'sink.yes',
    type: 'sink',
    kind: 'sink',
    inputs: [{ name: 'result', schema: 'object' }],
  };

  const edge = connectorsToEdge(
    outputConnectorId(decision.id, 'yes'),
    inputConnectorId(sink.id, 'result'),
    [decision, sink],
  );
  assert.deepEqual(edge, {
    from: decision.id,
    to: sink.id,
    kind: 'branch',
    branch_label: 'yes',
    from_port: 'yes',
    to_port: 'result',
  });

  const [view] = toConnectionViews([edge!], [decision, sink]);
  assert.equal(view.source, 'decision.approve::out::yes');
  assert.equal(view.branchLabel, 'yes');
  assert.match(view.id, /branch/);
  assert.match(view.id, /yes/);
});

test('legacy branch edges without from_port bind to their labelled Decision handle', () => {
  const decision: CanonicalFlowNode = {
    id: 'd',
    type: 'decision',
    kind: 'decision',
    outputs: [
      { name: 'yes', schema: 'object' },
      { name: 'no', schema: 'object' },
    ],
  };
  const sink: CanonicalFlowNode = { id: 's', type: 'sink', kind: 'sink' };
  const views = toConnectionViews([
    { from: 'd', to: 's', kind: 'branch', label: 'yes' },
    { from: 'd', to: 's', kind: 'branch', branch_label: 'no' },
  ], [decision, sink]);

  assert.equal(views[0].source, 'd::out::yes');
  assert.equal(views[1].source, 'd::out::no');
  assert.notEqual(views[0].id, views[1].id, 'branch label participates in edge identity');
});

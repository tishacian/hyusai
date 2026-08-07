import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { CanonicalFlow } from '@app/core/flow-serializer.service';
import {
  diffCanonicalFlows,
  formatFlowSemanticDiff,
} from './flow-semantic-diff.vm';

function flow(): CanonicalFlow {
  return {
    source: 'flow',
    schema_version: 3,
    io_mode: 'strict',
    variable_namespaces: ['case'],
    nodes: [
      { id: 'source', type: 'source', kind: 'source', config: {} },
      {
        id: 'decision',
        type: 'decision',
        kind: 'decision',
        label: 'Route',
        position: { x: 10, y: 20 },
        inputs: [{ name: 'value', schema: 'object' }],
        outputs: [{ name: 'yes', schema: 'object' }],
        config: {
          branches: [{ label: 'yes', condition: 'value == true' }],
          default_branch: 'yes',
        },
      },
      { id: 'sink', type: 'sink', kind: 'sink', config: {} },
    ],
    edges: [
      { from: 'source', to: 'decision', kind: 'data' },
      {
        from: 'decision',
        to: 'sink',
        kind: 'branch',
        branch_label: 'yes',
        from_port: 'yes',
        to_port: 'result',
      },
    ],
  };
}

test('semantic diff detects same-count node kind, port and config changes', () => {
  const baseline = flow();
  const candidate = structuredClone(baseline);
  const decision = candidate.nodes[1];
  decision.kind = 'task';
  decision.outputs = [{ name: 'approved', schema: 'boolean' }];
  decision.config = {
    default_branch: 'no',
    branches: [{ condition: 'value == false', label: 'no' }],
  };

  const diff = diffCanonicalFlows(baseline, candidate);
  assert.deepEqual(diff, {
    nodesAdded: 0,
    nodesRemoved: 0,
    nodesChanged: 1,
    nodeOrderChanged: false,
    edgesAdded: 0,
    edgesRemoved: 0,
    edgeOrderChanged: false,
    metadataChanged: false,
    executionContract: 'not_checked',
  });
  assert.equal(formatFlowSemanticDiff(diff), '~1n');
});

test('semantic diff detects edge kind, branch and port changes with equal counts', () => {
  const baseline = flow();
  const candidate = structuredClone(baseline);
  candidate.edges[1] = {
    from: 'decision',
    to: 'sink',
    kind: 'data',
    branch_label: 'no',
    from_port: 'approved',
    to_port: 'payload',
  };

  const diff = diffCanonicalFlows(baseline, candidate);
  assert.equal(diff.edgesAdded, 1);
  assert.equal(diff.edgesRemoved, 1);
  assert.equal(formatFlowSemanticDiff(diff), '+1 -1e');
});

test('semantic diff treats executable node and edge ordering as observable', () => {
  const baseline = flow();
  const reordered = structuredClone(baseline);
  reordered.nodes.reverse();
  reordered.edges.reverse();
  const decision = reordered.nodes.find((node) => node.id === 'decision');
  assert.ok(decision);
  decision.position = { x: 999, y: 888 };
  decision.config = {
    default_branch: 'yes',
    branches: [{ condition: 'value == true', label: 'yes' }],
  };
  assert.equal(
    formatFlowSemanticDiff(diffCanonicalFlows(baseline, reordered)),
    '↕n order · ↕e order',
  );

  const layoutOnly = structuredClone(baseline);
  layoutOnly.nodes[1].position = { x: 999, y: 888 };
  assert.equal(formatFlowSemanticDiff(diffCanonicalFlows(baseline, layoutOnly)), '= canvas');

  const metadata = structuredClone(baseline);
  metadata.variable_namespaces = ['case', 'ticket'];
  assert.equal(formatFlowSemanticDiff(diffCanonicalFlows(baseline, metadata)), '~flow');
});

test('semantic diff reports additions and removals rather than only count deltas', () => {
  const baseline = flow();
  const candidate = structuredClone(baseline);
  candidate.nodes = [
    candidate.nodes[0],
    candidate.nodes[1],
    { id: 'replacement', type: 'sink', kind: 'sink', config: {} },
  ];
  const diff = diffCanonicalFlows(baseline, candidate);
  assert.equal(diff.nodesAdded, 1);
  assert.equal(diff.nodesRemoved, 1);
  assert.equal(formatFlowSemanticDiff(diff), '+1 -1n');
});

test('semantic diff distinguishes changed and pinned-but-uncomparable contracts', () => {
  const baseline = flow();
  const candidate = structuredClone(baseline);
  const changed = diffCanonicalFlows(baseline, candidate, {
    executionContracts: {
      comparable: true,
      baseline: { contract_sha256: 'before' },
      candidate: { contract_sha256: 'after' },
    },
  });
  assert.equal(changed.executionContract, 'changed');
  assert.equal(formatFlowSemanticDiff(changed), '~contract');

  const uncomparable = diffCanonicalFlows(baseline, candidate, {
    executionContracts: {
      comparable: false,
      baseline: null,
      candidate: { contract_sha256: 'pinned' },
    },
  });
  assert.equal(uncomparable.executionContract, 'pinned_uncompared');
  assert.equal(
    formatFlowSemanticDiff(uncomparable),
    'pinned contract · not comparable to draft',
  );
});

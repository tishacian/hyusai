import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  buildPreconnectEdge,
  firstCompatibleRenderedConnector,
  isPaletteItemConnectable,
} from './flow-preconnect';
import { DEFAULT_PALETTE, type PaletteItem } from './flow.types';
import type { CanonicalFlowNode } from '@app/core/flow-serializer.service';

function item(overrides: Partial<PaletteItem>): PaletteItem {
  return {
    type: 'test',
    kind: 'task',
    label: 'Test',
    description: 'Test node',
    icon: 'box',
    tone: 'cyan',
    ...overrides,
  };
}

test('Decision palette seed is executable and fail-closed by default', () => {
  const decision = DEFAULT_PALETTE.find((entry) => entry.kind === 'decision');
  assert.ok(decision);
  assert.deepEqual(decision!.inputs, [{ name: 'value', schema: 'any' }]);
  assert.deepEqual((decision!.config as any).branches, [
    { label: 'yes', condition: 'value == True' },
    { label: 'no', condition: 'value == False' },
  ]);
  assert.deepEqual((decision!.config as any).passthrough_inputs, ['value']);
  assert.equal((decision!.config as any).default_branch, 'no');
});

test('source and asset without inputs are not offered as targets', () => {
  const source = item({ kind: 'source', outputs: [{ name: 'event', schema: 'object' }] });
  const asset = item({ kind: 'asset', outputs: [{ name: 'document', schema: 'object' }] });

  assert.equal(isPaletteItemConnectable(source, 'in', 'object'), false);
  assert.equal(isPaletteItemConnectable(asset, 'in', 'object'), false);
  assert.equal(buildPreconnectEdge(
    { nodeId: 'origin', direction: 'out', port: 'payload' },
    asset,
    'new-asset',
    'object',
  ), null);

  assert.equal(isPaletteItemConnectable(source, 'out', 'object'), true);
  assert.equal(isPaletteItemConnectable(asset, 'out', 'object'), true);
});

test('sink without outputs is not offered as a source but keeps its input handle', () => {
  const sink = item({
    kind: 'sink',
    inputs: [{ name: 'result', schema: 'object' }],
  });

  assert.equal(isPaletteItemConnectable(sink, 'out', 'object'), false);
  assert.equal(isPaletteItemConnectable(sink, 'in', 'object'), true);
  assert.equal(buildPreconnectEdge(
    { nodeId: 'origin', direction: 'in', port: 'input' },
    sink,
    'new-sink',
    'object',
  ), null);
});

test('preconnect chooses the first compatible port, not the first declared port', () => {
  const target = item({
    inputs: [
      { name: 'metadata', schema: 'object' },
      { name: 'prompt', schema: 'string' },
      { name: 'fallback', schema: 'string' },
    ],
  });

  const connector = firstCompatibleRenderedConnector(target, 'in', 'string', 'new-task');
  assert.equal(connector?.name, 'prompt');
  assert.deepEqual(
    buildPreconnectEdge(
      { nodeId: 'origin', direction: 'out', port: 'goal' },
      target,
      'new-task',
      'string',
    ),
    {
      from: 'origin',
      to: 'new-task',
      kind: 'data',
      from_port: 'goal',
      to_port: 'prompt',
    },
  );
});

test('a port-less task uses its rendered implicit connector', () => {
  const passthrough = item({ inputs: [], outputs: [] });

  assert.equal(isPaletteItemConnectable(passthrough, 'in', 'string'), true);
  assert.equal(isPaletteItemConnectable(passthrough, 'out', 'object'), true);
  assert.deepEqual(
    buildPreconnectEdge(
      { nodeId: 'origin', direction: 'out', port: 'goal' },
      passthrough,
      'new-task',
      'string',
    ),
    { from: 'origin', to: 'new-task', kind: 'data', from_port: 'goal' },
  );
});

test('no compatible rendered port yields neither menu item nor edge', () => {
  const target = item({
    inputs: [
      { name: 'metadata', schema: 'object' },
      { name: 'enabled', schema: 'boolean' },
    ],
  });

  assert.equal(firstCompatibleRenderedConnector(target, 'in', 'string'), null);
  assert.equal(isPaletteItemConnectable(target, 'in', 'string'), false);
  assert.equal(buildPreconnectEdge(
    { nodeId: 'origin', direction: 'out', port: 'goal' },
    target,
    'new-task',
    'string',
  ), null);
});

test('preconnect from a Decision route creates a labelled branch edge', () => {
  const decision: CanonicalFlowNode = {
    id: 'decision',
    type: 'decision',
    kind: 'decision',
    outputs: [
      { name: 'yes', schema: 'object' },
      { name: 'no', schema: 'object' },
    ],
  };
  const target = item({
    kind: 'task',
    inputs: [{ name: 'payload', schema: 'object' }],
  });

  assert.deepEqual(
    buildPreconnectEdge(
      { nodeId: 'decision', direction: 'out', port: 'no' },
      target,
      'new-task',
      'object',
      decision,
    ),
    {
      from: 'decision',
      to: 'new-task',
      kind: 'branch',
      branch_label: 'no',
      from_port: 'no',
      to_port: 'payload',
    },
  );
});

test('inserting a Decision upstream uses its first route handle as a branch', () => {
  const decision = item({
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
  });

  assert.deepEqual(
    buildPreconnectEdge(
      { nodeId: 'target', direction: 'in', port: 'payload' },
      decision,
      'new-decision',
      'object',
    ),
    {
      from: 'new-decision',
      to: 'target',
      kind: 'branch',
      branch_label: 'yes',
      from_port: 'yes',
      to_port: 'payload',
    },
  );
});

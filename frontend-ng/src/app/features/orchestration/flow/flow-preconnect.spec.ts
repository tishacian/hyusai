import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  buildPreconnectEdge,
  firstCompatibleRenderedConnector,
  isPaletteItemConnectable,
} from './flow-preconnect';
import type { PaletteItem } from './flow.types';

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

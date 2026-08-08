import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { CanonicalFlow, CanonicalFlowNode } from '@app/core/flow-serializer.service';
import { ingressPrefillText, resolveIngressNode } from './flow-ingress-prefill';

function flow(...nodes: CanonicalFlowNode[]): CanonicalFlow {
  return { source: 'flow', schema_version: 3, nodes, edges: [] };
}

function source(overrides: Partial<CanonicalFlowNode> = {}): CanonicalFlowNode {
  return {
    id: 'flow.start',
    type: 'source',
    kind: 'source',
    label: 'Trigger',
    outputs: [{ name: 'goal', schema: 'string' }],
    ...overrides,
  };
}

test('with no declared schema the ingress ports name the payload keys', () => {
  assert.equal(ingressPrefillText(flow(source())), '{\n  "goal": ""\n}');
  assert.equal(
    ingressPrefillText(
      flow(source({ outputs: [{ name: 'payload', schema: 'object' }, { name: 'count', schema: 'integer' }] })),
    ),
    '{\n  "payload": {},\n  "count": 0\n}',
  );
});

test('a declared schema seeds what it demands and never invents an optional value', () => {
  const declared = source({
    config: {
      input_schema: {
        type: 'object',
        properties: {
          query: { type: 'string' },
          locale: { type: 'string', default: 'fr' },
          verbosity: { type: 'string', enum: ['short', 'long'] },
          optional_note: { type: 'string' },
        },
        required: ['query', 'verbosity'],
      },
    },
  });
  assert.deepEqual(JSON.parse(ingressPrefillText(flow(declared))!), {
    query: '',
    locale: 'fr',
    verbosity: 'short',
  });
});

test('nothing is prefilled when the entry point is ambiguous or demands nothing', () => {
  const second = source({ id: 'flow.webhook', type: 'source.webhook', label: 'Webhook' });
  assert.equal(ingressPrefillText(flow(source(), second)), null);
  // The operator's explicit draft-test choice resolves the ambiguity.
  assert.equal(ingressPrefillText(flow(source(), second), 'flow.webhook'), '{\n  "goal": ""\n}');
  assert.equal(resolveIngressNode(flow(source(), second), 'flow.missing'), null);

  const openContract = source({
    config: { input_schema: { type: 'object', additionalProperties: true } },
  });
  assert.equal(ingressPrefillText(flow(openContract)), null);
  assert.equal(
    ingressPrefillText(flow({ id: 'sink', type: 'sink', kind: 'sink' })),
    null,
  );
});

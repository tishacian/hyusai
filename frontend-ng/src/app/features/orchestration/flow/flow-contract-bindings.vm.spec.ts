/**
 * Locks the three node-contract rules the editor cannot ask the backend for.
 *
 * `derivedIngressKind` and `schemaFromPorts` are hand-mirrors of
 * `flow_contracts._ingress_kind` / `_ports_schema`. The cases below are the
 * exact branches of those two Python functions, so a drift on either side
 * fails here rather than in a published contract the operator never saw
 * coming. `conditionNames` only has to be good enough to label the Decision
 * editor while typing, and these cases pin what "good enough" means.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import type { CanonicalFlowNode } from '@app/core/flow-serializer.service';
import {
  conditionNames,
  derivedIngressKind,
  isIngressKind,
  schemaFromPorts,
} from './flow-contract-bindings.vm';

const node = (partial: Partial<CanonicalFlowNode>): CanonicalFlowNode =>
  ({ id: 'n', type: 'source', kind: 'source', ...partial }) as CanonicalFlowNode;

test('derived ingress kind mirrors every branch of flow_contracts._ingress_kind', () => {
  assert.equal(derivedIngressKind(node({ type: 'source.webhook' })), 'http');
  assert.equal(derivedIngressKind(node({ type: 'source.schedule' })), 'schedule');
  assert.equal(
    derivedIngressKind(node({ id: 'source.request', type: 'input' })),
    'chat',
    'the legacy governed-chat request port stays chat',
  );
  assert.equal(
    derivedIngressKind(node({ id: 'other', type: 'input' })),
    'manual',
    'only source.request may impersonate the chat surface',
  );
  assert.equal(derivedIngressKind(node({ type: 'source.sftp_arrival' })), 'event');
  assert.equal(derivedIngressKind(node({ type: 'source.deposit_promoted' })), 'event');
  assert.equal(
    derivedIngressKind(node({ type: 'source' })),
    'manual',
    'the palette Trigger node is a manual entry point',
  );
});

test('a node that is not an executable source has no derived ingress kind', () => {
  assert.equal(derivedIngressKind(node({ kind: 'task', type: 'task' })), null);
  assert.equal(
    derivedIngressKind(node({ kind: 'asset', type: 'source.collection' })),
    null,
    'a declarative collection asset is graph context, not an entry point',
  );
});

test('ingress kind guard accepts exactly the backend enum', () => {
  for (const kind of ['manual', 'chat', 'http', 'schedule', 'event']) {
    assert.equal(isIngressKind(kind), true, kind);
  }
  assert.equal(isIngressKind('sftp'), false);
  assert.equal(isIngressKind(''), false);
  assert.equal(isIngressKind(null), false);
});

test('schema derived from ports matches flow_contracts._ports_schema', () => {
  assert.deepEqual(
    schemaFromPorts([
      { name: 'goal', schema: 'string', required: true },
      { name: 'file', schema: 'object' },
      { name: 'other', schema: 'ref:Case' },
      { name: 'case', schema: 'string', required: true },
    ]),
    {
      $schema: 'https://json-schema.org/draft/2020-12/schema',
      type: 'object',
      properties: {
        goal: { type: 'string' },
        file: { type: 'object' },
        // A non-primitive port constrains nothing, exactly as the backend.
        other: {},
        case: { type: 'string' },
      },
      additionalProperties: true,
      required: ['case', 'goal'],
    },
  );
});

test('no required port means the derived schema omits required entirely', () => {
  const schema = schemaFromPorts([{ name: 'tick', schema: 'object' }]);
  assert.equal('required' in schema, false);
  assert.deepEqual(schema['properties'], { tick: { type: 'object' } });
});

test('condition names report what a Decision predicate reads', () => {
  assert.deepEqual(conditionNames('line_manager_approved == True'), [
    'line_manager_approved',
  ]);
  assert.deepEqual(
    conditionNames('score > 0.8 and status == "open"'),
    ['score', 'status'],
    'string literals and numbers are not names',
  );
  assert.deepEqual(
    conditionNames('ctx.retries < 3'),
    ['ctx'],
    'an attribute tail belongs to its namespace, not to the input',
  );
  assert.deepEqual(conditionNames('not approved or escalate'), ['approved', 'escalate']);
  assert.deepEqual(conditionNames(''), []);
});

test('condition names ignore an operator name hiding inside a string literal', () => {
  assert.deepEqual(
    conditionNames('label == "line_manager_approved"'),
    ['label'],
    'the quoted name is data, not a binding the input has to supply',
  );
});

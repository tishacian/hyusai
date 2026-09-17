import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { MandateSpec } from './mandate.models';
import { mandateEditorDiff, mandateField, mandateJson, withMandateField } from './mandate-editor.vm';

const original = {
  version: 1,
  inbound: {collection_allowlist: ['allowed', 'hidden'], industrial_grounding: true},
  capabilities: {allowed_actions: ['read'], allowed_delegations: [{system_id: 'child', input_contract: {type: 'object', additionalProperties: false}, output_contract: {type: 'object'}, branches: ['ok', 'refused']}]},
  valves: {max_cost_per_decision: .2, circuit_breaker: {failure_threshold: 3}},
} as MandateSpec;

test('a supported field edit preserves hidden references, typed contracts and unrelated legacy flags', () => {
  const draft = withMandateField(original, 'valves.max_cost_per_decision', .1);
  assert.equal(original.valves?.max_cost_per_decision, .2);
  assert.equal(draft.valves?.max_cost_per_decision, .1);
  assert.deepEqual(draft.inbound, original.inbound);
  assert.deepEqual(draft.capabilities, original.capabilities);
  assert.deepEqual(draft.valves?.circuit_breaker, {failure_threshold: 3});
  assert.equal(draft.version, 1, 'editing a budget does not silently upgrade the membrane contract');
  assert.equal(draft.enforcement_mode, undefined);
});

test('diff describes only changed controls and respects nested contract values rather than key order', () => {
  assert.equal(mandateJson({a: 1, b: {c: 2}}), mandateJson({b: {c: 2}, a: 1}));
  const draft = withMandateField(original, 'valves.max_cost_per_decision', .000001);
  assert.deepEqual(mandateEditorDiff(original, draft).map(change => [change.key, change.before, change.after]), [['cost', .2, .000001]]);
  assert.equal(mandateField(original, 'inbound.industrial_grounding'), true);
});

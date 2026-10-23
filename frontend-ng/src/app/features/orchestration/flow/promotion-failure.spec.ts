import assert from 'node:assert/strict';
import { test } from 'node:test';
import { FLOW_EN, FLOW_FR } from '@app/core/i18n/flow.dict';
import { promotionFailure } from './promotion-failure';

const refused = (detail: unknown) => ({ status: 422, error: { detail } });

test('a refused promotion names the rule and the step the server pointed at', () => {
  const failure = promotionFailure(refused({
    error: 'skill_not_bound_to_system', code: 'SKILL_NOT_BOUND_TO_SYSTEM', path: 'nodes/flow.mvkz503l.2',
  }));
  assert.deepEqual(failure, { key: 'flow.promote.error.code.skill_not_bound_to_system', nodeId: 'flow.mvkz503l.2' });
  assert.match((FLOW_FR as Record<string, string>)[failure.key], /capability/i);
  assert.ok((FLOW_EN as Record<string, string>)[failure.key]);
});

test('every known rule has a message in both languages', () => {
  for (const code of ['skill_contract_missing', 'flow_output_sink_required', 'schema_invalid', 'ingress_unknown', 'agent_loop_allowlist_empty']) {
    const key = promotionFailure(refused({ code })).key;
    assert.equal(key, `flow.promote.error.code.${code}`);
    assert.ok((FLOW_FR as Record<string, string>)[key], key);
    assert.ok((FLOW_EN as Record<string, string>)[key], key);
  }
});

test('an unknown or missing reason keeps the generic message', () => {
  assert.deepEqual(promotionFailure(refused({ code: 'SOMETHING_NEW' })), { key: 'flow.promote.error.failed', nodeId: null });
  assert.deepEqual(promotionFailure(new Error('network')), { key: 'flow.promote.error.failed', nodeId: null });
  assert.deepEqual(promotionFailure(refused('plain text')), { key: 'flow.promote.error.failed', nodeId: null });
});

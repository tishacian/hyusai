import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import type { Run } from '@app/core/canonical-api.service';
import { comparisonDecision } from './decision-comparison.vm';

function candidate(overrides: Record<string, unknown> = {}): Run {
  return { id: 'compare', system_id: 'system', status: 'completed', skill_invocations: [{
    skill_slug: 'decide_next_v1', status: 'completed', latency_ms: 150,
    input_ref: { visible_skills: [{ slug: 'read_case_v1', purpose: 'Read the case' }] },
    output_ref: { next_skill: 'read_case_v1', done: false, exit: null, rationale: 'Verify the delivery' },
    ...overrides,
  }] } as Run;
}

describe('retained agent comparison', () => {
  it('uses the decision contract, leaves unmeasured cost unknown, never claims the tool ran', () => {
    const result = comparisonDecision(candidate({cost: 0, cost_measured: false}));
    assert.equal(result.available, true);
    assert.equal(result.nextSkill, 'Read the case');
    assert.equal(result.state, 'not_executed');
    assert.equal(result.cost, null);
    assert.equal(result.tokens, null);
  });
  it('renders a completed investigation without a selected tool', () => {
    const result = comparisonDecision(candidate({output_ref: {next_skill: null, done: true, exit: 'complete'}}));
    assert.equal(result.available, true);
    assert.equal(result.state, 'finished');
  });
  it('honors the effective guardrail decision and exposes normalization', () => {
    const result = comparisonDecision(candidate({trace: {agent_loop_decision: {
      effective: {next_skill: null, done: false, exit: 'ask_human', needs_human: true},
      normalization_reasons: ['confidence_below_floor'],
    }}}));
    assert.equal(result.state, 'human');
    assert.equal(result.nextSkill, null);
    assert.equal(result.normalized, true);
  });
  it('requires complete measured evidence for cost and tokens', () => {
    const result = comparisonDecision(candidate({cost: 0.003, cost_measured: true, metrics: {
      cost_evidence: {state: 'measured', currency: 'USD'}, token_evidence: {measurement_coverage: 'complete'}, total_tokens: 87,
    }}));
    assert.deepEqual(result.cost, {amount: 0.003, currency: 'USD'});
    assert.equal(result.tokens, 87);
    assert.equal(comparisonDecision(candidate({status: 'running'})).available, false);
  });
});

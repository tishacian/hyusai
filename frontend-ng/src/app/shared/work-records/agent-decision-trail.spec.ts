import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { Run, SkillInvocation } from '@app/core/canonical-api.service';
import { agentDecisionTrail, agentToolLabel } from './agent-decision-trail';

const decision = (overrides: Partial<SkillInvocation> = {}): SkillInvocation => ({
  id: 'decide-1', skill_slug: 'decide_next_v1', status: 'completed',
  trace: { node_id: 'loop-a', passage_id: 'passage-a', membrane_attempt_kind: 'agent_loop_decide', membrane_attempt_index: 1,
    agent_loop_decision: { effective: { next_skill: 'read_order', exit: null }, normalization_reasons: [] } },
  input_ref: { visible_skills: [{ slug: 'read_order', purpose: 'Read the order facts' }] },
  output_ref: { next_skill: 'read_order', rationale: 'The order facts are needed before checking delivery.' },
  ...overrides,
});
const action = (overrides: Partial<SkillInvocation> = {}): SkillInvocation => ({
  id: 'action-1', skill_slug: 'read_order', status: 'completed',
  trace: { node_id: 'loop-a', passage_id: 'passage-a', membrane_attempt_kind: 'agent_loop_act', membrane_attempt_index: 1 },
  ...overrides,
});
const run = (calls: SkillInvocation[], status: Run['status'] = 'running'): Run => ({ id: 'run-a', system_id: 'system-a', status, skill_invocations: calls });

test('a selected tool becomes executed only through the matching invocation', () => {
  const choice = agentDecisionTrail(run([decision()]))[0];
  assert.equal(choice.state, 'selected');
  assert.equal(choice.invocationId, null);
  assert.equal(choice.purpose, 'Read the order facts');
  assert.equal(choice.rationale, 'The order facts are needed before checking delivery.');
  assert.equal(agentDecisionTrail(run([decision(), action({ status: 'running' })]))[0].state, 'running');
  assert.equal(agentDecisionTrail(run([decision(), action()]))[0].state, 'completed');
  assert.equal(agentDecisionTrail(run([decision(), action({ status: 'failed' })]))[0].state, 'failed');
  assert.equal(agentDecisionTrail(run([decision()], 'failed'))[0].state, 'not_executed');
});

test('the same tool in another loop, turn or resumed passage is never attributed to this choice', () => {
  for (const changed of [{ node_id: 'loop-b' }, { passage_id: 'resumed-passage' }, { membrane_attempt_index: 2 }]) {
    const unrelated = action({ trace: { ...action().trace, ...changed } });
    assert.equal(agentDecisionTrail(run([decision(), unrelated]))[0].state, 'selected');
  }
  assert.equal(agentDecisionTrail(run([decision({ trace: {} }), action()]))[0].state, 'selected');
});

test('two resumed decisions retain their own action status', () => {
  const resumed = decision({ id: 'decide-resumed', trace: { ...decision().trace, passage_id: 'resumed' } });
  const resumedAction = action({ id: 'action-resumed', status: 'failed', trace: { ...action().trace, passage_id: 'resumed' } });
  const rows = agentDecisionTrail(run([decision(), action(), resumed, resumedAction]));
  assert.deepEqual(rows.map(item => [item.id, item.invocationId, item.state]), [
    ['decide-1', 'action-1', 'completed'], ['decide-resumed', 'action-resumed', 'failed'],
  ]);
});

test('ambiguous retries do not cherry-pick the successful invocation', () => {
  const choice = agentDecisionTrail(run([decision(), action(), action({ id: 'action-2', status: 'failed' })]))[0];
  assert.equal(choice.state, 'unavailable');
  assert.equal(choice.invocationId, null);
});

test('a post-decision policy gate requests approval and a resumed actual action confirms execution', () => {
  const paused = { ...run([decision()], 'hitl_pending'), checkpoints: [{ kind: 'agent_loop_policy_block',
    passage_id: 'passage-a', node_id: 'loop-a', turn: 1, skill: 'read_order', reason: 'write_needs_approval' }] };
  assert.equal(agentDecisionTrail(paused)[0].state, 'human');
  assert.equal(agentDecisionTrail(paused)[0].normalized, true);
  assert.equal(agentDecisionTrail({ ...paused, skill_invocations: [decision(), action()], status: 'completed' })[0].state, 'completed');
  assert.equal(agentDecisionTrail({ ...paused, status: 'completed' })[0].state, 'not_executed');
  assert.equal(agentDecisionTrail({ ...paused, checkpoints: [{ ...paused.checkpoints[0], reason: 'not_authorized' }] })[0].state, 'blocked');
  assert.equal(agentDecisionTrail({ ...paused, checkpoints: [{ ...paused.checkpoints[0], passage_id: 'other' }] })[0].state, 'selected');
});

test('an action executed after a rejected completion claim remains an executed step', () => {
  const claimed = decision({ trace: { ...decision().trace, agent_loop_decision: { effective: { next_skill: 'read_order', done: true } } } });
  assert.equal(agentDecisionTrail(run([claimed, action()]))[0].state, 'completed');
});

test('normalized controls take precedence over a rejected provider tool request', () => {
  const refused = decision({ trace: { ...decision().trace, agent_loop_decision: {
    raw: { next_skill: 'send_payment' }, effective: { next_skill: null, exit: 'policy_block' },
    normalization_reasons: ['not_visible_skill'],
  } }, output_ref: { next_skill: 'send_payment', rationale: 'This was requested, not executed.' } });
  const choice = agentDecisionTrail(run([refused, action({ skill_slug: 'send_payment' })]))[0];
  assert.equal(choice.skill, null);
  assert.equal(choice.state, 'blocked');
  assert.equal(choice.normalized, true);
  assert.equal(choice.invocationId, null);
  assert.equal(JSON.stringify(choice).includes('send_payment'), false);
});

test('human review, budget stop and declared completion are not tool success', () => {
  for (const [effective, expected] of [
    [{ next_skill: null, needs_human: true }, 'human'],
    [{ next_skill: null, exit: 'ask_human' }, 'human'],
    [{ next_skill: null, exit: 'budget' }, 'budget'],
    [{ next_skill: null, exit: 'complete' }, 'finished'],
  ] as const) {
    const call = decision({ trace: { ...decision().trace, agent_loop_decision: { effective } } });
    assert.equal(agentDecisionTrail(run([call]))[0].state, expected);
  }
});

test('an in-flight or failed decision never displays a stale rationale as a completed choice', () => {
  const pending = agentDecisionTrail(run([decision({ status: 'running' })]))[0];
  assert.equal(pending.state, 'deciding');
  assert.equal(pending.rationale, null);
  const broken = agentDecisionTrail(run([decision({ status: 'failed' })]))[0];
  assert.equal(broken.state, 'failed');
  assert.equal(broken.rationale, null);
  const malformed = decision({ trace: { ...decision().trace, agent_loop_decision: { effective: null } } });
  assert.equal(agentDecisionTrail(run([malformed]))[0].state, 'unavailable');
});

test('model evidence uses execution provenance, never the current or planned route', () => {
  const planned = decision({ trace: { ...decision().trace, model_resolution: { provider: 'planned', model: 'candidate' } } });
  assert.equal(agentDecisionTrail(run([planned]))[0].model, null);
  const executed = decision({ trace: { ...decision().trace, model_execution: { provider: 'openai', model: 'gpt-5', returned_model: 'gpt-5-version', model_source: 'node' } } });
  assert.equal(agentDecisionTrail(run([executed]))[0].model?.returned_model, 'gpt-5-version');
  const unreadable = decision({ trace: { ...decision().trace, model_execution: { provider: { token: 'never-shown' }, model: 'private' } } });
  assert.equal(agentDecisionTrail(run([unreadable]))[0].model, null);
});

test('context drill-down exposes only the authorized keys and recorded source identities', () => {
  const hash = 'a'.repeat(64);
  const call = decision({ trace: { ...decision().trace, agent_loop_context: {
    schema_version: 1, keys: ['facts', 'risk'], present_keys: ['facts'], missing_keys: ['risk'], bytes: 120, sha256: hash,
    values: { credentials: 'never-shown' }, sources: { facts: { node_id: 'prepare', path: ['facts'] }, risk: { reference: 'score.predictions' }, unwanted: { secret: 'never-shown' } },
  } } });
  assert.deepEqual(agentDecisionTrail(run([call]))[0].context, {
    fields: [{ key: 'facts', present: true, source: 'prepare › facts' }, { key: 'risk', present: false, source: 'score.predictions' }], sha256: hash, bytes: 120,
  });
  assert.equal(JSON.stringify(agentDecisionTrail(run([call]))).includes('never-shown'), false);
  assert.equal(agentDecisionTrail(run([decision()]))[0].context, null);
});

test('no decisions are invented for a non-agentic run and fallback labels remain readable', () => {
  assert.deepEqual(agentDecisionTrail(null), []);
  assert.deepEqual(agentDecisionTrail(run([action()])), []);
  assert.equal(agentToolLabel('lookup_customer_v2'), 'Lookup customer');
});

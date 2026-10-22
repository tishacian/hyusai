import { test } from 'node:test';
import assert from 'node:assert/strict';
import type { SkillInvocation } from '@app/core/canonical-api.service';
import {
  defaultObservationRun, hasObservedNodeResult, observationFlowMatch, observationNodeSummaries,
  observationRunIngress, observationRunVersion, observeFlowNodes, protectObservationRun,
  recentObservationRuns, type FlowObservationRun,
} from './flow-observation.vm';

function run(extra: Partial<FlowObservationRun> = {}): FlowObservationRun {
  return { id: 'r1', system_id: 's1', status: 'completed', ...extra };
}
function invocation(extra: Partial<SkillInvocation> = {}): SkillInvocation {
  return { id: 'i1', skill_slug: 'forecast', status: 'completed', started_at: '2026-10-22T08:00:00Z',
    trace: { node_id: 'forecast', passage_id: 'p1', membrane_attempt_index: 1 }, output_ref: { forecast: [5, 6] }, ...extra };
}

test('observation: correlates exact node ids, never Skill names or checkpoint payloads', () => {
  const nodes = observeFlowNodes(run({
    skill_invocations: [invocation(), invocation({ id: 'i2', trace: {} }), invocation({ id: 'i3', trace: { node_id: 'other' } })],
    checkpoints: [{ kind: 'node_end', node_id: 'unreadable', state: { node_outputs: { unreadable: { private: true } } } }],
  }));
  assert.deepEqual(Object.keys(nodes), ['forecast', 'other']);
  assert.equal(nodes['forecast'].attempts.length, 1);
  assert.deepEqual(nodes['forecast'].attempts[0].output, { forecast: [5, 6] });
});

test('observation: held Runs clear IO and decision traces even when an old server retained them', () => {
  const value = run({ result_held: true, input_ref: { secret: true }, output_ref: { secret: true },
    checkpoints: [{ kind: 'node_end', state: { secret: true } }],
    skill_invocations: [invocation({ input_ref: { secret: true }, trace: { node_id: 'forecast', agent_loop_decision: { effective: { secret: true } } } })],
  });
  const safe = protectObservationRun(value), attempt = observeFlowNodes(value)['forecast'].attempts[0];
  assert.deepEqual(safe.input_ref, {}); assert.deepEqual(safe.output_ref, {}); assert.deepEqual(safe.checkpoints, []);
  assert.equal(attempt.outputState, 'held'); assert.equal(attempt.output, null); assert.equal(attempt.input, null);
  assert.deepEqual(attempt.invocation.trace, { node_id: 'forecast' });
  assert.equal(hasObservedNodeResult(value, 'forecast'), false);
  assert.deepEqual(value.output_ref, { secret: true }, 'the input object is not mutated');
});

test('observation: repeated passages and attempts remain separate and prefer unique latest evidence', () => {
  const nodes = observeFlowNodes(run({ skill_invocations: [
    invocation({ id: 'retry', started_at: '2026-10-22T08:02:00Z', trace: { node_id: 'forecast', passage_id: 'p2', membrane_attempt_index: 2 }, output_ref: { forecast: [8] }, latency_ms: 20 }),
    invocation({ latency_ms: 10 }),
  ] }));
  assert.deepEqual(nodes['forecast'].attempts.map(item => item.id), ['i1', 'retry']);
  assert.equal(nodes['forecast'].preferredAttemptId, 'retry');
  assert.equal(nodes['forecast'].latencyMs, null, 'attempt durations are not invented node wall time');
  assert.deepEqual(nodes['forecast'].attempts[0].output, { forecast: [5, 6] });
});

test('observation: ambiguous timestamps do not silently choose a favourable retry', () => {
  for (const started_at of [undefined, '2026-10-22T08:00:00Z']) {
    const nodes = observeFlowNodes(run({ skill_invocations: [invocation(), invocation({ id: 'second', started_at, status: 'failed', output_ref: undefined })] }));
    assert.equal(nodes['forecast'].preferredAttemptId, null);
    assert.equal(nodes['forecast'].status, 'unknown');
  }
});

test('observation: pending, failed, absent and empty outputs retain distinct states', () => {
  const state = (extra: Partial<SkillInvocation>) => observeFlowNodes(run({ skill_invocations: [invocation(extra)] }))['forecast'].attempts[0];
  assert.equal(state({ status: 'running' }).output, null);
  assert.equal(state({ status: 'running' }).outputState, 'pending');
  assert.equal(state({ status: 'failed' }).outputState, 'failed');
  assert.equal(state({ output_ref: undefined }).outputState, 'missing');
  assert.equal(state({ output_ref: {} }).outputState, 'available');
  assert.deepEqual(state({ output_ref: {} }).output, {});
});

test('observation: node pause and known zero duration are retained truthfully', () => {
  const nodes = observeFlowNodes(run({ status: 'hitl_pending', hitl: { node_id: 'forecast' }, skill_invocations: [invocation({ latency_ms: 0 })] }));
  assert.equal(nodes['forecast'].status, 'hitl_pending');
  assert.equal(observationNodeSummaries(nodes)['forecast'].latencyMs, 0);
});

test('observation: canonical hash matches only canonical hash, and dirty drafts differ', () => {
  const sha = 'a'.repeat(64);
  assert.equal(observationFlowMatch(run({ flow_sha256: sha }), { flowSha256: sha }), 'same');
  assert.equal(observationFlowMatch(run({ flow_sha256: sha }), { flowSha256: sha, dirty: true }), 'different');
  assert.equal(observationFlowMatch(run({ flow_sha256: sha }), { flowSha256: 'b'.repeat(64) }), 'different');
  assert.equal(observationFlowMatch(run({ flow_evidence: { flow_snapshot_sha256: sha } }), { flowSha256: sha }), 'unknown');
  assert.equal(observationFlowMatch(run(), {}), 'unknown');
});

test('observation: recent Runs filter scope and default to latest completed business execution', () => {
  const runs = recentObservationRuns([
    run({ id: 'preview', started_at: '2026-10-22T10:00:00Z', execution_surface: 'node_preview' }),
    run({ id: 'foreign', system_id: 's2', started_at: '2026-10-22T11:00:00Z' }),
    run({ id: 'ongoing', status: 'running', started_at: '2026-10-22T09:00:00Z' }),
    run({ id: 'business', started_at: '2026-10-22T08:00:00Z' }),
  ], 's1');
  assert.deepEqual(runs.map(item => item.id), ['preview', 'ongoing', 'business']);
  assert.equal(defaultObservationRun(runs), 'business');
  assert.equal(defaultObservationRun([]), null);
});

test('observation: version and entry labels use retained identities, never current system metadata', () => {
  assert.equal(observationRunVersion(run({ flow_evidence: { flow_version_id: 'frozen-v1' } })), 'frozen-v1');
  assert.equal(observationRunIngress(run({ input_ref: { execution: { ingress_id: 'source.forecast' } } })), 'source.forecast');
  assert.equal(observationRunIngress(run()), null);
});

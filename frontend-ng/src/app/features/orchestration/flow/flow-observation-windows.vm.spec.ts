import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { Run, SkillInvocation } from '@app/core/canonical-api.service';
import type { FlowObservedAttempt } from './flow-observation.vm';
import {
  appendObservationPin,
  MAX_OBSERVATION_PINS,
  moveObservationPin,
  observationPinValue,
  removeObservationPin,
  snapshotObservationPin,
  selectObservationPinSeries,
  type FlowObservationPinInput,
} from './flow-observation-windows.vm';

function source(runId = 'run-1', nodeId = 'forecast', invocationId = 'invocation-1'): FlowObservationPinInput {
  const invocation: SkillInvocation = {
    id: invocationId, run_id: runId, system_id: 'system-1', status: 'completed',
    trace: { node_id: nodeId, passage_id: 'passage-1' },
    input_ref: { horizon: 7 }, output_ref: { rows: [{ ds: '2026-10-22', forecast: 23 }] },
  };
  const attempt: FlowObservedAttempt = {
    id: invocationId, nodeId, passageId: 'passage-1', attemptIndex: 1, iteration: null,
    skillSlug: 'ml_forecast_v1', status: 'completed', startedAt: '2026-10-22T10:00:00Z',
    completedAt: '2026-10-22T10:00:01Z', latencyMs: 1000, input: invocation.input_ref!,
    output: invocation.output_ref!, outputState: 'available', invocation,
  };
  const run: Run = {
    id: runId, system_id: 'system-1', status: 'completed',
    flow_version_id: 'version-10', flow_sha256: 'a'.repeat(64), execution_surface: 'published_manual',
    skill_invocations: [invocation],
  };
  return { run, attempt, nodeId, title: 'Prévoir la charge', mode: 'output', presentation: 'chart', position: { x: 300, y: 100 } };
}

test('a pin keeps the selected Run, attempt and data after later objects change', () => {
  const input = source();
  const pin = snapshotObservationPin(input)!;
  assert.ok(pin);
  input.run.flow_version_id = 'version-11';
  (input.attempt.output!['rows'] as Array<Record<string, unknown>>)[0]['forecast'] = 99;
  input.position.x = 800;
  assert.equal(pin.run.flow_version_id, 'version-10');
  assert.equal((observationPinValue(pin)!['rows'] as Array<Record<string, unknown>>)[0]['forecast'], 23);
  assert.deepEqual(pin.position, { x: 300, y: 100 });
  assert.ok(Object.isFrozen(pin.attempt.output));
  assert.throws(() => { pin.attempt.output!['extra'] = true; }, TypeError);
});

test('the identity separates Run, node, invocation, side and presentation', () => {
  const base = source();
  const inputs = [base, source('run-2'), source('run-1', 'prepare'), source('run-1', 'forecast', 'invocation-2'),
    { ...source(), mode: 'input' as const }, { ...source(), presentation: 'table' as const }];
  const ids = inputs.map(value => snapshotObservationPin(value)!.id);
  assert.equal(new Set(ids).size, inputs.length);
  const colon = snapshotObservationPin(source('run:1', 'node', 'call'))!;
  const percent = snapshotObservationPin(source('run%3A1', 'node', 'call'))!;
  assert.notEqual(colon.id, percent.id);
});

test('historical retained evidence keeps its explicit version without inventing a canonical hash', () => {
  const input = source();
  delete input.run.flow_version_id;
  delete input.run.flow_sha256;
  Object.assign(input.run, { flow_evidence: { flow_version_id: 'historical-version', snapshot_hash: 'b'.repeat(64) } });
  const pin = snapshotObservationPin(input)!;
  assert.equal(pin.run.flow_version_id, 'historical-version');
  assert.equal(pin.run.flow_sha256, undefined);
});

test('pinning the same evidence twice keeps the original snapshot and position', () => {
  const first = snapshotObservationPin(source())!;
  const later = source();
  later.position = { x: 900, y: 200 };
  later.attempt.output = { changed: true };
  const duplicate = snapshotObservationPin(later)!;
  const result = appendObservationPin([first], duplicate);
  assert.equal(result.outcome, 'duplicate');
  assert.equal(result.pins.length, 1);
  assert.equal(result.pins[0], first);
  assert.deepEqual(result.pins[0].position, { x: 300, y: 100 });
});

test('four pins is a hard cap and adding one never silently evicts a result', () => {
  const pins = Array.from({ length: MAX_OBSERVATION_PINS }, (_, index) => snapshotObservationPin(source(`run-${index}`))!);
  const result = appendObservationPin(pins, snapshotObservationPin(source('run-new'))!);
  assert.equal(result.outcome, 'limit');
  assert.deepEqual(result.pins, pins);
  const afterRemoval = removeObservationPin(pins, pins[1].id);
  const added = appendObservationPin(afterRemoval, snapshotObservationPin(source('run-new'))!);
  assert.equal(added.outcome, 'added');
  assert.equal(added.pins.length, 4);
  assert.equal(pins.length, 4);
});

test('held Runs cannot retain outputs or inputs even if stale payloads are present', () => {
  for (const mode of ['input', 'output'] as const) {
    const input = source();
    Object.assign(input.run, { result_held: true });
    assert.equal(snapshotObservationPin({ ...input, mode }), null);
  }
  const input = source();
  input.attempt.outputState = 'held';
  assert.equal(snapshotObservationPin(input), null);
});

test('missing output is not replaced by a Run root result or checkpoint payload', () => {
  const input = source();
  input.attempt.output = null;
  input.attempt.outputState = 'missing';
  input.run.output_ref = { tempting: 200 };
  input.run.checkpoints = [{ kind: 'node_end', node_id: input.nodeId, state: { node_outputs: { forecast: { rows: [99] } } } }];
  assert.equal(snapshotObservationPin(input), null);
});

test('pending input and failed partial output remain inspectable with their actual status', () => {
  const pending = source();
  pending.attempt.status = 'running';
  pending.attempt.outputState = 'pending';
  pending.attempt.output = null;
  assert.equal(snapshotObservationPin(pending), null);
  const inputPin = snapshotObservationPin({ ...pending, mode: 'input' })!;
  assert.equal(inputPin.attempt.status, 'running');
  assert.deepEqual(observationPinValue(inputPin), { horizon: 7 });
  const failed = source();
  failed.attempt.status = 'failed';
  failed.attempt.outputState = 'failed';
  const partial = snapshotObservationPin(failed)!;
  assert.equal(partial.attempt.status, 'failed');
  assert.deepEqual(observationPinValue(partial), failed.attempt.output);
});

test('foreign and unattributed invocations cannot be pinned by changing their labels', () => {
  const foreign = source();
  foreign.attempt.invocation.run_id = 'different-run';
  assert.equal(snapshotObservationPin(foreign), null);
  const wrongNode = source();
  wrongNode.attempt.nodeId = 'different-node';
  assert.equal(snapshotObservationPin(wrongNode), null);
  const unattributed = source();
  unattributed.attempt.invocation.trace = {};
  assert.equal(snapshotObservationPin(unattributed), null);
  const absent = source();
  absent.run.skill_invocations = [];
  assert.equal(snapshotObservationPin(absent), null);
});

test('a retained Run excludes unrelated calls, root payloads and checkpoint state', () => {
  const input = source();
  input.run.input_ref = { hiddenRoot: 'input' };
  input.run.output_ref = { hiddenRoot: 'output' };
  input.run.skill_invocations!.push({ id: 'another-call', run_id: input.run.id, trace: { node_id: 'another-node' }, output_ref: { unrelated: true } });
  input.run.checkpoints = [
    { kind: 'node_end', node_id: 'forecast', state: { secret: 'snapshot' } },
    { kind: 'agent_loop_policy_block', node_id: 'forecast', passage_id: 'p1', turn: 2, skill: 'tool', reason: 'not_allowed', state: { private: 'snapshot' } },
    { kind: 'agent_loop_policy_block', node_id: 'different', reason: 'other-node' },
  ];
  const pin = snapshotObservationPin(input)!;
  assert.equal(pin.run.input_ref, undefined);
  assert.equal(pin.run.output_ref, undefined);
  assert.deepEqual(pin.run.skill_invocations!.map(call => call.id), ['invocation-1']);
  assert.deepEqual(pin.run.checkpoints, [{ kind: 'agent_loop_policy_block', node_id: 'forecast', passage_id: 'p1', turn: 2, skill: 'tool', reason: 'not_allowed' }]);
});

test('a dataset preview is copied with its provenance only for the output view', () => {
  const input = source();
  input.datasetPreview = { dataset_id: 'dataset-7', rows: [{ score: 0.87 }], provenance: { version: 7 } };
  const pin = snapshotObservationPin(input)!;
  (input.datasetPreview.rows[0] as Record<string, unknown>)['score'] = 0;
  input.datasetPreview.provenance!['version'] = 8;
  assert.deepEqual(pin.datasetPreview, { dataset_id: 'dataset-7', rows: [{ score: 0.87 }], provenance: { version: 7 } });
  assert.equal(snapshotObservationPin({ ...input, mode: 'input' })!.datasetPreview, null);
});

test('moving a pin changes only its position without mutating the snapshot', () => {
  const pin = snapshotObservationPin(source())!;
  const moved = moveObservationPin([pin], pin.id, { x: -40, y: 520 });
  assert.deepEqual(moved[0].position, { x: -40, y: 520 });
  assert.deepEqual(pin.position, { x: 300, y: 100 });
  assert.equal(moved[0].attempt, pin.attempt);
  assert.equal(moved[0].id, pin.id);
  assert.deepEqual(moveObservationPin([pin], pin.id, { x: NaN, y: 0 }), [pin]);
  assert.deepEqual(moveObservationPin([pin], pin.id, { x: Infinity, y: 0 }), [pin]);
  assert.deepEqual(moveObservationPin([pin], pin.id, { x: 100_001, y: 0 }), [pin]);
});

test('pinning and expanding preserve the selected series without substituting a different curve', () => {
  const input = source();
  input.attempt.output!['rows'] = [
    { ds: '2026-10-22', forecast: 23, series: 'A' },
    { ds: '2026-10-22', forecast: 51, series: 'B' },
  ];
  input.selectedSeriesName = 'B';
  const pin = snapshotObservationPin(input)!;
  assert.equal(pin.selectedSeriesName, 'B');
  const first = snapshotObservationPin({ ...input, selectedSeriesName: 'A' })!;
  assert.notEqual(pin.id, first.id);
  assert.equal(appendObservationPin([pin], first).outcome, 'added');
  const changed = selectObservationPinSeries(pin, 'A');
  assert.equal(changed.selectedSeriesName, 'A');
  assert.equal(changed.attempt, pin.attempt);
  assert.equal(changed.run, pin.run);
  assert.equal(pin.selectedSeriesName, 'B');
  assert.equal(selectObservationPinSeries(pin, 'absent'), pin);
});

test('a different attempt never borrows an unavailable series from an earlier selection', () => {
  const input = source();
  input.selectedSeriesName = 'previous-series';
  const pin = snapshotObservationPin(input)!;
  assert.equal(pin.selectedSeriesName, '');
  assert.equal(snapshotObservationPin({ ...input, presentation: 'table' })!.selectedSeriesName, null);
});

test('uncloneable evidence is rejected instead of retaining a partial result', () => {
  const input = source();
  input.attempt.output!['notJson'] = () => 'runtime function';
  assert.equal(snapshotObservationPin(input), null);
});

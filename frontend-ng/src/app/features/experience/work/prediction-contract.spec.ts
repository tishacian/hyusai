import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import { predictionAdvice, predictionContract, type PredictionContract } from './prediction-contract';

const now = Date.parse('2026-10-09T12:00:00Z');
const contract: PredictionContract = {
  schema_version: 1, model_id: 'renewal', model_version: 2, task: 'classification',
  target: 'will_renew', positive_label: 'yes', label: 'Renewal likelihood', unit: 'probability',
  value_column: 'prediction', score_column: 'score', max_age_seconds: 600,
  bands: [{ key: 'contact', label: 'Contact', min: 0 }, { key: 'likely', label: 'Likely', min: .8 }], order: 'ascending',
};
const native = {
  served: { model_id: 'renewal', version: 2 }, target: 'will_renew', task: 'classification',
  positive_label: 'yes', captured_at: new Date(now).toISOString(),
  predictions: [{ prediction: 'no', score: .1, confidence: .9 }],
};

test('another target and class use authored semantics, never winning-class confidence', () => {
  const advice = predictionAdvice(native, contract, now);
  assert.equal(advice?.score, .1);
  assert.equal(advice?.band?.key, 'contact');
  assert.equal(advice?.model.version, 2);
  for (const patch of [{ target: 'other' }, { positive_label: 'no' }, { served: { model_id: 'renewal', version: 3 } }, { predictions: [{ prediction: 'no', confidence: .9 }] }]) {
    assert.equal(predictionAdvice({ ...native, ...patch }, contract, now), null);
  }
});

test('old, future and multiple-row predictions cannot become single-case advice', () => {
  assert.equal(predictionAdvice(native, contract, now + 600001), null);
  assert.equal(predictionAdvice(native, contract, now - 1), null);
  assert.equal(predictionAdvice({ ...native, predictions: [...native.predictions, ...native.predictions] }, contract, now), null);
  assert.equal(predictionAdvice({ ...native, captured_at: null }, contract, now), null);
});

test('regression interval and unit are explicit; invalid bounds are rejected', () => {
  const regression = { ...contract, task: 'regression', target: 'resolution_days', unit: 'days', positive_label: undefined, score_column: undefined, bands: [], lower_column: 'low', upper_column: 'high' };
  const output = { ...native, task: 'regression', target: 'resolution_days', predictions: [{ prediction: 3, low: 1, high: 5 }] };
  const advice = predictionAdvice(output, regression, now);
  assert.equal(advice?.value, 3);
  assert.equal(advice?.unit, 'days');
  assert.deepEqual(advice?.interval, { lower: 1, upper: 5 });
  assert.equal(advice?.score, null);
  assert.equal(predictionAdvice({ ...output, predictions: [{ prediction: 3, low: 4, high: 5 }] }, regression, now), null);
});

test('segments never acquire an ordinal rank or percentage', () => {
  const segment = { ...contract, task: 'clustering', target: undefined, positive_label: undefined, score_column: undefined, bands: [], order: 'none', unit: 'segment' };
  const output = { ...native, task: 'clustering', predictions: [{ prediction: 4 }] };
  assert.equal(predictionAdvice(output, segment, now)?.value, 4);
  assert.equal(predictionAdvice(output, segment, now)?.score, null);
  assert.equal(predictionContract({ ...segment, order: 'descending' }), null);
  assert.equal(predictionContract({ ...segment, unit: 'probability' }), null);
});

test('normalized evidence remains pinned and recomputes authored display bands', () => {
  const canonical = {
    schema_version: 1, status: 'ready', task: 'classification', target: 'will_renew', positive_label: 'yes',
    model: { id: 'renewal', version: 2 }, unit: 'probability', value: 'no', score: .1,
    band: { key: 'forged', label: 'Unverified', min: 0 }, captured_at: new Date(now).toISOString(),
    provenance: { run_id: 'evidence-run', dataset_id: 'scored-dataset' },
  };
  const advice = predictionAdvice(canonical, contract, now);
  assert.equal(advice?.band?.key, 'contact');
  assert.equal(advice?.provenance['dataset_id'], 'scored-dataset');
  assert.equal(predictionAdvice({ ...canonical, status: 'stale' }, contract, now), null);
});

import { selectRuntimeRunData, runtimeDataBinding } from '../runtime/model';

test('node binding retrieves intermediate evidence even when the final output is a receipt', () => {
  const binding = runtimeDataBinding({ type: 'prediction', props: { dataBinding: { source: 'run-output', componentId: 'inquiry', nodeId: 'model.context', selector: 'model_advice' } } })!;
  const run = { id: 'authorized-run', output_ref: { receipt: 'accepted' }, skill_invocations: [
    { run_id: 'authorized-run', status: 'completed', trace: { node_id: 'model.context' }, output_ref: { model_advice: native } },
    { run_id: 'authorized-run', status: 'completed', trace: { node_id: 'receipt' }, output_ref: { receipt: 'accepted' } },
  ] };
  assert.deepEqual(selectRuntimeRunData(run, binding), native);
  assert.equal(selectRuntimeRunData(run, { ...binding, nodeId: 'other' }), undefined);
  assert.equal(selectRuntimeRunData(null, binding), undefined);
  assert.deepEqual(selectRuntimeRunData(run, { selector: '' }), { receipt: 'accepted' });
  run.skill_invocations.push({ run_id: 'authorized-run', status: 'failed', trace: { node_id: 'model.context' }, output_ref: { receipt: 'failed' } });
  assert.equal(selectRuntimeRunData(run, binding), undefined);
  run.skill_invocations.pop();
  run.skill_invocations[0].run_id = 'foreign-run';
  assert.equal(selectRuntimeRunData(run, binding), undefined);
});

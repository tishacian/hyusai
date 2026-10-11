import { test } from 'node:test';
import assert from 'node:assert/strict';
import { tuningPoints, tuningKnobs, temporalTuning, tuningWarningKey, type TuningResult } from './tuning-evidence.vm';
const result: TuningResult = {
 metric: 'r2', direction: 'max', trials_run: 4, trials_pruned: 1, trials_failed: 1,
 stopped_by: 'budget', budget_s: 30, elapsed_s: 30, folds: 3,
 start: { knobs: { alpha: 1, max_depth: null }, score: -2 },
 best: { knobs: { alpha: 2, max_depth: 3 }, score: .4, trial: 1 },
 trials: [{ n: 0, score: -2, state: 'complete', duration_ms: 10 }, { n: 1, score: .4, state: 'complete', duration_ms: 10 }, { n: 2, score: null, state: 'failed', duration_ms: 10 }, { n: 3, score: .6, state: 'pruned', duration_ms: 10 }],
};
test('old models have no tuning evidence', () => { assert.deepEqual(tuningPoints(undefined), []); assert.deepEqual(tuningKnobs(undefined), []); });
test('scatter keeps negative R² and excludes incomplete scores', () => {
 const points = tuningPoints(result); assert.equal(points.length, 2); assert.equal(points[0].score, -2);
 assert.equal(points[1].best, true); assert.ok(points.every(p => Number.isFinite(p.x) && Number.isFinite(p.y)));
});
test('settings compare complete baseline including automatic depth', () => {
 assert.deepEqual(tuningKnobs(result), [{ key: 'alpha', before: 1, after: 2 }, { key: 'max_depth', before: null, after: 3 }]);
});

test('temporal validation is distinct from tabular CV and exposes the reserved backtest', () => {
  assert.equal(temporalTuning(result), null);
  const validation = {method:'expanding_window' as const, metric:'mae',aggregation:'mean_per_series',train_start:'2025-01-01',train_end:'2025-03-31',holdout_start:'2025-04-01',holdout_rows:10,initial_train_size:80,rows:90,horizon:5,folds:2};
  assert.deepEqual(temporalTuning({...result,metric:'mae',direction:'min',validation,baseline:{key:'seasonal_naive',mae:4}}),validation);
  assert.equal(tuningWarningKey({...result,warning:'ML_TS_TUNING_FAILED'}),'models.tuning.failed_warning');
  assert.equal(tuningWarningKey({...result,warning:'ML_TUNING_BASELINE_UNAVAILABLE'}),'models.tuning.baseline_unavailable');
});

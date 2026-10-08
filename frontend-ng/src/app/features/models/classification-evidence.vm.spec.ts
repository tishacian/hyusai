import assert from 'node:assert/strict';
import { test } from 'node:test';
import { calibrationWorsened, decisionRows, type CalibrationEvidence } from './classification-evidence.vm';

const evidence: CalibrationEvidence = { method: 'sigmoid', fit_rows: 800, calibration_rows: 200,
  before: { brier_score: 0.2, log_loss: 0.5 }, after: { brier_score: 0.1, log_loss: 0.4 } };
test('calibration uses amber only when a measured loss increases', () => {
  assert.equal(calibrationWorsened(evidence), false);
  assert.equal(calibrationWorsened({ ...evidence, after: { brier_score: 0.21, log_loss: 0.4 } }), true);
  assert.equal(calibrationWorsened({ ...evidence, after: { brier_score: null, log_loss: 0.6 } }), true);
  assert.equal(calibrationWorsened(undefined), false);
});
test('threshold comparisons preserve missing measurements and both decisions', () => {
  assert.deepEqual(decisionRows(undefined), []);
  assert.deepEqual(decisionRows({ threshold: 0.37, criterion: 'f1', default_metrics: { precision: 0.9, recall: 0.5 }, tuned_metrics: { precision: 0.8, recall: 0.7 } }), [
    { key: 'precision', before: 0.9, after: 0.8 }, { key: 'recall', before: 0.5, after: 0.7 }, { key: 'f1', before: null, after: null },
  ]);
});

import { trainChecklist } from './models.vm';
test('threshold-only training announces its calibration folds', () => {
  const steps = trainChecklist('training', 'calibrating:2/5', 0, 'en', 'classification', { threshold: 'f1', calibration: 'off' });
  assert.ok(steps.some((step) => step.step === 'calibrating'));
});

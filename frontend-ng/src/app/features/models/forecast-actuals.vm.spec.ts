import assert from 'node:assert/strict';
import { test } from 'node:test';
import { actualMetric, actualStatus, actualReason } from './forecast-actuals.vm';
test('observed coverage has a percentage while errors retain the target scale', () => {
 assert.equal(actualMetric(.8, 'en', true), '80%'); assert.equal(actualMetric(0, 'en'), '0');
 assert.equal(actualMetric(null, 'en'), '—'); assert.equal(actualMetric(NaN, 'en'), '—');
 assert.equal(actualMetric(Infinity, 'en'), '—'); assert.equal(actualMetric(1.25, 'fr'), '1,25');
});
test('missing status and unknown server refusals remain unavailable', () => {
 assert.equal(actualStatus('alert'), 'models.actuals.status.alert');
 assert.equal(actualStatus('anything'), 'models.actuals.status.unavailable');
 assert.equal(actualReason('ML_TS_ACTUALS_COLUMNS_MISSING'), 'models.actuals.reason.columns_missing');
 assert.equal(actualReason('untranslated server internals'), 'models.actuals.reason.unavailable');
});

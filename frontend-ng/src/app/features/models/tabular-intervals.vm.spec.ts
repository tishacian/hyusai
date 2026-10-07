import { test } from 'node:test';
import assert from 'node:assert/strict';
import { curlSnippet } from './models.vm';
import { intervalEvidence, predictionInterval } from './tabular-intervals.vm';

test('old or malformed evidence does not show intervals', () => {
  assert.equal(intervalEvidence(undefined), null);
  assert.equal(predictionInterval({ prediction: 12 }), null);
  assert.equal(predictionInterval({ prediction: 12, lower: 14, upper: 20, level: .9 }), null);
  assert.equal(predictionInterval({ prediction: 12, lower: NaN, upper: 20, level: .9 }), null);
});
test('a numeric prediction carries readable bounds and selected confidence', () => {
  assert.deepEqual(predictionInterval({ prediction: 12, lower: 8, upper: 16, level: .9 }), { lower: 8, upper: 16, level: .9 });
});
test('the copyable curl and Play request use the same optional level', () => {
  const options = { origin: 'https://example.test', endpoint: '/predict', header: 'X-API-Key', row: { x: 2 } };
  assert.doesNotMatch(curlSnippet(options), /interval_level/);
  assert.match(curlSnippet({ ...options, intervalLevel: .95 }), /"interval_level":0.95/);
});

import assert from 'node:assert/strict';
import { test } from 'node:test';
import { fairnessMetrics, partialPlot, partialSeries, readableRule, surrogateRules } from './explanation-evidence.vm';

test('rules preserve learned conditions and localize numeric boundaries', () => {
  assert.equal(readableRule([], 'fr', 'Toutes', 'et'), 'Toutes');
  assert.equal(readableRule([{ feature: 'age', op: '<=', value: 2.5 }, { feature: 'region_North', op: '>', value: 0.5 }], 'fr', 'Toutes', 'et'), 'age ≤ 2,5 et region_North > 0,5');
});
test('a weak or failed surrogate never advertises rules', () => {
  const rules = [{ rule: [], rows: 30, prediction: 'yes' }];
  assert.deepEqual(surrogateRules({ fidelity: 0.69, rules }), []);
  assert.deepEqual(surrogateRules({ fidelity: 0.7, rules }), rules);
  assert.deepEqual(surrogateRules({ fidelity: 0.9, rules, error: 'budget' }), []);
  assert.deepEqual(surrogateRules(undefined), []);
});
test('PDP rejects malformed dimensions and caps the individual curves', () => {
  assert.deepEqual(partialSeries({ feature: 'x', grid: [1], average: [] }).grid, []);
  const curve = partialSeries({ feature: 'region', grid: ['A', 'B'], average: [0.2, 0.5], ice: [[1], ...Array.from({ length: 40 }, () => [0.1, 0.4])] });
  assert.deepEqual(curve.grid, ['A', 'B']);
  assert.equal(curve.ice.length, 30);
});
test('fairness tables show only the metrics measured for their task', () => {
  assert.deepEqual(fairnessMetrics({ column: 'region', groups: [{ group: 'A', n: 50, low_support: false, mae: 1.5, bias: -0.2 }] }), ['mae', 'bias']);
  assert.deepEqual(fairnessMetrics({ column: 'region', groups: [{ group: 'A', n: 50, low_support: false, accuracy: 0.8 }] }), ['accuracy']);
});

test('numeric PDP and ICE preserve irregular spacing and missing predictions', () => {
  const plot = partialPlot({ feature: 'visits', kind: 'numeric', grid: [0, 1, 100],
    average: [0.1, 0.2, 0.8], ice: [[0.2, null, 0.9]] }, 'fr');
  assert.equal(plot.scale, 'linear');
  assert.deepEqual(plot.labels, []);
  assert.deepEqual(plot.average, [{ x: 0, y: 0.1 }, { x: 1, y: 0.2 }, { x: 100, y: 0.8 }]);
  assert.deepEqual(plot.ice, [[{ x: 0, y: 0.2 }, null, { x: 100, y: 0.9 }]]);
});

test('categorical PDP retains labeled categories and curve values', () => {
  const plot = partialPlot({ feature: 'region', kind: 'categorical', grid: ['North', 'South'],
    average: [0.2, 0.8], ice: [[0.1, 0.9]] }, 'en');
  assert.equal(plot.scale, 'category');
  assert.deepEqual(plot.labels, ['North', 'South']);
  assert.deepEqual(plot.average, [0.2, 0.8]);
  assert.deepEqual(plot.ice, [[0.1, 0.9]]);
});

test('rules expose missing-value branches instead of an infinite threshold', () => {
  assert.equal(readableRule([{ feature: 'age', op: 'missing', value: null }], 'en', 'All', 'and'), 'age is missing');
  assert.equal(readableRule([{ feature: 'age', op: '<=', value: 3, missing: true }], 'en', 'All', 'and'), '(age ≤ 3 or age is missing)');
});

import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { SignatureField } from './models.vm';
import {
  counterfactualRequest,
  counterfactualRows,
  fallbackOf,
  fallbackReasonKey,
  formatExplained,
  isTreeShap,
  methodKey,
  outputSpaceKey,
  searchableFields,
  shapView,
  signed,
  toggleField,
  type CounterfactualAnswer,
  type TreeShapExplanation,
} from './explanations.vm';

const shap: TreeShapExplanation = {
  method: 'tree_shap',
  output_space: 'log_odds',
  class: '1',
  base: -0.6,
  output: 1.1,
  contributions: [
    { field: 'tenure_months', value: 3, contribution: 1.2 },
    { field: 'plan', value: 'hybrid', contribution: -0.4 },
  ],
  other: { fields: 2, contribution: 0.9 },
  additivity_gap: 0,
};

test('a TreeSHAP answer is told apart from a counterfactual fallback', () => {
  assert.equal(isTreeShap(shap), true);
  assert.equal(isTreeShap({ method: 'counterfactual', reason: 'timeout' }), false);
  assert.equal(isTreeShap({ ...shap, base: Number.NaN }), false);
  assert.deepEqual(fallbackOf({ method: 'counterfactual', reason: 'timeout' }), {
    method: 'counterfactual',
    reason: 'timeout',
  });
  assert.equal(fallbackOf(shap), null);
  assert.equal(fallbackOf(undefined), null);
});

test('reasons and spaces map to known keys, unknown ones to a generic key', () => {
  assert.equal(fallbackReasonKey('not_a_tree_model'), 'models.play.explain.reason.not_a_tree_model');
  assert.equal(fallbackReasonKey('lime'), 'models.play.explain.reason.other');
  assert.equal(outputSpaceKey('raw_score'), 'models.play.explain.space.raw_score');
  assert.equal(outputSpaceKey('weird'), 'models.play.explain.space.value');
  assert.equal(methodKey({ ...shap, method: 'tree_shap_approximate' }), 'models.play.explain.method.approximate');
});

test('bars keep the server order, scale to the strongest and close with an other row', () => {
  const view = shapView(shap);
  assert.deepEqual(
    view.bars.map((bar) => [bar.key, bar.width, bar.positive]),
    [
      ['field:tenure_months', 50, true],
      ['field:plan', 16.7, false],
      ['other', 37.5, true],
    ],
  );
  const other = view.bars.at(-1)!;
  assert.equal(other.other, true);
  assert.equal(other.fields, 2);
  // base + Σ bars is the output: the view shows what the server summed.
  const total = view.base + view.bars.reduce((sum, bar) => sum + bar.contribution, 0);
  assert.ok(Math.abs(total - view.output) < 1e-9);
});

test('no remainder row when every field is shown, and junk rows are dropped', () => {
  const view = shapView({
    ...shap,
    other: null,
    contributions: [
      { field: 'a', contribution: 0.5 },
      { field: 'b', contribution: Number.NaN },
    ],
  });
  assert.deepEqual(view.bars.map((bar) => bar.key), ['field:a']);
});

test('a probability reads in percent and points, other spaces as numbers', () => {
  assert.equal(formatExplained(0.4231, 'probability', 'en'), '42.3%');
  assert.equal(formatExplained(-1.23456, 'log_odds', 'en'), '-1.235');
  assert.equal(signed(0.052, 'probability', 'en'), '+5.2 pt');
  assert.equal(signed(-0.5, 'value', 'en'), '−0.5');
});

const fields: SignatureField[] = [
  { name: 'tenure', type: 'double', kind: 'number', min: 1, max: 95 },
  { name: 'flat', type: 'double', kind: 'number', min: 3, max: 3 },
  { name: 'unknown_range', type: 'double', kind: 'number' },
  { name: 'plan', type: 'string', kind: 'category', choices: ['a', 'b'] },
  { name: 'note', type: 'string', kind: 'category' },
  { name: 'at', type: 'datetime', kind: 'datetime' },
  { name: 'vip', type: 'boolean', kind: 'category' },
];

test('only fields with training facts are searchable, with the server’s reasons', () => {
  assert.deepEqual(searchableFields(fields), [
    { name: 'tenure', usable: true },
    { name: 'flat', usable: false, reason: 'constant' },
    { name: 'unknown_range', usable: false, reason: 'no_range' },
    { name: 'plan', usable: true },
    { name: 'note', usable: false, reason: 'no_levels' },
    { name: 'at', usable: false, reason: 'unsupported_kind' },
    { name: 'vip', usable: true },
  ]);
});

test('the selection never exceeds three fields', () => {
  let selected = toggleField([], 'a');
  selected = toggleField(selected, 'b');
  selected = toggleField(selected, 'c');
  assert.deepEqual(toggleField(selected, 'd'), ['a', 'b', 'c']);
  assert.deepEqual(toggleField(selected, 'b'), ['a', 'c']);
});

test('requests name a class or a range, and refuse what the server would', () => {
  const row = { tenure: 6 };
  assert.deepEqual(counterfactualRequest(row, [], 'classification', {}), {
    error: 'models.play.cf.error.fields',
  });
  assert.deepEqual(counterfactualRequest(row, ['tenure'], 'classification', { class: '' }, 2), {
    body: { row, fields: ['tenure'], version: 2 },
  });
  assert.deepEqual(counterfactualRequest(row, ['tenure'], 'classification', { class: '0' }), {
    body: { row, fields: ['tenure'], target: { class: '0' } },
  });
  assert.deepEqual(counterfactualRequest(row, ['tenure'], 'regression', { min: ' ', max: '' }), {
    error: 'models.play.cf.error.range',
  });
  assert.deepEqual(counterfactualRequest(row, ['tenure'], 'regression', { min: '5', max: '2' }), {
    error: 'models.play.cf.error.order',
  });
  assert.deepEqual(counterfactualRequest(row, ['tenure'], 'regression', { min: '150' }), {
    body: { row, fields: ['tenure'], target: { min: 150 } },
  });
});

test('result rows read change by change, in the server’s rank order', () => {
  const answer: CounterfactualAnswer = {
    status: 'found',
    current: { prediction: '1', probability: 0.8 },
    target: { class: '0' },
    results: [
      { changes: [{ field: 'tenure', from: 6, to: 52 }], changed_fields: 1, distance: 0.489, prediction: '0', probability: 0.91 },
      { changes: [{ field: 'plan', from: 'prepaid', to: 'hybrid' }], changed_fields: 1, distance: 1, prediction: '0', probability: null },
    ],
    refused: [],
    fields: [],
    evaluated: 13,
    budget: 2000,
    exhausted: false,
  };
  assert.deepEqual(counterfactualRows(answer, 'en'), [
    { rank: 1, changes: [{ field: 'tenure', from: '6', to: '52' }], answer: '0', probability: '91%', distance: '0.49' },
    { rank: 2, changes: [{ field: 'plan', from: 'prepaid', to: 'hybrid' }], answer: '0', probability: null, distance: '1' },
  ]);
  assert.deepEqual(counterfactualRows(null, 'en'), []);
});

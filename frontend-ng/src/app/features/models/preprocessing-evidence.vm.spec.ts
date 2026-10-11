import assert from 'node:assert/strict';
import { test } from 'node:test';
import { fittedPreparation, preparationRows, preparationWidth, type PreprocessingEvidence } from './preprocessing-evidence.vm';

const evidence: PreprocessingEvidence = { schema: 1, status: 'available', learning_scope: 'training_folds',
  input_count: 2, retained_count: 1, excluded_count: 1, output_count: 3, columns: [
    { name: 'region', input_dtype: 'object', kind: 'low_cardinality', transformers: ['sklearn.preprocessing.OneHotEncoder'], output_count: 3, excluded: false, reason: null },
    { name: 'constant', input_dtype: 'float64', kind: 'numeric', transformers: [], output_count: 0, excluded: true, reason: 'constant' },
  ] };
test('only recorded fitted preparation describes the model; missing and wrong scopes stay unavailable', () => {
  assert.equal(fittedPreparation(undefined), null);
  assert.equal(fittedPreparation({ ...evidence, status: 'unavailable' }), null);
  assert.equal(fittedPreparation({ ...evidence, learning_scope: 'full_dataset' }), null);
  assert.equal(fittedPreparation({ ...evidence, retained_count: 2 }), null);
  assert.equal(fittedPreparation(evidence), evidence);
  assert.equal(preparationWidth({ ...evidence, output_count: null }), null);
  assert.equal(preparationWidth(evidence), 3);
});
test('retained and excluded columns preserve their actual operations without duplicate rows', () => {
  assert.deepEqual(preparationRows({ ...evidence, columns: [...evidence.columns, evidence.columns[0]] }), evidence.columns);
  assert.equal(preparationRows({ ...evidence, columns: Array.from({ length: 100 }, (_, i) => ({ ...evidence.columns[0], name: `feature_${i}` })) }).length, 64);
});

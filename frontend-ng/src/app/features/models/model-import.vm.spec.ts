import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  canSubmit, importEvidence, importPhase, isImported, lineageChoices, measurementLines, readerCodeKey,
  refusalKey, type ImportForm, type ImportJob,
} from './model-import.vm';
import type { ModelDto } from './models.vm';

function model(overrides: Partial<ModelDto> & Record<string, unknown> = {}): ModelDto {
  return {
    id: 'm1', name: 'Churn', slug: 'churn', version: 1, task: 'classification', family: 'external',
    algo: 'external', target: 'churn', is_champion: true, status: 'ready', ...overrides,
  } as unknown as ModelDto;
}

function job(overrides: Partial<ImportJob> = {}): ImportJob {
  return { id: 'j1', status: 'completed', error: null, updated_at: null, result: { verdict: 'accepted', model_id: 'm9' }, ...overrides };
}

const form: ImportForm = {
  archive: {} as File, validation: {} as File, task: 'classification', name: 'Churn', target: 'churn', lineageModelId: null,
};

test('only external models of the same task are offered as lineages, newest version each', () => {
  const choices = lineageChoices([
    model({ id: 'a1', slug: 'a', name: 'Beta', version: 1 }),
    model({ id: 'a2', slug: 'a', name: 'Beta', version: 2 }),
    model({ id: 'b1', slug: 'b', name: 'Alpha', version: 1 }),
    model({ id: 't1', slug: 't', name: 'Trained', family: 'tabular' }),
    model({ id: 'r1', slug: 'r', name: 'Regressor', task: 'regression' }),
  ], 'classification');
  assert.deepEqual(choices, [{ id: 'b1', name: 'Alpha', version: 1 }, { id: 'a2', name: 'Beta', version: 2 }]);
  assert.equal(isImported(model()), true);
  assert.equal(isImported(model({ family: 'tabular' })), false);
  assert.equal(isImported(null), false);
});

test('submitting needs the capability, both files and a name or a lineage', () => {
  assert.equal(canSubmit(form, true, false), true);
  assert.equal(canSubmit(form, false, false), false);
  assert.equal(canSubmit(form, true, true), false);
  assert.equal(canSubmit({ ...form, archive: null }, true, false), false);
  assert.equal(canSubmit({ ...form, validation: null }, true, false), false);
  assert.equal(canSubmit({ ...form, name: '  ' }, true, false), false);
  assert.equal(canSubmit({ ...form, name: '', lineageModelId: 'a2' }, true, false), true);
});

test('the phase follows the job, and only a completed acceptance is accepted', () => {
  assert.equal(importPhase(null), 'idle');
  assert.equal(importPhase(job({ status: 'queued' })), 'pending');
  assert.equal(importPhase(job({ status: 'running' })), 'pending');
  assert.equal(importPhase(job()), 'accepted');
  assert.equal(importPhase(job({ status: 'failed', result: { verdict: 'refused', code: 'ML_IMPORT_VALIDATION_FAILED' } })), 'refused');
  assert.equal(importPhase(job({ status: 'failed', result: { verdict: 'accepted' } })), 'refused');
});

test('refusals read as their reason, then their code, never as raw text', () => {
  assert.equal(refusalKey({ code: 'ML_IMPORT_REJECTED', reason: 'pickle_serialization' }), 'models.import.reason.pickle_serialization');
  assert.equal(refusalKey({ code: 'ML_IMPORT_DISABLED' }), 'models.import.error.ml_import_disabled');
  assert.equal(refusalKey({ code: 'ML_SOMETHING_NEW', reason: 'unknown_reason' }), 'models.import.error.generic');
  assert.equal(refusalKey(null, 'ML_IMPORT_ABANDONED'), 'models.import.error.ml_import_abandoned');
  assert.equal(readerCodeKey({ reason: 'reader_refused', error_code: 'ML_IMPORT_TREE_INVALID' }), 'models.import.error.ml_import_tree_invalid');
  assert.equal(readerCodeKey({ reason: 'outputs_differ', error_code: 'ML_IMPORT_TREE_INVALID' }), null);
});

test('measured costs sit next to their budget and flag the one exceeded', () => {
  const lines = measurementLines(
    { load_ms: 1200, single_row_ms: 2.5, model_memory_mb: 2048 },
    { max_load_ms: 30000, max_predict_ms: 1000, max_memory_mb: 1024 },
  );
  assert.deepEqual(lines.map(line => [line.key, line.over]), [
    ['models.import.measure.load', false], ['models.import.measure.latency', false], ['models.import.measure.memory', true],
  ]);
  assert.deepEqual(lines[0].params, { value: '1200 ms', limit: '30000 ms' });
  assert.deepEqual(measurementLines(null, null), []);
});

test('an imported card reads its validation and provenance, a trained one has none', () => {
  const evidence = importEvidence(model({
    metrics: { import: { validation: {
      rows: 30, metrics: { label_agreement: 1, label_disagreements: 0, max_abs_proba_diff: 0 },
      tolerances: { max_label_disagreements: 0, proba_atol: 1e-6 },
      measurements: { load_ms: 900 }, budgets: { max_load_ms: 30000, max_predict_ms: 1000, max_memory_mb: 1024 },
    } } } as never,
    params: { import: { estimator: 'RandomForestClassifier', archive_sha256: 'abcdef0123456789', requirements: ['scikit-learn==1.9.0'] } },
  }));
  assert.equal(evidence?.rows, 30);
  assert.equal(evidence?.estimator, 'RandomForestClassifier');
  assert.equal(evidence?.archiveSha, 'abcdef012345');
  assert.deepEqual(evidence?.requirements, ['scikit-learn==1.9.0']);
  assert.equal(evidence?.gaps[0].key, 'models.runtime.gap.labels');
  assert.equal(evidence?.measures.length, 1);
  assert.equal(importEvidence(model({ family: 'tabular' })), null);
});

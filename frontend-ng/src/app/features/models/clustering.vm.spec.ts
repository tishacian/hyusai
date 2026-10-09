import { test } from 'node:test';
import assert from 'node:assert/strict';
import { clusteringColumns } from './clustering.vm';
import { trainChecklist, trainingErrorKey, formatMetric, metricTone, refusalField, refusalKey, trainableTasks, type ModelCatalog, type PlanColumn } from './models.vm';
import { preflightTrain, readTrainParams } from '../orchestration/flow/flow-ml.vm';
import type { CanonicalFlowNode } from '@app/core/flow-serializer.service';

const column = (name: string, kind: string) => ({ name, kind, distinct: 30, nulls: 0, suggested_task: 'regression' }) as PlanColumn;
const node = (params: Record<string, unknown>) => ({ id: 'segment', kind: 'task', config: { params } }) as CanonicalFlowNode;

test('segmentation offers only numeric columns, including integer measurements', () => {
  assert.deepEqual(clusteringColumns([column('traffic', 'float'), column('age', 'integer'), column('amount', 'number'), column('site', 'string'), column('date', 'datetime'), column('active', 'boolean')]).map(c => c.name), ['traffic', 'age', 'amount']);
});

test('a saved targetless segmentation survives Flow reads and passes preflight', () => {
  const params = readTrainParams(node({ task: 'clustering', target: '', features: ['traffic', 'age'], algo: 'kmeans', knobs: { n_clusters: 3 }, sources: [{ dataset_slug: 'cells' }], test_size: 0 }));
  assert.equal(params.task, 'clustering');
  assert.equal(params.test_size, 0);
  assert.deepEqual(params.features, ['traffic', 'age']);
  assert.deepEqual(params.knobs, { n_clusters: 3 });
  assert.equal(preflightTrain(params), null);
});

test('segmentation requires explicit features while supervised models still require a target', () => {
  for (const features of [null, []]) {
    assert.equal(preflightTrain(readTrainParams(node({ task: 'clustering', features, sources: [{ dataset_slug: 'cells' }] })))?.key, refusalKey('ML_FEATURES_REQUIRED'));
  }
  assert.equal(preflightTrain(readTrainParams(node({ task: 'regression', features: ['traffic'], sources: [{ dataset_slug: 'cells' }] })))?.key, refusalKey('ML_TARGET_REQUIRED'));
});

test('negative clustering scores keep their scale and avoid arbitrary quality thresholds', () => {
  assert.equal(formatMetric('silhouette', -0.35, 'en'), '-0.35');
  assert.equal(formatMetric('stability_ari', -0.12, 'en'), '-0.12');
  assert.equal(metricTone('silhouette', -0.35), 'neutral');
});

test('segmentation requires an advertised available family and localizes numeric refusals', () => {
  const catalog = { tasks: ['classification', 'clustering'], families: [{ key: 'clustering', available: true, tasks: ['clustering'], spec_fields: [] }] } as ModelCatalog;
  assert.deepEqual(trainableTasks(catalog), ['clustering']);
  catalog.families![0].available = false;
  assert.deepEqual(trainableTasks(catalog), []);
  assert.equal(refusalField('ML_CLUSTER_FEATURE_NOT_NUMERIC'), 'features');
  assert.equal(refusalKey('ML_CLUSTER_FEATURE_NOT_NUMERIC'), 'models.refusal.ml_cluster_feature_not_numeric');
});


test('clustering progress reports profiles then three stability subsamples without a holdout', () => {
  const steps = trainChecklist('training', 'validating:1/3', 0, 'fr', 'clustering');
  assert.deepEqual(steps.map(step => step.step), ['queued', 'reading', 'fitting', 'scoring', 'validating', 'saving']);
  assert.equal(steps.find(step => step.state === 'active')?.step, 'validating');
  assert.equal(steps.find(step => step.step === 'scoring')?.key, 'models.progress.clustering.scoring');
  assert.deepEqual(steps.find(step => step.step === 'validating')?.params, {fold:1,folds:3});
  assert.equal(steps.find(step => step.step === 'validating')?.key, 'models.progress.clustering.validating.counted');
  const settled = trainChecklist('ready', 'saving', 0, 'en', 'clustering');
  assert.equal(settled.find(step => step.step === 'validating')?.key, 'models.progress.clustering.validating');
  assert.deepEqual(settled.find(step => step.step === 'validating')?.params, {folds:3});
  assert.equal(trainingErrorKey('ML_CLUSTER_DATA_UNUSABLE'), 'models.error.ml_cluster_data_unusable');
});

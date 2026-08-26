/**
 * The model plane's node logic, exercised without Angular.
 *
 * Two invariants dominate this file, and both are cross-plane:
 *
 *  - the param names are a mirror of `_TRAIN_PARAM_KEYS` / `_PREDICT_PARAM_KEYS`
 *    in `dag.py`. A rename on either side is a node that silently loses its
 *    configuration, so the names are asserted as data, not implied by usage.
 *  - a refusal has exactly one sentence. The node-owned codes live under
 *    `flow.ml.error.*`; everything else is the model plane's to phrase, and this
 *    spec is what stops a second copy from appearing.
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { CanonicalFlowNode } from '@app/core/flow-serializer.service';
import { FLOW_EN, FLOW_FR } from '@app/core/i18n/flow.dict';
import { MODELS_EN, MODELS_FR } from '@app/core/i18n/models.dict';
import {
  REFUSAL_CODES,
  SERVING_ERROR_CODES,
  TRAINING_ERROR_CODES,
  type ModelDto,
} from '@app/features/models/models.vm';
import {
  FLOW_ML_ERROR_CODES,
  ML_PREDICT_SKILL_SLUG,
  ML_SCORE_SKILL_SLUG,
  ML_TRAIN_SKILL_SLUG,
  SERVING_ROLES,
  TRAIN_CV_OPTIONS,
  TRAIN_STEPS,
  TRAIN_TEST_SIZE_DEFAULT,
  TRAIN_TEST_SIZE_MAX,
  TRAIN_TEST_SIZE_MIN,
  chooseModelPatch,
  clampFolds,
  clampTestSize,
  isBatchScoreNode,
  isServingNode,
  isTrainNode,
  lineageVersions,
  mlFailure,
  mlNodeRole,
  pinVersionPatch,
  pinnedDataset,
  predictDefaultParams,
  preflightServing,
  preflightTrain,
  readPredictParams,
  readTrainParams,
  servableModels,
  servingDescriptor,
  servingSummary,
  trainDefaultParams,
  trainSummary,
} from './flow-ml.vm';

function node(slug: string, params: Record<string, unknown> = {}): CanonicalFlowNode {
  return {
    id: `task.${slug}`,
    type: 'skill',
    kind: 'task',
    label: 'Churn',
    config: { skill_slug: slug, params },
  };
}

function model(overrides: Partial<ModelDto> = {}): ModelDto {
  return {
    id: 'model-1',
    slug: 'churn-risk',
    name: 'Churn risk',
    version: 3,
    status: 'ready',
    task: 'classification',
    ...overrides,
  } as ModelDto;
}

function key(dictionaryKey: string): void {
  const fr = { ...FLOW_FR, ...MODELS_FR } as Record<string, string>;
  const en = { ...FLOW_EN, ...MODELS_EN } as Record<string, string>;
  assert.ok(fr[dictionaryKey]?.trim(), `${dictionaryKey} has FR copy`);
  assert.ok(en[dictionaryKey]?.trim(), `${dictionaryKey} has EN copy`);
}

// ---------------------------------------------------------------------------
// Which node is which
// ---------------------------------------------------------------------------

test('the three model Skills are three roles, and nothing else is one', () => {
  assert.equal(mlNodeRole(node(ML_TRAIN_SKILL_SLUG)), 'train');
  assert.equal(mlNodeRole(node(ML_PREDICT_SKILL_SLUG)), 'predict');
  assert.equal(mlNodeRole(node(ML_SCORE_SKILL_SLUG)), 'score');
  assert.equal(mlNodeRole(node('python_recipe_v1')), null);
  assert.equal(mlNodeRole(null), null);
  assert.equal(mlNodeRole(undefined), null);

  assert.ok(isTrainNode(node(ML_TRAIN_SKILL_SLUG)));
  assert.ok(!isTrainNode(node(ML_PREDICT_SKILL_SLUG)));
  assert.ok(isServingNode(node(ML_PREDICT_SKILL_SLUG)));
  assert.ok(isServingNode(node(ML_SCORE_SKILL_SLUG)));
  assert.ok(!isServingNode(node(ML_TRAIN_SKILL_SLUG)));
  assert.ok(isBatchScoreNode(node(ML_SCORE_SKILL_SLUG)));
});

test('a non-task node bound to a model Skill is not a model node', () => {
  // A decision or a gate carrying a stale `skill_slug` must not grow a model
  // section: the kind is what decides, and the slug only refines it.
  const gate: CanonicalFlowNode = {
    id: 'hitl.1',
    type: 'hitl',
    kind: 'hitl',
    label: 'Approve',
    config: { skill_slug: ML_TRAIN_SKILL_SLUG },
  };
  assert.equal(mlNodeRole(gate), null);
});

test('the serving descriptor carries what differs, as data', () => {
  const predict = servingDescriptor(node(ML_PREDICT_SKILL_SLUG));
  const score = servingDescriptor(node(ML_SCORE_SKILL_SLUG));
  assert.ok(predict && score);
  // Only the dataset shape names an output; only the inline shape can afford
  // per-row contributions. A branch in a template would let these drift.
  assert.equal(predict.writesDataset, false);
  assert.equal(predict.supportsExplain, true);
  assert.equal(score.writesDataset, true);
  assert.equal(score.supportsExplain, false);
  assert.equal(servingDescriptor(node(ML_TRAIN_SKILL_SLUG)), null);
  for (const descriptor of Object.values(SERVING_ROLES)) {
    key(descriptor.copy.section);
    key(descriptor.copy.hint);
  }
});

// ---------------------------------------------------------------------------
// The param bag — a mirror of dag.py
// ---------------------------------------------------------------------------

test('a dropped training node carries every key the _train block projects', () => {
  // The exact key list of `_TRAIN_PARAM_KEYS`. A node missing one of these
  // sends `undefined` for a field the server reads, which is how a default
  // silently replaces an author's decision.
  assert.deepEqual(Object.keys(trainDefaultParams()).sort(), [
    'algo',
    'cross_validation',
    'features',
    'knobs',
    'model_name',
    'sources',
    'target',
    'task',
    'test_size',
  ]);
  // Nothing is guessed: what to predict is the one thing only the author knows.
  assert.equal(trainDefaultParams()['target'], '');
  assert.equal(trainDefaultParams()['features'], null);
  assert.equal(trainDefaultParams()['test_size'], TRAIN_TEST_SIZE_DEFAULT);
});

test('a dropped serving node carries only the keys its shape reads', () => {
  const predict = Object.keys(predictDefaultParams('predict')).sort();
  const score = Object.keys(predictDefaultParams('score')).sort();
  assert.deepEqual(predict, [
    'explain',
    'model_id',
    'model_slug',
    'pinned_version',
    'sources',
  ]);
  assert.deepEqual(score, [
    'model_id',
    'model_slug',
    'output_name',
    'pinned_version',
    'sources',
  ]);
});

test('reading a training node normalises what an author can leave broken', () => {
  const params = readTrainParams(
    node(ML_TRAIN_SKILL_SLUG, {
      task: 'clustering',
      target: '  churn  ',
      features: ['arpu', 42, '', 'plan'],
      algo: ' random_forest ',
      knobs: { max_iter: '250', depth: 'deep' },
      test_size: 0.9,
      cross_validation: 4,
      model_name: '  Churn risk ',
      sources: [{ dataset_slug: ' churn-features ' }, 'nope', {}],
    }),
  );
  assert.equal(params.task, null, 'an unknown task is no task, not a bad one');
  assert.equal(params.target, 'churn');
  assert.deepEqual(params.features, ['arpu', 'plan']);
  assert.equal(params.algo, 'random_forest');
  assert.deepEqual(params.knobs, { max_iter: 250 });
  assert.equal(params.test_size, TRAIN_TEST_SIZE_MAX);
  assert.equal(params.cross_validation, 0, 'a fold count nobody offers is off');
  assert.equal(params.model_name, 'Churn risk');
  assert.deepEqual(params.sources, [{ dataset_slug: 'churn-features' }]);
});

test('a pin is read under either spelling, because both are written', () => {
  // `slug` is how a run envelope names its lineage and `dataset_slug` is how a
  // node pins one. `resolve_dataset_ref` accepts both; so does this.
  const fromSlug = readTrainParams(
    node(ML_TRAIN_SKILL_SLUG, { sources: [{ slug: 'churn-features' }] }),
  );
  assert.deepEqual(pinnedDataset(fromSlug.sources), { dataset_slug: 'churn-features' });
  const fromId = readPredictParams(
    node(ML_SCORE_SKILL_SLUG, { sources: [{ dataset_id: 'ds-1' }] }),
  );
  assert.deepEqual(pinnedDataset(fromId.sources), { dataset_id: 'ds-1' });
  assert.equal(pinnedDataset([]), null);
});

test('reading a serving node keeps a version pin whole or drops it', () => {
  const pinned = readPredictParams(
    node(ML_PREDICT_SKILL_SLUG, { model_slug: 'churn-risk', pinned_version: '2.6' }),
  );
  assert.equal(pinned.pinned_version, 3, 'a version is an integer or it is nothing');
  const following = readPredictParams(
    node(ML_PREDICT_SKILL_SLUG, { model_slug: 'churn-risk', pinned_version: null }),
  );
  assert.equal(following.pinned_version, null);
  const nonsense = readPredictParams(
    node(ML_PREDICT_SKILL_SLUG, { pinned_version: 'champion' }),
  );
  assert.equal(nonsense.pinned_version, null);
  assert.equal(nonsense.explain, false, 'anything but true is false');
});

test('the split and the folds are clamped to what the studio offers', () => {
  assert.equal(clampTestSize(0.4), 0.4);
  assert.equal(clampTestSize(0.001), TRAIN_TEST_SIZE_MIN);
  assert.equal(clampTestSize(12), TRAIN_TEST_SIZE_MAX);
  assert.equal(clampTestSize('0.3'), 0.3);
  assert.equal(clampTestSize('nope'), TRAIN_TEST_SIZE_DEFAULT);
  assert.equal(clampTestSize(0), TRAIN_TEST_SIZE_DEFAULT);
  for (const folds of TRAIN_CV_OPTIONS) assert.equal(clampFolds(String(folds)), folds);
  assert.equal(clampFolds(7), 0);
  assert.equal(clampFolds(null), 0);
});

// ---------------------------------------------------------------------------
// Refusals — one sentence each
// ---------------------------------------------------------------------------

test('an unfinished training node is refused before a round-trip is spent', () => {
  const empty = readTrainParams(node(ML_TRAIN_SKILL_SLUG, trainDefaultParams()));
  assert.equal(preflightTrain(empty)?.key, 'flow.ml.error.ml_no_dataset');
  // Wired, the dataset arrives on the edge, so the next gap is the target.
  assert.equal(
    preflightTrain(empty, { wired: true })?.key,
    'models.refusal.ml_target_required',
  );

  const pinned = readTrainParams(
    node(ML_TRAIN_SKILL_SLUG, {
      target: 'churn',
      features: [],
      sources: [{ dataset_slug: 'churn-features' }],
    }),
  );
  assert.equal(preflightTrain(pinned)?.key, 'models.refusal.ml_features_required');

  const leaking = readTrainParams(
    node(ML_TRAIN_SKILL_SLUG, {
      target: 'churn',
      features: ['arpu', 'churn'],
      sources: [{ dataset_slug: 'churn-features' }],
    }),
  );
  const refusal = preflightTrain(leaking);
  assert.equal(refusal?.key, 'flow.ml.error.ml_target_in_features');
  assert.equal(refusal?.detail, 'churn', 'naming the column IS the fix');

  const complete = readTrainParams(
    node(ML_TRAIN_SKILL_SLUG, {
      target: 'churn',
      features: null,
      sources: [{ dataset_slug: 'churn-features' }],
    }),
  );
  assert.equal(preflightTrain(complete), null, 'the default feature set is not empty');
});

test('a serving node has to name a model, and a score node a dataset', () => {
  const predict = SERVING_ROLES.predict;
  const score = SERVING_ROLES.score;
  const blank = readPredictParams(node(ML_PREDICT_SKILL_SLUG));
  assert.equal(
    preflightServing(blank, predict)?.key,
    'flow.ml.error.ml_model_required',
  );

  const chosen = readPredictParams(
    node(ML_SCORE_SKILL_SLUG, { model_slug: 'churn-risk' }),
  );
  assert.equal(
    preflightServing(chosen, score)?.key,
    'flow.ml.error.ml_score_dataset_required',
  );
  assert.equal(
    preflightServing(chosen, score, { wired: true }),
    null,
    'an upstream edge is a dataset too',
  );
  // The inline shape writes no dataset, so it never asks for one.
  assert.equal(preflightServing(chosen, predict), null);
});

test('the node keeps its own refusals and hands the rest to the model plane', () => {
  for (const code of FLOW_ML_ERROR_CODES) {
    assert.equal(mlFailure(code).key, `flow.ml.error.${code.toLowerCase()}`);
    key(`flow.ml.error.${code.toLowerCase()}`);
  }
  // A spec refusal, a settled-run failure and a serving refusal each already
  // have one sentence on the model plane. Re-homing any of them here would be a
  // second sentence to keep true.
  assert.equal(
    mlFailure('ML_TARGET_SINGLE_CLASS').key,
    'models.refusal.ml_target_single_class',
  );
  assert.equal(mlFailure('ML_FIT_FAILED').key, 'models.error.ml_fit_failed');
  assert.equal(
    mlFailure('ML_ARTIFACT_UNLOADABLE').key,
    'models.serving.error.ml_artifact_unloadable',
  );
  // Case and padding come from an HTTP envelope, not from a keyboard.
  assert.equal(mlFailure(' ml_fit_failed ').key, 'models.error.ml_fit_failed');
});

test('every code the model plane can emit resolves to a sentence, not a blank', () => {
  for (const code of [
    ...REFUSAL_CODES,
    ...TRAINING_ERROR_CODES,
    ...SERVING_ERROR_CODES,
  ]) {
    const failure = mlFailure(code, 'raw worker text');
    assert.notEqual(
      failure.key,
      'flow.ml.error.unknown',
      `${code} must resolve to its own sentence`,
    );
    key(failure.key);
  }
});

test('a code nobody named keeps the server’s own words', () => {
  const unknown = mlFailure('ML_SOMETHING_NEW', 'the worker said this');
  assert.equal(unknown.key, 'flow.ml.error.unknown');
  assert.equal(unknown.detail, 'the worker said this');
  assert.equal(mlFailure(null, '').detail, undefined);
  key('flow.ml.error.unknown');
  key('flow.ml.run.cancelled');
});

// ---------------------------------------------------------------------------
// Summaries and the model picker
// ---------------------------------------------------------------------------

test('a training node is summarised by what it predicts', () => {
  const withDefault = readTrainParams(
    node(ML_TRAIN_SKILL_SLUG, { target: 'churn', features: null }),
  );
  assert.equal(trainSummary(withDefault), 'churn');
  const narrowed = readTrainParams(
    node(ML_TRAIN_SKILL_SLUG, { target: 'churn', features: ['arpu', 'plan'] }),
  );
  assert.equal(trainSummary(narrowed), 'churn · 2');
  assert.equal(trainSummary(readTrainParams(node(ML_TRAIN_SKILL_SLUG))), '');
});

test('a serving summary distinguishes following from freezing', () => {
  const registry = [model(), model({ id: 'model-0', version: 2 })];
  const following = servingSummary(
    readPredictParams(node(ML_PREDICT_SKILL_SLUG, { model_slug: 'churn-risk' })),
    registry,
  );
  assert.deepEqual(following, { label: 'churn-risk', pinned: false });

  const frozen = servingSummary(
    readPredictParams(
      node(ML_PREDICT_SKILL_SLUG, { model_slug: 'churn-risk', pinned_version: 2 }),
    ),
    registry,
  );
  assert.deepEqual(frozen, { label: 'churn-risk v2', pinned: true });

  // An id is a frozen reference by construction, even with no version pin.
  const byId = servingSummary(
    readPredictParams(node(ML_PREDICT_SKILL_SLUG, { model_id: 'model-1' })),
    registry,
  );
  assert.deepEqual(byId, { label: 'Churn risk v3', pinned: true });
  assert.equal(servingSummary(readPredictParams(node(ML_PREDICT_SKILL_SLUG))), null);
});

test('the picker only offers models that can answer', () => {
  const registry = [
    model({ id: 'a', slug: 'churn-risk', version: 2 }),
    model({ id: 'b', slug: 'churn-risk', version: 3 }),
    model({ id: 'c', slug: 'arpu-forecast', version: 1 }),
    model({ id: 'd', slug: 'churn-risk', version: 4, status: 'training' }),
    model({ id: 'e', slug: 'churn-risk', version: 5, status: 'failed' }),
  ];
  // A model still fitting cannot answer, and offering it would turn a
  // configuration mistake into a run-time refusal.
  assert.deepEqual(
    servableModels(registry).map((row) => row.id),
    ['c', 'b', 'a'],
  );
  assert.deepEqual(
    lineageVersions(registry, 'churn-risk').map((row) => row.version),
    [3, 2],
  );
  assert.deepEqual(lineageVersions(registry, ''), []);
});

test('choosing a lineage follows it; pinning a version freezes it', () => {
  // The champion/challenger story only works if choosing a lineage does NOT
  // freeze an id behind the author's back.
  assert.deepEqual(chooseModelPatch(model()), {
    model_slug: 'churn-risk',
    model_id: '',
    pinned_version: null,
  });
  assert.deepEqual(pinVersionPatch(2), { pinned_version: 2 });
  assert.deepEqual(pinVersionPatch(null), { pinned_version: null });
  assert.deepEqual(pinVersionPatch(0), { pinned_version: null });
});

// ---------------------------------------------------------------------------
// The live check-list
// ---------------------------------------------------------------------------

test('every step of a fit has copy in both languages', () => {
  // The list itself is `trainChecklist`, exercised in `models.vm.spec.ts`; what
  // is asserted here is that the studio can name what it draws.
  for (const step of TRAIN_STEPS) key(`models.progress.step.${step}`);
  key('models.progress.step.fitting.counted');
  key('models.progress.step.validating.counted');
});

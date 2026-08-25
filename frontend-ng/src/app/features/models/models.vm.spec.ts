/**
 * The model card's arguments, asserted.
 *
 * Everything here decides what a viewer concludes about a model — whether a
 * score is called good, which mistake the confusion matrix highlights, which
 * column looks decisive. Those are the claims worth pinning down: a plot that
 * renders and lies is worse than a plot that does not render.
 */
import test from 'node:test';
import assert from 'node:assert/strict';

import { MODELS_EN, MODELS_FR } from '@app/core/i18n/models.dict';
import {
  MODEL_ACTIVE_STATUSES,
  PLAN_WARNING_CODES,
  REFUSAL_CODES,
  TRAINING_ERROR_CODES,
  UNIT_DOMAIN,
  algoIcon,
  balanceBars,
  bestScore,
  clampKnob,
  confusionView,
  curveDomain,
  curvePath,
  defaultFeatures,
  defaultKnobs,
  formatMetric,
  higherIsBetter,
  importanceBars,
  isActiveStatus,
  knobIsAuto,
  metricScale,
  metricTone,
  primaryScore,
  refusalField,
  refusalKey,
  splitError,
  targetCandidates,
  taskIcon,
  trainingErrorKey,
  warningKey,
  type KnobDescriptor,
  type ModelDto,
  type ModelStatus,
  type PlanColumn,
} from './models.vm';

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

test('only a queued or running fit keeps a surface polling', () => {
  assert.ok(isActiveStatus('pending'));
  assert.ok(isActiveStatus('training'));
  assert.ok(!isActiveStatus('ready'));
  assert.ok(!isActiveStatus('failed'));
  assert.ok(!isActiveStatus('cancelled'));
  assert.ok(!isActiveStatus(null));
  assert.ok(!isActiveStatus(undefined));
});

test('every model status is classified, so none can silently spin forever', () => {
  const all: ModelStatus[] = ['pending', 'training', 'ready', 'failed', 'cancelled'];
  assert.deepEqual(all.filter(isActiveStatus), [...MODEL_ACTIVE_STATUSES]);
  assert.deepEqual(all.filter((status) => !isActiveStatus(status)), [
    'ready',
    'failed',
    'cancelled',
  ]);
});

test('each algorithm family gets its own icon so the picker reads at a glance', () => {
  assert.equal(algoIcon('gradient_boosting'), 'bar-chart-3');
  assert.equal(algoIcon('random_forest'), 'git-branch');
  assert.equal(algoIcon('linear'), 'line-chart');
  assert.equal(algoIcon('knn'), 'circle-dot');
  assert.equal(algoIcon('something_new'), 'brain');
  assert.equal(taskIcon('classification'), 'target');
  assert.equal(taskIcon('regression'), 'trending-up');
});

// ---------------------------------------------------------------------------
// Metrics
// ---------------------------------------------------------------------------

test('a metric is rendered in its own units, never as a bare ratio', () => {
  assert.equal(formatMetric('roc_auc', 0.8123, 'en'), '81.2%');
  assert.equal(formatMetric('accuracy', 1, 'en'), '100%');
  assert.equal(formatMetric('mape', 12.34, 'en'), '12.3%');
  assert.equal(formatMetric('mae', 4.567, 'en'), '4.57');
  assert.equal(formatMetric('mae', 1234.5, 'en'), '1,235');
  assert.equal(formatMetric('rmse', 0.001234, 'en'), '0.0012');
  assert.equal(metricScale('roc_auc'), 'ratio');
  assert.equal(metricScale('mape'), 'percent');
  assert.equal(metricScale('mae'), 'value');
  assert.equal(metricScale('made_up'), 'value');
});

test('a missing score reads as absent rather than as a zero', () => {
  assert.equal(formatMetric('roc_auc', null, 'en'), '—');
  assert.equal(formatMetric('roc_auc', undefined, 'en'), '—');
  assert.equal(formatMetric('roc_auc', Number.NaN, 'en'), '—');
});

test('a verdict is only given where the metric scale is absolute', () => {
  assert.equal(metricTone('roc_auc', 0.91), 'pos');
  assert.equal(metricTone('roc_auc', 0.71), 'warn');
  assert.equal(metricTone('roc_auc', 0.52), 'neg');
  // Lower is better, so the thresholds invert rather than being reused.
  assert.equal(metricTone('mape', 6), 'pos');
  assert.equal(metricTone('mape', 18), 'warn');
  assert.equal(metricTone('mape', 40), 'neg');
  // An MAE is in the target's units: no threshold can be honest about it.
  assert.equal(metricTone('mae', 0.01), 'neutral');
  assert.equal(metricTone('rmse', 9999), 'neutral');
  assert.equal(metricTone('roc_auc', null), 'neutral');
  assert.equal(metricTone('unknown_metric', 0.99), 'neutral');
});

test('higher-is-better is stated per metric, not assumed', () => {
  assert.ok(higherIsBetter('roc_auc'));
  assert.ok(higherIsBetter('r2'));
  assert.ok(!higherIsBetter('mae'));
  assert.ok(!higherIsBetter('mape'));
  assert.ok(higherIsBetter('unknown_metric'));
});

test('the row score prefers the list payload but falls back to the detail block', () => {
  const listRow = { primary_metric: { key: 'roc_auc', value: 0.8 } } as ModelDto;
  assert.deepEqual(primaryScore(listRow), { key: 'roc_auc', value: 0.8 });

  const detailRow = { metrics: { primary: { key: 'r2', value: 0.5 } } } as ModelDto;
  assert.deepEqual(primaryScore(detailRow), { key: 'r2', value: 0.5 });

  assert.equal(primaryScore({} as ModelDto), null);
  assert.equal(primaryScore(null), null);
});

function scored(
  key: string,
  value: number,
  status: ModelStatus = 'ready',
): ModelDto {
  return { status, primary_metric: { key, value } } as ModelDto;
}

test('the best score never ranks one metric against another', () => {
  // Newest first, as the API serves it: the AUC sets the comparison.
  const best = bestScore([
    scored('roc_auc', 0.71),
    scored('r2', 0.99),
    scored('roc_auc', 0.88),
    scored('roc_auc', 0.64),
  ]);
  assert.deepEqual(best, { key: 'roc_auc', value: 0.88 });
});

test('the best score minimises a metric where lower is better', () => {
  const best = bestScore([scored('mae', 12.5), scored('mae', 3.25), scored('mae', 40)]);
  assert.deepEqual(best, { key: 'mae', value: 3.25 });
});

test('an unfinished or unscored run cannot become the best score', () => {
  assert.equal(bestScore([]), null);
  assert.equal(bestScore([scored('roc_auc', 0.9, 'training')]), null);
  assert.equal(bestScore([{ status: 'ready' } as ModelDto]), null);
  assert.deepEqual(
    bestScore([scored('roc_auc', 0.9, 'failed'), scored('roc_auc', 0.6)]),
    { key: 'roc_auc', value: 0.6 },
  );
});

// ---------------------------------------------------------------------------
// Curves
// ---------------------------------------------------------------------------

const BOX = { width: 100, height: 50 };

test('a curve is drawn with y flipped, so a better model climbs', () => {
  const path = curvePath(
    [
      { x: 0, y: 0 },
      { x: 0.5, y: 1 },
      { x: 1, y: 1 },
    ],
    BOX,
    UNIT_DOMAIN,
  );
  assert.equal(path, 'M0,50 L50,0 L100,0');
});

test('a curve with nothing to draw yields no path rather than a stray dot', () => {
  assert.equal(curvePath([], BOX), '');
  assert.equal(curvePath(undefined, BOX), '');
  assert.equal(curvePath([{ x: 0.5, y: 0.5 }], BOX), '');
  // Non-finite samples are dropped before the count is judged.
  assert.equal(curvePath([{ x: 0, y: 0 }, { x: Number.NaN, y: 1 }], BOX), '');
});

test('a regression fit is scaled to the target’s own units, not the unit square', () => {
  const fit = [
    { x: 10, y: 12 },
    { x: 30, y: 28 },
  ];
  const ideal = [
    { x: 10, y: 10 },
    { x: 30, y: 30 },
  ];
  const domain = curveDomain([fit, ideal]);
  assert.deepEqual(domain, { minX: 10, maxX: 30, minY: 10, maxY: 30 });
  // Both series share the domain, so the diagonal really is the diagonal.
  assert.equal(curvePath(ideal, BOX, domain), 'M0,50 L100,0');
});

test('a degenerate domain is padded instead of dividing by zero', () => {
  const domain = curveDomain([[{ x: 5, y: 5 }]]);
  assert.deepEqual(domain, { minX: 5, maxX: 6, minY: 5, maxY: 6 });
  assert.deepEqual(curveDomain([]), UNIT_DOMAIN);
  assert.deepEqual(curveDomain([[]]), UNIT_DOMAIN);
});

// ---------------------------------------------------------------------------
// Confusion matrix
// ---------------------------------------------------------------------------

test('the confusion matrix is shaded per actual row, not per grand total', () => {
  // 96 loyal / 4 churners: the interesting cell is the one that is 50% of a
  // tiny row and 1% of the table. Row-normalizing is what keeps it visible.
  const view = confusionView({
    labels: ['loyal', 'churn'],
    matrix: [
      [94, 2],
      [2, 2],
    ],
  });
  assert.ok(view);
  assert.equal(view!.total, 100);
  assert.equal(view!.rows[1].total, 4);
  const missed = view!.rows[1].cells[0];
  assert.equal(missed.count, 2);
  assert.equal(missed.share, 0.5);
  assert.equal(missed.correct, false);
  assert.equal(view!.rows[1].cells[1].correct, true);
});

test('a malformed or absent matrix renders nothing at all', () => {
  assert.equal(confusionView(null), null);
  assert.equal(confusionView(undefined), null);
  assert.equal(confusionView({ labels: [], matrix: [] }), null);
  assert.equal(confusionView({ labels: ['a', 'b'], matrix: [[1, 2]] }), null);
});

test('an empty row divides by nothing and stays at zero', () => {
  const view = confusionView({ labels: ['a', 'b'], matrix: [[0, 0], [1, 1]] });
  assert.equal(view!.rows[0].cells[0].share, 0);
});

// ---------------------------------------------------------------------------
// Importances and balance
// ---------------------------------------------------------------------------

test('importances are normalized against the strongest column of the run', () => {
  const bars = importanceBars([
    { feature: 'tenure', value: 0.2 },
    { feature: 'arpu', value: 0.1 },
    { feature: 'region', value: 0 },
    { feature: 'id', value: null },
  ]);
  assert.deepEqual(
    bars.map((bar) => [bar.feature, bar.width, bar.negative]),
    [
      ['tenure', 100, false],
      ['arpu', 50, false],
      ['region', 0, false],
    ],
  );
});

test('a column that hurt the score is flagged, and still sized by magnitude', () => {
  const bars = importanceBars([
    { feature: 'tenure', value: 0.4 },
    { feature: 'noise', value: -0.2 },
  ]);
  assert.equal(bars[1].negative, true);
  assert.equal(bars[1].width, 50);
});

test('importances are capped so a wide table cannot become the whole card', () => {
  const many = Array.from({ length: 40 }, (_, index) => ({
    feature: `c${index}`,
    value: 1 - index / 100,
  }));
  assert.equal(importanceBars(many).length, 12);
  assert.equal(importanceBars(many, 3).length, 3);
  assert.deepEqual(importanceBars(undefined), []);
});

test('class balance carries the share, which is what makes accuracy readable', () => {
  const bars = balanceBars([
    { label: 'loyal', count: 960 },
    { label: 'churn', count: 40 },
  ]);
  assert.equal(bars[0].share, 0.96);
  assert.equal(bars[1].share, 0.04);
  assert.equal(bars[0].width, 100);
  assert.ok(bars[1].width < 5);
  assert.deepEqual(balanceBars([]), []);
  assert.deepEqual(balanceBars(undefined), []);
});

// ---------------------------------------------------------------------------
// The training form
// ---------------------------------------------------------------------------

const ITERS: KnobDescriptor = {
  key: 'max_iter',
  kind: 'int',
  default: 200,
  min: 20,
  max: 600,
  step: 10,
};

const DEPTH: KnobDescriptor = {
  key: 'max_depth',
  kind: 'int',
  default: 0,
  min: 0,
  max: 40,
  step: 1,
  auto_at: 0,
};

const RATE: KnobDescriptor = {
  key: 'learning_rate',
  kind: 'float',
  default: 0.1,
  min: 0.01,
  max: 1,
  step: 0.01,
};

test('a knob is clamped the way the backend will clamp it', () => {
  assert.equal(clampKnob(ITERS, 900), 600);
  assert.equal(clampKnob(ITERS, 1), 20);
  assert.equal(clampKnob(ITERS, 205.7), 206);
  assert.equal(clampKnob(ITERS, 'nonsense'), 200);
  assert.equal(clampKnob(ITERS, null), 20);
  assert.equal(clampKnob(RATE, 0.123456789), 0.123457);
  assert.equal(clampKnob(RATE, 5), 1);
});

test('a knob at its auto point reads as “let the estimator decide”', () => {
  assert.ok(knobIsAuto(DEPTH, 0));
  assert.ok(!knobIsAuto(DEPTH, 6));
  // A knob with no auto point never claims one.
  assert.ok(!knobIsAuto(ITERS, 20));
  assert.ok(!knobIsAuto(ITERS, 0));
});

test('knob defaults come from the descriptor, so the form opens where the server would', () => {
  assert.deepEqual(
    defaultKnobs({ key: 'gb', tasks: ['classification'], estimators: {}, scale: false, tags: [], knobs: [ITERS, RATE] }),
    { max_iter: 200, learning_rate: 0.1 },
  );
  assert.deepEqual(defaultKnobs(undefined), {});
});

const COLUMNS: PlanColumn[] = [
  { name: 'customer_id', kind: 'string', distinct: 5000, nulls: 0, suggested_task: 'classification' },
  { name: 'churned', kind: 'boolean', distinct: 2, nulls: 0, suggested_task: 'classification' },
  { name: 'arpu', kind: 'float', distinct: 4800, nulls: 3, suggested_task: 'regression' },
  { name: 'plan', kind: 'string', distinct: 4, nulls: 0, suggested_task: 'classification' },
  { name: 'country', kind: 'string', distinct: 1, nulls: 0, suggested_task: 'classification' },
];

test('the target picker offers only what can actually be predicted', () => {
  const offered = targetCandidates(COLUMNS, 24).map((column) => column.name);
  // `customer_id` has 5000 classes, `country` has one: neither is trainable.
  assert.deepEqual(offered, ['churned', 'arpu', 'plan']);
});

test('a numeric column stays offered however many values it holds', () => {
  const offered = targetCandidates(COLUMNS, 3).map((column) => column.name);
  assert.deepEqual(offered, ['churned', 'arpu']);
});

test('features default to every column but the target, as the backend does', () => {
  assert.deepEqual(defaultFeatures(COLUMNS, 'churned'), [
    'customer_id',
    'arpu',
    'plan',
    'country',
  ]);
});

// ---------------------------------------------------------------------------
// Refusals, warnings and failures
// ---------------------------------------------------------------------------

test('every refusal the backend can raise has a sentence and a field', () => {
  for (const code of REFUSAL_CODES) {
    assert.equal(refusalKey(code), `models.refusal.${code.toLowerCase()}`);
  }
  assert.equal(refusalKey('SOMETHING_NEW'), null);
  assert.equal(refusalKey(null), null);
});

test('a refusal renders next to the choice that caused it', () => {
  assert.equal(refusalField('ML_TARGET_SINGLE_CLASS'), 'target');
  assert.equal(refusalField('ML_TOO_MANY_FEATURES'), 'features');
  assert.equal(refusalField('ML_ALGO_TASK_MISMATCH'), 'algo');
  assert.equal(refusalField('ML_ROWS_INSUFFICIENT'), 'dataset');
  // A refusal no field owns still has to be read: the footer takes it.
  assert.equal(refusalField('ML_TRAIN_DISABLED'), null);
  assert.equal(refusalField('SOMETHING_NEW'), null);
});

test('the identifier warning is named, so a leaky column is called out by name', () => {
  assert.equal(warningKey('ML_FEATURE_IDENTIFIER'), 'models.warning.ml_feature_identifier');
  assert.equal(warningKey('NOT_A_WARNING'), null);
  assert.equal(warningKey(undefined), null);
});

test('a worker error splits into the code the UI can name and the line it cannot', () => {
  assert.deepEqual(splitError('ML_FIT_FAILED: ValueError: could not convert'), {
    code: 'ML_FIT_FAILED',
    detail: 'ValueError: could not convert',
  });
  // No code: the whole line is the detail rather than being dropped.
  assert.deepEqual(splitError('something went sideways'), {
    code: null,
    detail: 'something went sideways',
  });
  assert.deepEqual(splitError(''), { code: null, detail: '' });
  assert.deepEqual(splitError(null), { code: null, detail: '' });
});

test('a multi-line harness error keeps its tail, which is where the cause is', () => {
  const { code, detail } = splitError('ML_HARNESS_ERROR: line one\nline two');
  assert.equal(code, 'ML_HARNESS_ERROR');
  assert.equal(detail, 'line one\nline two');
});

test('every terminal failure the worker writes has a sentence of its own', () => {
  for (const code of TRAINING_ERROR_CODES) {
    assert.equal(trainingErrorKey(code), `models.error.${code.toLowerCase()}`);
  }
  assert.equal(trainingErrorKey('ML_SOMETHING_ELSE'), null);
  assert.equal(trainingErrorKey(null), null);
});

// ---------------------------------------------------------------------------
// Copy coverage
// ---------------------------------------------------------------------------

/**
 * A key with no entry renders as the key itself, which on a model card means a
 * prospect reads `models.refusal.ml_target_single_class` where a sentence
 * should be. Every key this module can assemble at runtime is checked here
 * rather than trusted, in both locales, because the demo is played in French.
 */
test('every key the model plane assembles at runtime has FR and EN copy', () => {
  const keys = [
    ...REFUSAL_CODES.map((code) => `models.refusal.${code.toLowerCase()}`),
    ...TRAINING_ERROR_CODES.map((code) => `models.error.${code.toLowerCase()}`),
    ...PLAN_WARNING_CODES.map((code) => `models.warning.${code.toLowerCase()}`),
    ...(['pending', 'training', 'ready', 'failed', 'cancelled'] as const).map(
      (status) => `models.status.${status}`,
    ),
    ...(['classification', 'regression'] as const).flatMap((task) => [
      `models.task.${task}`,
      `models.task.${task}.hint`,
    ]),
  ];
  const missing = keys.filter(
    (key) =>
      !MODELS_FR[key as keyof typeof MODELS_FR] ||
      !MODELS_EN[key as keyof typeof MODELS_EN],
  );
  assert.deepEqual(missing, []);
});

test('every metric the card can score has a label and a hint in both locales', () => {
  // The metric set is the harness's, and it is fixed: AUC and the four
  // classification scores, then the four regression ones.
  const metrics = [
    'roc_auc',
    'accuracy',
    'balanced_accuracy',
    'f1',
    'precision',
    'recall',
    'r2',
    'mae',
    'rmse',
    'mape',
  ];
  const missing = metrics.flatMap((metric) =>
    [`models.metric.${metric}`, `models.metric.${metric}.hint`].filter(
      (key) =>
        !MODELS_FR[key as keyof typeof MODELS_FR] ||
        !MODELS_EN[key as keyof typeof MODELS_EN],
    ),
  );
  assert.deepEqual(missing, []);
  // Every metric the tone table judges must also be one the card can name.
  for (const metric of metrics) {
    assert.ok(
      ['ratio', 'percent', 'value'].includes(metricScale(metric)),
      `${metric} has no scale`,
    );
  }
});

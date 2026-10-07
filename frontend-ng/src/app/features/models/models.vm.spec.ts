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
  GAUGE_ARC,
  GAUGE_HANDLE,
  GAUGE_RADIUS,
  MODEL_ACTIVE_STATUSES,
  PLAN_WARNING_CODES,
  REFUSAL_CODES,
  SERVING_ERROR_CODES,
  TRAINING_ERROR_CODES,
  TRAIN_STEPS,
  algoIcon,
  balanceBars,
  bestScore,
  clampKnob,
  comparisonRows,
  contributionBars,
  curlSnippet,
  defaultFeatures,
  defaultKnobs,
  planColumnStats,
  planColumnsAsTable,
  formatMetric,
  gaugeView,
  higherIsBetter,
  importanceBars,
  isActiveStatus,
  knobIsAuto,
  groupModelsBySlug,
  metricDelta,
  metricScale,
  metricTone,
  numericKnobs,
  setMetricRegistry,
  trainableTasks,
  pinnedVersion,
  playgroundSeed,
  predictPayload,
  comparisonPair,
  driftBars,
  aucTrace,
  monitorTone,
  previousVersion,
  primaryScore,
  refusalField,
  refusalKey,
  pipelineHops,
  provenanceLineParams,
  servingErrorKey,
  splitError,
  targetCandidates,
  taskIcon,
  parseTrainDetail,
  trainChecklist,
  trainStepKey,
  trainingErrorKey,
  warningKey,
  type ModelCatalog,
  type NumericKnobDescriptor,
  type ModelDto,
  type ModelStatus,
  type PlanColumn,
  type SignatureField,
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
  // Unknown means unranked: assuming “higher” would rank every error backwards.
  assert.equal(higherIsBetter('unknown_metric'), null);
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

test('the models list collapses versions into one row per slug', () => {
  const rows = groupModelsBySlug([
    {
      id: 'v3',
      name: 'Churn Radar',
      slug: 'churn-radar',
      version: 3,
      task: 'classification',
      algo: 'gradient_boosting',
      target: 'churn',
      features: [],
      status: 'ready',
      is_champion: true,
      created_at: '2026-09-20T10:00:00Z',
    } as ModelDto,
    {
      id: 'v4',
      name: 'Churn Radar',
      slug: 'churn-radar',
      version: 4,
      task: 'classification',
      algo: 'gradient_boosting',
      target: 'churn',
      features: [],
      status: 'ready',
      is_champion: false,
      created_at: '2026-09-22T10:00:00Z',
    } as ModelDto,
    {
      id: 'delay-v1',
      name: 'Delay',
      slug: 'delay',
      version: 1,
      task: 'regression',
      algo: 'linear',
      target: 'days',
      features: [],
      status: 'ready',
      is_champion: true,
      created_at: '2026-09-21T10:00:00Z',
    } as ModelDto,
  ]);
  assert.equal(rows.length, 2);
  const churn = rows.find((row) => row.slug === 'churn-radar');
  assert.ok(churn);
  assert.equal(churn!.served_version, 3);
  assert.equal(churn!.served_id, 'v3');
  assert.equal(churn!.version_count, 2);
  // Navigation prefers the champion when nothing is mid-fit.
  assert.equal(churn!.id, 'v3');
});

test('an active fit is the list row, while the served version stays a column', () => {
  const [row] = groupModelsBySlug([
    {
      id: 'v3',
      name: 'Churn',
      slug: 'churn',
      version: 3,
      task: 'classification',
      algo: 'linear',
      target: 'y',
      features: [],
      status: 'ready',
      is_champion: true,
    } as ModelDto,
    {
      id: 'v4',
      name: 'Churn',
      slug: 'churn',
      version: 4,
      task: 'classification',
      algo: 'linear',
      target: 'y',
      features: [],
      status: 'training',
      is_champion: false,
    } as ModelDto,
  ]);
  assert.equal(row.served_version, 3);
  assert.equal(row.id, 'v4');
  assert.equal(row.row.status, 'training');
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

const ITERS: NumericKnobDescriptor = {
  key: 'max_iter',
  kind: 'int',
  default: 200,
  min: 20,
  max: 600,
  step: 10,
};

const DEPTH: NumericKnobDescriptor = {
  key: 'max_depth',
  kind: 'int',
  default: 0,
  min: 0,
  max: 40,
  step: 1,
  auto_at: 0,
};

const RATE: NumericKnobDescriptor = {
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

test('plan columns project into the shared table without losing the profile', () => {
  const withProfile = [
    {
      ...COLUMNS[0],
      profile: { kind: 'integer' as const, distinct: 2, histogram: [{ upper: 1, count: 4 }] },
    },
  ];
  assert.deepEqual(planColumnsAsTable(withProfile), [
    { name: 'customer_id', kind: 'string', dtype: 'string' },
  ]);
  assert.equal(planColumnStats(withProfile)['customer_id']?.distinct, 2);
  assert.equal(planColumnStats(COLUMNS)['churned']?.distinct, 2);
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
  // A forecast's problem definition is one block; a shape the algorithm
  // cannot fit is still the algorithm's to answer for.
  assert.equal(refusalField('ML_TS_HISTORY_TOO_SHORT'), 'spec');
  assert.equal(refusalField('ML_SPEC_INVALID'), 'spec');
  assert.equal(refusalField('ML_TS_ALGO_SHAPE_MISMATCH'), 'algo');
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
// The serving plane
// ---------------------------------------------------------------------------

const CONTRACT: SignatureField[] = [
  { name: 'tenure_months', type: 'double', kind: 'number', min: 1, max: 72, default: 24 },
  {
    name: 'contract',
    type: 'string',
    kind: 'category',
    choices: ['month_to_month', 'one_year'],
    default: 'one_year',
  },
];

test('the form opens on the example the fit carried, not on the contract default', () => {
  assert.deepEqual(
    playgroundSeed(CONTRACT, [{ tenure_months: 3, contract: 'month_to_month' }]),
    { tenure_months: '3', contract: 'month_to_month' },
  );
});

test('with no example the form still opens filled, from the typical row', () => {
  assert.deepEqual(playgroundSeed(CONTRACT, undefined), {
    tenure_months: '24',
    contract: 'one_year',
  });
});

test('a field with neither example nor default opens empty rather than as "undefined"', () => {
  const fields: SignatureField[] = [{ name: 'plan', type: 'string', kind: 'category' }];
  assert.deepEqual(playgroundSeed(fields, [{}]), { plan: '' });
});

test('a numeric box is sent as a number and a cleared box as a hole', () => {
  assert.deepEqual(
    predictPayload(CONTRACT, { tenure_months: '18', contract: 'month_to_month' }),
    { tenure_months: 18, contract: 'month_to_month' },
  );
  // A hole is a production value the pipeline was fitted to take; an empty
  // string in a numeric column is a type error the endpoint would refuse.
  assert.deepEqual(predictPayload(CONTRACT, { tenure_months: '  ', contract: '' }), {
    tenure_months: null,
    contract: null,
  });
});

test('a numeric field holding text is sent as it was typed, so the refusal names it', () => {
  assert.deepEqual(
    predictPayload(CONTRACT, { tenure_months: 'twelve', contract: 'one_year' }),
    { tenure_months: 'twelve', contract: 'one_year' },
  );
});

test('the gauge is about the positive class, named, not a bare number', () => {
  const dial = gaugeView(
    {
      prediction: 'yes',
      probabilities: [
        { label: 'no', value: 0.13 },
        { label: 'yes', value: 0.87 },
      ],
    },
    'yes',
    'en',
  );
  assert.equal(dial?.label, 'yes');
  assert.equal(dial?.percent, '87%');
  assert.equal(dial?.predicted, 'yes');
  assert.ok(dial?.flagged);
  assert.equal(dial?.dash, Math.round(0.87 * GAUGE_ARC * 100) / 100);
});

test('the dial is measured against the circle a browser actually draws', () => {
  // `A56,56` between endpoints 116 apart describes no circle at all, so SVG
  // scales the radii until it does — to 58. A dial measured with 56 stops two
  // degrees short of its own end at 100%, and any marker placed from the same
  // figure lands somewhere the stroke is not.
  assert.equal(GAUGE_RADIUS, 58);
  assert.equal(GAUGE_ARC, Math.PI * 58);
});

test('the handle rides the tip of the stroke it terminates', () => {
  for (const value of [0, 0.13, 0.5, 0.87, 1]) {
    const dial = gaugeView(
      { prediction: 'yes', probabilities: [{ label: 'yes', value }] },
      'yes',
      'en',
    );
    // The handle's dash sits one whole period back from the tip, which is the
    // same arithmetic read from the other end: subtracting recovers the stroke
    // length, so the dot cannot land where the stroke does not end.
    const at = GAUGE_ARC + GAUGE_HANDLE - dial!.handle;
    assert.ok(
      Math.abs(at - dial!.dash) < 0.02,
      `${value}: handle at ${at}, stroke ends at ${dial!.dash}`,
    );
    // Offsets stay positive: negative dash offsets are an SVG 2 addition, and
    // an SVG 1.1 renderer treats them as an error rather than as a shift.
    assert.ok(dial!.handle > 0, `${value}: offset ${dial!.handle} is not positive`);
  }
});

test('a full dial parks its handle a dot short of the pattern, not off the end', () => {
  const full = gaugeView(
    { prediction: 'yes', probabilities: [{ label: 'yes', value: 1 }] },
    'yes',
    'en',
  );
  assert.equal(full?.dash, Math.round(GAUGE_ARC * 100) / 100);
  assert.equal(full?.handle, Math.round(GAUGE_HANDLE * 100) / 100);
});

test('landing outside the positive class reads as a probability of it, not of the answer', () => {
  const dial = gaugeView(
    {
      prediction: 'no',
      probabilities: [
        { label: 'no', value: 0.78 },
        { label: 'yes', value: 0.22 },
      ],
    },
    'yes',
    'en',
  );
  assert.equal(dial?.percent, '22%');
  assert.equal(dial?.label, 'yes');
  assert.equal(dial?.predicted, 'no');
  assert.ok(!dial?.flagged);
});

test('with no positive class the gauge falls back to how sure the model is', () => {
  const dial = gaugeView(
    { prediction: 'fibre', confidence: 0.61, probabilities: [] },
    null,
    'en',
  );
  assert.equal(dial?.label, 'fibre');
  assert.equal(dial?.percent, '61%');
  assert.ok(!dial?.flagged);
});

test('a row with nothing to show on the dial draws no dial at all', () => {
  assert.equal(gaugeView(null, 'yes'), null);
  assert.equal(gaugeView({ prediction: 'yes' }, 'yes'), null);
  assert.equal(gaugeView({ prediction: 'yes', confidence: Number.NaN }, 'yes'), null);
});

test('contributions are normalized against the strongest effect on this row', () => {
  const bars = contributionBars([
    { field: 'contract', value: 'month_to_month', typical: 'one_year', effect: 0.24 },
    { field: 'tenure_months', value: 2, typical: 24.5, effect: -0.12 },
  ]);
  assert.deepEqual(
    bars.map((bar) => [bar.field, bar.width, bar.raises]),
    [
      ['contract', 100, true],
      ['tenure_months', 50, false],
    ],
  );
  // Values are rendered, so a float does not print fifteen decimals and a hole
  // does not print "undefined".
  assert.equal(bars[1]?.typical, '24.5');
  assert.deepEqual(contributionBars(undefined), []);
  assert.deepEqual(contributionBars([{ field: 'x', value: 1, typical: 1, effect: NaN }]), []);
});

test('the snippet is the request that was just made, key masked to its prefix', () => {
  const snippet = curlSnippet({
    origin: 'https://agentium.papai.ai',
    endpoint: '/api/v1/ml-models/m1/predict',
    header: 'X-API-Key',
    row: { tenure_months: 2 },
    prefix: 'agk_9f3c',
  });
  assert.match(snippet, /curl -X POST https:\/\/agentium\.papai\.ai\/api\/v1\/ml-models\/m1\/predict/);
  assert.match(snippet, /-H 'X-API-Key: agk_9f3c…'/);
  assert.match(snippet, /-d '\{"inputs":\[\{"tenure_months":2\}\]\}'/);
});

test('a card that is not the one serving names its own version, so its form is judged against its own signature', () => {
  // The bug this rules out: two versions of a lineage need not share a column
  // list, so a card's form sent to whatever serves gets refused on the contract.
  assert.equal(pinnedVersion({ is_serving: false }, 3), 3);
  // The serving version's card leaves the call open, which is where the alias
  // answering for the lineage is the thing being demonstrated.
  assert.equal(pinnedVersion({ is_serving: true }, 3), null);
  // A version the API would reject anyway is not worth sending: `version` is
  // `ge=1` there, and a card mid-load has no number yet.
  assert.equal(pinnedVersion({ is_serving: false }, 0), null);
  assert.equal(pinnedVersion({ is_serving: false }, undefined), null);
  assert.equal(pinnedVersion({ is_serving: false }, '2'), 2);
});

test('the snippet carries the same pin the button used, so a copy reproduces the answer', () => {
  const pinned = curlSnippet({
    origin: '',
    endpoint: '/predict',
    header: 'X-API-Key',
    row: { tenure_months: 2 },
    version: 3,
  });
  assert.match(pinned, /-d '\{"inputs":\[\{"tenure_months":2\}\],"version":3\}'/);
  // Unpinned it stays the shape `mlflow models serve` takes, which is the point
  // of the snippet on the card the audience is shown.
  const open = curlSnippet({
    origin: '',
    endpoint: '/predict',
    header: 'X-API-Key',
    row: { tenure_months: 2 },
    version: null,
  });
  assert.match(open, /-d '\{"inputs":\[\{"tenure_months":2\}\]\}'/);
});

test('the one response that carried a secret puts it in the snippet verbatim', () => {
  const snippet = curlSnippet({
    origin: '',
    endpoint: '/predict',
    header: 'X-API-Key',
    row: {},
    secret: 'agk_live_secret',
    prefix: 'agk_live',
  });
  assert.match(snippet, /X-API-Key: agk_live_secret/);
});

test('with no key at all the snippet says where one goes rather than looking done', () => {
  const snippet = curlSnippet({
    origin: '',
    endpoint: '/predict',
    header: 'X-API-Key',
    row: {},
  });
  assert.match(snippet, /X-API-Key: YOUR_API_KEY/);
});

test('a provenance line names the serving version and quotes its score', () => {
  const params = provenanceLineParams(
    { name: 'Churn risk', version: 3, metric: { key: 'roc_auc', value: 0.8712 } },
    (key) => (key === 'roc_auc' ? 'AUC' : key),
    'en',
  );
  assert.deepEqual(params, {
    name: 'Churn risk',
    version: 3,
    evidence: 'AUC 87.1%',
  });
});

test('a provenance with no readable score still says which version answers', () => {
  // A number nobody can interpret is worse than no number, but "which version
  // answers" is never the part worth dropping.
  const params = provenanceLineParams(
    { name: 'Cell load', version: 2, metric: null },
    (key) => key,
    'en',
  );
  assert.deepEqual(params, { name: 'Cell load', version: 2, evidence: '' });
  const broken = provenanceLineParams(
    { name: 'Cell load', version: 2, metric: { key: 'r2', value: Number.NaN } },
    (key) => key,
    'en',
  );
  assert.equal(broken?.evidence, '');
});

test('the pipeline banner walks dataset, transform, this version and scored tables', () => {
  const hops = pipelineHops(
    {
      dataset: { id: 'ds', name: 'Churn raw', version: 1, kind: 'dataset' },
      transform: {
        id: 'tf',
        name: 'Churn features',
        version: 1,
        kind: 'transform',
        engine: 'sql',
      },
      model: { id: 'md', name: 'Churn Radar', version: 2, kind: 'model' },
      scored: [{ id: 'sc', name: 'Churn scored', version: 1, kind: 'scored' }],
    },
    (chip) => `${chip.kind}:${chip.name}`,
  );
  assert.deepEqual(
    hops.map((hop) => hop.kind),
    ['dataset', 'transform', 'model', 'scored'],
  );
  assert.deepEqual(hops[0].link, { leaf: 'data-doc', ref: 'ds' });
  assert.deepEqual(hops[2].link, { leaf: 'model-doc', ref: 'md' });
  assert.equal(hops[2].current, true);
  assert.deepEqual(hops[3].link, { leaf: 'data-doc', ref: 'sc' });
});

test('a card with only this version is not a pipeline', () => {
  assert.deepEqual(
    pipelineHops(
      {
        dataset: null,
        transform: null,
        model: { id: 'md', name: 'Lonely', version: 1, kind: 'model' },
        scored: [],
      },
      (chip) => chip.name,
    ),
    [],
  );
  assert.deepEqual(pipelineHops(null, (chip) => chip.name), []);
});

test('a skill that answers from no model claims no provenance', () => {
  assert.equal(provenanceLineParams(null, (key) => key), null);
  assert.equal(provenanceLineParams(undefined, (key) => key), null);
  // A version the transport left at 0 or below still reads as v1 rather than as
  // a version that cannot exist.
  assert.equal(
    provenanceLineParams({ name: 'Churn', version: 0 }, (key) => key)?.version,
    1,
  );
});

test('drift bars rank PSI the same way importances rank a feature', () => {
  const bars = driftBars([
    { name: 'arpu', kind: 'number', value: 0.3, status: 'alert' },
    { name: 'plan', kind: 'category', value: 0.05, status: 'ok' },
  ]);
  assert.equal(bars[0].label, 'arpu');
  assert.equal(bars[0].negative, true);
  assert.ok(bars[0].width > bars[1].width);
});

test('the AUC trace is two points so the curve kit can draw the drop', () => {
  assert.deepEqual(aucTrace(0.84, 0.61), [
    { x: 0, y: 0.84 },
    { x: 1, y: 0.61 },
  ]);
  assert.deepEqual(aucTrace(null, null), []);
  assert.equal(monitorTone('alert'), 'neg');
  assert.equal(monitorTone('watch'), 'warn');
  assert.equal(monitorTone(null), 'neutral');
});

test('every coded serving refusal has a sentence of its own', () => {
  for (const code of SERVING_ERROR_CODES) {
    assert.equal(servingErrorKey(code), `models.serving.error.${code.toLowerCase()}`);
  }
  assert.equal(servingErrorKey('ML_SOMETHING_ELSE'), null);
  assert.equal(servingErrorKey(null), null);
});

// ---------------------------------------------------------------------------
// Comparison across versions
// ---------------------------------------------------------------------------

function version(
  id: string,
  number: number,
  scores: { key: string; value: number }[],
  status: ModelStatus = 'ready',
): ModelDto {
  return {
    id,
    version: number,
    status,
    primary_metric: scores[0] ?? null,
    metrics: { scores },
  } as unknown as ModelDto;
}

test('a delta is judged by the metric, so a smaller error is an improvement', () => {
  const auc = metricDelta('roc_auc', 0.87, 0.84, 'en');
  assert.equal(auc?.display, '+0.03');
  assert.ok(auc?.better);
  assert.ok(!auc?.flat);

  const mae = metricDelta('mae', 3.1, 4.4, 'en');
  assert.equal(mae?.display, '−1.3');
  assert.ok(mae?.better, 'a smaller MAE is a better model');
});

test('a move too small to mean anything is rendered flat, not as a win', () => {
  const delta = metricDelta('roc_auc', 0.8701, 0.87, 'en');
  assert.equal(delta?.display, '=');
  assert.ok(delta?.flat);
});

test('with nothing to compare against there is no delta rather than a fake zero', () => {
  assert.equal(metricDelta('roc_auc', 0.87, null), null);
  assert.equal(metricDelta('roc_auc', 0.87, undefined), null);
  assert.equal(metricDelta('roc_auc', null, 0.84), null);
});

test('a delta is measured against the newest trained version below this one', () => {
  const current = version('v3', 3, [{ key: 'roc_auc', value: 0.87 }]);
  const earlier = previousVersion(current, [
    current,
    version('v2b', 2, [], 'failed'),
    version('v2', 2, [{ key: 'roc_auc', value: 0.84 }]),
    version('v1', 1, [{ key: 'roc_auc', value: 0.79 }]),
  ]);
  assert.equal(earlier?.id, 'v2');
});

test('a lineage of one has nothing to measure against', () => {
  const only = version('v1', 1, [{ key: 'roc_auc', value: 0.8 }]);
  assert.equal(previousVersion(only, [only]), null);
  assert.equal(previousVersion(null, []), null);
});

test('a failed retrain never becomes the version a delta is read against', () => {
  const current = version('v3', 3, [{ key: 'roc_auc', value: 0.87 }]);
  const earlier = previousVersion(current, [
    current,
    version('v2', 2, [{ key: 'roc_auc', value: 0.9 }], 'failed'),
    version('v1', 1, [{ key: 'roc_auc', value: 0.79 }]),
  ]);
  assert.equal(earlier?.id, 'v1');
});

test('the version that serves compares against its contender, not against nothing', () => {
  const champion = version('v1', 1, [{ key: 'roc_auc', value: 0.835 }]);
  const pair = comparisonPair(champion, [
    champion,
    version('v2', 2, [{ key: 'roc_auc', value: 0.86 }]),
    version('v3', 3, [{ key: 'roc_auc', value: 0.856 }]),
  ]);

  // The nearest one above, and still in version order: the table's left column
  // is "before" whichever card the reader arrived from.
  assert.equal(pair?.before.id, 'v1');
  assert.equal(pair?.after.id, 'v2');
});

test('a version with one below it still compares backwards', () => {
  const current = version('v3', 3, [{ key: 'roc_auc', value: 0.856 }]);
  const pair = comparisonPair(current, [
    version('v1', 1, [{ key: 'roc_auc', value: 0.835 }]),
    version('v2', 2, [{ key: 'roc_auc', value: 0.86 }]),
    current,
  ]);

  assert.equal(pair?.before.id, 'v2');
  assert.equal(pair?.after.id, 'v3');
});

test('a lineage of one, and a failed sibling, have nothing worth a table', () => {
  const only = version('v1', 1, [{ key: 'roc_auc', value: 0.8 }]);
  assert.equal(comparisonPair(only, [only]), null);
  assert.equal(comparisonPair(only, [only, version('v2', 2, [], 'failed')]), null);
  assert.equal(comparisonPair(null, []), null);
});

test('comparison aligns two versions and marks the side each metric favours', () => {
  const rows = comparisonRows(
    version('v2', 2, [
      { key: 'roc_auc', value: 0.84 },
      { key: 'recall', value: 0.7 },
    ]),
    version('v3', 3, [
      { key: 'roc_auc', value: 0.87 },
      { key: 'recall', value: 0.62 },
    ]),
    'en',
  );
  assert.deepEqual(
    rows.map((row) => [row.key, row.winner, row.delta?.display]),
    [
      ['roc_auc', 'right', '+0.03'],
      ['recall', 'left', '−0.08'],
    ],
  );
});

test('a metric only one side produced is left out rather than shown as a drop to zero', () => {
  const rows = comparisonRows(
    version('v1', 1, [{ key: 'r2', value: 0.6 }]),
    version('v2', 2, [{ key: 'roc_auc', value: 0.9 }]),
    'en',
  );
  assert.deepEqual(rows, []);
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
    ...SERVING_ERROR_CODES.map((code) => `models.serving.error.${code.toLowerCase()}`),
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

// ---------------------------------------------------------------------------
// The live check-list of a fit
// ---------------------------------------------------------------------------

test('a step brings the count that says how much of the wait is left', () => {
  assert.deepEqual(parseTrainDetail('fitting:6903'), {
    step: 'fitting',
    rows: 6903,
    fold: null,
    folds: null,
  });
  assert.deepEqual(parseTrainDetail('validating:3/5'), {
    step: 'validating',
    rows: null,
    fold: 3,
    folds: 5,
  });
  // A bare step is still a step.
  assert.deepEqual(parseTrainDetail('scoring').step, 'scoring');
  // A sentence from an older worker is not a step: rendering it would put
  // English on the French page, which is what the codes exist to prevent.
  assert.equal(parseTrainDetail('Fitting HistGradientBoostingClassifier').step, 'queued');
  assert.equal(trainStepKey('fitting:6903'), 'models.progress.step.fitting');
  assert.equal(trainStepKey(null), 'models.progress.step.queued');
  // A tail that is not a count is dropped rather than shown.
  for (const bad of ['fitting:', 'fitting:x', 'validating:3/0', 'validating:3/x']) {
    const parsed = parseTrainDetail(bad);
    assert.equal(parsed.rows, null, bad);
    assert.equal(parsed.fold, null, bad);
  }
});

test('the check-list follows the step the row claims, and invents none', () => {
  const states = (status: string | null, step: string | null) =>
    trainChecklist(status, step, 0).map((line) => line.state);

  // Five lines without folds: queued, reading, fitting, scoring, saving.
  assert.deepEqual(states('pending', 'queued'), [
    'active',
    'todo',
    'todo',
    'todo',
    'todo',
  ]);
  assert.deepEqual(states('training', 'fitting'), [
    'done',
    'done',
    'active',
    'todo',
    'todo',
  ]);
  // Training but silent: the run is past the queue, and no progress it did not
  // claim is invented.
  assert.deepEqual(states('training', null), ['done', 'active', 'todo', 'todo', 'todo']);
  assert.deepEqual(states('training', 'Fitting HistGradientBoosting'), [
    'active',
    'todo',
    'todo',
    'todo',
    'todo',
  ]);
  // Terminal ticks everything, failure included: the list says how far the run
  // got, and the refusal beside it says what stopped it.
  for (const status of ['ready', 'failed', 'cancelled']) {
    assert.deepEqual(states(status, 'fitting'), Array(5).fill('done'));
  }
});

test('a line that will never tick is not drawn', () => {
  // `validating` only happens when folds were asked for. Showing it on a run
  // that asked for none would read as a step that is stuck for good.
  assert.deepEqual(
    trainChecklist('training', 'scoring', 0).map((line) => line.step),
    ['queued', 'reading', 'fitting', 'scoring', 'saving'],
  );
  assert.deepEqual(
    trainChecklist('training', 'scoring', 5).map((line) => line.step),
    TRAIN_STEPS,
  );
  // One fold is not cross-validation, and neither is nonsense.
  for (const folds of [1, 0, null, undefined, Number.NaN]) {
    assert.ok(
      !trainChecklist('training', 'scoring', folds as number).some(
        (line) => line.step === 'validating',
      ),
      String(folds),
    );
  }
});

test('the fold counter is live while the folds run, and never after', () => {
  const validating = (status: string, detail: string) =>
    trainChecklist(status, detail, 5).find((line) => line.step === 'validating')!;

  const running = validating('training', 'validating:3/5');
  assert.equal(running.key, 'models.progress.step.validating.counted');
  assert.deepEqual(running.params, { fold: 3, folds: 5 });
  assert.equal(running.state, 'active');

  // Before the folds start, the line says how many are coming but claims no
  // progress through them.
  const waiting = validating('training', 'fitting:6903');
  assert.equal(waiting.key, 'models.progress.step.validating');
  assert.deepEqual(waiting.params, { folds: 5 });

  // And once the run has settled, a frozen "3/5" would still read as a live
  // number, so it is dropped.
  const settled = validating('ready', 'validating:3/5');
  assert.equal(settled.key, 'models.progress.step.validating');
  assert.equal(settled.state, 'done');
});

test('the row count belongs to the fit, and to no other line', () => {
  const lines = trainChecklist('training', 'fitting:6903', 5, 'en');
  const fitting = lines.find((line) => line.step === 'fitting')!;
  assert.equal(fitting.key, 'models.progress.step.fitting.counted');
  // Localised where it is read, not where it is produced: the worker writes
  // 6903 and the page decides whether that is "6,903" or "6 903".
  assert.equal(fitting.params['rows'], '6,903');
  assert.equal(
    trainChecklist('training', 'fitting:6903', 5, 'fr').find(
      (line) => line.step === 'fitting',
    )!.params['rows'],
    (6903).toLocaleString('fr'),
  );
  // The learning rows are not what the scoring line counts, so they stay put.
  for (const line of lines) {
    if (line.step !== 'fitting') assert.equal(line.params['rows'], undefined, line.step);
  }
});

test('every sentence the check-list can render exists in both languages', () => {
  const keys = new Set<string>();
  for (const folds of [0, 5]) {
    for (const status of ['pending', 'training', 'ready', 'failed']) {
      for (const detail of [null, 'fitting:6903', 'validating:2/5', 'saving']) {
        for (const line of trainChecklist(status, detail, folds)) keys.add(line.key);
      }
    }
  }
  assert.ok(keys.size >= 7, 'the scan covered the list, not one line of it');
  for (const key of keys) {
    assert.ok(MODELS_FR[key as keyof typeof MODELS_FR], `${key} has FR copy`);
    assert.ok(MODELS_EN[key as keyof typeof MODELS_EN], `${key} has EN copy`);
  }
  // The settling toast, which is the other half of "no silent wait".
  for (const key of [
    'models.progress.settled',
    'models.progress.settled.plain',
    'models.progress.failed',
  ]) {
    assert.ok(MODELS_FR[key as keyof typeof MODELS_FR], `${key} has FR copy`);
    assert.ok(MODELS_EN[key as keyof typeof MODELS_EN], `${key} has EN copy`);
  }
});

test('the catalog’s metric registry ranks what the offline copy does not know', () => {
  // Before the catalog arrives, an unknown metric has no direction: no tone,
  // no delta arrow, never "higher is better" by default.
  assert.equal(higherIsBetter('mase'), null);
  assert.equal(metricDelta('mase', 0.7, 0.9), null);
  assert.equal(metricTone('mase', 0.7), 'neutral');

  setMetricRegistry([
    { key: 'roc_auc', direction: 'max', scale: 'ratio', good: 0.8, poor: 0.65 },
    { key: 'mase', direction: 'min', scale: 'value', good: 0.8, poor: 1.0 },
    { key: 'coverage', direction: 'none', scale: 'ratio' },
  ]);
  assert.equal(higherIsBetter('mase'), false);
  assert.equal(metricDelta('mase', 0.7, 0.9)?.better, true, 'a lower MASE is an improvement');
  assert.equal(metricTone('mase', 0.7), 'pos');
  assert.equal(metricTone('mase', 1.3), 'neg');
  assert.equal(metricScale('coverage'), 'ratio');
  // Coverage is judged against its nominal level, so it never wins or loses.
  assert.equal(higherIsBetter('coverage'), null);
  assert.equal(metricDelta('coverage', 0.9, 0.8), null);
  assert.equal(metricTone('coverage', 0.9), 'neutral');
  assert.equal(metricTone('roc_auc', 0.91), 'pos');
  // An empty registry (a catalog from before families) leaves the copy in place.
  setMetricRegistry([]);
  assert.equal(higherIsBetter('mase'), false);
});

const EMPTY_CATALOG_FOR_TASKS: ModelCatalog = {
  enabled: true,
  tasks: [],
  algos: [],
  limits: { min_rows: 40, max_rows: 1000, max_features: 10, max_classes: 5, timeout_s: 60 },
  defaults: { task: 'classification', algo: 'gb', test_size: 0.25, cross_validation: 0 },
};

test('a form offers the tasks of the families a worker can train now', () => {
  const base = { ...EMPTY_CATALOG_FOR_TASKS, tasks: ['classification', 'regression', 'forecasting'] };
  assert.deepEqual(trainableTasks(base), ['classification', 'regression', 'forecasting']);
  const withFamilies = {
    ...base,
    families: [
      { key: 'tabular', tasks: ['classification', 'regression'], runtime: 'worker', serving: 'in_process' as const, available: true, spec_fields: [] },
      { key: 'forecasting', tasks: ['forecasting'], runtime: 'ml-ts', serving: 'remote' as const, available: false, reason: 'no_worker', spec_fields: [] },
    ],
  };
  assert.deepEqual(trainableTasks(withFamilies), ['classification', 'regression']);
  assert.deepEqual(trainableTasks(null), []);
});

test('a family that needs a problem definition waits for a form that renders it', () => {
  const horizon = { key: 'horizon', kind: 'int' as const, required: true };
  const catalog = {
    ...EMPTY_CATALOG_FOR_TASKS,
    tasks: ['classification', 'forecasting'],
    families: [
      { key: 'tabular', tasks: ['classification'], runtime: 'worker', serving: 'in_process' as const, available: true, spec_fields: [] },
      { key: 'forecasting', tasks: ['forecasting'], runtime: 'ml-ts', serving: 'remote' as const, available: true, spec_fields: [horizon] },
    ],
  };
  // A form without spec fields would send a forecast with no date column.
  assert.deepEqual(trainableTasks(catalog), ['classification']);
  assert.deepEqual(trainableTasks(catalog, { specFields: true }), ['classification', 'forecasting']);
});

test('only numeric knobs render as sliders; other kinds keep the server default', () => {
  const algo = {
    key: 'gb',
    tasks: ['classification'],
    estimators: {},
    scale: false,
    tags: [],
    knobs: [
      ITERS,
      { key: 'text_encoder', kind: 'enum' as const, default: 'lsa', choices: ['lsa', 'minhash'] },
      { key: 'calibrate', kind: 'bool' as const, default: false },
      { key: 'lags', kind: 'int_list' as const, default: [1, 24], min: 1, max: 168, step: 1, max_items: 4 },
    ],
  };
  assert.deepEqual(numericKnobs(algo).map((knob) => knob.key), [ITERS.key]);
  assert.deepEqual(Object.keys(defaultKnobs(algo)), [ITERS.key]);
});


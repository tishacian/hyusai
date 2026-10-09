/**
 * Forecasting in the studio and on the card: the spec a draft sends, and the
 * evidence a backtest is read as.
 */
import test from 'node:test';
import assert from 'node:assert/strict';

import {
  forecastChartSeries,
  forecastExtent,
  formatForecastStamp,
} from '@app/features/data/viz/forecast-chart.vm';

import {
  DEFAULT_FORECAST_DRAFT,
  draftFromSpec,
  forecastTuningIssue,
  tuningBounds,
  baselineGain,
  covariateCandidates,
  coverageTone,
  acfBars,
  anatomyFacts,
  answerPoints,
  diagnosticScore,
  seriesAnalysis,
  strengthLevel,
  contributionBars,
  excursionsOf,
  featureLabel,
  groupShareBars,
  lagBars,
  lagSpan,
  peakFeatureBars,
  forecastCurlSnippet,
  forecastPeak,
  forecastMaxSteps,
  forecastRequest,
  forecastSpec,
  forecastFieldsFor,
  forecastDraftForFields,
  frequencyKey,
  futureStamps,
  horizonBars,
  isForecast,
  parseLags,
  plottedSeries,
  recentActuals,
  roleChoices,
  seriesBars,
  seriesColumnCandidates,
  seriesEvidence,
  strategyApplies,
  timeColumns,
  type ForecastMetrics,
} from './forecast.vm';
import type { ModelCatalog, PlanColumn, SpecFieldDescriptor } from './models.vm';

const column = (name: string, kind: string): PlanColumn => ({
  name,
  kind,
  distinct: 10,
  nulls: 0,
  suggested_task: 'regression',
});

const CELLS: PlanColumn[] = [
  column('ts', 'datetime'),
  column('cell_id', 'string'),
  column('region', 'string'),
  column('prb', 'float'),
  column('users', 'integer'),
  column('maintenance', 'boolean'),
];

// ---------------------------------------------------------------------------
// The draft
// ---------------------------------------------------------------------------

test('lags are read as a sorted set of whole numbers, or refused as text', () => {
  assert.deepEqual(parseLags('24, 1 168;1'), [1, 24, 168]);
  assert.deepEqual(parseLags('  '), []);
  assert.equal(parseLags('1, soon'), null);
  assert.equal(parseLags('0, 1'), null);
  assert.equal(parseLags('1.5'), null);
});

test('a covariate role exists only in the shape that can use it', () => {
  assert.deepEqual(roleChoices('single'), ['future']);
  assert.deepEqual(roleChoices('panel'), ['future', 'static']);
  assert.deepEqual(roleChoices('multivariate'), ['future', 'past']);
});

test('a single series sends its strategy; a panel, its series and no strategy', () => {
  const single = forecastSpec({ ...DEFAULT_FORECAST_DRAFT, timeColumn: 'ts', strategy: 'direct' }, 'linear');
  assert.equal(single['time_column'], 'ts');
  assert.equal(single['strategy'], 'direct');
  assert.equal(single['series_columns'], undefined);
  assert.equal(single['lags'], undefined, 'empty lags are the frequency’s to choose');

  const panel = forecastSpec(
    { ...DEFAULT_FORECAST_DRAFT, timeColumn: 'ts', shape: 'panel', seriesColumns: ['cell_id'], lags: '1,24' },
    'gradient_boosting',
  );
  assert.deepEqual(panel['series_columns'], ['cell_id']);
  assert.equal(panel['strategy'], undefined);
  assert.deepEqual(panel['lags'], [1, 24]);
  // A statistical model has no strategy to choose.
  assert.equal(strategyApplies('single', 'ets'), false);
  assert.equal(forecastSpec({ ...DEFAULT_FORECAST_DRAFT, timeColumn: 'ts' }, 'ets')['strategy'], undefined);
});

test('switching shape drops the roles the new shape cannot use instead of sending them', () => {
  const draft = {
    ...DEFAULT_FORECAST_DRAFT,
    timeColumn: 'ts',
    exog: { region: 'static' as const, users: 'past' as const, maintenance: 'future' as const },
  };
  assert.deepEqual(forecastSpec(draft)['exog'], { maintenance: 'future' });
  assert.deepEqual(forecastSpec({ ...draft, shape: 'multivariate' })['exog'], { users: 'past', maintenance: 'future' });
  const panel = forecastSpec({ ...draft, shape: 'panel', seriesColumns: ['region'] });
  // A column that names the series is not also a covariate of it.
  assert.deepEqual(panel['exog'], { maintenance: 'future' });
});

test('the pickers offer dates to date, labels to group and numbers to explain', () => {
  assert.deepEqual(timeColumns(CELLS), ['ts']);
  // An integer can be a store id; a measurement or a flag cannot name a series.
  assert.deepEqual(seriesColumnCandidates(CELLS, 'prb', 'ts'), ['cell_id', 'region', 'users']);
  const single = covariateCandidates(CELLS, { shape: 'single', seriesColumns: [], timeColumn: 'ts' }, 'prb');
  assert.deepEqual(
    single.map((candidate) => candidate.name),
    ['users', 'maintenance'],
    'a text column is no covariate of a single series',
  );
  const panel = covariateCandidates(CELLS, { shape: 'panel', seriesColumns: ['cell_id'], timeColumn: 'ts' }, 'prb');
  assert.deepEqual(panel.find((candidate) => candidate.name === 'region')?.roles, ['static']);
  assert.deepEqual(panel.find((candidate) => candidate.name === 'users')?.roles, ['future', 'static']);
  assert.equal(panel.find((candidate) => candidate.name === 'cell_id'), undefined);
});

// ---------------------------------------------------------------------------
// The evidence
// ---------------------------------------------------------------------------

const METRICS: ForecastMetrics = {
  task: 'forecasting',
  primary: { key: 'mase', value: 0.5 },
  scores: [
    { key: 'mae', value: 3 },
    { key: 'mase', value: 0.5 },
    { key: 'coverage', value: 0.78 },
  ],
  forecast: { frequency: 'h', horizon: 2, interval_level: 0.8, folds: 2 },
  baseline: { key: 'seasonal_naive', mae: 4 },
  per_horizon: [
    { step: 1, mae: 2 },
    { step: 2, mae: 4 },
  ],
  per_series: [
    { series: 'A', mae: 2, mase: 0.4 },
    { series: 'B', mae: 5, mase: 0.9 },
  ],
  history_tail: [
    { t: '2026-08-01 00:00:00', series: 'A', value: 10 },
    { t: '2026-08-01 01:00:00', series: 'A', value: 11 },
    { t: '2026-08-01 00:00:00', series: 'B', value: 20 },
  ],
  backtest: [
    { t: '2026-08-01 02:00:00', series: 'A', fold: 0, step: 1, actual: 12, pred: 11, lower: null, upper: null },
    { t: '2026-08-01 03:00:00', series: 'A', fold: 1, step: 1, actual: 13, pred: 12, lower: 10, upper: 14 },
    { t: '2026-08-01 02:00:00', series: 'B', fold: 0, step: 1, actual: 21, pred: 22, lower: null, upper: null },
  ],
};

test('a forecast card reads the series it plotted and one series at a time', () => {
  assert.ok(isForecast(METRICS));
  assert.equal(isForecast({ task: 'regression' }), false);
  assert.deepEqual(plottedSeries(METRICS), ['A', 'B']);
  const evidence = seriesEvidence(METRICS, 'A');
  assert.equal(evidence.history.length, 2);
  assert.equal(evidence.backtest.length, 2);
  assert.equal(seriesEvidence(METRICS, undefined).backtest[0].t, '2026-08-01 02:00:00');
});

test('the gain over the seasonal naive is a share of its error, and absent without one', () => {
  assert.equal(baselineGain(METRICS), 0.25);
  assert.equal(baselineGain({ ...METRICS, baseline: { key: 'seasonal_naive', mae: null } }), null);
  assert.equal(baselineGain({ ...METRICS, scores: [] }), null);
});

test('an interval is judged by how close its coverage is to its level', () => {
  assert.equal(coverageTone(0.78, 0.8), 'pos');
  assert.equal(coverageTone(0.68, 0.8), 'warn');
  assert.equal(coverageTone(0.4, 0.8), 'neg');
  assert.equal(coverageTone(null, 0.8), 'neutral');
});

test('error bars run per step ahead and put the worst series first', () => {
  const steps = horizonBars(METRICS, String, (step) => `+${step}`);
  assert.deepEqual(steps.map((bar) => [bar.label, bar.width]), [['+1', 50], ['+2', 100]]);
  const series = seriesBars(METRICS, String);
  assert.deepEqual(series.map((bar) => bar.label), ['B', 'A']);
  assert.equal(series[0].display, 'MASE 0.9');
});

// ---------------------------------------------------------------------------
// The chart's axis
// ---------------------------------------------------------------------------

test('context and backtest share one sorted axis, with gaps rather than zeros', () => {
  const { history, backtest } = seriesEvidence(METRICS, 'A');
  const series = forecastChartSeries(history, backtest);
  assert.deepEqual(series.labels, [
    '2026-08-01 00:00:00',
    '2026-08-01 01:00:00',
    '2026-08-01 02:00:00',
    '2026-08-01 03:00:00',
  ]);
  assert.deepEqual(series.actual, [10, 11, 12, 13]);
  assert.deepEqual(series.pred, [null, null, 11, 12]);
  assert.deepEqual(series.upper, [null, null, null, 14]);
  assert.equal(series.start, 2);
  assert.deepEqual(series.folds, [null, null, 0, 1]);
  const extent = forecastExtent(series)!;
  assert.ok(extent.min < 10 && extent.max > 14);
  assert.equal(forecastExtent(forecastChartSeries([], [])), null);
});

test('a timestamp is labelled in the unit of the series frequency', () => {
  const hourly = formatForecastStamp('2026-08-24 13:00:00', 'h', 'fr-FR');
  assert.match(hourly, /24\/08/);
  assert.match(hourly, /13/);
  const monthly = formatForecastStamp('2026-08-01 00:00:00', 'MS', 'en-GB');
  assert.match(monthly, /Aug/);
  assert.equal(formatForecastStamp('not a date', 'h', 'fr-FR'), 'not a date');
});

test('a fitted frequency is named the way the form offered it', () => {
  assert.equal(frequencyKey('h'), 'h');
  assert.equal(frequencyKey('W-SUN'), 'W');
  assert.equal(frequencyKey('QS-OCT'), 'QS');
  assert.equal(frequencyKey('MS'), 'MS');
  assert.equal(frequencyKey('2h'), null);
  assert.equal(frequencyKey(undefined), null);
});

// ---------------------------------------------------------------------------
// Forecasts on demand
// ---------------------------------------------------------------------------

test('the future is dated on the model’s own step, or not at all', () => {
  assert.deepEqual(futureStamps('2026-08-23 23:00:00', 'h', 2), ['2026-08-24 00:00:00', '2026-08-24 01:00:00']);
  assert.deepEqual(futureStamps('2026-01-31 00:00:00', 'MS', 1), ['2026-02-01 00:00:00']);
  assert.deepEqual(futureStamps('2026-08-23 00:00:00', 'W-SUN', 1), ['2026-08-30 00:00:00']);
  assert.equal(futureStamps('2026-08-23 00:00:00', '2h', 3), null);
  assert.equal(futureStamps(null, 'h', 3), null);
});

test('a forecast call carries a row per step only when a covariate needs one', () => {
  const plain = forecastRequest({ horizon: 24, level: 0.8, series: null, covariates: {} });
  assert.deepEqual(plain, { params: { horizon: 24, interval_level: 0.8 }, inputs: [] });
  const one = forecastRequest({ horizon: 6, level: 0.9, series: 'CAS-400-L04', covariates: {} });
  assert.deepEqual(one.inputs, [{ series: 'CAS-400-L04' }]);
  const planned = forecastRequest({
    horizon: 2,
    level: 0.8,
    series: 'A',
    covariates: { maintenance: 1 },
    stamps: ['2026-08-24 00:00:00', '2026-08-24 01:00:00'],
  });
  assert.deepEqual(planned.inputs[1], { series: 'A', timestamp: '2026-08-24 01:00:00', maintenance: 1 });
  const curl = forecastCurlSnippet({
    origin: 'https://x',
    endpoint: '/api/v1/ml-models/m/forecast',
    header: 'X-Agentium-Model-Key',
    body: planned,
    prefix: 'agm_ab',
  });
  assert.match(curl, /forecast/);
  assert.match(curl, /agm_ab…/);
  assert.match(curl, /"interval_level":0.8/);
});

test('an answer is drawn after its context and read at its peak', () => {
  const answer = {
    served: { model_id: 'm', version: 1 },
    horizon: 2,
    interval_level: 0.8,
    series: ['A', 'B'],
    rows: 4,
    duration_ms: 12,
    forecast: [
      { series: 'A', timestamp: 't1', pred: 40, lower_bound: 35, upper_bound: 45 },
      { series: 'A', timestamp: 't2', pred: 52, lower_bound: 44, upper_bound: 60 },
      { series: 'B', timestamp: 't1', pred: 90, lower_bound: 80, upper_bound: 99 },
    ],
  };
  const points = answerPoints(answer, 'A');
  assert.equal(points.length, 2);
  assert.equal(points[0].actual, null);
  assert.deepEqual(forecastPeak(points), { t: 't2', pred: 52, upper: 60 });
  assert.equal(forecastPeak([]), null);
});

test('an on-demand forecast leaves from the latest actuals, not from the backtest’s start', () => {
  const recent = recentActuals(METRICS, 'A');
  assert.deepEqual(recent.map((point) => point.value), [10, 11, 12, 13]);
  assert.deepEqual(recentActuals(METRICS, 'A', 2).map((point) => point.t), ['2026-08-01 02:00:00', '2026-08-01 03:00:00']);
});

// ---------------------------------------------------------------------------
// Explanations
// ---------------------------------------------------------------------------

const t = (key: string, params?: Record<string, string | number>) =>
  params ? `${key}(${Object.values(params).join(',')})` : key;

test('a lag is read in the unit its frequency is thought in', () => {
  assert.deepEqual(lagSpan(168, 'h'), { unit: 'days', n: 7 });
  assert.deepEqual(lagSpan(3, 'h'), { unit: 'hours', n: 3 });
  assert.deepEqual(lagSpan(28, 'D'), { unit: 'weeks', n: 4 });
  assert.deepEqual(lagSpan(12, 'MS'), { unit: 'years', n: 1 });
  assert.deepEqual(lagSpan(5, null), { unit: 'steps', n: 5 });
});

test('features are named for a reader, not for the matrix', () => {
  assert.equal(featureLabel('lag_168', 'lags', 'h', t), 't−168 (models.explain.span.days(7))');
  assert.equal(featureLabel('active_users_lag_1', 'past', 'h', t), 'active_users · t−1 (models.explain.span.hours(1))');
  assert.equal(featureLabel('hour_sin', 'calendar', 'h', t), 'models.explain.calendar.hour');
  assert.equal(featureLabel('day_of_week_cos_step_3', 'calendar', 'h', t), 'models.explain.calendar.day_of_week');
  assert.equal(featureLabel('_level_skforecast', 'series', 'h', t), 'models.explain.feature.series');
  assert.equal(featureLabel('maintenance', 'future', 'h', t), 'maintenance');
});

test('a fit reads as families, strongest first, and as the past it repeats', () => {
  const explanation = {
    method: 'shap' as const,
    groups: [
      { group: 'lags' as const, share: 0.88 },
      { group: 'calendar' as const, share: 0.09 },
      { group: 'static' as const, share: 0 },
    ],
    lags: [
      { lag: 1, value: 1 },
      { lag: 24, value: 5 },
      { lag: 168, value: 8 },
    ],
  };
  const groups = groupShareBars(explanation, t, (share) => `${Math.round(share * 100)}%`);
  assert.deepEqual(groups.map((bar) => bar.label), ['models.explain.group.lags', 'models.explain.group.calendar']);
  // A reading, not an alert: no warn-toned emphasis on the dominant family.
  assert.ok(groups.every((bar) => !bar.emphasis));
  const lags = lagBars(explanation, 'h', t, String);
  assert.deepEqual(lags.map((bar) => bar.width), [13, 63, 100]);
});

test('the peak reads as signed contributions on top of the base', () => {
  const step = { step: 3, timestamp: 't', pred: 52, base: 40, groups: { lags: 14, calendar: -2 } };
  const bars = contributionBars(step, t, String);
  assert.deepEqual(bars.map((bar) => [bar.label, bar.display, bar.negative]), [
    ['models.explain.group.lags', '+14', false],
    ['models.explain.group.calendar', '−2', true],
  ]);
  const features = peakFeatureBars(
    {
      series: 'A',
      method: 'shap',
      steps: [step],
      peak: { ...step, features: [{ feature: 'lag_24', group: 'lags', contribution: 9, value: 61 }] },
    },
    'h',
    t,
    String,
  );
  assert.equal(features[0].label, 't−24 (models.explain.span.days(1))');
  assert.equal(features[0].display, '+9');
  assert.equal(excursionsOf({ task: 'forecasting', excursions: { count: 0, share: 0, points: [] } }).length, 0);
});

// ---------------------------------------------------------------------------
// Anatomy and diagnostic
// ---------------------------------------------------------------------------

const ANATOMY = {
  series: 'A',
  confidence: 0.06,
  acf: [
    { lag: 1, value: 0.9 },
    { lag: 24, value: 0.81 },
    { lag: 36, value: -0.04 },
  ],
  suggested_lags: [1, 2, 24],
  stl: { period: 24, trend_strength: 0.12, seasonal_strength: 0.93 },
  adf: { statistic: -5.2, pvalue: 0.0001, stationary: true },
};

test('a series reads as how seasonal, how trending, and whether it wanders', () => {
  assert.equal(strengthLevel(0.93), 'strong');
  assert.equal(strengthLevel(0.4), 'moderate');
  assert.equal(strengthLevel(0.1), 'weak');
  assert.equal(strengthLevel(null), null);
  const facts = anatomyFacts(ANATOMY);
  assert.deepEqual(facts.map((fact) => fact.key), [
    'models.analysis.season.strong',
    'models.analysis.trend.weak',
    'models.analysis.stationary',
  ]);
  assert.equal(facts[2].tone, 'pos');
  assert.equal(anatomyFacts({ ...ANATOMY, adf: { statistic: -1, pvalue: 0.4, stationary: false } })[2].tone, 'warn');
  assert.deepEqual(anatomyFacts(null), []);
});

test('autocorrelation is signed, and noise inside the band is called noise', () => {
  const bars = acfBars(ANATOMY, 'h', t, (value) => value.toFixed(2));
  assert.deepEqual(bars.map((bar) => bar.display), ['0.90', '0.81', '−0.04']);
  assert.equal(bars[2].negative, true);
  assert.equal(bars[2].share, 'models.analysis.acf.noise');
  assert.equal(bars[0].share, undefined);
});

test('the card finds the anatomy of the series it is showing, and the diagnostic scores', () => {
  const metrics = { task: 'forecasting', analysis: [ANATOMY, { ...ANATOMY, series: 'B' }] };
  assert.equal(seriesAnalysis(metrics, 'B')?.series, 'B');
  assert.equal(seriesAnalysis(metrics, 'missing')?.series, 'A');
  assert.equal(seriesAnalysis({ task: 'forecasting' }, 'A'), null);
  const diagnostic = {
    step: null,
    rows: { train: 800, test: 200 },
    scores: [{ key: 'r2', value: 0.82 }],
    curves: { fit: [], ideal: [] },
  };
  assert.equal(diagnosticScore(diagnostic, 'r2'), 0.82);
  assert.equal(diagnosticScore(diagnostic, 'rmse'), null);
});

const tuningFields = [
  { key: 'tuning', kind: 'enum' as const, required: false, choices: ['off', 'budget'] },
  { key: 'tuning_budget_s', kind: 'int' as const, required: false, min: 30, max: 60, default: 60 },
];
test('forecast tuning follows catalog defaults and round-trips saved settings for Studio and Flow', () => {
  const draft = draftFromSpec({time_column: 'ts', tuning: 'budget', tuning_trials: 9, tuning_folds: 2}, tuningFields);
  assert.equal(draft.tuningBudget, 60);
  assert.deepEqual(tuningBounds(tuningFields, 'tuning_budget_s'), {min:30,max:60,default:60});
  const spec = forecastSpec(draft, 'linear');
  assert.equal(spec['tuning_budget_s'], 60);
  assert.equal(spec['tuning_trials'], 9);
  assert.equal(spec['tuning_folds'], 2);
  assert.deepEqual(draftFromSpec(spec, tuningFields), draft);
  const off = forecastSpec({...draft, tuning: 'off'}, 'linear');
  assert.equal(off['tuning'], 'off');
  assert.equal(off['tuning_budget_s'], undefined);
});
test('saved settings remain visible when a new server budget makes them invalid', () => {
  const draft = draftFromSpec({tuning: 'budget', tuning_budget_s: 300}, tuningFields);
  assert.equal(draft.tuningBudget, 300);
  assert.equal(forecastTuningIssue(draft, 'linear', tuningFields), 'models.forecast.tuning.bounds');
  assert.equal(forecastTuningIssue({...draft, tuningBudget:60}, 'linear', tuningFields), null);
});
test('unsupported forecast tuning is refused explicitly rather than silently removed', () => {
  const draft = {...DEFAULT_FORECAST_DRAFT, tuning: 'budget' as const};
  for (const algo of ['ets','arima','seasonal_naive']) {
    assert.equal(forecastSpec(draft, algo)['tuning'], 'budget');
    assert.equal(forecastTuningIssue(draft, algo), 'models.refusal.ml_ts_tuning_unsupported');
  }
  assert.equal(forecastTuningIssue({...draft, fill:'interpolate'}, 'linear'), 'models.refusal.ml_ts_tuning_fill_unsafe');
  assert.equal(forecastTuningIssue({...draft, tuning:'off', fill:'interpolate'}, 'ets'), null);
  for (const patch of [{tuningBudget:NaN}, {tuningFolds:1}, {tuningTrials:101}, {tuningTrials:5.2}])
    assert.equal(forecastTuningIssue({...draft,...patch}, 'linear'), 'models.forecast.tuning.bounds');
});

test('older catalogs receive no unsupported tuning keys and saved tuning is visibly refused', () => {
  const ordinary = forecastSpec(DEFAULT_FORECAST_DRAFT, 'linear', []);
  assert.equal(ordinary['tuning'], undefined);
  assert.ok(!Object.keys(ordinary).some((key) => key.startsWith('tuning')));
  const saved = {...DEFAULT_FORECAST_DRAFT, tuning:'budget' as const};
  assert.equal(forecastTuningIssue(saved,'linear',[]), 'models.forecast.tuning.unavailable');
  assert.equal(forecastSpec(saved,'linear',[])['tuning'],'budget');
});


const foundationFields: SpecFieldDescriptor[] = [
  { key: 'time_column', kind: 'column', required: true },
  { key: 'shape', kind: 'enum', choices: ['single', 'panel'], default: 'single' },
  { key: 'series_columns', kind: 'columns' },
  { key: 'horizon', kind: 'int', min: 1, max: 64 },
  { key: 'frequency', kind: 'enum' },
  { key: 'interval_level', kind: 'float' },
  { key: 'backtest_folds', kind: 'int', min: 1, max: 5 },
  { key: 'fill', kind: 'enum', choices: ['refuse', 'zero'], default: 'refuse' },
];

test('foundation forecast sends only its family fields, preserving the selected series', () => {
  const draft = {...DEFAULT_FORECAST_DRAFT, timeColumn:'ts', shape:'panel' as const, seriesColumns:['cell_id'],
    strategy:'direct' as const, lags:'1,24', exog:{users:'future' as const}, calendar:true};
  const spec = forecastSpec(draft,'chronos_zero_shot',foundationFields);
  assert.deepEqual(spec, {time_column:'ts',shape:'panel',series_columns:['cell_id'],horizon:24,
    frequency:'auto',interval_level:.8,backtest_folds:3,fill:'refuse'});
  assert.deepEqual(forecastSpec(draftFromSpec(spec),'chronos_zero_shot',foundationFields), spec);
});

test('switching to foundation adapts unsupported choices and bounds without hiding a saved tuning budget', () => {
  const draft = forecastDraftForFields({...DEFAULT_FORECAST_DRAFT,shape:'multivariate',horizon:168,folds:8,
    fill:'interpolate',tuning:'budget'},foundationFields);
  assert.equal(draft.shape,'single');
  assert.equal(draft.horizon,64);
  assert.equal(draft.folds,5);
  assert.equal(draft.fill,'refuse');
  assert.equal(forecastTuningIssue(draft,'chronos_zero_shot',foundationFields),'models.forecast.tuning.unavailable');
});

test('forecast fields follow the algorithm family, with legacy catalog fallback', () => {
  const classic = [{key:'lags',kind:'int_list'}] as SpecFieldDescriptor[];
  const catalog = {algos:[{key:'chronos_zero_shot',family:'forecasting_deep'},{key:'linear'}],
    families:[{key:'forecasting',spec_fields:classic},{key:'forecasting_deep',spec_fields:foundationFields}]} as ModelCatalog;
  assert.deepEqual(forecastFieldsFor(catalog,'chronos_zero_shot'),foundationFields);
  assert.deepEqual(forecastFieldsFor(catalog,'linear'),classic);
  assert.deepEqual(forecastFieldsFor(catalog),classic);
});


test('Play obeys the artifact horizon for foundation forecasts and keeps legacy direct limits', () => {
  assert.equal(forecastMaxSteps({spec:{horizon:24},signature:{output:{max_steps:64}}}),64);
  assert.equal(forecastMaxSteps({spec:{horizon:24},metrics:{task:'forecasting',forecast:{max_steps:64}} as ForecastMetrics}),64);
  assert.equal(forecastMaxSteps({spec:{horizon:12,strategy:'direct'},signature:{output:{max_steps:64}}}),12);
  assert.equal(forecastMaxSteps({spec:{horizon:24}}),720);
});

test('imported forecasting artifacts round-trip only for families that advertise artifact selection', () => {
  const fields = [{ key: 'artifact_id', kind: 'artifact', required: false }] as SpecFieldDescriptor[];
  const draft = draftFromSpec({ artifact_id: 'hf-chronos' }, fields);
  assert.equal(draft.artifactId, 'hf-chronos');
  assert.equal(forecastSpec(draft, undefined, fields)['artifact_id'], 'hf-chronos');
  assert.equal(forecastSpec(draft, undefined, [])['artifact_id'], undefined);
  assert.equal(forecastDraftForFields(draft, [{ key: 'horizon', kind: 'int', required: true }]).artifactId, undefined);
});

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
  baselineGain,
  covariateCandidates,
  coverageTone,
  forecastSpec,
  frequencyKey,
  horizonBars,
  isForecast,
  parseLags,
  plottedSeries,
  roleChoices,
  seriesBars,
  seriesColumnCandidates,
  seriesEvidence,
  strategyApplies,
  timeColumns,
  type ForecastMetrics,
} from './forecast.vm';
import type { PlanColumn } from './models.vm';

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

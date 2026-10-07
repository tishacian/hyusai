/**
 * Forecasting, as the studio asks for it and the model card reads it back.
 *
 * Angular-free like `models.vm.ts`. Two halves:
 *
 * - **the draft** — what the author is choosing in the studio (date column,
 *   shape, horizon, covariates and what is known about each), and the `spec`
 *   it becomes on the wire. The server validates it (`families/forecasting`);
 *   this only refuses to send what the form already knows is meaningless — a
 *   static covariate on a single series, lags typed as "soon";
 * - **the evidence** — the backtest the harness wrote (`ml_forecast_harness`),
 *   projected into the chart, the error per step ahead, the error per series and
 *   the one comparison that decides whether a forecast is worth having: did it
 *   beat repeating the last season.
 */
import type { VizBar } from '@app/features/data/viz/viz.vm';
import type {
  ForecastBacktestPoint,
  ForecastHistoryPoint,
} from '@app/features/data/viz/forecast-chart.vm';

import type { MetricsBlock, PlanColumn } from './models.vm';

export const FORECASTING_TASK = 'forecasting';

export type ForecastShape = 'single' | 'panel' | 'multivariate';
export type ForecastRole = 'future' | 'static' | 'past';
export type ForecastFill = 'refuse' | 'interpolate' | 'zero';

export const FORECAST_SHAPES: readonly ForecastShape[] = ['single', 'panel', 'multivariate'];
export const FORECAST_FREQUENCIES = ['auto', 'h', 'D', 'W', 'MS', 'QS'] as const;
export const FORECAST_FILLS: readonly ForecastFill[] = ['refuse', 'interpolate', 'zero'];
/** Algorithms that fit one series at a time (and keep their own intervals). */
export const SINGLE_SERIES_ALGOS: ReadonlySet<string> = new Set(['ets', 'arima', 'seasonal_naive']);

export interface ForecastDraft {
  timeColumn: string;
  shape: ForecastShape;
  seriesColumns: string[];
  horizon: number;
  frequency: (typeof FORECAST_FREQUENCIES)[number];
  strategy: 'recursive' | 'direct';
  /** As typed: "1, 24, 168". Empty leaves the lags to the frequency. */
  lags: string;
  /** Covariate → what is known about it. Absent means unused. */
  exog: Record<string, ForecastRole>;
  calendar: boolean;
  intervalLevel: number;
  folds: number;
  fill: ForecastFill;
}

export const DEFAULT_FORECAST_DRAFT: ForecastDraft = {
  timeColumn: '',
  shape: 'single',
  seriesColumns: [],
  horizon: 24,
  frequency: 'auto',
  strategy: 'recursive',
  lags: '',
  exog: {},
  calendar: true,
  intervalLevel: 0.8,
  folds: 3,
  fill: 'refuse',
};

/** The roles a covariate can take in a shape: static needs a panel, past a multivariate. */
export function roleChoices(shape: ForecastShape): ForecastRole[] {
  if (shape === 'panel') return ['future', 'static'];
  if (shape === 'multivariate') return ['future', 'past'];
  return ['future'];
}

/**
 * Lags as typed, or `null` when the text is not a list of whole numbers.
 *
 * Sorted and de-duplicated, as the server stores them; an empty text is an
 * empty list, which means "the frequency's defaults".
 */
export function parseLags(text: string): number[] | null {
  const parts = (text ?? '')
    .split(/[\s,;]+/)
    .map((part) => part.trim())
    .filter(Boolean);
  if (!parts.length) return [];
  const numbers = parts.map((part) => Number(part));
  if (numbers.some((value) => !Number.isInteger(value) || value < 1)) return null;
  return [...new Set(numbers)].sort((a, b) => a - b);
}

/**
 * A draft rebuilt from the spec a version was trained with, so a retrain opens
 * on the same question rather than on the defaults.
 */
export function draftFromSpec(spec: Record<string, unknown> | null | undefined): ForecastDraft {
  const draft: ForecastDraft = { ...DEFAULT_FORECAST_DRAFT, exog: {} };
  if (!spec) return draft;
  const text = (key: string) => (typeof spec[key] === 'string' ? (spec[key] as string) : undefined);
  const number = (key: string) => (typeof spec[key] === 'number' ? (spec[key] as number) : undefined);
  draft.timeColumn = text('time_column') ?? '';
  const shape = text('shape');
  if (shape && (FORECAST_SHAPES as readonly string[]).includes(shape)) draft.shape = shape as ForecastShape;
  if (Array.isArray(spec['series_columns'])) draft.seriesColumns = (spec['series_columns'] as unknown[]).map(String);
  draft.horizon = number('horizon') ?? draft.horizon;
  const frequency = text('frequency');
  if (frequency && (FORECAST_FREQUENCIES as readonly string[]).includes(frequency)) {
    draft.frequency = frequency as ForecastDraft['frequency'];
  }
  if (text('strategy') === 'direct') draft.strategy = 'direct';
  if (Array.isArray(spec['lags'])) draft.lags = (spec['lags'] as unknown[]).join(', ');
  const exog = spec['exog'];
  if (exog && typeof exog === 'object') {
    for (const [column, role] of Object.entries(exog as Record<string, unknown>)) {
      if (role === 'future' || role === 'static' || role === 'past') draft.exog[column] = role;
    }
  }
  if (typeof spec['calendar'] === 'boolean') draft.calendar = spec['calendar'] as boolean;
  draft.intervalLevel = number('interval_level') ?? draft.intervalLevel;
  draft.folds = number('backtest_folds') ?? draft.folds;
  const fill = text('fill');
  if (fill && (FORECAST_FILLS as readonly string[]).includes(fill)) draft.fill = fill as ForecastFill;
  return draft;
}

/** Whether a recursive/direct choice means anything for this shape and algorithm. */
export function strategyApplies(shape: ForecastShape, algo: string | undefined): boolean {
  return shape === 'single' && !SINGLE_SERIES_ALGOS.has(algo ?? '');
}

/** The draft as the `spec` the plan and train endpoints read. */
export function forecastSpec(draft: ForecastDraft, algo?: string): Record<string, unknown> {
  const spec: Record<string, unknown> = {
    time_column: draft.timeColumn,
    shape: draft.shape,
    horizon: Math.round(draft.horizon),
    frequency: draft.frequency,
    calendar: draft.calendar,
    interval_level: draft.intervalLevel,
    backtest_folds: draft.folds,
    fill: draft.fill,
  };
  if (draft.shape === 'panel') spec['series_columns'] = [...draft.seriesColumns];
  if (strategyApplies(draft.shape, algo)) spec['strategy'] = draft.strategy;
  const lags = parseLags(draft.lags);
  if (lags?.length) spec['lags'] = lags;
  // A role the shape cannot use is dropped rather than sent to be refused: the
  // author switched shape, they did not ask for a static covariate on one series.
  const allowed = new Set(roleChoices(draft.shape));
  const exog = Object.fromEntries(
    Object.entries(draft.exog).filter(
      ([column, role]) => allowed.has(role) && !draft.seriesColumns.includes(column),
    ),
  );
  if (Object.keys(exog).length) spec['exog'] = exog;
  return spec;
}

/** Columns that can date a series. */
export function timeColumns(columns: readonly PlanColumn[]): string[] {
  return columns.filter((column) => column.kind === 'datetime').map((column) => column.name);
}

/** Columns that can tell the series of a panel apart: labels and ids, not measurements. */
export function seriesColumnCandidates(
  columns: readonly PlanColumn[],
  target: string,
  timeColumn: string,
): string[] {
  return columns
    .filter((column) => column.name !== target && column.name !== timeColumn)
    .filter((column) => !['float', 'datetime', 'boolean'].includes(column.kind))
    .map((column) => column.name);
}

/**
 * Columns that can be covariates, each with the roles it may take.
 *
 * A numeric column can be known in advance or only up to now; a text column
 * only makes sense as an attribute of a series of a panel.
 */
export function covariateCandidates(
  columns: readonly PlanColumn[],
  draft: Pick<ForecastDraft, 'shape' | 'seriesColumns' | 'timeColumn'>,
  target: string,
): { name: string; kind: string; roles: ForecastRole[] }[] {
  const roles = roleChoices(draft.shape);
  return columns
    .filter((column) => column.name !== target && column.name !== draft.timeColumn)
    .filter((column) => !draft.seriesColumns.includes(column.name))
    .map((column) => {
      const numeric = ['integer', 'float', 'boolean'].includes(column.kind);
      return {
        name: column.name,
        kind: column.kind,
        roles: roles.filter((role) => numeric || role === 'static'),
      };
    })
    .filter((candidate) => candidate.roles.length > 0);
}

// ---------------------------------------------------------------------------
// Evidence
// ---------------------------------------------------------------------------

export interface ForecastSummary {
  shape?: ForecastShape;
  algo?: string;
  strategy?: string;
  frequency?: string;
  season?: number;
  horizon?: number;
  folds?: number;
  interval_level?: number;
  interval_method?: 'conformal' | 'model';
  lags?: number[];
  calendar?: string[];
  series_count?: number;
  filled_steps?: number;
  fill?: ForecastFill;
  last_timestamp?: string;
  serialization?: string;
}

export interface ForecastBacktestRow extends ForecastBacktestPoint {
  series: string;
  step?: number;
}

export interface ForecastMetrics extends MetricsBlock {
  forecast?: ForecastSummary;
  baseline?: { key: string; season?: number; mae: number | null };
  per_horizon?: { step: number; mae: number | null; coverage?: number | null }[];
  per_series?: { series: string; mae: number | null; mase: number | null; smape?: number | null }[];
  backtest?: ForecastBacktestRow[];
  history_tail?: (ForecastHistoryPoint & { series: string })[];
}

export function isForecast(metrics: MetricsBlock | null | undefined): metrics is ForecastMetrics {
  return (metrics as ForecastMetrics | null | undefined)?.task === FORECASTING_TASK;
}

/** The series the card can plot, in the order the harness kept them. */
export function plottedSeries(metrics: ForecastMetrics | null | undefined): string[] {
  const seen: string[] = [];
  for (const point of metrics?.backtest ?? []) {
    if (point.series && !seen.includes(point.series)) seen.push(point.series);
  }
  return seen;
}

/** One series' context and backtest, for `forecastChartSeries`. */
export function seriesEvidence(
  metrics: ForecastMetrics | null | undefined,
  series: string | undefined,
): { history: ForecastHistoryPoint[]; backtest: ForecastBacktestPoint[] } {
  const name = series ?? plottedSeries(metrics)[0];
  return {
    history: (metrics?.history_tail ?? []).filter((point) => point.series === name),
    backtest: (metrics?.backtest ?? []).filter((point) => point.series === name),
  };
}

function score(metrics: MetricsBlock | null | undefined, key: string): number | null {
  const value = (metrics?.scores ?? []).find((entry) => entry.key === key)?.value;
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

/**
 * How much better than repeating the last season, as a share of its error.
 *
 * Positive is better. `null` when there is nothing to compare — the seasonal
 * naive model is its own reference.
 */
export function baselineGain(metrics: ForecastMetrics | null | undefined): number | null {
  const naive = metrics?.baseline?.mae;
  const mae = score(metrics, 'mae');
  if (typeof naive !== 'number' || !Number.isFinite(naive) || naive <= 0 || mae === null) return null;
  return 1 - mae / naive;
}

/**
 * Whether the interval held what it promised: an 80% interval that covered
 * 79% of the actuals is calibrated, one that covered 40% is decoration.
 */
export function coverageTone(
  coverage: number | null | undefined,
  level: number | null | undefined,
): 'pos' | 'warn' | 'neg' | 'neutral' {
  if (typeof coverage !== 'number' || typeof level !== 'number') return 'neutral';
  const gap = Math.abs(coverage - level);
  if (gap <= 0.07) return 'pos';
  if (gap <= 0.15) return 'warn';
  return 'neg';
}

/** The error at each step ahead: how fast the forecast degrades. */
export function horizonBars(
  metrics: ForecastMetrics | null | undefined,
  format: (value: number) => string,
  stepLabel: (step: number) => string,
): VizBar[] {
  const rows = (metrics?.per_horizon ?? []).filter(
    (row): row is { step: number; mae: number } => typeof row.mae === 'number' && Number.isFinite(row.mae),
  );
  const widest = Math.max(0, ...rows.map((row) => row.mae));
  return rows.map((row) => ({
    label: stepLabel(row.step),
    display: format(row.mae),
    width: widest > 0 ? Math.max(2, Math.round((row.mae / widest) * 100)) : 0,
    negative: false,
    emphasis: false,
  }));
}

/** The worst series first: the one an operator opens. */
export function seriesBars(
  metrics: ForecastMetrics | null | undefined,
  format: (value: number) => string,
  limit = 12,
): VizBar[] {
  const rows = (metrics?.per_series ?? [])
    .filter((row): row is { series: string; mae: number; mase: number | null } => typeof row.mae === 'number')
    .sort((a, b) => (b.mase ?? b.mae) - (a.mase ?? a.mae))
    .slice(0, limit);
  const widest = Math.max(0, ...rows.map((row) => row.mase ?? row.mae));
  return rows.map((row) => ({
    label: row.series,
    display: row.mase !== null ? `MASE ${format(row.mase)}` : format(row.mae),
    width: widest > 0 ? Math.max(2, Math.round(((row.mase ?? row.mae) / widest) * 100)) : 0,
    negative: false,
    // A series the model forecasts worse than repeating its last value is the
    // one to look at first, so it is drawn loud.
    emphasis: row.mase !== null && row.mase >= 1,
  }));
}

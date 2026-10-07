/**
 * The numbers behind `<ck-forecast-chart>`: one time axis, four lines.
 *
 * A forecast is read against what really happened, so the chart lays the
 * context before the backtest, the actuals during it, the forecast and its
 * interval on one shared axis of timestamps. chart.js draws categories, not
 * times, so the alignment is done here: every series gets one value (or a gap)
 * per label, and a gap is `null` — never zero, which would draw a cliff.
 */

export interface ForecastHistoryPoint {
  t: string;
  value: number | null;
}

export interface ForecastBacktestPoint {
  t: string;
  actual: number | null;
  pred: number | null;
  lower?: number | null;
  upper?: number | null;
  fold?: number;
}

export interface ForecastChartSeries {
  /** ISO timestamps, sorted, one per column of the chart. */
  labels: string[];
  /** What happened: the context, then the actuals of the backtest. */
  actual: (number | null)[];
  /** What the model said, only over the backtest. */
  pred: (number | null)[];
  lower: (number | null)[];
  upper: (number | null)[];
  /** The fold each forecast belongs to, for the tooltip. */
  folds: (number | null)[];
  /** Index of the first forecast column, where the backtest starts. */
  start: number;
}

function finite(value: number | null | undefined): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

/** Context and backtest of one series, on one sorted axis. */
export function forecastChartSeries(
  history: readonly ForecastHistoryPoint[],
  backtest: readonly ForecastBacktestPoint[],
): ForecastChartSeries {
  const byStamp = new Map<string, { actual: number | null; pred: number | null; lower: number | null; upper: number | null; fold: number | null }>();
  for (const point of history) {
    if (!point?.t) continue;
    byStamp.set(point.t, { actual: finite(point.value), pred: null, lower: null, upper: null, fold: null });
  }
  for (const point of backtest) {
    if (!point?.t) continue;
    byStamp.set(point.t, {
      actual: finite(point.actual),
      pred: finite(point.pred),
      lower: finite(point.lower),
      upper: finite(point.upper),
      fold: typeof point.fold === 'number' ? point.fold : null,
    });
  }
  const labels = [...byStamp.keys()].sort((a, b) => Date.parse(a) - Date.parse(b) || a.localeCompare(b));
  const rows = labels.map((label) => byStamp.get(label)!);
  const start = rows.findIndex((row) => row.pred !== null);
  return {
    labels,
    actual: rows.map((row) => row.actual),
    pred: rows.map((row) => row.pred),
    lower: rows.map((row) => row.lower),
    upper: rows.map((row) => row.upper),
    folds: rows.map((row) => row.fold),
    start: start < 0 ? labels.length : start,
  };
}

/**
 * A timestamp as a reader of this frequency expects it.
 *
 * Hourly data names the hour, daily data the day, monthly data the month: the
 * axis of a 48-hour forecast labelled "2026-08-24T00:00:00" is noise, and the
 * same axis labelled "24/08" hides the hour the peak is at.
 */
export function formatForecastStamp(iso: string, frequency: string | undefined, locale: string): string {
  const date = new Date(iso.includes('T') || iso.includes(' ') ? iso.replace(' ', 'T') : `${iso}T00:00:00`);
  if (Number.isNaN(date.getTime())) return iso;
  const head = (frequency ?? '').replace(/^\d+/, '').toUpperCase();
  const options: Intl.DateTimeFormatOptions = head.startsWith('H') || head.startsWith('MIN') || head === 'T'
    ? { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }
    : head.startsWith('MS') || head.startsWith('ME') || head === 'M' || head.startsWith('Q')
      ? { month: 'short', year: 'numeric' }
      : { day: '2-digit', month: '2-digit', year: '2-digit' };
  return new Intl.DateTimeFormat(locale, options).format(date);
}

/** The vertical extent that holds every line and the whole band. */
export function forecastExtent(series: ForecastChartSeries): { min: number; max: number } | null {
  const values = [...series.actual, ...series.pred, ...series.lower, ...series.upper].filter(
    (value): value is number => value !== null,
  );
  if (!values.length) return null;
  let min = Math.min(...values);
  let max = Math.max(...values);
  if (min === max) {
    min -= 1;
    max += 1;
  }
  const pad = (max - min) * 0.06;
  return { min: min - pad, max: max + pad };
}

import { forecastChartSeries, type ForecastChartSeries } from '../../data/viz/forecast-chart.vm';

export const TIMESERIES_ROW_LIMIT = 1000;
export const TIMESERIES_GROUP_LIMIT = 12;
export interface TimeseriesMapping {
  time: string; value: string; actual: string; lower: string; upper: string; series: string;
}
const record = (value: unknown): Record<string, unknown> =>
  value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
export function timeseriesMapping(value: unknown): TimeseriesMapping {
  const raw = record(value);
  const field = (name: string, fallback: string) => typeof raw[name] === 'string' ? String(raw[name]).trim().slice(0, 128) : fallback;
  return { time: field('time', 'ds'), value: field('value', 'forecast'), actual: field('actual', 'actual'), lower: field('lower', 'lower'), upper: field('upper', 'upper'), series: field('series', '') };
}
const numeric = (value: unknown): number | null => {
  if (value === null || value === undefined || (typeof value === 'string' && !value.trim()) || typeof value === 'boolean') return null;
  const result = typeof value === 'number' ? value : typeof value === 'string' ? Number(value) : NaN;
  return Number.isFinite(result) ? result : null;
};
export interface TimeseriesProjection {
  groups: { name: string; series: ForecastChartSeries }[];
  omitted: number; invalid: number; duplicate: number; invalidIntervals: number;
}
/** Bounded display projection. Missing values remain gaps; duplicates never silently overwrite evidence. */
export function projectTimeseries(value: unknown, rawMapping: unknown): TimeseriesProjection {
  const map = timeseriesMapping(rawMapping);
  const raw = Array.isArray(value) ? value : record(value)['rows'];
  const rows = Array.isArray(raw) ? raw : [];
  const groups = new Map<string, Map<string, { t: string; actual: number | null; pred: number | null; lower: number | null; upper: number | null }>>();
  let omitted = Math.max(0, rows.length - TIMESERIES_ROW_LIMIT), invalid = 0, duplicate = 0, invalidIntervals = 0;
  for (const item of rows.slice(0, TIMESERIES_ROW_LIMIT)) {
    const row = record(item), time = row[map.time];
    if (typeof time !== 'string' || !/^\d{4}-\d{2}-\d{2}(?:[T ].*)?$/.test(time) || !Number.isFinite(Date.parse(time))) { invalid++; continue; }
    const t = new Date(time).toISOString();
    const name = map.series ? String(row[map.series] ?? '').slice(0, 160) : '';
    if (!groups.has(name) && groups.size >= TIMESERIES_GROUP_LIMIT) { omitted++; continue; }
    const actual = numeric(row[map.actual]), pred = numeric(row[map.value]);
    if (actual === null && pred === null) { invalid++; continue; }
    let lower = numeric(row[map.lower]), upper = numeric(row[map.upper]);
    if (lower !== null && upper !== null && lower > upper) { lower = upper = null; invalidIntervals++; }
    if ((lower === null) !== (upper === null)) { lower = upper = null; invalidIntervals++; }
    if (pred === null) lower = upper = null;
    const points = groups.get(name) ?? new Map();
    // Two rows can describe an observation and a forecast at the same instant.
    // Conflicting values are rejected instead of choosing a convenient value.
    const previous = points.get(t);
    if (previous && ((previous.actual !== null && actual !== null) || (previous.pred !== null && pred !== null))) { duplicate++; continue; }
    points.set(t, { t, actual: actual ?? previous?.actual ?? null, pred: pred ?? previous?.pred ?? null, lower: lower ?? previous?.lower ?? null, upper: upper ?? previous?.upper ?? null });
    groups.set(name, points);
  }
  return { groups: [...groups].map(([name, points]) => ({ name, series: forecastChartSeries([], [...points.values()]) })), omitted, invalid, duplicate, invalidIntervals };
}

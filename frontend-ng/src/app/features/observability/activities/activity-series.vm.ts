import type { ChartData } from 'chart.js';

export interface SeriesSummary {
  total: number;
  by_status: Record<string, number>;
  by_kind: Record<string, number>;
  durations: Record<string, { eligible_count: number; measured_count: number; p50_ms: number | null; p95_ms: number | null }>;
  costs: Array<{ basis: string; currency: string; known_amount: number; known_count: number }>;
  cost_unknown_count: number;
  cost_known_count: number;
  cost_complete: boolean;
  snapshot_only_count: number;
}
export interface ActivitySeries {
  from: string; until: string; as_of: string;
  population: { metric: 'activity' | 'cost'; kind: string | null; time_basis: 'created' | 'finished' };
  bucket: 'hour' | 'day'; quantile_method: string;
  totals: SeriesSummary;
  buckets: Array<SeriesSummary & { from: string; until: string }>;
  coverage: { missing_finished_at: number; historical_state_reconstruction: false };
}

export const STATUS_COLOURS: Record<string, string> = {
  pending: '#94a3b8', running: '#38bdf8', waiting: '#2dd4bf', succeeded: '#34d399',
  failed: '#fb7185', cancelled: '#64748b', timed_out: '#fbbf24', lost: '#fb923c', unknown: '#a3a3a3',
};

export function volumeChart(series: ActivitySeries, label: (status: string) => string): ChartData<'bar'> {
  return { labels: series.buckets.map(cell => cell.from), datasets: Object.keys(STATUS_COLOURS).map(status => ({
    label: label(status), data: series.buckets.map(cell => cell.by_status[status] ?? 0),
    backgroundColor: STATUS_COLOURS[status], stack: 'activities',
  })) };
}

export function durationChart(series: ActivitySeries, label: (kind: string) => string = value => value): ChartData<'line'> {
  const colours = ['#38bdf8', '#2dd4bf', '#34d399', '#fbbf24', '#fb7185', '#94a3b8', '#fb923c', '#a3a3a3'];
  return { labels: series.buckets.map(cell => cell.from), datasets: Object.keys(series.totals.durations).flatMap((kind, index) =>
    (['p50_ms', 'p95_ms'] as const).map(metric => ({
      label: `${label(kind)} · ${metric === 'p50_ms' ? 'p50' : 'p95'} (ms)`,
      data: series.buckets.map(cell => cell.durations[kind]?.[metric] ?? null),
      borderColor: colours[index % colours.length], borderDash: metric === 'p50_ms' ? [4, 4] : [],
      spanGaps: false, pointRadius: 1, fill: false,
    }))) };
}

export function expenseChart(series: ActivitySeries, label: (basis: string) => string = value => value): ChartData<'bar'> {
  return { labels: series.buckets.map(cell => cell.from), datasets: series.totals.costs.map((cost, index) => ({
    label: `${label(cost.basis)} · ${cost.currency}`,
    data: series.buckets.map(cell => cell.costs.find(value => value.basis === cost.basis && value.currency === cost.currency)?.known_amount ?? null),
    backgroundColor: ['#38bdf8', '#2dd4bf', '#34d399'][index % 3],
    // Different currencies/bases are separate bars, never an apparent total.
  })) };
}

/** UTC bounds shared by the Operations tiles and the series chart (same anchor, same cutoff). */
export function seriesRange(since: string, anchor: string, now = Date.now()): { from: string; until: string; bucket: 'hour' | 'day' } {
  const until = new Date(anchor || now);
  const hours = since === '24h' ? 24 : since === '30d' ? 720 : 168;
  return { from: new Date(until.getTime() - hours * 3600000).toISOString(), until: until.toISOString(), bucket: hours > 168 ? 'day' : 'hour' };
}

/**
 * Operations tiles from the exhaustive Run series (created basis): current state
 * of the Runs created in the period. "Running" keeps the overview's native set
 * (pending, running, hitl/debug pending, waiting subflows), i.e. the unified
 * pending, running and waiting statuses. The p95 is the exact nearest rank over
 * measured terminal Runs; absent durations stay absent.
 */
export function runTiles(series: ActivitySeries): { total: number; succeeded: number; running: number; failed: number; p95_ms: number | null; measured: number; eligible: number } {
  const status = series.totals.by_status;
  const durations = series.totals.durations['run'];
  return {
    total: series.totals.total,
    succeeded: status['succeeded'] ?? 0,
    running: (status['pending'] ?? 0) + (status['running'] ?? 0) + (status['waiting'] ?? 0),
    failed: status['failed'] ?? 0,
    p95_ms: durations?.p95_ms ?? null,
    measured: durations?.measured_count ?? 0,
    eligible: durations?.eligible_count ?? 0,
  };
}

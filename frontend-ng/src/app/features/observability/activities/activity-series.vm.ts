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

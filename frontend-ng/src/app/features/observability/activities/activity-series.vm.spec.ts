import { test } from 'node:test';
import assert from 'node:assert/strict';
import { durationChart, expenseChart, STATUS_COLOURS, volumeChart, type ActivitySeries, type SeriesSummary } from './activity-series.vm';

const cell: SeriesSummary = {
  total: 2, by_status: { succeeded: 1, unknown: 1 }, by_kind: { run: 2 },
  durations: { run: { eligible_count: 2, measured_count: 1, p50_ms: 10, p95_ms: 10 } },
  costs: [{ basis: 'provider_measured', currency: 'USD', known_amount: .1, known_count: 1 }],
  cost_unknown_count: 1, cost_known_count: 1, cost_complete: false, snapshot_only_count: 0,
};
const series: ActivitySeries = {
  from: '2026-01-01T00:00:00Z', until: '2026-01-02T00:00:00Z', as_of: '2026-01-02T00:00:00Z',
  population: { metric: 'activity', kind: 'run', time_basis: 'created' }, bucket: 'day', quantile_method: 'nearest_rank_exact',
  totals: cell, buckets: [{ from: '2026-01-01T00:00:00Z', until: '2026-01-02T00:00:00Z', ...cell }],
  coverage: { missing_finished_at: 0, historical_state_reconstruction: false },
};
test('status stacks retain unknown and distinguish loss, timeout and cancellation', () => {
  const chart = volumeChart(series, value => value);
  assert.equal(chart.datasets.find(value => value.label === 'unknown')!.data[0], 1);
  assert.equal(new Set(['lost', 'timed_out', 'cancelled', 'unknown'].map(value => STATUS_COLOURS[value])).size, 4);
  assert.equal(chart.datasets.reduce((sum, value) => sum + Number(value.data[0]), 0), 2);
});
test('duration charts keep absent measures as gaps and never merge unlike kinds', () => {
  const value = structuredClone(series);
  value.totals.durations.skill_invocation = { eligible_count: 1, measured_count: 0, p50_ms: null, p95_ms: null };
  value.buckets[0].durations = {};
  const chart = durationChart(value);
  assert.equal(chart.datasets.length, 4);
  assert.ok(chart.datasets.every(line => line.data[0] === null && line.spanGaps === false));
});
test('expense charts preserve genuine zero and use gaps for uncovered buckets', () => {
  const value = structuredClone(series);
  value.totals.costs.push({ basis: 'catalogue_calculated', currency: 'EUR', known_amount: 0, known_count: 1 });
  value.buckets[0].costs = [{ basis: 'catalogue_calculated', currency: 'EUR', known_amount: 0, known_count: 1 }];
  const chart = expenseChart(value);
  assert.equal(chart.datasets[0].data[0], null);
  assert.equal(chart.datasets[1].data[0], 0);
  assert.notEqual(chart.datasets[0].label, chart.datasets[1].label);
  assert.equal(chart.datasets[0].stack, undefined);
});

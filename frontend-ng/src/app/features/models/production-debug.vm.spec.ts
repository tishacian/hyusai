import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  badgeTone,
  canRun,
  dateText,
  exclusionRows,
  fairnessReasonKey,
  fairnessSeries,
  gapDomain,
  gapMetricKey,
  isActive,
  productionEvidence,
  readView,
  statusKey,
  windowText,
  type ProductionDebugView,
  type ProductionReport,
} from './production-debug.vm';

function report(overrides: Partial<ProductionReport> = {}): ProductionReport {
  return {
    id: 'r1',
    model_id: 'm1',
    version: 1,
    trigger: 'manual',
    status: 'completed',
    window: { from: null, until: null },
    counts: { labeled: 241, used: 180, excluded: { inputs_not_retained: 61 } },
    metrics: { accuracy: 0.66, rows: 180 },
    report: {
      error_measure: 'served_answer_vs_label',
      rows: 180,
      error_tree: { rules: [], global_error: 0.34, rows: 180 },
      fairness: {
        columns: [{ column: 'plan', groups: [{ group: 'a', n: 90, low_support: false, accuracy: 1 }] }],
        gaps: [{ column: 'plan', metric: 'equalized_odds_difference', gap: 1, badge: 'alert' }],
        badge: 'alert',
      },
    },
    fairness_badge: 'alert',
    error_code: null,
    created_at: '2026-10-17T10:00:00',
    completed_at: '2026-10-17T10:00:05',
    ...overrides,
  };
}

function view(latest: ProductionReport | null, supported = true): ProductionDebugView {
  return {
    supported,
    latest,
    series: [],
    fairness_columns: ['plan'],
    limits: { min_rows: 50, max_rows: 5000, interval_minutes: 1440, watch_gap: 0.05, alert_gap: 0.1, min_group_rows: 30 },
  };
}

test('the run button needs the write permission, a supported model and nothing running', () => {
  assert.equal(canRun(view(report()), { score: true }), true);
  assert.equal(canRun(view(report()), { score: false, read: true }), false);
  assert.equal(canRun(view(report()), null), false);
  assert.equal(canRun(view(report(), false), { score: true }), false);
  assert.equal(canRun(view(report({ status: 'queued' })), { score: true }), false);
  assert.equal(canRun(view(null), { score: true }), true);
  assert.equal(isActive(report({ status: 'running' })), true);
  assert.equal(isActive(report({ status: 'insufficient_data' })), false);
  assert.equal(statusKey(report({ status: 'insufficient_data' })), 'models.production.status.insufficient_data');
});

test('a completed report reads as the training pack’s evidence shape', () => {
  const evidence = productionEvidence(report());
  assert.equal(evidence?.rows, 180);
  assert.equal(evidence?.error_tree?.global_error, 0.34);
  assert.deepEqual(Array.isArray(evidence?.fairness) && evidence.fairness.map((item) => item.column), ['plan']);
  assert.equal(productionEvidence(report({ status: 'insufficient_data' })), null);
  assert.equal(productionEvidence(report({ report: { error: 'too_large' } })), null);
  const noFairness = productionEvidence(report({ report: { error_tree: { rules: [] }, fairness: { reason: 'no_sensitive_columns' } } }));
  assert.equal(noFairness && 'fairness' in noFairness, false);
});

test('exclusions list each reason once, largest first, unknown reasons kept', () => {
  assert.deepEqual(
    exclusionRows(report({ counts: { labeled: 300, used: 100, excluded: { beyond_max_rows: 140, inputs_not_retained: 61, odd: 2, zero: 0 } } })),
    [
      { reason: 'beyond_max_rows', key: 'models.production.excluded.beyond_max_rows', count: 140 },
      { reason: 'inputs_not_retained', key: 'models.production.excluded.inputs_not_retained', count: 61 },
      { reason: 'odd', key: 'models.production.excluded.other', count: 2 },
    ],
  );
  assert.deepEqual(exclusionRows(null), []);
});

test('only a real fairness signal is coloured', () => {
  assert.equal(badgeTone('ok'), 'neutral');
  assert.equal(badgeTone(null), 'neutral');
  assert.equal(badgeTone('watch'), 'warn');
  assert.equal(badgeTone('alert'), 'alert');
  assert.equal(gapMetricKey('mae_gap_ratio'), 'models.production.gap.mae_gap_ratio');
  assert.equal(gapMetricKey(undefined), 'models.production.gap.other');
  assert.equal(fairnessReasonKey('not_in_inputs'), 'models.production.fairness.not_in_inputs');
  assert.equal(fairnessReasonKey('mystery'), 'models.production.fairness.unavailable');
});

test('gap series keep positions and never invent a zero', () => {
  const series = fairnessSeries([
    { report_id: 'a', at: '2026-10-01T00:00:00', badge: 'ok', gaps: [{ column: 'plan', metric: 'accuracy_gap', gap: 0.02 }] },
    { report_id: 'b', at: '2026-10-02T00:00:00', badge: null, gaps: [{ column: 'plan', gap: null }] },
    { report_id: 'c', at: '2026-10-03T00:00:00', badge: 'alert', gaps: [{ column: 'plan', gap: 0.2 }, { column: 'region', gap: 0.01 }] },
  ]);
  assert.deepEqual(series.map((item) => [item.column, item.metric, item.points]), [
    ['plan', 'accuracy_gap', [{ x: 1, y: 0.02 }, { x: 3, y: 0.2 }]],
    ['region', null, [{ x: 3, y: 0.01 }]],
  ]);
  assert.equal(series[0].dates.length, 3);
  assert.deepEqual(gapDomain(series[0].points, 0.1), { minX: 1, maxX: 3, minY: 0, maxY: 0.2 });
  assert.ok(Math.abs(gapDomain([], 0.1).maxY - 0.12) < 1e-12);
});

test('the window reads as all production or as its bounds', () => {
  const words = { all: 'all', since: 'since', until: 'until' };
  assert.equal(windowText({ from: null, until: null }, 'en', words), 'all');
  assert.match(windowText({ from: '2026-01-01T12:00:00', until: null }, 'en', words), /^since /);
  assert.doesNotMatch(windowText({ from: null, until: '2026-01-01T12:00:00' }, 'en', words), /since/);
  assert.equal(dateText('not a date', 'en'), '');
  assert.equal(dateText(null, 'en'), '');
});

test('anything but a production view leaves the section absent', () => {
  assert.equal(readView({}), null);
  assert.equal(readView(null), null);
  assert.equal(readView({ supported: true }), null);
  const parsed = readView({ supported: true, limits: view(null).limits, latest: {}, series: 'x' });
  assert.deepEqual(parsed && [parsed.latest, parsed.series, parsed.fairness_columns], [null, [], []]);
  assert.equal(readView(view(report()))?.latest?.id, 'r1');
});

import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { Run } from '@app/core/canonical-api.service';
import {
  FLOW_RESULT_COLUMN_LIMIT, FLOW_RESULT_ROW_LIMIT,
  flowNodeDecisionRun, flowResultStructured, flowResultSupports, flowResultTable,
  flowResultTimeseriesMapping, projectFlowResult,
} from './flow-result.vm';

test('native forecast dataset rows retain intervals, independent series and actual gaps', () => {
  const result = projectFlowResult({ dataset_id: 'forecast-data', forecast: { frequency: 'D' } }, {
    rows: [
      { timestamp: '2026-10-22', pred: 14, lower_bound: 10, upper_bound: 18, series: 'A' },
      { timestamp: '2026-10-22', pred: 7, lower_bound: 4, upper_bound: 9, series: 'B' },
      { timestamp: '2026-10-23', pred: 16, lower_bound: 11, upper_bound: 19, series: 'A' },
    ], total_rows: 3,
  });
  assert.equal(result.frequency, 'D');
  assert.equal(result.chart?.groups.length, 2);
  assert.deepEqual(result.chart?.groups[0].series.pred, [14, 16]);
  assert.deepEqual(result.chart?.groups[0].series.actual, [null, null]);
  assert.deepEqual(result.chart?.groups[0].series.lower, [10, 11]);
  assert.deepEqual(result.chart?.groups[0].series.upper, [18, 19]);
});

test('Work timeseries reuse its exact projection, including missing values and conflicting evidence', () => {
  const result = projectFlowResult({ rows: [
    { ds: '2026-10-22', actual: 9 },
    { ds: '2026-10-23', forecast: 14, lower: 18, upper: 10 },
    { ds: '2026-10-23', forecast: 1 },
    { ds: '2026-10-24', forecast: null },
  ] });
  assert.deepEqual(result.chart?.groups[0].series.pred, [null, 14]);
  assert.deepEqual(result.chart?.groups[0].series.lower, [null, null]);
  assert.equal(result.chart?.invalidIntervals, 1);
  assert.equal(result.chart?.duplicate, 1);
  assert.equal(result.chart?.invalid, 1);
});

test('forecast metadata and peaks never masquerade as the underlying timeseries', () => {
  const result = projectFlowResult({ dataset_id: 'frozen-id', forecast: { horizon: 12, peaks: [{ timestamp: '2026-10-22', pred: 100 }] } });
  assert.equal(result.chart, null);
  assert.equal(flowResultSupports(result, 'chart', false), false);
  assert.ok(result.structured.includes('frozen-id'));
});

test('unknown columns need an explicit chart mapping instead of guessing a measure', () => {
  const rows = [{ at: '2026-10-22', total: 8, team: 'A' }];
  assert.equal(flowResultTimeseriesMapping(rows), null);
  assert.equal(projectFlowResult(rows).chart, null);
  const mapped = projectFlowResult(rows, null, { time: 'at', value: 'total', series: 'team' });
  assert.deepEqual(mapped.chart?.groups[0].series.pred, [8]);
});

test('dataset preview totals remain unknown unless supplied, and preview length is not a total', () => {
  const result = projectFlowResult({}, { rows: [{ case: 'C1', score: 0 }], truncated: true });
  assert.equal(result.table?.total, null);
  assert.equal(result.table?.truncated, true);
  assert.equal(result.table?.rows[0]['score'], 0);
  assert.equal(projectFlowResult({ rows: [{ score: 0 }] }).table?.total, 1);
});

test('table windows bound rows, columns and long cells without modifying the retained output', () => {
  const columns = Array.from({ length: 30 }, (_, index) => `field_${index}`);
  const rows = Array.from({ length: 100 }, () => Object.fromEntries(columns.map((name, index) => [name, index ? index : 'x'.repeat(2_000)])));
  const original = structuredClone(rows);
  const table = flowResultTable(rows)!;
  assert.equal(table.rows.length, FLOW_RESULT_ROW_LIMIT);
  assert.equal(table.columns.length, FLOW_RESULT_COLUMN_LIMIT);
  assert.equal(table.total, 100);
  assert.equal(table.truncated, true);
  assert.equal((table.rows[0]['field_0'] as string).length, 1_001);
  assert.deepEqual(rows, original);
});

test('empty datasets can still retain their recorded schema and zero total', () => {
  const result = projectFlowResult({}, { rows: [], total_rows: 0, schema: [{ name: 'amount', dtype: 'Float64', kind: 'float' }] });
  assert.equal(result.table?.total, 0);
  assert.equal(result.table?.columns[0].name, 'amount');
  assert.equal(flowResultSupports(result, 'table', false), true);
});

test('recorded historical predictions are readable without a present-time freshness invention', () => {
  const result = projectFlowResult({ model_advice: {
    schema_version: 1, status: 'ready', task: 'classification', unit: 'probability', score: 0,
    target: 'late', positive_label: 'late', captured_at: '2026-01-01T09:00:00Z',
  } });
  assert.equal(result.prediction?.value, 0);
  assert.equal(result.prediction?.capturedAt, '2026-01-01T09:00:00Z');
  assert.equal(projectFlowResult({ schema_version: 1, status: 'ready', task: 'classification', unit: 'probability', score: 1.2 }).prediction, null);
});

test('scalar zero and false remain recorded values and absent output stays absent', () => {
  assert.deepEqual(projectFlowResult(0).facts, [{ key: 'value', value: 0 }]);
  assert.deepEqual(projectFlowResult(false).facts, [{ key: 'value', value: false }]);
  assert.equal(projectFlowResult(null).empty, true);
  assert.equal(flowResultSupports(projectFlowResult(null), 'metric', false), false);
});

test('recorded ML metrics are consultable without recomputing or filling unknown measurements', () => {
  const result = projectFlowResult({ model_id: 'model-v5', metrics: { roc_auc: 0.87, missing: null, confusion_matrix: [[1, 0], [0, 1]] } });
  assert.deepEqual(result.facts, [{ key: 'metrics.roc_auc', value: 0.87 }]);
  assert.equal(flowResultSupports(result, 'metric', false), true);
});

test('document output and evidence are literal text, with bounded excerpts', () => {
  const result = projectFlowResult({ answer: '<script>alert(1)</script>', citations: [{ evidence_id: 'evidence-2', quote: 'x'.repeat(15_000), title: 'Policy' }] });
  assert.equal(result.documents[0].text, '<script>alert(1)</script>');
  assert.equal(result.documents[1].source, 'evidence-2');
  assert.equal(result.documents[1].text.length, 12_000);
  assert.equal(result.documentTruncated, true);
  assert.equal(flowResultSupports(result, 'document', false), true);
});

test('structured fallback bounds recursive/wide objects instead of failing the renderer', () => {
  const value: Record<string, unknown> = { many: Array.from({ length: 300 }, () => ({ data: 'x'.repeat(50_000) })) };
  value['self'] = value;
  const result = flowResultStructured(value);
  assert.ok(result.text.length <= 18_000);
  assert.equal(result.truncated, true);
});

test('agent decisions remain scoped to the selected node and do not borrow an adjacent loop', () => {
  const run: Run = {
    id: 'run-a', system_id: 'system-a', status: 'completed',
    skill_invocations: [
      { id: 'decide-a', skill_slug: 'decide_next_v1', trace: { node_id: 'loop-a' } },
      { id: 'act-a', skill_slug: 'search_v1', trace: { node_id: 'loop-a' } },
      { id: 'decide-b', skill_slug: 'decide_next_v1', trace: { node_id: 'loop-b' } },
      { id: 'unattributed', skill_slug: 'decide_next_v1' },
    ],
    checkpoints: [{ node_id: 'loop-a', kind: 'agent_loop_policy_block' }, { node_id: 'loop-b', kind: 'agent_loop_policy_block' }],
  };
  const selected = flowNodeDecisionRun(run, 'loop-a')!;
  assert.deepEqual(selected.skill_invocations?.map(call => call.id), ['decide-a', 'act-a']);
  assert.equal(selected.checkpoints?.length, 1);
  assert.equal(flowNodeDecisionRun(run, 'other'), null);
  assert.equal(flowNodeDecisionRun(run, null), null);
  assert.equal(run.skill_invocations?.length, 4);
});

test('explicit result types fail clearly on incompatible retained data', () => {
  const value = projectFlowResult({ rows: [{ name: 'A', amount: 10 }] });
  assert.equal(flowResultSupports(value, 'table', false), true);
  for (const kind of ['chart', 'document', 'decisions', 'metric'] as const) assert.equal(flowResultSupports(value, kind, false), false);
  assert.equal(flowResultSupports(value, 'decisions', true), true);
});

test('selected agent decision retains only its attributed action and never future turns or passages', () => {
  const trace = (kind: string, turn: number, passage = 'p1') => ({ node_id: 'loop', passage_id: passage, membrane_attempt_kind: kind, membrane_attempt_index: turn });
  const run: Run = { id: 'run', system_id: 'system', status: 'completed', skill_invocations: [
    { id: 'd1', skill_slug: 'decide_next_v1', trace: trace('agent_loop_decide', 1) },
    { id: 'a1', skill_slug: 'search_v1', trace: trace('agent_loop_act', 1) },
    { id: 'd2', skill_slug: 'decide_next_v1', trace: trace('agent_loop_decide', 2) },
    { id: 'a2', skill_slug: 'search_v1', trace: trace('agent_loop_act', 2) },
    { id: 'other-passage', skill_slug: 'search_v1', trace: trace('agent_loop_act', 1, 'p2') },
  ], checkpoints: [
    { node_id: 'loop', passage_id: 'p1', turn: 1, kind: 'agent_loop_policy_block' },
    { node_id: 'loop', passage_id: 'p1', turn: 2, kind: 'agent_loop_policy_block' },
    { node_id: 'loop', passage_id: 'p2', turn: 1, kind: 'agent_loop_policy_block' },
  ] };
  const selected = flowNodeDecisionRun(run, 'loop', 'd1')!;
  assert.deepEqual(selected.skill_invocations?.map(call => call.id), ['d1', 'a1']);
  assert.equal(selected.checkpoints?.length, 1);
  assert.equal(flowNodeDecisionRun(run, 'loop', 'a1'), null);
  assert.equal(flowNodeDecisionRun(run, 'loop', 'missing'), null);
});

test('an old decision without passage evidence cannot borrow actions or checkpoints', () => {
  const run: Run = { id: 'run', system_id: 'system', status: 'completed', skill_invocations: [
    { id: 'old', skill_slug: 'decide_next_v1', trace: { node_id: 'loop' } },
    { id: 'later', skill_slug: 'search_v1', trace: { node_id: 'loop', passage_id: 'p1', membrane_attempt_index: 1, membrane_attempt_kind: 'agent_loop_act' } },
  ], checkpoints: [{ node_id: 'loop', passage_id: 'p1', turn: 1 }] };
  const selected = flowNodeDecisionRun(run, 'loop', 'old')!;
  assert.deepEqual(selected.skill_invocations?.map(call => call.id), ['old']);
  assert.deepEqual(selected.checkpoints, []);
});

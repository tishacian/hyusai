/**
 * The figures a settled node puts on the canvas.
 *
 * These tests are about an editorial decision, not about formatting: a node
 * card has room for exactly one number, and which number wins is the whole
 * argument of the badge. A training node that showed "8 000 rows" instead of
 * "AUC 0.87" would be technically correct and useless.
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { FLOW_EN, FLOW_FR } from '@app/core/i18n/flow.dict';
import { MODELS_EN, MODELS_FR } from '@app/core/i18n/models.dict';
import {
  formatDuration,
  formatMetricValue,
  metricLabelKey,
  modelChip,
  nodeRunBadge,
  readNodeRunData,
  readNodeRunSummary,
  type NodeRunSummary,
} from './flow-node-run.vm';

function source(name: string): string {
  return readFileSync(
    join(process.cwd(), 'src/app/features/orchestration/flow', name),
    'utf8',
  );
}

function assertFlowKey(key: string): void {
  assert.ok((FLOW_FR as Record<string, string>)[key]?.trim(), `${key} has FR copy`);
  assert.ok((FLOW_EN as Record<string, string>)[key]?.trim(), `${key} has EN copy`);
}

function summary(patch: Partial<NodeRunSummary> = {}): NodeRunSummary {
  return { nodeId: 'n1', status: 'completed', ...patch };
}

// ---------------------------------------------------------------------------
// Reading the frame
// ---------------------------------------------------------------------------

test('a node_end frame becomes a run summary, badge block included', () => {
  const read = readNodeRunSummary({
    kind: 'node_end',
    node_id: 'clean',
    node_kind: 'task',
    status: 'completed',
    skill_slug: 'sql_transform_v1',
    latency_ms: 142.4,
    data: { rows_in: 8412, rows_out: 6903 },
  });

  assert.deepEqual(read, {
    nodeId: 'clean',
    status: 'completed',
    latencyMs: 142.4,
    skillSlug: 'sql_transform_v1',
    data: { rows_in: 8412, rows_out: 6903 },
  });
});

test('a frame without a node id names nothing and is dropped', () => {
  assert.equal(readNodeRunSummary({ kind: 'run_end', status: 'completed' }), null);
  assert.equal(readNodeRunSummary(null), null);
  assert.equal(readNodeRunSummary('node_end'), null);
});

test('a settled node with no status reads as completed', () => {
  assert.equal(readNodeRunSummary({ node_id: 'n1' })?.status, 'completed');
});

test('the badge block refuses values it cannot render', () => {
  const data = readNodeRunData({
    rows_in: 'many',
    rows_out: 12,
    metric: { key: '', value: 0.9 },
    model: { slug: '  ', version: 3 },
    model_id: '   ',
  });

  assert.deepEqual(data, { rows_out: 12 });
});

test('a badge block with nothing usable in it is absent, not empty', () => {
  assert.equal(readNodeRunData({ metric: { key: 'roc_auc' } }), undefined);
  assert.equal(readNodeRunData('rows'), undefined);
});

// ---------------------------------------------------------------------------
// Which figure wins
// ---------------------------------------------------------------------------

test('a metric outranks every row count on the same node', () => {
  const badge = nodeRunBadge(
    summary({
      latencyMs: 4200,
      data: {
        rows_in: 8000,
        rows_out: 8000,
        metric: { key: 'roc_auc', value: 0.8713 },
      },
    }),
  );

  assert.equal(badge?.kind, 'metric');
  assert.equal(badge?.key, 'flow.node.run.metric');
  assert.equal(badge?.params['metric'], 'roc_auc', 'the label is resolved at render');
  assert.equal(badge?.params['value'], '0.871');
  assert.equal(badge?.duration, '4.2 s', 'the time it took rides along');
});

test('a transform badge reads as a transition, not as two numbers', () => {
  const badge = nodeRunBadge(summary({ data: { rows_in: 8412, rows_out: 6903 } }));

  assert.equal(badge?.kind, 'rows_delta');
  assert.equal(badge?.params['from'], '8,412');
  assert.equal(badge?.params['to'], '6,903');
});

test('a node that only produced rows shows the count it wrote', () => {
  assert.equal(nodeRunBadge(summary({ data: { rows_out: 6903 } }))?.kind, 'rows');
  assert.equal(
    nodeRunBadge(summary({ data: { rows_out: 6903 } }))?.params['rows'],
    '6,903',
  );
  // Only an input count: a node that consumed a dataset without writing one.
  assert.equal(
    nodeRunBadge(summary({ data: { rows_in: 40 } }))?.params['rows'],
    '40',
  );
});

test('a single-record prediction counts its answers', () => {
  const badge = nodeRunBadge(
    summary({ data: { predictions: 1, model: { slug: 'churn-risk', version: 3 } } }),
  );

  assert.equal(badge?.kind, 'predictions');
  assert.equal(badge?.params['count'], 1);
  assert.equal(badge?.model, 'churn-risk v3', 'provenance is a second chip');
});

test('a node with no data still says how long it took', () => {
  const badge = nodeRunBadge(summary({ latencyMs: 87 }));

  assert.equal(badge?.kind, 'duration');
  assert.equal(badge?.params['duration'], '87 ms');
});

test('a node that produced neither a figure nor a duration gets no badge', () => {
  assert.equal(nodeRunBadge(summary()), null);
  assert.equal(nodeRunBadge(null), null);
});

test('a running node shows no figure, so the pulse is not contradicted', () => {
  assert.equal(
    nodeRunBadge(summary({ status: 'running', data: { rows_out: 10 } })),
    null,
  );
  assert.equal(
    nodeRunBadge(summary({ status: 'pending', latencyMs: 10 })),
    null,
  );
});

test('a failed node keeps its figure and is flagged as failed', () => {
  const badge = nodeRunBadge(
    summary({ status: 'failed', latencyMs: 300, data: { rows_in: 8412 } }),
  );

  assert.equal(badge?.failed, true);
  assert.equal(badge?.kind, 'rows');
});

// ---------------------------------------------------------------------------
// How the figures read
// ---------------------------------------------------------------------------

test('a score keeps the decimals that distinguish two models', () => {
  assert.equal(formatMetricValue(0.8713), '0.871');
  assert.equal(formatMetricValue(0.87), '0.87');
  assert.equal(formatMetricValue(0.9), '0.90', 'a trailing zero is information');
});

test('a metric on the target scale is read as a quantity, not as a score', () => {
  assert.equal(formatMetricValue(12.4567), '12.46');
  assert.equal(formatMetricValue(1284.6, 'en-US'), '1,285');
});

test('a duration never asks the reader to count zeros', () => {
  assert.equal(formatDuration(142.4), '142 ms');
  assert.equal(formatDuration(4200), '4.2 s');
  assert.equal(formatDuration(41_000), '41 s');
  assert.equal(formatDuration(185_000), '3 min 5 s');
});

test('a model chip names its version, and survives not having one', () => {
  assert.equal(modelChip({ slug: 'churn-risk', version: 3 }), 'churn-risk v3');
  assert.equal(modelChip({ slug: 'churn-risk' }), 'churn-risk');
  assert.equal(modelChip(undefined), undefined);
});

test('a metric name resolves through the dictionary the model card uses', () => {
  const key = metricLabelKey('roc_auc');
  assert.equal(key, 'models.metric.roc_auc');
  assert.equal((MODELS_FR as Record<string, string>)[key], 'AUC');
  assert.ok((MODELS_EN as Record<string, string>)[key]?.trim());
});

// ---------------------------------------------------------------------------
// The wiring: the service records it, the card renders it
// ---------------------------------------------------------------------------

test('every key a run badge names has FR and EN copy', () => {
  for (const key of [
    'flow.node.run.rows_delta',
    'flow.node.run.rows',
    'flow.node.run.predictions',
    'flow.node.run.metric',
    'flow.node.run.duration',
    'flow.node.run.model',
  ]) {
    assertFlowKey(key);
  }
});

test('the run service records a node_end and clears the node on node_start', () => {
  const service = source('flow-run.service.ts');
  assert.match(service, /readNodeRunSummary/, 'frames are read through the vm');
  assert.match(service, /recordNodeRun\(event\.data\)/, 'node_end is recorded');
  assert.match(
    service,
    /forgetNodeRun\(data\.node_id\)/,
    'a node that starts again drops its previous figure',
  );
  assert.match(service, /nodeRunFor\(/, 'the card reads one node, not the whole map');
});

test('a new run and a workspace switch both invalidate every figure', () => {
  const service = source('flow-run.service.ts');
  const resets = service.match(/_nodeRuns\.set\(\{\}\)/g) ?? [];
  assert.ok(
    resets.length >= 2,
    'the dispatch and the workspace reset each clear the map',
  );
});

test('the node card renders the badge it is given, and only then', () => {
  const card = source('flow-node.component.ts');
  assert.match(card, /data-testid="node-run-badge"/);
  assert.match(card, /@if \(runBadge\(\); as run\)/, 'no badge, no row');
  assert.match(card, /i18n\.t\(run\.key, badgeParams\(run\)\)/, 'the figure is a sentence');
  assert.match(card, /run\.model/, 'the model that answered is shown');
  assert.match(
    card,
    /run\.duration && run\.kind !== 'duration'/,
    'the duration is not printed twice',
  );
  const styles = source('flow-node.component.scss');
  assert.match(styles, /\.ck-flow-node__run-figure/, 'the figure has a chip of its own');
  assert.match(
    styles,
    /prefers-reduced-motion/,
    'the badge entrance respects the motion preference',
  );
});

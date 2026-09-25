import assert from 'node:assert/strict';
import { test } from 'node:test';
import { recordedTimeline } from '../observability/observability-chart.vm';
import {
  arrivalProvenanceLabel,
  arrivalProvenanceState,
  readArrivalProvenance,
} from './arrival-provenance';
import {
  longestTimelineRowIndex,
  traceStepSummary,
} from './run-trace.vm';

test('trace cascade builds from skill_invocations and marks the longest step', () => {
  const invocations = [
    {
      id: 'inv-short',
      skill_slug: 'short-skill',
      started_at: '2026-09-15T10:00:00Z',
      completed_at: '2026-09-15T10:00:02Z',
      status: 'completed' as const,
    },
    {
      id: 'inv-long',
      skill_slug: 'long-skill',
      started_at: '2026-09-15T10:00:00Z',
      completed_at: '2026-09-15T10:00:05Z',
      status: 'completed' as const,
    },
  ];
  const timeline = recordedTimeline(invocations);
  assert.equal(timeline.rows.length, 2);
  assert.equal(longestTimelineRowIndex(timeline.rows), 1);

  const summary = traceStepSummary({
    duration_ms: 5000,
    skill_invocations: invocations,
  });
  assert.equal(summary.longestLabel, 'long-skill');
  assert.equal(summary.longestMs, 5000);
  assert.equal(summary.longestInvocationId, 'inv-long');
});

test('opening a skill from the trace carries Depuis la trace {id} provenance', () => {
  const state = arrivalProvenanceState({
    kind: 'trace',
    traceId: 'run-abcdef123456',
    backUrl: '/runs/run-abcdef123456?facet=trace',
  });
  const provenance = readArrivalProvenance(state);
  assert.ok(provenance);
  const label = arrivalProvenanceLabel(provenance, (key, params) => {
    if (key === 'runs.provenance.from_trace') {
      return `Depuis la trace ${params?.['id']}`;
    }
    if (key === 'nav.provenance.chip') {
      return `↰ ${params?.['from']} · Revenir`;
    }
    return key;
  });
  assert.equal(label, '↰ Depuis la trace run-abcdef12 · Revenir');
});

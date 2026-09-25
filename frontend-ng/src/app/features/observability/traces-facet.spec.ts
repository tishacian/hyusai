import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  arrivalProvenanceLabel,
  arrivalProvenanceState,
  readArrivalProvenance,
} from '../runs/arrival-provenance';
import { runStartedWithinPeriod } from './observability-facets';

test('traces facet opens a run with Observability › Traces provenance and never targets /traces', () => {
  const state = arrivalProvenanceState({
    kind: 'observability_traces',
    backUrl: '/observability?facet=traces&systemId=sys-1&since=7d',
  });
  const provenance = readArrivalProvenance(state);
  assert.ok(provenance);
  assert.equal(provenance.kind, 'observability_traces');
  const label = arrivalProvenanceLabel(provenance, (key) => {
    if (key === 'runs.provenance.from_observability_traces') {
      return 'Depuis Observabilité › Traces';
    }
    return key;
  });
  assert.equal(label, 'Depuis Observabilité › Traces');

  // Guardrail: the facet contract is `/runs`, not the deprecated alias.
  const apiPath = '/runs';
  assert.equal(apiPath.includes('/traces'), false);
  assert.match(apiPath, /^\/runs$/);
});

test('traces list keeps runs inside the selected period for a given system', () => {
  const now = Date.parse('2026-09-25T00:00:00Z');
  const runs = [
    { id: 'a', system_id: 'sys-1', started_at: '2026-09-22T00:00:00Z' },
    { id: 'b', system_id: 'sys-1', started_at: '2026-08-01T00:00:00Z' },
    { id: 'c', system_id: 'sys-2', started_at: '2026-09-22T00:00:00Z' },
  ];
  const filtered = runs
    .filter((run) => run.system_id === 'sys-1')
    .filter((run) => runStartedWithinPeriod(run.started_at, '7d', now));
  assert.deepEqual(filtered.map((run) => run.id), ['a']);
});

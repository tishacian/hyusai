import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  OBSERVABILITY_FACETS, resolveObservabilityFacet, observabilityAnchor, periodCutoffMs,
  isObservabilityFacet,
  normalizeObservabilityFacet,
  observabilitySystemId,
  runStartedWithinPeriod,
} from './observability-facets';
import { OBSERVABILITY_FR } from '../../core/i18n/observability.dict';

test('observability exposes five facets including traces', () => {
  assert.deepEqual([...OBSERVABILITY_FACETS], [
    'operations',
    'activities',
    'quality',
    'performance',
    'traces',
  ]);
  assert.equal(isObservabilityFacet('traces'), true);
  assert.equal(normalizeObservabilityFacet(null), 'operations');
  assert.equal(normalizeObservabilityFacet('bogus'), 'operations');
  assert.ok(OBSERVABILITY_FR['observability.tabs.traces']);
  assert.ok(OBSERVABILITY_FR['observability.tabs.operations']);
});

test('systemId wins over legacy system_id', () => {
  const params = new Map([
    ['systemId', 'sys-a'],
    ['system_id', 'sys-legacy'],
  ]);
  assert.equal(
    observabilitySystemId({ get: (name) => params.get(name) ?? null }),
    'sys-a',
  );
  assert.equal(
    observabilitySystemId({ get: (name) => (name === 'system_id' ? 'legacy' : null) }),
    'legacy',
  );
});

test('period filter keeps only runs started inside the window', () => {
  const now = Date.parse('2026-09-25T12:00:00Z');
  assert.equal(
    runStartedWithinPeriod('2026-09-20T12:00:00Z', '7d', now),
    true,
  );
  assert.equal(
    runStartedWithinPeriod('2026-09-01T12:00:00Z', '7d', now),
    false,
  );
  assert.equal(
    runStartedWithinPeriod('2026-09-01T12:00:00Z', '30d', now),
    true,
  );
  assert.equal(runStartedWithinPeriod(undefined, '7d', now), false);
});

test('legacy links normalize without replacing an explicit quality/traces selection', () => {
 const facet=(query:Record<string,string>)=>resolveObservabilityFacet({get:key=>query[key]??null});
 assert.equal(facet({activityId:'a'}),'activities'); assert.equal(facet({facet:'operations',activityId:'a'}),'activities');
 assert.equal(facet({scope:'platform'}),'activities'); assert.equal(facet({facet:'operations',scope:'platform'}),'operations');
 for(const explicit of ['quality','performance','traces'])assert.equal(facet({facet:explicit,activityId:'a'}),explicit);
});
test('24h period uses a fixed upper bound across facets and excludes future work', () => {
 const now=Date.parse('2026-10-16T12:00:00Z'); assert.equal(periodCutoffMs('24h',now),now-86400000);
 assert.equal(observabilityAnchor('2026-10-16T12:00:00Z'),'2026-10-16T12:00:00.000Z');
 assert.equal(runStartedWithinPeriod('2026-10-15T12:00:00Z','24h',now),true);
 assert.equal(runStartedWithinPeriod('2026-10-16T12:00:00Z','24h',now),false);
});

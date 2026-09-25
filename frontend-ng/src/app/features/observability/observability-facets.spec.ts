import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  OBSERVABILITY_FACETS,
  isObservabilityFacet,
  normalizeObservabilityFacet,
  observabilitySystemId,
  runStartedWithinPeriod,
} from './observability-facets';
import { OBSERVABILITY_FR } from '../../core/i18n/observability.dict';

test('observability exposes four facets including traces', () => {
  assert.deepEqual([...OBSERVABILITY_FACETS], [
    'operations',
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

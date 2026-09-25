import assert from 'node:assert/strict';
import { test } from 'node:test';
import { observabilityFacetRedirectUrl } from './observability-facet-redirect';

test('traces redirect keeps systemId and since when building the facet URL', () => {
  assert.deepEqual(
    observabilityFacetRedirectUrl('traces', { systemId: 'X', since: '7d' }),
    {
      path: '/observability',
      queryParams: { facet: 'traces', systemId: 'X', since: '7d' },
    },
  );
});

test('quality redirect targets facet=quality', () => {
  assert.deepEqual(
    observabilityFacetRedirectUrl('quality', { system_id: 's1' }),
    {
      path: '/observability',
      queryParams: { facet: 'quality', system_id: 's1' },
    },
  );
});

test('performance redirect targets facet=performance', () => {
  assert.equal(
    observabilityFacetRedirectUrl('performance', {}).queryParams['facet'],
    'performance',
  );
});

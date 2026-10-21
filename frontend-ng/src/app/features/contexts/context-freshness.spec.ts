import test from 'node:test';
import assert from 'node:assert/strict';
import { contextFreshness } from './context-freshness';

const now = Date.parse('2026-10-21T00:00:00Z');
test('recent edits never become old from their version number', () => {
  assert.equal(contextFreshness({ updated_at: '2026-10-20T00:00:00Z' }, now), 'recent');
});
test('an old source remains old after a recent context edit', () => {
  assert.equal(contextFreshness({ updated_at: '2026-10-20T00:00:00Z', source_dates: [{ ref: 'manual', updated_at: '2026-01-01T00:00:00Z' }] }, now), 'old');
});
test('undated, invalid or future timestamps never establish freshness', () => {
  for (const date of [null, 'not-a-date', '2027-01-01']) {
    assert.equal(contextFreshness({ updated_at: date }, now), 'unknown');
  }
  assert.equal(contextFreshness({ updated_at: '2026-10-20', source_dates: [{ ref: 'manual', updated_at: null }] }, now), 'unknown');
});
test('90 days is a strict boundary', () => {
  assert.equal(contextFreshness({ updated_at: new Date(now - 90 * 86_400_000).toISOString() }, now), 'recent');
  assert.equal(contextFreshness({ updated_at: new Date(now - 90 * 86_400_000 - 1).toISOString() }, now), 'old');
});

test('referenced sources absent from the response remain unknown', () => {
  assert.equal(contextFreshness({ updated_at: '2026-10-20', data_refs: ['manual'] }, now), 'unknown');
  assert.equal(contextFreshness({ updated_at: '2026-10-20', data_refs: ['manual'], source_dates: [] }, now), 'unknown');
});

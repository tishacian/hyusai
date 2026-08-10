import assert from 'node:assert/strict';
import { test } from 'node:test';
import { MAX_YIELD_RATIO, formatYieldIndex, formatYieldPercent } from './yield-format';

test('renders yields below the ceiling exactly as measured', () => {
  assert.equal(formatYieldPercent(0), '0%');
  assert.equal(formatYieldPercent(0.5), '50%');
  assert.equal(formatYieldPercent(1.5), '150%');
  assert.equal(formatYieldPercent(-0.4), '-40%');
  assert.equal(formatYieldIndex(0), '0.00');
  assert.equal(formatYieldIndex(0.85), '0.85');
  assert.equal(formatYieldIndex(3.125), '3.13');
});

test('keeps the ceiling itself in full and bounds everything above it', () => {
  assert.equal(MAX_YIELD_RATIO, 10);
  assert.equal(formatYieldPercent(MAX_YIELD_RATIO), '1000%');
  assert.equal(formatYieldIndex(MAX_YIELD_RATIO), '10.00');
  assert.equal(formatYieldPercent(10.01), '> 1000%');
  assert.equal(formatYieldIndex(10.01), '> 10.00');
});

test('renders a missing or unusable measurement as an em dash', () => {
  assert.equal(formatYieldPercent(null), '—');
  assert.equal(formatYieldPercent(undefined), '—');
  assert.equal(formatYieldIndex(null), '—');
  assert.equal(formatYieldIndex(undefined), '—');
  assert.equal(formatYieldPercent(Number.NaN), '—');
  assert.equal(formatYieldIndex(Number.POSITIVE_INFINITY), '—');
});

test('bounds the ratios observed in production instead of printing them', () => {
  // Run outcome on the NAWA reconciliation System: $1.50 of value over a
  // sub-cent cost, stored as an efficiency ratio, printed as "EFFICIENCY
  // 1303293%" before the ceiling existed.
  assert.equal(formatYieldPercent(13032.93), '> 1000%');
  assert.notEqual(formatYieldPercent(13032.93), '1303293%');
  assert.equal(formatYieldPercent(13394.33), '> 1000%');

  // Hypervisor balance sheet and CAPABILITIES row: arithmetically exact, still
  // unreadable at four digits.
  assert.equal(formatYieldPercent(62.77), '> 1000%');
  assert.notEqual(formatYieldPercent(62.77), '6277%');
  assert.equal(formatYieldPercent(63.82), '> 1000%');
  assert.equal(formatYieldIndex(992.4), '> 10.00');
  assert.equal(formatYieldIndex(1001.18), '> 10.00');
});

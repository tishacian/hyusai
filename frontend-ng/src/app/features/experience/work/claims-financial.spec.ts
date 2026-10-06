import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import { claimsFinancialProjection } from './claims-financial';

const approved = { manualMinutes: 8, assistedMinutes: 2, hourlyEur: 40, budgetEur: 0.5, volume: 1000 };

test('approved demo assumptions yield €3.50 per case and 700% projected ROI', () => {
  assert.deepEqual(claimsFinancialProjection(approved), {
    savedMinutes: 6, capacityEur: 4, netEur: 3.5, roi: 7,
    breakEvenSavedMinutes: 0.75, monthlyNetEur: 3500,
  });
});

test('a longer assisted treatment preserves negative benefit and ROI', () => {
  const value = claimsFinancialProjection({ ...approved, assistedMinutes: 11 })!;
  assert.equal(value.netEur, -2.5);
  assert.equal(value.roi, -5);
});

test('zero budget leaves ROI unknown; zero hourly rate leaves the threshold unknown', () => {
  assert.equal(claimsFinancialProjection({ ...approved, budgetEur: 0 })!.roi, null);
  assert.equal(claimsFinancialProjection({ ...approved, hourlyEur: 0 })!.breakEvenSavedMinutes, null);
});

test('empty, non-finite, negative and fractional-volume inputs never become a projection', () => {
  for (const value of [null, undefined, NaN, Infinity, -1]) {
    assert.equal(claimsFinancialProjection({ ...approved, budgetEur: value as number }), null);
  }
  assert.equal(claimsFinancialProjection({ ...approved, volume: 1.5 }), null);
});

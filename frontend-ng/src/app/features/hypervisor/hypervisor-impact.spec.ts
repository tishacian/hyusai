import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  formatHypervisorImpact,
  measuredCapabilityCount,
  measuredImpactDelta,
} from './hypervisor-impact';

test('computes a delta only when both measurements are present', () => {
  assert.equal(measuredImpactDelta(12, 10), 2);
  assert.equal(measuredImpactDelta(0, 0), 0);
  assert.equal(measuredImpactDelta(null, 10), null);
  assert.equal(measuredImpactDelta(12, null), null);
  assert.equal(measuredImpactDelta(undefined, 10), null);
  assert.equal(measuredImpactDelta(12, undefined), null);
});

test('counts capabilities independently from any Run aggregate', () => {
  assert.equal(measuredCapabilityCount(2, 3), 3);
  assert.equal(measuredCapabilityCount(4, 1), 4);
  assert.equal(measuredCapabilityCount(0, null), 0);
});

test('formats numeric impact values without changing the historical display', () => {
  assert.equal(formatHypervisorImpact(1250), '$1.3k');
  assert.equal(formatHypervisorImpact(-1250), '$-1.3k');
  assert.equal(formatHypervisorImpact(0.25), '25%');
  assert.equal(formatHypervisorImpact(0), '0.00');
  assert.equal(formatHypervisorImpact('4'), '4.00');
});

test('renders descriptive impact values and rejects values that cannot be displayed', () => {
  assert.equal(
    formatHypervisorImpact('increase_budget_and_enable_runtime_monitoring'),
    'increase budget and enable runtime monitoring',
  );
  assert.equal(formatHypervisorImpact(null), '—');
  assert.equal(formatHypervisorImpact(Number.NaN), '—');
  assert.equal(formatHypervisorImpact(Number.POSITIVE_INFINITY), '—');
  assert.equal(formatHypervisorImpact({}), '—');
  assert.equal(formatHypervisorImpact(false), '—');
  assert.equal(formatHypervisorImpact('  '), '—');
});

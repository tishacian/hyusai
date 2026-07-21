import assert from 'node:assert/strict';
import { test } from 'node:test';
import { formatHypervisorImpact } from './hypervisor-impact';

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

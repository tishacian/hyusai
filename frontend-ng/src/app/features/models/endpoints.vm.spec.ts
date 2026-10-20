import { strict as assert } from 'node:assert';
import { test } from 'node:test';
import { readFileSync } from 'node:fs';
import { latencyUpperBound, measuredCost, UsageWindow } from './endpoints.vm';

test('unknown measured cost stays unknown even when a tariff exists', () => {
  assert.deepEqual(measuredCost({measured_cost_per_1000_rows_usd: null, tariff_cost_usd: 3, unknown_cost_requests: 4} as UsageWindow), {value: null, partial: true});
});
test('measured zero is distinct from missing data', () => {
  assert.deepEqual(measuredCost({measured_cost_per_1000_rows_usd: 0, unknown_cost_requests: 0} as UsageWindow), {value: 0, partial: false});
});
test('latency never implies exact percentile or treats unknown as zero', () => {
  assert.equal(latencyUpperBound(null), '—');
  assert.equal(latencyUpperBound(20), '≤ 20 ms');
});
test('scope, async stale response guard and secret references are exposed', () => {
  const source = readFileSync('src/app/features/models/endpoints.component.ts', 'utf8');
  assert.match(source, /generation !== this.generation/);
  assert.match(source, /scope === 'system'/);
  assert.match(source, /scope === 'platform'/);
  assert.match(source, /webhook_url_ref:/);
  assert.match(source, /signing_key_ref:/);
  assert.doesNotMatch(source, /innerHTML/);
});
test('dedicated route precedes dynamic model id', () => {
  const source = readFileSync('src/app/features/models/models.routes.ts', 'utf8');
  assert.ok(source.indexOf("path: 'endpoints'") < source.indexOf("path: ':modelId'"));
});

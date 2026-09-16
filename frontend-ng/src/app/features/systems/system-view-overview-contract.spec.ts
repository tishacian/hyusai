import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import test from 'node:test';

const source = readFileSync(
  join(process.cwd(), 'src/app/features/systems/system-view.component.ts'),
  'utf8',
);

test('System Overview has one canonical implementation', () => {
  assert.match(source, /<app-system-overview\b/);
  assert.doesNotMatch(source, /canonicalOverviewEnabled/);
  assert.doesNotMatch(source, /<ck-stat-readout\b/);
  assert.doesNotMatch(source, /<app-system-value-loop\b/);
});

test('System view does not fetch workspace-wide metrics for object-level claims', () => {
  for (const legacySymbol of [
    'kpiRequests',
    'kpiErrors',
    'kpiErrorRate',
    'kpiQuality',
    'kpiTraces',
    'kpiLatency',
    'loadKpis',
    'hasCollections',
    'completedSteps',
  ]) {
    assert.doesNotMatch(source, new RegExp(`\\b${legacySymbol}\\b`));
  }

  assert.doesNotMatch(source, /['"]\/metrics/);
  assert.doesNotMatch(source, /['"]\/traces/);
});

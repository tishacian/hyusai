import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { MandateEvent } from '@app/features/mandate/mandate.models';
import { MANDATE_SYSTEM_EN, MANDATE_SYSTEM_FR } from '@app/core/i18n/mandate-system.dict';
import { mandateCoverageCell, mandateCoverageCounts, mandateFacetEvents, type MandateCoverageRun } from './system-mandate-coverage.vm';

const run = (facets: MandateCoverageRun['facets'] = {}): MandateCoverageRun => ({
  run_id: 'run-1', status: 'completed', started_at: null, evidence_state: 'not_recorded', event_count: 0, facets,
});

test('mandate coverage counts only recorded facet events, never a configured or completed Run', () => {
  assert.deepEqual(mandateCoverageCounts([run()]), {total: 5, recorded: 0, missing: 5});
  assert.deepEqual(mandateCoverageCell(run({inbound: {state: 'recorded', event_count: 0, breach_count: 0}}), 'inbound'), {state: 'not_recorded', count: 0});
  assert.deepEqual(mandateCoverageCell(run({valves: {state: 'recorded', event_count: NaN, breach_count: 0}}), 'valves'), {state: 'not_recorded', count: 0});
});

test('a reported breach is distinguished from a successful check or a proven runtime stop', () => {
  const r = run({
    inbound: {state: 'recorded', event_count: 2, breach_count: 0},
    valves: {state: 'breached', event_count: 1, breach_count: 1},
  });
  assert.deepEqual(mandateCoverageCell(r, 'valves'), {state: 'breached', count: 1});
  assert.deepEqual(mandateCoverageCounts([r]), {total: 5, recorded: 2, missing: 3});
  assert.equal(MANDATE_SYSTEM_EN['mandate_system.breached'], 'Limit reported');
});

test('the selected facet filters actual evidence without folding a human approval into a gate', () => {
  const events = [
    {id: 'decision', facet: 'human', status: 'approved'},
    {id: 'gate', facet: 'outbound', status: 'awaiting_human'},
    {id: 'limit', facet: 'valves', status: 'observed'},
    {id: 'delegation', facet: 'delegation', status: 'recorded'},
  ] as MandateEvent[];
  assert.deepEqual(mandateFacetEvents(events, 'outbound').map(e => e.id), ['gate']);
  assert.deepEqual(mandateFacetEvents(events, 'inbound'), []);
  assert.deepEqual(mandateFacetEvents(events, 'capabilities').map(e => e.id), ['delegation']);
  assert.equal(mandateFacetEvents(events, null), events);
});

test('governance FR and EN keys and placeholders stay aligned', () => {
  assert.deepEqual(Object.keys(MANDATE_SYSTEM_FR).sort(), Object.keys(MANDATE_SYSTEM_EN).sort());
  for (const [key, fr] of Object.entries(MANDATE_SYSTEM_FR)) {
    assert.deepEqual(fr.match(/\{[^}]+\}/g)?.sort(), MANDATE_SYSTEM_EN[key as keyof typeof MANDATE_SYSTEM_EN].match(/\{[^}]+\}/g)?.sort(), key);
  }
});

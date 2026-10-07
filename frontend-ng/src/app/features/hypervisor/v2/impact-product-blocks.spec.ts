import assert from 'node:assert/strict';
import { test } from 'node:test';
import { activityMetrics, financialScenario, scopedSeries, summarySections } from './impact-product-blocks';
import { cloneView, DEFAULT_HYPERVISOR_VIEWS, moveStratumBlock, parseViewsPayload, serializeViewsForWrite } from './hypervisor-v2-views';

const scenario = { manual_minutes: 12, assisted_minutes: 3, hourly_cost: 30, unit_budget: 1, currency: 'GBP' };
test('generic financial assumptions are incomplete until explicitly configured; monthly volume is optional', () => {
  assert.equal(financialScenario({}), null);
  assert.deepEqual(financialScenario(scenario), { currency: 'GBP', savedMinutes: 9, capacity: 4.5, net: 3.5, roi: 3.5, breakEvenMinutes: 2, monthlyNet: null });
  assert.equal(financialScenario({ ...scenario, monthly_volume: 100 })?.monthlyNet, 350);
  assert.equal(financialScenario({ ...scenario, monthly_volume: 0 })?.monthlyNet, 0);
});
test('negative projections and real zero rates survive; invalid or absent assumptions do not become zero', () => {
  assert.equal(financialScenario({ ...scenario, assisted_minutes: 18 })?.net, -4);
  assert.equal(financialScenario({ ...scenario, unit_budget: 0 })?.roi, null);
  assert.equal(financialScenario({ ...scenario, hourly_cost: 0 })?.breakEvenMinutes, null);
  for (const invalid of [null, '', NaN, Infinity, -1, 1441]) assert.equal(financialScenario({ ...scenario, manual_minutes: invalid }), null);
  assert.equal(financialScenario({ ...scenario, currency: '' }), null);
  assert.equal(financialScenario({ ...scenario, monthly_volume: 1.5 }), null);
});
test('saved block order, System scope, metrics, assumptions and seven-day period round trip without a domain identity', () => {
  const view = cloneView(DEFAULT_HYPERVISOR_VIEWS[0]!);
  view.system_id = 'inventory'; view.period = '7d';
  view.strata.comprendre = [{ type: 'activity', title: 'Inventory activity', settings: { metrics: ['costs'] } }, { type: 'financial_scenario', settings: scenario }, ...view.strata.comprendre];
  const reordered = moveStratumBlock(view, 'comprendre', 'financial_scenario', -1);
  const saved = parseViewsPayload({ views: serializeViewsForWrite([reordered]), default_view_id: view.id }).views[0]!;
  assert.equal(saved.system_id, 'inventory'); assert.equal(saved.period, '7d');
  assert.deepEqual(summarySections(saved).slice(0, 2), ['financial_scenario', 'activity']);
  assert.deepEqual(activityMetrics(saved.strata.comprendre[1]!), ['costs']);
  assert.deepEqual(saved.strata.comprendre[0]?.settings, scenario);
});
test('scope affects all chart rows and never falls back to the portfolio when the selected System is absent', () => {
  const raw = { window: '7d' as const, from: '2026-10-01', to: '2026-10-07', systems: [{ system_id: 'inventory' }, { system_id: 'support' }] };
  const view = { ...DEFAULT_HYPERVISOR_VIEWS[0]!, system_id: 'inventory' };
  const typed = raw as Parameters<typeof scopedSeries>[0];
  assert.deepEqual(scopedSeries(typed, view).systems.map(system => system.system_id), ['inventory']);
  assert.equal(scopedSeries(typed, { ...view, system_id: 'missing' }).systems.length, 0);
  assert.equal(raw.systems.length, 2);
  assert.equal(scopedSeries(typed, null), typed);
});

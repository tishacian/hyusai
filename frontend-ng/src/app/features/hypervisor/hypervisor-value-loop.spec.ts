import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { PortfolioValueLoop } from '@app/core/canonical-api.service';
import { summarizePortfolioValueLoop } from './hypervisor-value-loop';

function payload(): PortfolioValueLoop {
  const fact = <T>(value: T, sampleCount: number) => ({
    state: 'available' as const,
    value,
    source: 'persisted-test-source',
    sample_count: sampleCount,
  });
  return {
    schema_version: 1,
    scope: 'portfolio',
    state: 'available',
    systems: [{
      system_id: 'system-1',
      capability_id: 'capability-1',
      name: 'System 1',
      scenario_count: 1,
      open_count: 0,
      measured_count: 1,
      scenario_state: 'available',
      actuator_state: 'available',
    }],
    status_counts: { measured: 1 },
    observed_value_delta: fact(12, 1),
    outcomes: {
      state: 'available',
      observed_value_delta: fact(12, 1),
      measured_scenarios: fact(1, 1),
      forecast_verdict_counts: fact({ confirmed: 1 }, 1),
    },
    risks: { state: 'available', count: 0, items: [], source: 'persisted-risk-source' },
    arbitrations: {
      state: 'available',
      source: 'decisions',
      items: [{
        id: 'decision-1',
        scenario_id: 'scenario-1',
        system_id: 'system-1',
        status: 'applied',
        title: 'Decision',
        created_at: '2026-07-22T00:00:00Z',
      }],
    },
    scenarios: {
      state: 'available',
      source: 'value_scenarios',
      items: [{
        id: 'scenario-1',
        system_id: 'system-1',
        capability_id: 'capability-1',
        status: 'measured',
        objective: 'Improve value',
        created_at: '2026-07-22T00:00:00Z',
        decision: { id: 'decision-1', status: 'applied', title: 'Decision' },
        decision_state: 'available',
        outcome: {
          state: 'available',
          measurement_id: 'measurement-1',
          delta: { value: 12 },
          forecast_delta: { value: 2 },
          assumption_verdict: 'confirmed',
        },
      }],
    },
    simulation_is_measurement: false,
  };
}

test('portfolio value-loop summary preserves real zero risk and measured outcome', () => {
  assert.deepEqual(summarizePortfolioValueLoop(payload()), {
    state: 'available',
    outcomeState: 'available',
    observedValueDelta: 12,
    riskState: 'available',
    riskCount: 0,
    arbitrationState: 'available',
    arbitrationCount: 1,
    scenarioState: 'available',
    scenarioCount: 1,
    unconfiguredActuators: 0,
  });
});

test('portfolio value-loop summary never turns missing or unconfigured evidence into zero', () => {
  assert.equal(summarizePortfolioValueLoop(null).state, 'unavailable');
  assert.equal(summarizePortfolioValueLoop(null).scenarioCount, null);

  const notConfigured = payload();
  notConfigured.state = 'not_configured';
  notConfigured.systems = [];
  assert.equal(summarizePortfolioValueLoop(notConfigured).riskCount, null);

  const notMeasured = payload();
  notMeasured.outcomes.state = 'not_measured';
  notMeasured.outcomes.observed_value_delta = {
    state: 'not_measured',
    value: null,
    source: 'value_measurements.delta.value',
    sample_count: 0,
  };
  assert.equal(summarizePortfolioValueLoop(notMeasured).observedValueDelta, null);

  const drifted = payload();
  drifted.systems[0].actuator_state = 'not_configured';
  assert.equal(summarizePortfolioValueLoop(drifted).unconfiguredActuators, 1);

  const restricted = payload();
  restricted.scenarios = {
    state: 'restricted',
    source: 'value_scenarios',
    items: [],
  };
  restricted.risks = {
    state: 'restricted',
    count: null,
    source: 'value_scenarios.status',
    items: [],
  };
  restricted.arbitrations = {
    state: 'restricted',
    source: 'decisions',
    items: [],
  };
  assert.equal(summarizePortfolioValueLoop(restricted).scenarioState, 'restricted');
  assert.equal(summarizePortfolioValueLoop(restricted).scenarioCount, null);
  assert.equal(summarizePortfolioValueLoop(restricted).riskCount, null);
  assert.equal(summarizePortfolioValueLoop(restricted).arbitrationCount, null);
});

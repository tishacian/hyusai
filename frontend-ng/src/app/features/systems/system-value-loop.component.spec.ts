import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import type {
  Run,
  ValueLoopMeasurement,
  ValueLoopSimulation,
  ValueScenario,
} from '@app/core/canonical-api.service';
import {
  ValueLoopCommandLedger,
  latestValueLoopMeasurement,
  valueLoopBaselineRunIsEligible,
  valueLoopMeasurementLabel,
  valueLoopResponseIsCurrent,
  valueLoopStepRows,
} from './system-value-loop.component';
import {
  systemPerspectiveAuthorizesValueLoop,
  type SystemPerspectiveResponse,
} from './system-perspective.models';

function simulation(): ValueLoopSimulation {
  return {
    id: 'simulation-1',
    scenario_id: 'scenario-1',
    system_id: 'system-a',
    status: 'available',
    evidence_type: 'simulation',
    model: 'system-steering:v1',
    assumptions: {},
    projected_outcome: { value: 110, value_state: 'available' },
    recommended_action: {
      actuator: 'control_policy.guardrails.patch.v1',
      patch: { mandatory_hitl_if_confidence_below: 0.6 },
    },
    provenance: { system_id: 'system-a' },
    confidence: 0.7,
    generated_at: '2026-07-22T10:00:00Z',
  };
}

function baselineRun(
  id: string,
  options: {
    source?: 'auto' | 'operator' | 'unset';
    eligible?: boolean;
    reason?: string | null;
  } = {},
): Run {
  return {
    id,
    system_id: 'system-a',
    status: 'completed',
    outcome: {
      value_estimated: 100,
      value_source: options.source ?? 'auto',
      baseline_eligible: options.eligible,
      baseline_ineligible_reason: options.reason ?? null,
    },
  };
}

function measurement(status: ValueLoopMeasurement['status']): ValueLoopMeasurement {
  return {
    id: `measurement-${status}`,
    scenario_id: 'scenario-1',
    system_id: 'system-a',
    action_execution_id: 'action-1',
    simulation_id: 'simulation-1',
    source_run_id: status === 'measured' ? 'run-after' : null,
    status,
    reason: status === 'not_measured' ? 'no_comparable_post_action_run' : null,
    evidence_type: status === 'measured' ? 'run' : null,
    baseline_outcome: { value: 100, value_source: 'operator' },
    observed_outcome: status === 'measured' ? { value: 112, value_source: 'auto' } : null,
    delta: status === 'measured' ? { value: 12 } : null,
    forecast_delta: status === 'measured' ? { value: 2 } : null,
    assumption_verdict: status === 'measured' ? 'confirmed' : 'not_evaluable',
    assumption_evaluation: {
      schema_version: 1,
      method: 'directional_forecast_v1',
      causality: 'not_established',
    },
    measured_at: '2026-07-22T10:05:00Z',
  };
}

function scenario(
  status: ValueScenario['status'],
  options: { simulated?: boolean; measurement?: ValueLoopMeasurement } = {},
): ValueScenario {
  return {
    id: 'scenario-1',
    workspace_id: 'workspace-a',
    system_id: 'system-a',
    source_run_id: 'run-before',
    status,
    objective: 'Improve measured value',
    baseline_outcome: { value: 100, value_source: 'operator' },
    approved_simulation_id: options.simulated ? 'simulation-1' : null,
    approved_simulation_content_sha256: options.simulated ? 'a'.repeat(64) : null,
    approved_by: null,
    approved_at: null,
    acted_at: null,
    measured_at: status === 'measured' ? '2026-07-22T10:05:00Z' : null,
    created_at: '2026-07-22T09:00:00Z',
    updated_at: '2026-07-22T10:05:00Z',
    decision: null,
    simulations: options.simulated ? [simulation()] : [],
    action: null,
    measurements: options.measurement ? [options.measurement] : [],
  };
}

test('value-loop helpers distinguish simulation, missing measurement and observed evidence', () => {
  const proposed = scenario('decision_proposed');
  assert.equal(valueLoopMeasurementLabel(proposed), 'Baseline outcome');

  const simulated = scenario('simulated', { simulated: true });
  assert.equal(valueLoopMeasurementLabel(simulated), 'Simulation only');

  const missing = scenario('acted', {
    simulated: true,
    measurement: measurement('not_measured'),
  });
  assert.equal(valueLoopMeasurementLabel(missing), 'Not measured');
  assert.equal(latestValueLoopMeasurement(missing)?.reason, 'no_comparable_post_action_run');
  assert.equal(
    valueLoopStepRows(missing).find((step) => step.label === 'Measure')?.complete,
    false,
    'a not_measured record must not falsely close the value loop',
  );

  const measured = scenario('measured', {
    simulated: true,
    measurement: measurement('measured'),
  });
  assert.equal(valueLoopMeasurementLabel(measured), 'Observed evidence');
  assert.equal(valueLoopStepRows(measured).every((step) => step.complete), true);
});

test('value-loop progress advances only through persisted scenario states', () => {
  const expectedCompleted = new Map<ValueScenario['status'], number>([
    ['decision_proposed', 2],
    ['simulated', 3],
    ['approved', 4],
    ['acted', 5],
    ['measured', 6],
  ]);
  for (const [status, count] of expectedCompleted) {
    assert.equal(
      valueLoopStepRows(scenario(status)).filter((step) => step.complete).length,
      count,
      status,
    );
  }
});

test('baseline selector trusts the server eligibility flag and excludes operator, seed and canary runs', () => {
  const runtime = baselineRun('runtime', { eligible: true });
  const operator = baselineRun('operator', {
    source: 'operator',
    eligible: false,
    reason: 'baseline_runtime_provenance_unavailable',
  });
  const seed = baselineRun('seed', {
    eligible: false,
    reason: 'baseline_run_is_synthetic_demo',
  });
  const canary = baselineRun('canary', {
    eligible: false,
    reason: 'baseline_run_is_canary_authored',
  });
  const contradictoryCanary = baselineRun('contradictory-canary', {
    eligible: true,
    reason: 'baseline_run_is_canary_authored',
  });
  const legacyAuto = baselineRun('legacy-auto');

  assert.deepEqual(
    [runtime, operator, seed, canary, contradictoryCanary, legacyAuto]
      .filter(valueLoopBaselineRunIsEligible)
      .map((run) => run.id),
    ['runtime'],
    'missing or false server eligibility must fail closed even when a Run has a measured value',
  );
});

test('late value-loop responses are rejected after a workspace, System or request change', () => {
  assert.equal(valueLoopResponseIsCurrent(4, 4, 'system-a', 'system-a', '7:showcase', '7:showcase'), true);
  assert.equal(valueLoopResponseIsCurrent(4, 5, 'system-a', 'system-a', '7:showcase', '7:showcase'), false);
  assert.equal(valueLoopResponseIsCurrent(4, 4, 'system-a', 'system-b', '7:showcase', '7:showcase'), false);
  assert.equal(valueLoopResponseIsCurrent(4, 4, 'system-a', 'system-a', '7:showcase', '8:other'), false);
});

test('command ledger reuses an idempotency key across retries and rotates after success or context reset', () => {
  let nonce = 0;
  const ledger = new ValueLoopCommandLedger(() => `nonce-${++nonce}`);
  const first = ledger.key('system-a', 'simulate:scenario-1');

  assert.equal(ledger.key('system-a', 'simulate:scenario-1'), first, 'retry must reuse the key');
  ledger.complete('simulate:scenario-1');
  assert.notEqual(ledger.key('system-a', 'simulate:scenario-1'), first, 'success retires the key');

  const beforeReset = ledger.key('system-a', 'act:scenario-1');
  ledger.clear();
  assert.notEqual(ledger.key('system-b', 'act:scenario-1'), beforeReset, 'workspace/System reset clears keys');
});

function authoritativeSteerPerspective(): SystemPerspectiveResponse {
  const fact = (
    key: string,
    source: string,
  ) => ({ key, label: key, state: 'available' as const, value: 'configured', source });
  return {
    schema_version: 1,
    snapshot_id: 'snapshot-current-revision',
    generated_at: '2026-07-22T10:00:00Z',
    window: '30d',
    identity: {
      workspace_id: 'workspace-a',
      capability_id: 'capability-a',
      system_id: 'system-a',
      version_id: 'version-a',
      name: 'System A',
    },
    header: {
      status: fact('status', 'systems.status'),
      last_run_at: fact('last_run_at', 'runs.created_at'),
      run_count: fact('run_count', 'runs'),
      success_rate: fact('success_rate', 'runs.status'),
    },
    lens: 'steer',
    facets: {
      overview: {
        blocks: [{
          id: 'value-loop',
          title: 'Value loop',
          facts: [
            fact('lifecycle', 'value_scenarios.status'),
            fact('scenarios', 'value_scenarios,value_simulations,value_action_executions,value_measurements'),
          ],
        }],
      },
      runs: { blocks: [] },
      design: {
        blocks: [{
          id: 'value-actuator',
          title: 'Value actuator',
          facts: [fact('actuator', 'systems.settings.value_loop.actuators')],
        }],
      },
      context: { blocks: [] },
    },
  };
}

test('System value-loop visibility is authorized only by the current server Steer projection', () => {
  const current = authoritativeSteerPerspective();
  assert.equal(systemPerspectiveAuthorizesValueLoop(current, 'system-a', 'workspace-a'), true);
  assert.equal(systemPerspectiveAuthorizesValueLoop(undefined, 'system-a', 'workspace-a'), false);

  const staleRevision = structuredClone(current);
  staleRevision.facets.overview.blocks = [];
  assert.equal(
    systemPerspectiveAuthorizesValueLoop(staleRevision, 'system-a', 'workspace-a'),
    false,
    'backend gate removes the block when the rollout revision is stale',
  );

  const wrongSystem = structuredClone(current);
  wrongSystem.identity.system_id = 'system-b';
  assert.equal(systemPerspectiveAuthorizesValueLoop(wrongSystem, 'system-a', 'workspace-a'), false);

  const decorative = structuredClone(current);
  decorative.facets.design.blocks = [];
  assert.equal(
    systemPerspectiveAuthorizesValueLoop(decorative, 'system-a', 'workspace-a'),
    false,
    'a decorative overview block without the governed actuator is insufficient',
  );

  const driftedActuator = structuredClone(current);
  const actuator = driftedActuator.facets.design.blocks.find((block) => block.id === 'value-actuator');
  const actuatorFact = actuator?.facts.find((fact) => fact.key === 'actuator');
  if (!actuatorFact) throw new Error('test fixture must expose the actuator fact');
  actuatorFact.state = 'not_configured';
  actuatorFact.value = null;
  assert.equal(
    systemPerspectiveAuthorizesValueLoop(driftedActuator, 'system-a', 'workspace-a'),
    false,
    'an explicit not_configured actuator remains visible but cannot authorize interactive writes',
  );
});

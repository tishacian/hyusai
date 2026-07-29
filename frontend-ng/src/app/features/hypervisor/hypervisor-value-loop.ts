import type {
  PortfolioEvidenceState,
  PortfolioValueLoop,
} from '@app/core/canonical-api.service';

export interface PortfolioValueLoopSummary {
  state: PortfolioEvidenceState;
  outcomeState: PortfolioEvidenceState;
  observedValueDelta: number | null;
  riskState: PortfolioEvidenceState;
  riskCount: number | null;
  arbitrationState: PortfolioEvidenceState;
  arbitrationCount: number | null;
  scenarioState: PortfolioEvidenceState;
  scenarioCount: number | null;
  unconfiguredActuators: number | null;
}

/** Build an explicit-state view model without manufacturing zeroes. */
export function summarizePortfolioValueLoop(
  payload: PortfolioValueLoop | null | undefined,
): PortfolioValueLoopSummary {
  if (!payload) {
    return {
      state: 'unavailable',
      outcomeState: 'unavailable',
      observedValueDelta: null,
      riskState: 'unavailable',
      riskCount: null,
      arbitrationState: 'unavailable',
      arbitrationCount: null,
      scenarioState: 'unavailable',
      scenarioCount: null,
      unconfiguredActuators: null,
    };
  }
  if (payload.state === 'not_configured') {
    return {
      state: 'not_configured',
      outcomeState: 'not_configured',
      observedValueDelta: null,
      riskState: 'not_configured',
      riskCount: null,
      arbitrationState: 'not_configured',
      arbitrationCount: null,
      scenarioState: 'not_configured',
      scenarioCount: null,
      unconfiguredActuators: null,
    };
  }
  return {
    state: payload.state,
    outcomeState: payload.outcomes.state,
    observedValueDelta: payload.outcomes.observed_value_delta.state === 'available'
      ? payload.outcomes.observed_value_delta.value
      : null,
    riskState: payload.risks.state,
    riskCount: payload.risks.state === 'available' ? payload.risks.count : null,
    arbitrationState: payload.arbitrations.state,
    arbitrationCount: payload.arbitrations.state === 'available'
      ? payload.arbitrations.items.length
      : null,
    scenarioState: payload.scenarios.state,
    scenarioCount: payload.scenarios.state === 'available'
      ? payload.scenarios.items.length
      : null,
    unconfiguredActuators: payload.systems.length
      ? payload.systems.filter((row) => row.actuator_state === 'not_configured').length
      : null,
  };
}

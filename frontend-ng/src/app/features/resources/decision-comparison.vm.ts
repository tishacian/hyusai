import type { Run, SkillInvocation } from '@app/core/canonical-api.service';
import { recordedModelExecution } from '@app/core/model-catalog';
import { agentDecisionTrail, agentToolLabel } from '@app/shared/work-records/agent-decision-trail';

/** A candidate result is an observed decision, never a quality verdict. */
export function comparisonDecision(run: Run) {
  const invocation = run.skill_invocations?.find((item) => item.skill_slug === 'decide_next_v1');
  const output = invocation?.output_ref ?? {};
  const choice = agentDecisionTrail(run)[0];
  const available = invocation?.status === 'completed'
    && (output['next_skill'] === null || typeof output['next_skill'] === 'string') && typeof output['done'] === 'boolean';
  return {
    available,
    exit: available && choice?.state === 'finished',
    state: choice?.state ?? 'unavailable',
    normalized: choice?.normalized ?? false,
    nextSkill: available && choice?.skill ? choice.purpose || agentToolLabel(choice.skill) : null,
    rationale: available && typeof output['rationale'] === 'string' ? output['rationale'] : null,
    duration: typeof invocation?.latency_ms === 'number' ? invocation.latency_ms : null,
    resolution: invocation ? recordedModelExecution(invocation) : null,
    cost: observedComparisonCost(invocation),
    tokens: observedComparisonTokens(invocation),
  };
}

function observedComparisonCost(invocation?: SkillInvocation): { amount: number; currency: string } | null {
  const evidence = invocation?.metrics?.['cost_evidence'] as Record<string, unknown> | undefined;
  const measured = evidence?.['state'] === 'measured' || evidence?.['method'] === 'provider_measurement';
  return invocation?.cost_measured === true && typeof invocation.cost === 'number'
    && Number.isFinite(invocation.cost) && invocation.cost >= 0 && measured
    && typeof evidence?.['currency'] === 'string'
    ? { amount: invocation.cost, currency: evidence['currency'] } : null;
}

function observedComparisonTokens(invocation?: SkillInvocation): number | null {
  const evidence = invocation?.metrics?.['token_evidence'] as Record<string, unknown> | undefined;
  return evidence?.['measurement_coverage'] === 'complete' && typeof invocation?.metrics?.['total_tokens'] === 'number'
    ? invocation.metrics['total_tokens'] : null;
}

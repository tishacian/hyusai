import type { SkillInvocation } from '@app/core/canonical-api.service';
import { formatSkillCost } from '@app/features/skills/skill-cost';

/** Recorded invocation amounts are not invoices; old default zeros prove nothing. */
export function invocationCost(invocation: SkillInvocation, locale = 'en') {
  const evidence = invocation.metrics?.['cost_evidence'];
  const record = evidence && typeof evidence === 'object' && !Array.isArray(evidence)
    ? evidence as Record<string, unknown> : {};
  const calculated = record['state'] === 'calculated';
  const qualified = calculated || record['state'] === 'measured' || invocation.cost_measured === true;
  const amount = invocation.cost;
  const unavailable = invocation.cost_measured === false || record['state'] === 'not_measured'
    || amount == null || !Number.isFinite(amount) || amount < 0 || (amount === 0 && !qualified);
  const currency = typeof record['currency'] === 'string' ? record['currency'] : 'USD';
  return {
    value: formatSkillCost(unavailable ? null : amount, currency, locale),
    labelKey: unavailable ? 'runs.outcome.cost_unavailable'
      : calculated ? 'runs.outcome.cost_calculated' : 'runs.outcome.cost_recorded',
  };
}

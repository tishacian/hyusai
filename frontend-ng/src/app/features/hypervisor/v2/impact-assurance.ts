import { HYPERVISOR_FR, HYPERVISOR_EN } from '@app/core/i18n/hypervisor.dict';
export type AssuranceTraffic = 'business' | 'evaluation' | 'all';
export interface AssuranceQuality {
  totals: { evaluations: number; distinct_runs: number; technical_failures: number; assessed: number; passed: number; failed: number; unassessed: number; pass_rate: number | null; pass_rate_denominator: number; reviewed: number };
  has_more?: boolean;
}
export interface AssuranceUsage {
  coverage?: { complete: boolean; mode?: string };
  counts: { calls: number; dispatched: number; completed: number; failed: number; unknown: number; blocked: number };
  tokens: { input: number | null; output: number | null; total: number | null; known_calls: number; unknown_calls: number };
  costs: Array<{ currency: string; known_amount: string | number | null; known_calls: number; unknown_calls: number; basis: string }>;
}
export function assuranceTraffic(settings: Record<string, unknown>): AssuranceTraffic {
  return settings['traffic'] === 'evaluation' || settings['traffic'] === 'all' ? settings['traffic'] : 'business';
}
export function qualityPassFraction(value: AssuranceQuality | null): number | null {
  const counts = value?.totals;
  return counts && counts.assessed > 0 ? counts.passed / counts.assessed : null;
}
export function knownSpend(value: AssuranceUsage | null): Array<{ currency: string; amount: number }> {
  return (value?.costs ?? []).flatMap(cost => {
    if (cost.known_amount == null || cost.known_calls <= 0 || !/^[A-Z]{3}$/.test(cost.currency)) return [];
    const amount = Number(cost.known_amount);
    return Number.isFinite(amount) && amount >= 0 ? [{ currency: cost.currency, amount }] : [];
  });
}
export const ASSURANCE_MESSAGES = {
  fr: { quality: HYPERVISOR_FR['hypervisor.v2.assurance.quality'], ai_usage: HYPERVISOR_FR['hypervisor.v2.assurance.ai_usage'], business: HYPERVISOR_FR['hypervisor.v2.assurance.business'], evaluation: HYPERVISOR_FR['hypervisor.v2.assurance.evaluation'], all: HYPERVISOR_FR['hypervisor.v2.assurance.all'], traffic: HYPERVISOR_FR['hypervisor.v2.assurance.traffic'], controls: HYPERVISOR_FR['hypervisor.v2.assurance.controls'], runs: HYPERVISOR_FR['hypervisor.v2.assurance.runs'], valid: HYPERVISOR_FR['hypervisor.v2.assurance.valid'], failures: HYPERVISOR_FR['hypervisor.v2.assurance.failures'], pass: HYPERVISOR_FR['hypervisor.v2.assurance.pass'], passBasis: HYPERVISOR_FR['hypervisor.v2.assurance.passBasis'], unknown: HYPERVISOR_FR['hypervisor.v2.assurance.unknown'], reviewed: HYPERVISOR_FR['hypervisor.v2.assurance.reviewed'], calls: HYPERVISOR_FR['hypervisor.v2.assurance.calls'], input: HYPERVISOR_FR['hypervisor.v2.assurance.input'], output: HYPERVISOR_FR['hypervisor.v2.assurance.output'], costs: HYPERVISOR_FR['hypervisor.v2.assurance.costs'], detail: HYPERVISOR_FR['hypervisor.v2.assurance.detail'], coverage: HYPERVISOR_FR['hypervisor.v2.assurance.coverage'], costsNote: HYPERVISOR_FR['hypervisor.v2.assurance.costsNote'], qualityNote: HYPERVISOR_FR['hypervisor.v2.assurance.qualityNote'], empty: HYPERVISOR_FR['hypervisor.v2.assurance.empty'], limited: HYPERVISOR_FR['hypervisor.v2.assurance.limited'], observedAt: HYPERVISOR_FR['hypervisor.v2.assurance.observedAt'] },
  en: { quality: HYPERVISOR_EN['hypervisor.v2.assurance.quality'], ai_usage: HYPERVISOR_EN['hypervisor.v2.assurance.ai_usage'], business: HYPERVISOR_EN['hypervisor.v2.assurance.business'], evaluation: HYPERVISOR_EN['hypervisor.v2.assurance.evaluation'], all: HYPERVISOR_EN['hypervisor.v2.assurance.all'], traffic: HYPERVISOR_EN['hypervisor.v2.assurance.traffic'], controls: HYPERVISOR_EN['hypervisor.v2.assurance.controls'], runs: HYPERVISOR_EN['hypervisor.v2.assurance.runs'], valid: HYPERVISOR_EN['hypervisor.v2.assurance.valid'], failures: HYPERVISOR_EN['hypervisor.v2.assurance.failures'], pass: HYPERVISOR_EN['hypervisor.v2.assurance.pass'], passBasis: HYPERVISOR_EN['hypervisor.v2.assurance.passBasis'], unknown: HYPERVISOR_EN['hypervisor.v2.assurance.unknown'], reviewed: HYPERVISOR_EN['hypervisor.v2.assurance.reviewed'], calls: HYPERVISOR_EN['hypervisor.v2.assurance.calls'], input: HYPERVISOR_EN['hypervisor.v2.assurance.input'], output: HYPERVISOR_EN['hypervisor.v2.assurance.output'], costs: HYPERVISOR_EN['hypervisor.v2.assurance.costs'], detail: HYPERVISOR_EN['hypervisor.v2.assurance.detail'], coverage: HYPERVISOR_EN['hypervisor.v2.assurance.coverage'], costsNote: HYPERVISOR_EN['hypervisor.v2.assurance.costsNote'], qualityNote: HYPERVISOR_EN['hypervisor.v2.assurance.qualityNote'], empty: HYPERVISOR_EN['hypervisor.v2.assurance.empty'], limited: HYPERVISOR_EN['hypervisor.v2.assurance.limited'], observedAt: HYPERVISOR_EN['hypervisor.v2.assurance.observedAt'] },
} as const;

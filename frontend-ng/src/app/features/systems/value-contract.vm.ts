/**
 * The value contract panel, without Angular: the form a System administrator
 * fills, the proposal it becomes, and the refusals the API can answer.
 * ADR 0003 lot 3.
 */

export const CONTRACT_INDICATORS = [
  'completed_volume',
  'mean_duration_ms',
  'human_validation_rate',
  'measured_cost_usd',
] as const;
export type ContractIndicator = (typeof CONTRACT_INDICATORS)[number];

export const SOURCE_KINDS = ['agreement', 'document', 'measurement', 'estimate'] as const;
export type SourceKind = (typeof SOURCE_KINDS)[number];

export const MAX_PERIOD_DAYS = 90;

export interface ContractTerms {
  revision: number;
  status: string;
  owner_user_id: string;
  owner: string;
  indicator: ContractIndicator;
  unit: string;
  target: number;
  period_start: string;
  period_end: string;
  convention: { value_per_unit: number; currency: string; unit: string };
  source: { kind: SourceKind; reference: string };
  content_sha256: string;
  proposed_by: string;
  proposed_at: string | null;
  decided_by: string | null;
  decided_at: string | null;
  decision_note: string | null;
}

export interface ContractState {
  system_id: string;
  automation: boolean;
  latest_revision: number;
  current: ContractTerms | null;
  pending: ContractTerms | null;
  history: ContractTerms[];
  gap: Record<string, unknown>;
  convention: Record<string, unknown>;
  can_propose: boolean;
  can_decide: boolean;
  owner_options: Array<{ user_id: string; label: string }>;
  prefill: Partial<{
    indicator: ContractIndicator;
    target: number;
    period_start: string;
    period_end: string;
    convention: { value_per_unit: number; currency: string; unit: string };
    source: { kind: SourceKind; reference: string };
  }>;
}

export interface ContractForm {
  owner_user_id: string;
  indicator: ContractIndicator;
  target: number | null;
  period_start: string;
  period_end: string;
  value_per_unit: number | null;
  currency: string;
  unit: string;
  source_kind: SourceKind;
  source_reference: string;
}

/** Start from the approved terms, else from the objective and the value basis. */
export function initialForm(state: ContractState): ContractForm {
  const base = state.pending ?? state.current;
  if (base) {
    return {
      owner_user_id: base.owner_user_id,
      indicator: base.indicator,
      target: base.target,
      period_start: base.period_start,
      period_end: base.period_end,
      value_per_unit: base.convention.value_per_unit,
      currency: base.convention.currency,
      unit: base.convention.unit,
      source_kind: base.source.kind,
      source_reference: base.source.reference,
    };
  }
  const draft = state.prefill ?? {};
  return {
    owner_user_id: '',
    indicator: draft.indicator ?? 'completed_volume',
    target: draft.target ?? null,
    period_start: draft.period_start ?? '',
    period_end: draft.period_end ?? '',
    value_per_unit: draft.convention?.value_per_unit ?? null,
    currency: draft.convention?.currency ?? 'EUR',
    unit: draft.convention?.unit ?? '',
    source_kind: draft.source?.kind ?? 'agreement',
    source_reference: draft.source?.reference ?? '',
  };
}

function days(start: string, end: string): number | null {
  const from = Date.parse(`${start}T00:00:00Z`);
  const to = Date.parse(`${end}T00:00:00Z`);
  if (Number.isNaN(from) || Number.isNaN(to)) return null;
  return Math.round((to - from) / 86_400_000);
}

/** The first reason the form is not a proposal yet, as a dictionary key. */
export function formProblem(form: ContractForm): string | null {
  if (!form.owner_user_id) return 'systems.value_contract.problem.owner';
  if (form.target === null || !Number.isFinite(form.target) || form.target < 0) {
    return 'systems.value_contract.problem.target';
  }
  if (form.indicator === 'human_validation_rate' && form.target > 100) {
    return 'systems.value_contract.problem.percent';
  }
  const span = days(form.period_start, form.period_end);
  if (span === null || span <= 0 || span > MAX_PERIOD_DAYS) return 'systems.value_contract.problem.period';
  if (form.value_per_unit === null || !Number.isFinite(form.value_per_unit) || form.value_per_unit < 0) {
    return 'systems.value_contract.problem.value';
  }
  if (!/^[A-Z]{3}$/.test(form.currency.trim())) return 'systems.value_contract.problem.currency';
  if (!form.unit.trim()) return 'systems.value_contract.problem.unit';
  if (!form.source_reference.trim()) return 'systems.value_contract.problem.source';
  return null;
}

export function proposalBody(form: ContractForm, expectedRevision: number): Record<string, unknown> {
  return {
    owner_user_id: form.owner_user_id,
    indicator: form.indicator,
    target: form.target,
    period_start: form.period_start,
    period_end: form.period_end,
    convention: {
      value_per_unit: form.value_per_unit,
      currency: form.currency.trim().toUpperCase(),
      unit: form.unit.trim(),
    },
    source: { kind: form.source_kind, reference: form.source_reference.trim() },
    expected_revision: expectedRevision,
  };
}

const REFUSALS: Record<string, string> = {
  value_contract_stale: 'systems.value_contract.refused.stale',
  value_contract_owner_not_member: 'systems.value_contract.refused.owner_not_member',
  value_contract_owner_only: 'systems.value_contract.refused.owner_only',
  value_contract_changed: 'systems.value_contract.refused.changed',
  value_contract_not_pending: 'systems.value_contract.refused.not_pending',
};

export function refusalKey(code: unknown, status?: number): string {
  if (typeof code === 'string' && REFUSALS[code]) return REFUSALS[code];
  if (status === 403) return 'systems.value_contract.refused.forbidden';
  if (status === 422) return 'systems.value_contract.refused.invalid';
  return 'systems.value_contract.refused.error';
}

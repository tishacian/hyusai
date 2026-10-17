/**
 * Runtime requalification (M4.2) — pure view-model of `GET /ml-models/{id}/runtime`.
 *
 * The server decides the status; this file only words it. Rights come from
 * `serving.permissions.requalify` (M1), never from a role read here.
 */

export type RuntimeStatus =
  | 'current'
  | 'attested'
  | 'requalification_required'
  | 'reference_missing'
  | 'unsupported';

export interface RuntimeDifference { package: string; producer: string | null; reader: string | null; }

export interface RuntimeGaps {
  rows?: number;
  label_agreement?: number;
  label_disagreements?: number;
  max_abs_proba_diff?: number | null;
  max_abs_diff?: number | null;
  max_rel_diff?: number | null;
  out_of_tolerance?: number;
}

export interface RuntimeTolerances {
  max_label_disagreements: number;
  proba_atol: number;
  regression_atol: number;
  regression_rtol: number;
}

export interface RuntimeAttestation {
  id: string;
  verdict: 'qualified' | 'failed';
  error_code: string | null;
  active: boolean;
  applies_to_reader: boolean;
  reader_runtime: Record<string, string>;
  producer_runtime: Record<string, string>;
  rows_compared: number;
  metrics: RuntimeGaps;
  tolerances: Partial<RuntimeTolerances>;
  actor: string;
  created_at: string | null;
  revoked_at: string | null;
  revoked_by: string | null;
}

export interface RuntimeJob {
  id: string;
  kind: 'ml_reference_capture' | 'ml_requalification';
  status: 'created' | 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  error: string | null;
  updated_at: string | null;
}

export interface RuntimeState {
  model_id: string;
  version: number;
  status: RuntimeStatus;
  supported: boolean;
  reason: string | null;
  producer_runtime: Record<string, string> | null;
  reader_runtime: Record<string, string> | null;
  differences: RuntimeDifference[];
  reference: { status: 'stored' | 'missing'; rows?: number; captured_at?: string | null; captured_by?: string | null };
  can_capture: boolean;
  can_requalify: boolean;
  attestations: RuntimeAttestation[];
  jobs: Partial<Record<RuntimeJob['kind'], RuntimeJob | null>>;
  tolerances: RuntimeTolerances;
}

export type RuntimeTone = 'neutral' | 'warn' | 'neg';

export interface RuntimeActions { capture: boolean; requalify: boolean; revoke: string | null; }

const STATUSES: readonly RuntimeStatus[] = [
  'current', 'attested', 'requalification_required', 'reference_missing', 'unsupported',
];
const REASONS = [
  'remote_family', 'no_evaluation_partition', 'family_unsupported', 'task_unsupported',
  'legacy_artifact', 'format_unsupported', 'reader_incomplete',
];
const ERRORS = [
  'ML_REFERENCE_SOURCE_UNAVAILABLE', 'ML_REFERENCE_MISSING', 'ML_REFERENCE_PRODUCER_RUNTIME_REQUIRED',
  'ML_REFERENCE_INVALID', 'ML_REFERENCE_TOO_LARGE', 'ML_REQUALIFICATION_UNSUPPORTED',
  'ML_REQUALIFICATION_NOT_REQUIRED', 'ML_REQUALIFICATION_OUTPUT_MISMATCH',
  'ML_REQUALIFICATION_CLASS_ORDER_CHANGED', 'ML_REQUALIFICATION_TIMEOUT',
  'ML_REQUALIFICATION_READER_CHANGED', 'ML_FORBIDDEN_ACTION',
];

export function runtimeStatusKey(state: RuntimeState | null): string {
  if (!state) return 'models.runtime.loading';
  return STATUSES.includes(state.status) ? `models.runtime.status.${state.status}` : 'models.runtime.status.unsupported';
}

export function runtimeReasonKey(reason: string | null | undefined): string | null {
  if (!reason) return null;
  return REASONS.includes(reason) ? `models.runtime.reason.${reason}` : 'models.runtime.reason.family_unsupported';
}

/** A `CODE: detail` job error or a bare code, as a dictionary key. */
export function runtimeErrorKey(error: string | null | undefined): string | null {
  if (!error) return null;
  const code = error.split(':', 1)[0].trim();
  return ERRORS.includes(code) ? `models.runtime.error.${code.toLowerCase()}` : 'models.runtime.error.generic';
}

/** The most recent attempt; failures stay visible until a newer attempt. */
export function lastAttempt(state: RuntimeState | null): RuntimeAttestation | null {
  const attempts = [...(state?.attestations ?? [])];
  attempts.sort((a, b) => (b.created_at ?? '').localeCompare(a.created_at ?? ''));
  return attempts[0] ?? null;
}

/**
 * Neutral by default. Amber only while calls are refused and requalification
 * is the way back; red when they are refused with no way back but a retrain,
 * or when the latest attempt failed.
 */
export function runtimeTone(state: RuntimeState | null): RuntimeTone {
  if (!state) return 'neutral';
  if (state.status === 'current' || state.status === 'attested') return 'neutral';
  if (state.status === 'reference_missing') return 'neg';
  if (state.status === 'unsupported') return state.differences.length ? 'neg' : 'neutral';
  return lastAttempt(state)?.verdict === 'failed' ? 'neg' : 'warn';
}

export function activeJob(state: RuntimeState | null): RuntimeJob | null {
  const jobs = Object.values(state?.jobs ?? {});
  return jobs.find(job => job?.status === 'queued' || job?.status === 'running') ?? null;
}

/** Buttons the server state allows, intersected with the M1 capability. */
export function runtimeActions(state: RuntimeState | null, allowed: boolean, busy: boolean): RuntimeActions {
  if (!state || !allowed || busy) return { capture: false, requalify: false, revoke: null };
  const pending = activeJob(state);
  const active = state.attestations.find(item => item.active && item.applies_to_reader);
  return {
    capture: state.can_capture && pending?.kind !== 'ml_reference_capture',
    requalify: state.can_requalify && pending?.kind !== 'ml_requalification',
    revoke: active?.id ?? null,
  };
}

/** Exponent notation below 1e-3, so 2e-13 does not read as "0.000". */
export function formatGap(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  if (value === 0) return '0';
  const magnitude = Math.abs(value);
  return magnitude < 1e-3 ? value.toExponential(1) : String(Number(value.toPrecision(3)));
}

export interface GapLine { key: string; params: Record<string, string | number>; }

/** The measured gaps of one attempt, next to the tolerance they were judged by. */
export function gapLines(attempt: RuntimeAttestation | null): GapLine[] {
  if (!attempt) return [];
  const m = attempt.metrics ?? {}, limits = attempt.tolerances ?? {};
  const lines: GapLine[] = [];
  if (m.label_agreement !== undefined) {
    lines.push({
      key: 'models.runtime.gap.labels',
      params: {
        agreement: `${Math.round(m.label_agreement * 1000) / 10} %`,
        disagreements: m.label_disagreements ?? 0,
        allowed: limits.max_label_disagreements ?? 0,
      },
    });
  }
  if (m.max_abs_proba_diff !== undefined) {
    lines.push({
      key: 'models.runtime.gap.proba',
      params: { value: formatGap(m.max_abs_proba_diff), limit: formatGap(limits.proba_atol) },
    });
  }
  if (m.max_abs_diff !== undefined) {
    lines.push({
      key: 'models.runtime.gap.values',
      params: {
        abs: formatGap(m.max_abs_diff),
        rel: formatGap(m.max_rel_diff),
        outside: m.out_of_tolerance ?? 0,
        atol: formatGap(limits.regression_atol),
        rtol: formatGap(limits.regression_rtol),
      },
    });
  }
  return lines;
}

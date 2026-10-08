export interface ShadowConfig { enabled: boolean; sample_percent: number; timeout_s: number; }
export interface ShadowReport {
  supported: boolean;
  config: ShadowConfig;
  can_configure: boolean;
  challenger: { id: string; version: number } | null;
  limits: { max_rows: number; max_pending: number; max_attempts: number; window?: number };
  comparison_scope?: 'current_pair';
  window: { jobs: number; completed: number; pending: number; failed: number; skipped: number; compared_rows: number; labeled_pairs: number };
  comparison: { agreement: number | null; mean_absolute_difference: number | null; champion_accuracy: number | null; challenger_accuracy: number | null; champion_mae: number | null; challenger_mae: number | null };
  latencies: { primary_ms: number | null; shadow_ms: number | null; shadow_load_ms?: number | null; shadow_total_ms?: number | null };
  recent: Array<{ prediction_id: string; challenger_id: string | null; version: number | null; status: string; error: string | null; rows: number; created_at: string; total_duration_ms?: number | null }>;
}

export function shadowConfig(enabled: boolean, sample: string, timeout: string): ShadowConfig | null {
  const sample_percent = Number(sample), timeout_s = Number(timeout);
  if (!sample.trim() || !timeout.trim() || !Number.isInteger(sample_percent) || sample_percent < 1 || sample_percent > 100
    || !Number.isInteger(timeout_s) || timeout_s < 1 || timeout_s > 60) return null;
  return { enabled, sample_percent, timeout_s };
}

export function shadowValue(value: number | null | undefined, locale: string, percent = false): string | null {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0 || (percent && value > 1)) return null;
  return new Intl.NumberFormat(locale, percent
    ? { style: 'percent', maximumFractionDigits: 1 } : { maximumFractionDigits: 3 }).format(value);
}

const REASONS = new Set(['FORBIDDEN', 'UNSUPPORTED', 'NO_CHALLENGER', 'INCOMPATIBLE', 'ARTIFACT_TOO_LARGE',
  'PAYLOAD_TOO_LARGE', 'BUSY', 'BACKLOG_FULL', 'RETRY_LIMIT', 'SOURCE_UNAVAILABLE', 'SOURCE_CHANGED',
  'MODEL_CHANGED', 'DISABLED', 'TIMEOUT', 'FAILED', 'INVALID_OUTPUT']);
export function shadowErrorKey(code: string | null | undefined): string {
  const suffix = code?.replace(/^ML_SHADOW_/, '');
  return `models.shadow.error.${suffix && REASONS.has(suffix) ? suffix.toLowerCase() : 'failed'}`;
}

export interface PublicBenchRun {
  id: string;
  status: string;
  git_sha?: string | null;
  k: number;
  case_count: number;
  error_count: number;
  recall_at_k?: number | null;
  supporting_fact_rate?: number | null;
  mean_latency_ms?: number | null;
  started_at?: string | null;
}

export interface PublicBenchMetric {
  value: number | null;
  delta: number | null;
}

/** A 0..1 ratio as a whole percentage; anything else is unmeasured, never 0. */
export function ratioPercent(value: unknown): number | null {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0 || value > 1) return null;
  return Math.round(value * 1000) / 10;
}

/** Latest completed run against the previous completed one; runs come newest first. */
export function benchMetric(runs: readonly PublicBenchRun[], key: 'recall_at_k' | 'supporting_fact_rate'): PublicBenchMetric {
  const completed = runs.filter((run) => run.status === 'completed');
  const value = ratioPercent(completed[0]?.[key]);
  const previous = ratioPercent(completed[1]?.[key]);
  return { value, delta: value !== null && previous !== null ? Math.round((value - previous) * 10) / 10 : null };
}

export function shortSha(sha: string | null | undefined): string {
  return sha && /^[0-9a-f]{7,40}$/.test(sha) ? sha.slice(0, 12) : '—';
}

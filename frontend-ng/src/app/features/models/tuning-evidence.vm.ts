/** Evidence is absent on models trained before automatic tuning existed. */
export interface TuningResult {
  metric: string;
  direction: 'max' | 'min';
  trials_run: number;
  trials_pruned: number;
  trials_failed: number;
  stopped_by: 'trials' | 'budget';
  budget_s: number;
  elapsed_s: number;
  folds: number;
  warning?: string;
  start: { knobs: Record<string, unknown>; score: number | null; std?: number | null };
  best: { knobs: Record<string, unknown>; score: number | null; std?: number | null; trial: number | null };
  trials: { n: number; score: number | null; state: string; duration_ms: number }[];
}

export function tuningPoints(tuning: TuningResult | undefined) {
  const trials = (tuning?.trials ?? []).filter((row) => row.state === 'complete' && typeof row.score === 'number' && Number.isFinite(row.score));
  const scores = trials.map((row) => row.score!);
  const low = Math.min(...scores), high = Math.max(...scores);
  const span = high - low || 1;
  const maxTrial = Math.max(1, ...(tuning?.trials ?? []).map((row) => row.n));
  return trials.map((row) => ({ n: row.n, score: row.score!, x: 24 + 352 * row.n / maxTrial,
    y: high === low ? 85 : 145 - 120 * (row.score! - low) / span, best: row.n === tuning?.best.trial }));
}

export function tuningKnobs(tuning: TuningResult | undefined) {
  if (!tuning) return [];
  return Object.keys(tuning.start.knobs).map((key) => ({ key, before: tuning.start.knobs[key], after: tuning.best.knobs[key] }));
}

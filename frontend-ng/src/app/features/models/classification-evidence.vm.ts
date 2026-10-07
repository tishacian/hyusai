/** Measurements of the classifier actually served, evaluated on its holdout. */
export interface CalibrationMeasure {
  brier_score: number | null;
  log_loss: number | null;
  curve?: { x: number; y: number }[];
}
export interface CalibrationEvidence {
  method: string;
  fit_rows: number;
  calibration_rows: number;
  before: CalibrationMeasure;
  after: CalibrationMeasure;
}
export interface DecisionEvidence {
  threshold: number;
  criterion: string;
  source?: string;
  default_metrics: Record<string, number | null>;
  tuned_metrics: Record<string, number | null>;
}
export function calibrationWorsened(evidence: CalibrationEvidence | null | undefined): boolean {
  return !!evidence && (['brier_score', 'log_loss'] as const).some((key) => {
    const before = evidence.before[key], after = evidence.after[key];
    return before !== null && after !== null && Number.isFinite(before) && Number.isFinite(after) && after > before;
  });
}
export function decisionRows(evidence: DecisionEvidence | null | undefined): { key: string; before: number | null; after: number | null }[] {
  if (!evidence) return [];
  return ['precision', 'recall', 'f1'].map((key) => ({ key, before: evidence.default_metrics[key] ?? null, after: evidence.tuned_metrics[key] ?? null }));
}

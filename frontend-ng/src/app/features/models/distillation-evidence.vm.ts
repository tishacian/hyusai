export interface DistillationEvidence {
  version: number;
  evaluation: 'held_out';
  test_rows: number;
  rows_reviewed: number;
  corrected_rows: number;
  agreement: number | null;
  reviewed_accuracy: number | null;
  teacher_accuracy_on_reviewed: number | null;
  source_dataset_id: string;
  source_version: number;
  reviewed_dataset_id: string;
  decision_id: string;
  teacher_model: { provider?: string; model?: string };
  llm_estimated_cost_per_1000: number | null;
  llm_cost_basis: 'declared_tariff';
  llm_labeled_rows: number;
  unknown_attempts: number;
  inference_cost_per_1000: number | null;
  inference_cost_basis: 'declared' | 'unavailable';
}

export function distillationValue(value: unknown, maximum = Number.POSITIVE_INFINITY): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= maximum ? value : null;
}

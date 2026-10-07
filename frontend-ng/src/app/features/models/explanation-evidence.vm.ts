/** Small explanations of held-out rows; failures are local to each section. */
export interface ExplainRule { feature: string; op: string; value: number | null; }
export interface ExplainLeaf { rule: ExplainRule[]; rows: number; error?: number | null; global_error?: number | null; lift?: number | null; prediction?: unknown; }
export interface ExplainTree { error?: string; rules?: ExplainLeaf[]; global_error?: number | null; rows?: number; }
export interface SurrogateEvidence extends ExplainTree { fidelity?: number | null; metric?: string; train_rows?: number; validation_rows?: number; }
export interface PartialEffect { feature: string; error?: string; kind?: string; grid?: (number | string | null)[]; average?: (number | null)[]; ice?: (number | null)[][]; class?: string | number; }
export interface FairnessGroup { group: unknown; n: number; low_support: boolean; [key: string]: unknown; }
export interface FairnessEvidence { column: string; error?: string; groups?: FairnessGroup[]; selection_ratio?: number | null; equalized_odds_diff?: number | null; mae_gap_ratio?: number | null; signal?: boolean; }
export interface ExplanationEvidence {
  error?: string;
  rows?: number;
  elapsed_s?: number;
  budget_s?: number;
  error_tree?: ExplainTree;
  surrogate?: SurrogateEvidence;
  pdp?: PartialEffect[];
  fairness?: FairnessEvidence[] | { error: string };
}
export function readableRule(rule: readonly ExplainRule[], locale: string, all: string, and: string): string {
  if (!rule.length) return all;
  return rule.map((term) => `${term.feature} ${term.op === '<=' ? '≤' : term.op} ${term.value?.toLocaleString(locale, { maximumFractionDigits: 3 }) ?? '—'}`).join(` ${and} `);
}
export function surrogateRules(evidence: SurrogateEvidence | null | undefined): ExplainLeaf[] {
  return evidence && !evidence.error && typeof evidence.fidelity === 'number' && evidence.fidelity >= 0.7 ? evidence.rules ?? [] : [];
}
export function fairnessMetrics(evidence: FairnessEvidence): string[] {
  const available = evidence.groups ?? [];
  return ['selection_rate', 'tpr', 'fpr', 'accuracy', 'mae', 'bias'].filter((key) => available.some((group) => key in group));
}
export function partialSeries(effect: PartialEffect): { grid: (number | string | null)[]; average: (number | null)[]; ice: (number | null)[][] } {
  const grid = effect.grid ?? [], average = effect.average ?? [];
  if (!grid.length || grid.length !== average.length || effect.error) return { grid: [], average: [], ice: [] };
  return { grid, average, ice: (effect.ice ?? []).filter((row) => row.length === grid.length).slice(0, 30) };
}

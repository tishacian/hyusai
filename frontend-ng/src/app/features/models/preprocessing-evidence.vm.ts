/** A fitted preparation record, never inferred from the selected options. */
export interface PreprocessingColumn {
  name: string;
  input_dtype: string | null;
  kind: string | null;
  transformers: string[];
  output_count: number;
  excluded: boolean;
  reason: string | null;
}
export interface PreprocessingEvidence {
  schema: number;
  status: string;
  learning_scope: string;
  input_count: number;
  retained_count: number;
  excluded_count: number;
  output_count: number | null;
  columns: PreprocessingColumn[];
  truncated?: boolean;
  versions?: Record<string, string>;
}
export function fittedPreparation(value: PreprocessingEvidence | null | undefined): PreprocessingEvidence | null {
  if (!value || value.schema !== 1 || value.status !== 'available' ||
      value.learning_scope !== 'training_folds' || !Array.isArray(value.columns)) return null;
  if (![value.input_count, value.retained_count, value.excluded_count].every(count =>
      Number.isSafeInteger(count) && count >= 0) || value.retained_count + value.excluded_count !== value.input_count) return null;
  return value;
}
export function preparationRows(value: PreprocessingEvidence | null | undefined): PreprocessingColumn[] {
  const evidence = fittedPreparation(value);
  if (!evidence) return [];
  const seen = new Set<string>();
  return evidence.columns.slice(0, 64).filter(column => {
    if (!column || typeof column.name !== 'string' || !column.name || column.name.length > 512 || seen.has(column.name) ||
        typeof column.excluded !== 'boolean' || !Number.isSafeInteger(column.output_count) || column.output_count < 0 ||
        !Array.isArray(column.transformers) || !column.transformers.every(name => typeof name === 'string')) return false;
    seen.add(column.name);
    return true;
  }).map(column => ({ ...column, transformers: column.transformers.slice(0, 8).map(name => name.slice(0, 240)) }));
}
export function preparationWidth(value: PreprocessingEvidence | null | undefined): number | null {
  const count = fittedPreparation(value)?.output_count;
  return typeof count === 'number' && Number.isSafeInteger(count) && count >= 0 ? count : null;
}

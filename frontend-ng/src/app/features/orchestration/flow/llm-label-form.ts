/** Presentation metadata for the graph-owned dataset labeling parameters. */
export const LLM_LABEL_SKILL_SLUG = 'llm_label_dataset_v1';

const FIELDS = new Set([
  'sources', 'text_columns', 'labels', 'label_column', 'instruction', 'output_name',
  'batch_size', 'max_rows', 'max_tokens', 'max_output_tokens', 'max_cost_usd',
  'input_cost_per_million', 'output_cost_per_million', 'timeout_s', 'resume_job_id',
]);
const REQUIRED = new Set([
  'text_columns', 'labels', 'instruction', 'input_cost_per_million', 'output_cost_per_million',
]);

export function labelDatasetField(slug: unknown, key: string) {
  if (slug !== LLM_LABEL_SKILL_SLUG || !FIELDS.has(key)) return null;
  return {
    labelKey: `flow.label.fields.${key}`,
    helpKey: `flow.label.help.${key}`,
    required: REQUIRED.has(key),
    multiline: key === 'instruction',
  };
}

export function labelDatasetValueMissing(value: unknown): boolean {
  return value === undefined || value === null
    || (typeof value === 'string' && !value.trim())
    || (Array.isArray(value) && value.length === 0);
}

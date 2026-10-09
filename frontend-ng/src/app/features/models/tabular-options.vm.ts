/** Catalog-driven tabular options, shared by the studio and the Flow workshop. */
import type { ModelCatalog, ModelTask, PlanColumn, SpecFieldDescriptor } from './models.vm';

export function tabularFields(
  catalog: ModelCatalog, task: ModelTask, spec?: Record<string, unknown> | null,
): SpecFieldDescriptor[] {
  const classic = catalog.families?.find((family) => family.key === 'tabular' && family.tasks.includes(task))?.spec_fields ?? [];
  const deep = catalog.families?.find((family) => family.key === 'tabular_deep' && family.tasks.includes(task));
  const embedding = spec?.['text_encoder'] === 'embedding';
  const encoder = classic.find((field) => field.key === 'text_encoder');
  if (!encoder) return classic;
  const choices = [...(encoder.choices ?? [])];
  if ((deep?.available || embedding) && !choices.includes('embedding')) choices.push('embedding');
  const fields = embedding && deep ? deep.spec_fields : classic;
  return fields.map((field) => {
    if (field.key === 'text_encoder') return { ...encoder, choices };
    const defaultValue = EMBEDDING_UNSUPPORTED[field.key];
    if (embedding && defaultValue !== undefined) {
      // A saved incompatible choice stays editable until explicitly turned off.
      const current = spec?.[field.key];
      return { ...field, choices: [...new Set([defaultValue, ...(typeof current === 'string' ? [current] : [])])] };
    }
    return field;
  });
}

const EMBEDDING_UNSUPPORTED: Record<string, string> = {
  tuning: 'off', calibration: 'off', threshold: 'default', intervals: 'off', explain: 'off',
};

/** Local refusal mirrors the bounded first release without discarding saved choices. */
export function embeddingIssue(
  catalog: ModelCatalog, spec: Record<string, unknown> | null | undefined,
  crossValidation: number, features?: readonly string[],
): string | null {
  if (spec?.['text_encoder'] !== 'embedding') return null;
  const family = catalog.families?.find((entry) => entry.key === 'tabular_deep');
  if (!family?.available) return 'models.embedding.unavailable';
  if (crossValidation >= 2 || Object.entries(EMBEDDING_UNSUPPORTED).some(([key, fallback]) =>
    spec[key] != null && spec[key] !== fallback)) return 'models.embedding.unsupported';
  const columns = spec['embedding_columns'];
  const descriptor = family.spec_fields.find((field) => field.key === 'embedding_columns');
  if (!Array.isArray(columns) || !columns.length || columns.length > (descriptor?.max_items ?? 1)) return 'models.embedding.columns_required';
  if (features && columns.some((column) => !features.includes(column))) return 'models.embedding.feature_required';
  const components = family.spec_fields.find((field) => field.key === 'embedding_components');
  const count = spec['embedding_components'] ?? components?.default ?? 30;
  if (typeof count !== 'number' || !Number.isInteger(count) || count < (components?.min ?? 2) || count > (components?.max ?? 128)) return 'models.embedding.components_invalid';
  return null;
}

/** The resolved task is context, never an authored or persisted spec field. */
export function specValues(
  fields: readonly SpecFieldDescriptor[],
  spec: Record<string, unknown> | null | undefined,
  task: ModelTask,
): Record<string, unknown> {
  const values: Record<string, unknown> = {};
  for (const field of fields) if (field.default !== undefined) values[field.key] = field.default;
  for (const [key, value] of Object.entries(spec ?? {})) if (value != null) values[key] = value;
  values['task'] = task;
  return values;
}

export function shownSpecFields(
  fields: readonly SpecFieldDescriptor[],
  spec: Record<string, unknown> | null | undefined,
  task: ModelTask,
): SpecFieldDescriptor[] {
  const values = specValues(fields, spec, task);
  return fields.filter((field) => Object.entries(field.when ?? {}).every(([key, allowed]) => allowed.includes(values[key] as string)));
}

/** Changing the target cannot send a hidden, incompatible option to training. */
export function tabularSpec(
  fields: readonly SpecFieldDescriptor[],
  spec: Record<string, unknown> | null | undefined,
  task: ModelTask,
): Record<string, unknown> {
  const values = specValues(fields, spec, task);
  return Object.fromEntries(shownSpecFields(fields, spec, task)
    .filter((field) => values[field.key] !== undefined)
    .map((field) => [field.key, values[field.key]]));
}

export function specColumns(field: SpecFieldDescriptor, columns: readonly PlanColumn[], target: string): PlanColumn[] {
  return columns.filter((column) => column.name !== target && (!field.column_kinds?.length || field.column_kinds.includes(column.kind)));
}

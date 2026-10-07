/** Catalog-driven tabular options, shared by the studio and the Flow workshop. */
import type { ModelCatalog, ModelTask, PlanColumn, SpecFieldDescriptor } from './models.vm';

export function tabularFields(catalog: ModelCatalog, task: ModelTask): SpecFieldDescriptor[] {
  return catalog.families?.find((family) => family.key === 'tabular' && family.tasks.includes(task))?.spec_fields ?? [];
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

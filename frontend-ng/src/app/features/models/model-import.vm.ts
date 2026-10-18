/**
 * Model import (M4.3) — pure view-model of the import dialog and of an
 * imported model's evidence. The server decides; this file only words it.
 * Rights come from the list's `permissions.import` (M1), never from a role.
 */
import { formatGap, gapLines, type GapLine, type RuntimeAttestation, type RuntimeGaps, type RuntimeTolerances } from './model-runtime.vm';
import type { ModelDto } from './models.vm';

export type ImportTask = 'classification' | 'regression';

export interface ImportMeasurements {
  load_ms?: number | null;
  predict_ms?: number | null;
  single_row_ms?: number | null;
  model_memory_mb?: number | null;
}

export interface ImportBudgets { max_load_ms: number; max_predict_ms: number; max_memory_mb: number; }

export interface ImportJob {
  id: string;
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled' | 'created';
  error: string | null;
  updated_at: string | null;
  result: {
    verdict?: 'accepted' | 'refused';
    model_id?: string;
    code?: string;
    reason?: string;
    error_code?: string;
    metrics?: RuntimeGaps;
    measurements?: ImportMeasurements;
    budgets?: ImportBudgets;
  };
}

/** What a refusal returns synchronously, before any job exists. */
export interface ImportRefusal { code: string; reason?: string; error_code?: string; types?: string[]; rows?: number; min?: number; max?: number; }

export interface ImportForm {
  archive: File | null;
  validation: File | null;
  task: ImportTask;
  name: string;
  target: string;
  lineageModelId: string | null;
}

export type ImportPhase = 'idle' | 'pending' | 'accepted' | 'refused';

export interface LineageChoice { id: string; name: string; version: number; }

const REASONS = [
  'archive_invalid', 'archive_too_large', 'archive_too_many_entries', 'archive_path_unsafe',
  'archive_symlink', 'archive_encrypted', 'archive_duplicate', 'archive_compression', 'archive_layout',
  'mlmodel_missing', 'mlmodel_invalid', 'metadata_too_large', 'custom_pyfunc', 'code_paths',
  'flavor_unsupported', 'pickle_serialization', 'cloudpickle_serialization', 'joblib_serialization',
  'serialization_unsupported', 'loader_unsupported', 'native_library', 'unexpected_file',
  'signature_missing', 'signature_tensor', 'signature_unnamed', 'signature_type_unsupported',
  'signature_too_wide', 'untrusted_types', 'trusted_types_undeclared', 'task_unsupported',
  'name_invalid', 'lineage_not_external', 'lineage_name_taken', 'too_large', 'format',
  'rows_out_of_bounds', 'rows_do_not_match_signature', 'expected_missing', 'expected_invalid',
  'outputs_differ', 'reader_refused', 'load_time', 'predict_latency', 'memory',
];
const CODES = [
  'ML_IMPORT_DISABLED', 'ML_FORBIDDEN_ACTION', 'ML_IMPORT_READER_CHANGED', 'ML_IMPORT_SOURCE_CHANGED',
  'ML_IMPORT_LINEAGE_CONFLICT', 'ML_IMPORT_ABANDONED', 'ML_AUDIT_UNAVAILABLE', 'ML_IMPORT_TREE_INVALID',
];

export function isImported(model: Pick<ModelDto, 'family'> | null | undefined): boolean {
  return model?.family === 'external';
}

/** Existing imported lineages of this task, newest version per lineage. */
export function lineageChoices(models: ModelDto[], task: ImportTask): LineageChoice[] {
  const latest = new Map<string, ModelDto>();
  for (const model of models) {
    if (!isImported(model) || model.task !== task) continue;
    const current = latest.get(model.slug);
    if (!current || model.version > current.version) latest.set(model.slug, model);
  }
  return [...latest.values()]
    .map(model => ({ id: model.id, name: model.name, version: model.version }))
    .sort((a, b) => a.name.localeCompare(b.name));
}

export function canSubmit(form: ImportForm, allowed: boolean, busy: boolean): boolean {
  return allowed && !busy && !!form.archive && !!form.validation
    && (form.lineageModelId !== null || form.name.trim().length > 0);
}

export function importPhase(job: ImportJob | null): ImportPhase {
  if (!job) return 'idle';
  if (job.status === 'queued' || job.status === 'running' || job.status === 'created') return 'pending';
  return job.result?.verdict === 'accepted' && job.status === 'completed' ? 'accepted' : 'refused';
}

/** The most precise plain-words key: the reason, the reader's code, then the code. */
export function refusalKey(refusal: ImportRefusal | ImportJob['result'] | null | undefined, fallback?: string | null): string {
  const reason = refusal?.reason;
  if (reason && REASONS.includes(reason)) return `models.import.reason.${reason}`;
  const code = refusal?.error_code ?? refusal?.code ?? fallback ?? null;
  if (code && CODES.includes(code)) return `models.import.error.${code.toLowerCase()}`;
  return 'models.import.error.generic';
}

/** The reader code behind a reader refusal, when the reason alone is too vague. */
export function readerCodeKey(result: ImportJob['result'] | null | undefined): string | null {
  const code = result?.reason === 'reader_refused' ? result.error_code : null;
  return code && CODES.includes(code) ? `models.import.error.${code.toLowerCase()}` : null;
}

export interface MeasureLine { key: string; params: Record<string, string>; over: boolean; }

/** Measured costs next to the budget they were judged by. */
export function measurementLines(measurements: ImportMeasurements | null | undefined, budgets: ImportBudgets | null | undefined): MeasureLine[] {
  if (!measurements) return [];
  const lines: MeasureLine[] = [];
  const add = (key: string, value: number | null | undefined, limit: number | undefined, unit: string) => {
    if (value === null || value === undefined) return;
    lines.push({
      key,
      params: { value: `${formatGap(value)} ${unit}`, limit: limit === undefined ? '—' : `${formatGap(limit)} ${unit}` },
      over: limit !== undefined && value > limit,
    });
  };
  add('models.import.measure.load', measurements.load_ms, budgets?.max_load_ms, 'ms');
  add('models.import.measure.latency', measurements.single_row_ms, budgets?.max_predict_ms, 'ms');
  add('models.import.measure.memory', measurements.model_memory_mb, budgets?.max_memory_mb, 'MB');
  return lines;
}

/** Measured gaps between the importer's expected outputs and this reader's. */
export function validationGaps(metrics: RuntimeGaps | null | undefined, tolerances?: Partial<RuntimeTolerances> | null): GapLine[] {
  if (!metrics) return [];
  return gapLines({ metrics, tolerances: tolerances ?? {} } as RuntimeAttestation);
}

export interface ImportEvidence {
  rows: number | null;
  estimator: string | null;
  archiveSha: string | null;
  requirements: string[];
  gaps: GapLine[];
  measures: MeasureLine[];
}

/** An imported model's provenance and validation, read off its card payload. */
export function importEvidence(model: ModelDto | null | undefined): ImportEvidence | null {
  if (!isImported(model)) return null;
  const metrics = (model?.metrics ?? {}) as Record<string, any>;
  const params = ((model as unknown as { params?: Record<string, any> })?.params ?? {}) as Record<string, any>;
  const validation = metrics['import']?.validation ?? {};
  const provenance = params['import'] ?? {};
  return {
    rows: typeof validation.rows === 'number' ? validation.rows : null,
    estimator: typeof provenance.estimator === 'string' ? provenance.estimator : null,
    archiveSha: typeof provenance.archive_sha256 === 'string' ? provenance.archive_sha256.slice(0, 12) : null,
    requirements: Array.isArray(provenance.requirements) ? provenance.requirements.slice(0, 12) : [],
    gaps: validationGaps(validation.metrics, validation.tolerances),
    measures: measurementLines(validation.measurements, validation.budgets),
  };
}

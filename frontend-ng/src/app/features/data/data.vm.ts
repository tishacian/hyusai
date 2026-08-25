/**
 * Dataset-specific view-model bits, free of Angular.
 *
 * Rendering logic shared with every other tabular surface lives in
 * `shared/ui/data-table.vm.ts`; this module only holds what is specific to a
 * dataset row (its lifecycle and its provenance cue).
 */

export type DatasetSource = 'upload' | 'transform' | 'score' | 'generated';
export type DatasetStatus = 'pending' | 'ingesting' | 'ready' | 'failed' | 'deleted';

/** Statuses the worker is still working through; surfaces poll while any holds. */
export const DATASET_ACTIVE_STATUSES: readonly DatasetStatus[] = ['pending', 'ingesting'];

export function isActiveStatus(status: DatasetStatus | undefined | null): boolean {
  return !!status && DATASET_ACTIVE_STATUSES.includes(status);
}

/**
 * The ingest steps the worker reports, in order — a mirror of the backend's
 * `INGEST_STEPS`. A row carries the step it is on as a bare code in
 * `status_detail` precisely so the sentence can be French here and English
 * there; a rename on either side is a bug on both.
 */
export const INGEST_STEPS: readonly string[] = ['queued', 'reading', 'profiling', 'writing'];

/**
 * Dictionary key for the step a row is on, or the queued one when it names none.
 *
 * Unknown text is refused rather than shown: a worker from an older deployment
 * may still be writing a sentence, and a raw English sentence on a French page
 * is exactly what the codes exist to prevent.
 */
export function ingestStepKey(detail: string | null | undefined): string {
  const step = (detail ?? '').trim();
  return INGEST_STEPS.includes(step)
    ? `data.progress.step.${step}`
    : 'data.progress.step.queued';
}

/** Lucide icon for a dataset origin — the list's at-a-glance provenance cue. */
export function sourceIcon(source: DatasetSource | undefined): string {
  switch (source) {
    case 'transform':
      return 'git-branch';
    case 'score':
      return 'target';
    case 'generated':
      return 'sparkles';
    default:
      return 'table';
  }
}

/** The model that wrote a scored dataset's extra columns. */
export interface DatasetLineageModel {
  model_id?: string;
  slug?: string;
  version?: number;
  task?: string;
  algo?: string;
  target?: string;
}

/** How a produced dataset came to exist, as the detail page tells it. */
export interface DatasetLineage {
  engine?: string;
  model?: DatasetLineageModel;
  added_columns?: string[];
  output_model?: string;
  models?: string[];
  tests_total?: number;
  tests_failed?: number;
  code_lines?: number;
  duration_ms?: number;
}

/**
 * Columns this dataset does not owe to its parent.
 *
 * A scored dataset is its input plus a prediction, a confidence and a score,
 * and the whole point of the lineage thread is that those three are visibly
 * attributed: a column nobody uploaded and nobody wrote a statement for must
 * say where it came from, on the row itself.
 */
export function scoredColumns(lineage: DatasetLineage | null | undefined): Set<string> {
  const added = lineage?.added_columns;
  if (!Array.isArray(added)) return new Set();
  return new Set(added.filter((name): name is string => typeof name === 'string' && !!name));
}

/**
 * `churn-risk v3` — the model credited on a scored column and in the chain.
 *
 * Returns `null` rather than a partial label when the block names no model:
 * a badge that says "scored by" and then nothing is worse than no badge.
 */
export function scoredByLabel(lineage: DatasetLineage | null | undefined): string | null {
  const model = lineage?.model;
  const slug = typeof model?.slug === 'string' ? model.slug.trim() : '';
  if (!slug) return null;
  const version = model?.version;
  return typeof version === 'number' && Number.isFinite(version)
    ? `${slug} v${version}`
    : slug;
}

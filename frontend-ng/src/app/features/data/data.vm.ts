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
 * The step code and the row count a `status_detail` carries, e.g. `profiling:8412`.
 *
 * Unknown text is refused rather than shown: a worker from an older deployment
 * may still be writing a sentence, and a raw English sentence on a French page
 * is exactly what the codes exist to prevent.
 */
export function parseIngestDetail(detail: string | null | undefined): {
  step: string;
  rows: number | null;
} {
  const [head, tail] = (detail ?? '').trim().split(':', 2);
  const step = INGEST_STEPS.includes(head) ? head : INGEST_STEPS[0];
  const rows = Number(tail);
  return { step, rows: Number.isFinite(rows) && rows > 0 ? rows : null };
}

/**
 * Dictionary key for the step a row is on, or the queued one when it names none.
 */
export function ingestStepKey(detail: string | null | undefined): string {
  return `data.progress.step.${parseIngestDetail(detail).step}`;
}

/** One line of the ingest check-list: where the worker got to, and where it is. */
export interface IngestStep {
  step: string;
  /**
   * Dictionary key for this line's sentence — the `.counted` variant once the
   * row count is known, so the template renders a key rather than choosing one.
   */
  key: string;
  /** Rows counted so far, on the line that knows the number. */
  rows: number | null;
  state: 'done' | 'active' | 'todo';
}

/**
 * The whole ingest as a check-list, with the steps already passed ticked off.
 *
 * One line at a time is what a spinner is: it says something is happening and
 * nothing about how much is left. Because the step order is known on both sides
 * (:data:`INGEST_STEPS` mirrors the worker's tuple), a row that says
 * `profiling` also says that `queued` and `reading` are behind it — so the list
 * can be drawn complete from a single poll, without the worker sending it.
 *
 * A finished row returns every line done, which is what makes the check-list
 * settle rather than vanish: the reader sees the file was parsed, profiled and
 * written, not merely that a spinner stopped.
 */
export function ingestChecklist(
  status: DatasetStatus | undefined | null,
  detail: string | null | undefined,
): IngestStep[] {
  const settled = status === 'ready';
  const { step, rows } = parseIngestDetail(detail);
  const at = settled ? INGEST_STEPS.length : INGEST_STEPS.indexOf(step);
  const counted = INGEST_STEPS.indexOf('profiling');
  return INGEST_STEPS.map((name, index) => {
    // The count belongs to the step that produced it and to the ones after it:
    // once the rows are known they stay known, and repeating them reads as the
    // same fact rather than as new news.
    const withCount = rows !== null && index >= counted;
    return {
      step: name,
      key: `data.progress.step.${name}${withCount ? '.counted' : ''}`,
      rows: withCount ? rows : null,
      state: index < at ? 'done' : index === at ? 'active' : 'todo',
    };
  });
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

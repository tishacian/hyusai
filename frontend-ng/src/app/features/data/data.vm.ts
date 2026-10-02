/**
 * Dataset-specific view-model bits, free of Angular.
 *
 * Rendering logic shared with every other tabular surface lives in
 * `shared/ui/data-table.vm.ts`; this module only holds what is specific to a
 * dataset row (its lifecycle and its provenance cue).
 */

export type DatasetSource = 'upload' | 'transform' | 'score' | 'generated' | 'postgresql';
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
 * The steps a batch score reports — a mirror of the backend's `SCORE_STEPS`.
 *
 * A different list rather than a longer shared one: an upload never scores and
 * a score never profiles under its own name, so one merged vocabulary would
 * draw every reader a line for a step their row will never reach.
 */
export const SCORE_STEPS: readonly string[] = ['queued', 'reading', 'scoring', 'writing'];

/**
 * Which vocabulary a row's progress is written in, decided by what made it.
 *
 * The step codes are only meaningful against the list the producer used, so the
 * source is not decoration here: read `scoring:0/30` against the ingest list and
 * it falls back to `queued`, which is a check-list that says nothing while
 * looking like it is working.
 */
export function stepsFor(source: DatasetSource | undefined | null): readonly string[] {
  return source === 'score' ? SCORE_STEPS : INGEST_STEPS;
}

/**
 * The step code and the count a `status_detail` carries — `profiling:8412` from
 * an ingest, `scoring:3000/6903` from a score.
 *
 * Unknown text is refused rather than shown: a worker from an older deployment
 * may still be writing a sentence, and a raw English sentence on a French page
 * is exactly what the codes exist to prevent.
 *
 * A score's count is a position out of a total, and only the total is rendered:
 * "scoring 6 903 rows" is the fact a reader wants, where "3 000" alone reads as
 * a row count that keeps changing.
 */
export function parseIngestDetail(
  detail: string | null | undefined,
  source: DatasetSource | undefined | null = 'upload',
): {
  step: string;
  rows: number | null;
} {
  const steps = stepsFor(source);
  const [head, tail] = (detail ?? '').trim().split(':', 2);
  const step = steps.includes(head) ? head : steps[0];
  const rows = Number((tail ?? '').split('/').pop());
  return { step, rows: Number.isFinite(rows) && rows > 0 ? rows : null };
}

/**
 * Dictionary key for the step a row is on, or the queued one when it names none.
 */
export function ingestStepKey(
  detail: string | null | undefined,
  source: DatasetSource | undefined | null = 'upload',
): string {
  return `data.progress.step.${parseIngestDetail(detail, source).step}`;
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
  source: DatasetSource | undefined | null = 'upload',
): IngestStep[] {
  const steps = stepsFor(source);
  const settled = status === 'ready';
  const { step, rows } = parseIngestDetail(detail, source);
  const at = settled ? steps.length : steps.indexOf(step);
  // The step that first knows the height: an ingest learns it by profiling, a
  // score is told it by the table it was handed.
  const counted = steps.indexOf(source === 'score' ? 'scoring' : 'profiling');
  return steps.map((name, index) => {
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
    case 'postgresql':
      return 'database';
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
  postgresql?: {
    database: string; schema: string; table: string; columns: string[];
    captured_at: string; mode: 'snapshot'; row_count: number; truncated: false;
    schema_fingerprint: string; snapshot_sha256: string; text_columns: string[];
  };
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

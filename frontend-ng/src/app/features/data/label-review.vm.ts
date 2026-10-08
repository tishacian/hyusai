export interface LabelReviewSubmission {
  dataset_id: string;
  sha256: string;
  acknowledged: true;
  corrections: Array<{ row_id: number; label: string }>;
}

export interface LabelReviewPage {
  decision_id: string;
  dataset_id: string;
  dataset_name: string;
  source_version: number;
  sha256: string;
  label_column: string;
  labels: string[];
  text_columns: string[];
  total: number;
  offset: number;
  rows: Array<{ row_id: number; values: Record<string, string | null>; label: string }>;
}

export function sameLabelReview(a: LabelReviewPage, b: LabelReviewPage): boolean {
  return a.decision_id === b.decision_id && a.dataset_id === b.dataset_id
    && a.sha256 === b.sha256 && a.source_version === b.source_version && a.total === b.total
    && a.label_column === b.label_column && JSON.stringify(a.labels) === JSON.stringify(b.labels);
}

/** Only classes and stable row IDs in the inspected page can be edited. */
export function updateLabelCorrection(page: LabelReviewPage, previous: Readonly<Record<number, string>>, rowId: number, label: string): Record<number, string> {
  const row = page.rows.find(row => row.row_id === rowId);
  if (!row || !Number.isInteger(rowId) || !page.labels.includes(label)) return { ...previous };
  const next = { ...previous };
  if (label === row.label) delete next[rowId];
  else next[rowId] = label;
  return next;
}

export function labelReviewSubmission(page: LabelReviewPage | null, corrections: Readonly<Record<number, string>>, acknowledged: boolean): LabelReviewSubmission | null {
  if (!page || !acknowledged) return null;
  const changes = Object.entries(corrections).map(([row, label]) => ({ row_id: Number(row), label })).sort((a, b) => a.row_id - b.row_id);
  if (changes.some(row => !Number.isInteger(row.row_id) || row.row_id < 0 || row.row_id >= page.total || !page.labels.includes(row.label))) return null;
  return { dataset_id: page.dataset_id, sha256: page.sha256, acknowledged: true, corrections: changes };
}

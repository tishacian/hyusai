/**
 * Review workbench: the client mirror of the server rules
 * (docs/agentium-experience-lot10-review-workbench.md). The server stays the
 * authority; these functions only let the screen say why a decision cannot be
 * sent yet. Free of Angular so the unit runner can load it.
 */

export type ReviewDecisionKind = 'approve' | 'correct' | 'reject';
export type ReviewItemStatus = 'pending' | ReviewDecisionKind;

export interface ReviewCategory {
  key: string;
  label: string;
  description?: string;
  severities: string[];
}

export interface ReviewTaxonomy {
  categories: ReviewCategory[];
  comment_required_for: string[];
  severity_weights?: Record<string, number>;
  severity_order?: string[];
}

export interface ReviewTier {
  key: string;
  label: string;
  unlock_after: { tiers: string[]; threshold: number } | null;
}

export interface ReviewSetView {
  id: string;
  namespace: string;
  group_key: string;
  group_labels: Record<string, string>;
  title: string;
  taxonomy: ReviewTaxonomy;
  policy: { tiers: ReviewTier[]; package_weight: number };
  status: 'open' | 'closed';
  item_count: number;
  decided_count: number;
  progress: number;
  deadline_at: string | null;
  completed_at: string | null;
}

export interface ReviewPackage {
  key: string;
  tier: string;
  locked: boolean;
  items: number;
  decided: number;
  weight: number;
  duration_ms: number;
}

export interface ReviewStats {
  items: number;
  decided: number;
  by_decision: Record<ReviewDecisionKind, number>;
  by_category: Record<string, Record<string, number>>;
  penalty: number;
  penalty_per_1000_weight: number | null;
  duration_ms: number;
}

export interface ReviewSetDetail extends ReviewSetView {
  stats: ReviewStats;
  packages: ReviewPackage[];
}

export interface ReviewReference {
  source?: string;
  target?: string;
  score?: number;
  label?: string;
}

export interface ReviewFinding {
  category?: string;
  severity?: string;
  text?: string;
  fixed?: boolean;
}

export interface ReviewSubject {
  source?: string;
  candidate?: string;
  direction?: 'ltr' | 'rtl';
  context?: { before?: string[]; after?: string[] };
  references?: ReviewReference[];
  findings?: ReviewFinding[];
  protected_spans?: string[];
  [key: string]: unknown;
}

export interface ReviewItemView {
  id: string;
  item_ref: string;
  tier: string;
  weight: number;
  revision: number;
  status: ReviewItemStatus;
  worst_severity: string | null;
  categories: string[];
  claimed_by: string | null;
  decided_by: string | null;
  decided_at: string | null;
  duration_ms: number;
  subject?: ReviewSubject;
}

export interface ReviewItemPage {
  total: number;
  offset: number;
  limit: number;
  items: ReviewItemView[];
}

export interface ReviewAnnotation {
  category: string;
  severity: string;
}

export interface ReviewDraft {
  value: string;
  annotations: ReviewAnnotation[];
  comment: string;
  reject: boolean;
}

/** The decision a draft would send, the way the server infers `auto`. */
export function draftDecision(subject: ReviewSubject | undefined, draft: ReviewDraft): ReviewDecisionKind {
  if (draft.reject) return 'reject';
  return draft.value === (subject?.candidate ?? '') ? 'approve' : 'correct';
}

/** First protected span the value drops or reorders, or null. */
export function lostProtectedSpan(subject: ReviewSubject | undefined, value: string): string | null {
  let cursor = 0;
  for (const span of subject?.protected_spans ?? []) {
    if (typeof span !== 'string' || !span) continue;
    const found = value.indexOf(span, cursor);
    if (found < 0) return span;
    cursor = found + span.length;
  }
  return null;
}

export type DraftProblem =
  | 'value_empty'
  | 'protected_span_lost'
  | 'annotations_on_approve'
  | 'comment_required';

/** Why the draft cannot be sent yet; an empty list means it can. */
export function draftProblems(
  taxonomy: ReviewTaxonomy,
  subject: ReviewSubject | undefined,
  draft: ReviewDraft,
): DraftProblem[] {
  const problems: DraftProblem[] = [];
  const decision = draftDecision(subject, draft);
  if (decision === 'correct') {
    if (!draft.value.trim()) problems.push('value_empty');
    else if (lostProtectedSpan(subject, draft.value)) problems.push('protected_span_lost');
  }
  if (decision === 'approve' && draft.annotations.length) problems.push('annotations_on_approve');
  const required = new Set(taxonomy.comment_required_for ?? []);
  const needsComment = decision === 'reject' || draft.annotations.some((a) => required.has(a.severity));
  if (needsComment && !draft.comment.trim()) problems.push('comment_required');
  return problems;
}

/** Set, change or clear the severity of one category (one annotation per category). */
export function toggleAnnotation(
  annotations: ReviewAnnotation[],
  category: string,
  severity: string | null,
): ReviewAnnotation[] {
  const rest = annotations.filter((a) => a.category !== category);
  return severity ? [...rest, { category, severity }] : rest;
}

/** Elapsed time a reader actually spent: pauses (hidden tab) excluded. */
export class ReviewTimer {
  private started: number | null = null;
  private spent = 0;

  constructor(private readonly now: () => number = () => Date.now()) {}

  start(): void {
    if (this.started === null) this.started = this.now();
  }

  pause(): void {
    if (this.started !== null) {
      this.spent += this.now() - this.started;
      this.started = null;
    }
  }

  /** Returns the time spent so far and starts a new measure. */
  take(): number {
    this.pause();
    const value = Math.max(0, Math.round(this.spent));
    this.spent = 0;
    this.start();
    return value;
  }
}

/** Two-axis grouping of sets for the progress matrix. */
export function matrixOf(
  sets: ReviewSetView[],
  rowLabel: string,
  columnLabel: string,
): { rows: string[]; columns: string[]; cell: (row: string, column: string) => ReviewSetView[] } {
  const rows = new Set<string>();
  const columns = new Set<string>();
  const cells = new Map<string, ReviewSetView[]>();
  for (const set of sets) {
    const row = set.group_labels?.[rowLabel] ?? set.group_key;
    const column = set.group_labels?.[columnLabel] ?? '';
    rows.add(row);
    columns.add(column);
    const key = `${row}\u0000${column}`;
    cells.set(key, [...(cells.get(key) ?? []), set]);
  }
  const sort = (values: Set<string>) => [...values].sort((a, b) => a.localeCompare(b));
  return {
    rows: sort(rows),
    columns: sort(columns),
    cell: (row, column) => cells.get(`${row}\u0000${column}`) ?? [],
  };
}

/** Overdue, due within a day, or neither, for the deadline badge. */
export function deadlineState(deadline: string | null, now = Date.now()): 'overdue' | 'soon' | 'none' {
  if (!deadline) return 'none';
  const due = Date.parse(deadline.endsWith('Z') || deadline.includes('+') ? deadline : `${deadline}Z`);
  if (Number.isNaN(due)) return 'none';
  if (due <= now) return 'overdue';
  return due - now <= 24 * 3600 * 1000 ? 'soon' : 'none';
}

/** Results newer than the reserved one. Runs arrive newest first. */
export function laterResults<T extends { id: string }>(runs: readonly T[], reservedRunId: string | undefined): T[] {
  const reserved = runs.findIndex((run) => run.id === reservedRunId);
  return reserved >= 0 ? runs.slice(0, reserved) : runs.filter((run) => run.id !== reservedRunId);
}

/** Refusals a person can act on; any other stop keeps the generic message. */
const REFUSAL_MESSAGES: Record<string, string> = {
  unchanged_draft: 'flow.review.refused.unchanged_draft',
  stale_reread: 'flow.review.refused.stale_reread',
  not_later: 'flow.review.refused.not_later',
};

export function reviewRefusalKey(code: unknown): string {
  return (typeof code === 'string' && REFUSAL_MESSAGES[code]) || 'flow.review.error';
}

/**
 * Where a reservation stands: 1 to raise, 2 to reread the corrected draft,
 * 3 to confirm the reread correction, 4 to compare with a later result, 5 closed.
 */
export function reviewStep(
  row: { draft_hash?: string | null; correction_hash?: string | null; same_object?: boolean } | null | undefined,
): number {
  if (!row) return 1;
  if (row.same_object) return 5;
  if (row.correction_hash) return 4;
  if (row.draft_hash) return 3;
  return 2;
}

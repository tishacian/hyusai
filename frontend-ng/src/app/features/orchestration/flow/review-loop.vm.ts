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

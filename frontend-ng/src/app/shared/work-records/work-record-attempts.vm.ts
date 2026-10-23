/** One line of a Work record's attempt list. */
export interface AttemptLine<T> {
  runId: string;
  /** The ledger row, or null for a known Run the ledger does not hold yet. */
  attempt: T | null;
}

export interface AttemptsView<T> {
  lines: AttemptLine<T>[];
  /** The ledger is known to miss attempts: a Run shown elsewhere is absent. */
  historyIncomplete: boolean;
  /** Nothing to list, and nothing known to be missing. */
  empty: boolean;
}

/**
 * Attempts of a record as the reader should see them.
 *
 * The ledger only holds Runs started since it exists. When the page already
 * shows a Run of this record that the fully read ledger does not contain,
 * that Run is listed first and the history is said to be incomplete, instead
 * of claiming there is no attempt.
 */
export function attemptsView<T extends { run_id: string }>(
  attempts: readonly T[],
  hasMore: boolean,
  currentRunId: string | null | undefined,
): AttemptsView<T> {
  const lines: AttemptLine<T>[] = attempts.map((attempt) => ({ runId: attempt.run_id, attempt }));
  const missing = !!currentRunId && !hasMore && !attempts.some((attempt) => attempt.run_id === currentRunId);
  if (missing) lines.unshift({ runId: currentRunId!, attempt: null });
  return { lines, historyIncomplete: missing, empty: !lines.length };
}

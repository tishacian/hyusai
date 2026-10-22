/**
 * RunFollowUp — the server-derived follow-up state of a Run.
 *
 * The backend keeps `Run.status` with its engine meaning and adds
 * `follow_up` (native status + business state + cause). Every surface that
 * labels a Run reads it through these helpers, so a planned stop at a review
 * boundary is never shown as "Cancelled" or "Run failed" on one screen and as
 * a success on another.
 */

export type RunBusinessState =
  | 'in_progress'
  | 'awaiting_human_decision'
  | 'paused_for_debug'
  | 'stopped_at_review_boundary'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'unknown';

export interface RunFollowUpCause {
  code: string;
  boundary?: 'human_gate' | 'policy_gate' | string;
  node_id?: string;
  decision_id?: string;
}

export interface RunFollowUpAttempt {
  /** Evaluation retry number, when the Run is a retry of a campaign case. */
  index: number | null;
  /** The Run this attempt repeats (replay or evaluation retry). */
  previous_run_id: string | null;
}

export interface RunFollowUp {
  native_status: string;
  business_state: RunBusinessState | string;
  cause: RunFollowUpCause | null;
  /** Absent on older servers; null when the Run repeats nothing. */
  attempt?: RunFollowUpAttempt | null;
}

interface FollowUpCarrier {
  status?: string | null;
  follow_up?: RunFollowUp | null;
}

/**
 * i18n key of the label to show for a Run. Projections that predate
 * `follow_up` fall back to the native status key.
 */
export function runStatusKey(run: FollowUpCarrier | null | undefined): string | null {
  const state = run?.follow_up?.business_state;
  if (state) return `runs.follow_up.${state}`;
  return run?.status ? `runs.status.${run.status}` : null;
}

/**
 * Translate a Run's follow-up label; an unknown key stays visible as the raw
 * value rather than becoming a blank chip.
 */
export function runStatusLabel(
  run: FollowUpCarrier | null | undefined,
  t: (key: string) => string,
): string {
  const key = runStatusKey(run);
  if (!key) return '';
  const label = t(key);
  if (label !== key) return label;
  return run?.follow_up?.business_state ?? run?.status ?? '';
}

/** True when the Run stopped where its evaluation planned to stop. */
export function stoppedAtReviewBoundary(run: FollowUpCarrier | null | undefined): boolean {
  return run?.follow_up?.business_state === 'stopped_at_review_boundary';
}

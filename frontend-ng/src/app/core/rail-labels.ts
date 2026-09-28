/**
 * Readable rail (L27) — when the Cockpit rail shows its zone names.
 *
 * The member's experience record (`GET /auth/workspaces/{slug}/me/experience`)
 * carries `rail_labels` and the server-owned `first_seen_at`:
 *
 * - `shown` / `hidden`: the member's explicit choice, always wins;
 * - `auto` (default): labels during the member's first two weeks in the
 *   workspace, counted from `first_seen_at`, then icons only.
 *
 * Deliberately dependency-free so the rule is unit-tested in plain Node.
 */

export type RailLabelsPreference = 'auto' | 'shown' | 'hidden';

export const RAIL_LABELS_AUTO_DAYS = 14;

const DAY_MS = 24 * 60 * 60 * 1000;

export function isRailLabelsPreference(value: unknown): value is RailLabelsPreference {
  return value === 'auto' || value === 'shown' || value === 'hidden';
}

/**
 * Whether the rail shows its labels.
 *
 * `auto` without a readable `first_seen_at` hides them: the server stamps the
 * date on the first read, so a missing one means an older backend or a failed
 * load, and the expert rail is the state that never has to be taken back.
 * A `first_seen_at` in the future (clock skew) counts as a newcomer.
 */
export function railLabelsVisible(
  preference: RailLabelsPreference | null | undefined,
  firstSeenAt: string | null | undefined,
  nowMs: number,
): boolean {
  if (preference === 'shown') return true;
  if (preference === 'hidden') return false;
  if (!firstSeenAt) return false;
  const seenMs = Date.parse(firstSeenAt);
  if (!Number.isFinite(seenMs)) return false;
  return nowMs - seenMs < RAIL_LABELS_AUTO_DAYS * DAY_MS;
}

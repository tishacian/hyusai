/**
 * Publish dialog gating. Creating a release is blocked when ready-check
 * reports blockers, or when notes are empty. Deploy is a later step.
 */

export interface ReadyCheck {
  ready: boolean;
  blockers: Array<{ code?: string; message?: string }>;
  warnings: Array<{ code?: string; message?: string }>;
}

export function canCreateRelease(input: {
  blockers: readonly unknown[];
  notes: string;
}): boolean {
  return input.blockers.length === 0 && input.notes.trim().length > 0;
}

export function canDeploy(input: { releaseId: string | null | undefined; channel: string }): boolean {
  return !!input.releaseId && (input.channel === 'pilot' || input.channel === 'live');
}

/**
 * New version detection: the revision this tab loaded versus the one the
 * server now serves. The reader is invited to refresh; nothing reloads on its
 * own, so unsaved work is never lost to a deployment.
 */
export interface BuildInfo {
  revision?: unknown;
  revision_verified?: unknown;
}

export const NEW_VERSION_CHECK_MS = 10 * 60 * 1000;

function revisionOf(info: BuildInfo | null | undefined): string | null {
  const value = typeof info?.revision === 'string' ? info.revision.trim().toLowerCase() : '';
  return value && value !== 'development' ? value : null;
}

/**
 * True only when both revisions are known, real builds and different. A
 * development build, a missing file or a failed read never raises a notice.
 */
export function newVersionAvailable(loaded: BuildInfo | null | undefined, served: BuildInfo | null | undefined): boolean {
  const before = revisionOf(loaded), now = revisionOf(served);
  return !!before && !!now && before !== now;
}

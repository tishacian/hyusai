import type { Router, UrlTree } from '@angular/router';

/**
 * Why a destination is closed (plan lot 4, PL02). Chosen from what the server
 * said, never guessed:
 * - `disabled`: the feature is off in this workspace (EXPERIENCE_V1_DISABLED,
 *   EXPERIENCE_STUDIO_V1_DISABLED, or the flags of GET /auth/workspaces);
 * - `forbidden`: the caller's role does not allow it;
 * - `not_found`: nothing at this address. An object the caller may not see is
 *   shown the same way, so its existence is not revealed;
 * - `unverifiable`: access could not be checked (network or server failure).
 */
export type AccessReason = 'disabled' | 'forbidden' | 'not_found' | 'unverifiable';
export type AccessFeature = 'work' | 'studio';

const REASONS: readonly AccessReason[] = ['disabled', 'forbidden', 'not_found', 'unverifiable'];
const FEATURES: readonly AccessFeature[] = ['work', 'studio'];

export const ACCESS_STATE_PATH = '/unavailable';

export function parseAccessReason(value: string | null | undefined): AccessReason {
  return REASONS.includes(value as AccessReason) ? (value as AccessReason) : 'not_found';
}

export function parseAccessFeature(value: string | null | undefined): AccessFeature | null {
  return FEATURES.includes(value as AccessFeature) ? (value as AccessFeature) : null;
}

/**
 * An in-app path to go back to, or null. Only a same-origin absolute path is
 * kept, so the page can never be turned into an open redirect, and it never
 * points back at itself.
 */
export function safeReturnPath(value: string | null | undefined): string | null {
  if (!value || !value.startsWith('/') || value.startsWith('//') || value.includes('\\')) return null;
  if (value === ACCESS_STATE_PATH || value.startsWith(`${ACCESS_STATE_PATH}?`)) return null;
  return value.length > 2000 ? null : value;
}

export function accessStateUrl(
  router: Router,
  reason: AccessReason,
  options: { from?: string | null; feature?: AccessFeature | null } = {},
): UrlTree {
  const queryParams: Record<string, string> = { reason };
  const from = safeReturnPath(options.from);
  if (from) queryParams['from'] = from;
  if (options.feature) queryParams['feature'] = options.feature;
  return router.createUrlTree([ACCESS_STATE_PATH], { queryParams });
}

/**
 * The reason a server error designates, for screens that load one object.
 * 403 and 404 both read as `not_found` for an object (no existence leak);
 * a feature code wins over the status.
 */
export function accessReasonFromError(error: unknown): { reason: AccessReason; feature: AccessFeature | null } {
  const status = typeof error === 'object' && error !== null && 'status' in error
    ? Number((error as { status: unknown }).status)
    : 0;
  const body = typeof error === 'object' && error !== null && 'error' in error
    ? (error as { error: unknown }).error
    : null;
  const code = errorCode(body);
  if (code === 'EXPERIENCE_V1_DISABLED') return { reason: 'disabled', feature: 'work' };
  if (code === 'EXPERIENCE_STUDIO_V1_DISABLED') return { reason: 'disabled', feature: 'studio' };
  if (status === 403 || status === 404) return { reason: 'not_found', feature: null };
  return { reason: 'unverifiable', feature: null };
}

function errorCode(body: unknown): string | null {
  if (!body || typeof body !== 'object') return null;
  const record = body as Record<string, unknown>;
  if (typeof record['code'] === 'string') return record['code'];
  const detail = record['detail'];
  if (detail && typeof detail === 'object' && typeof (detail as Record<string, unknown>)['code'] === 'string') {
    return (detail as Record<string, string>)['code'];
  }
  return null;
}

/**
 * Post-sign-in destination contract.
 *
 * A destination is an in-app path. Sign-in pages are never a destination: an
 * `/auth/*` URL that carries its own `redirectURL` is unwrapped to the page the
 * person originally asked for, so an expiry that happens on the sign-in page
 * cannot nest `/auth/signin?redirectURL=/auth/signin…`. Protocol-relative
 * (`//host`) and backslash (`/\host`) values are rejected because browsers
 * resolve them to another origin.
 */
export const DEFAULT_AUTH_REDIRECT = '/';

/** Maximum `/auth/*` wrappers unwrapped before giving up. */
const MAX_UNWRAP_DEPTH = 5;

export function isAuthPath(url: string): boolean {
  return /^\/auth(?:[/?#]|$)/.test(url);
}

function isInAppPath(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    value.startsWith('/') &&
    !value.startsWith('//') &&
    !value.startsWith('/\\')
  );
}

function nestedRedirect(url: string): string | null {
  const query = url.indexOf('?');
  if (query < 0) return null;
  const end = url.indexOf('#', query);
  const search = url.slice(query + 1, end < 0 ? undefined : end);
  return new URLSearchParams(search).get('redirectURL');
}

/**
 * Return the in-app destination carried by `value`, or `null` when there is
 * none (missing, foreign origin, or a sign-in page without a destination).
 */
export function unwrapAuthRedirect(value: unknown): string | null {
  let current: unknown = value;
  for (let depth = 0; depth <= MAX_UNWRAP_DEPTH; depth += 1) {
    if (!isInAppPath(current)) return null;
    if (!isAuthPath(current)) return current;
    current = nestedRedirect(current);
  }
  return null;
}

/** Destination to open after sign-in; the home page when there is none. */
export function normalizeAuthRedirect(value: unknown): string {
  return unwrapAuthRedirect(value) ?? DEFAULT_AUTH_REDIRECT;
}

export type SigninErrorKey =
  | 'auth.signin.error.credentials'
  | 'auth.signin.error.unavailable'
  | 'auth.signin.error.unexpected';

/**
 * Keep credential rejection separate from transport and service failures.
 * Authentication errors must never imply that a password was wrong when the
 * request did not reach a working authentication service.
 */
export function signinErrorKey(error: unknown): SigninErrorKey {
  const status = Number((error as { status?: unknown } | null)?.status);

  if (status === 401 || status === 403) return 'auth.signin.error.credentials';
  if (status === 0 || status >= 500) return 'auth.signin.error.unavailable';
  return 'auth.signin.error.unexpected';
}

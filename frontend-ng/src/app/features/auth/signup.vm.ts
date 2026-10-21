import type { WriteOutcome } from '@app/shared/ui/load-state';

/**
 * Pure view logic for the signup page (US01, report L11–L13 and L16).
 *
 * The server says whether the verification email left (`verification_email_sent`).
 * Only an explicit `true` means it did: `false` and a missing field are both
 * an account the person cannot verify yet, and the page says so with a way
 * out instead of presenting the account as ready.
 */

export interface SignupResponse {
  status?: string;
  message?: string;
  verification_email_sent?: boolean;
}

export interface ResendResponse {
  status?: string;
  verification_email_sent?: boolean;
}

/** What the page shows once the request has been sent. */
export type SignupView =
  | 'form'
  /** Account created, verification email sent. */
  | 'sent'
  /** Account created, the server says the email was not sent. */
  | 'not_sent'
  /** Account created, the server did not say whether the email was sent. */
  | 'unconfirmed'
  /** No answer: the account may or may not exist. */
  | 'unknown';

/** Form-level error, already a dictionary key. */
export type SignupErrorKey =
  | 'auth.signup.error.exists'
  | 'auth.signup.error.unavailable'
  | 'auth.signup.error.invalid'
  | 'auth.signup.error.server';

export interface SignupResult {
  readonly view: SignupView;
  readonly error: SignupErrorKey | null;
}

export function signupResult(outcome: WriteOutcome<SignupResponse | null>): SignupResult {
  switch (outcome.s) {
    case 'sent':
      return { view: 'form', error: null };
    case 'accepted':
    case 'confirmed':
      return { view: verificationView(outcome.value?.verification_email_sent), error: null };
    case 'unknown':
      return { view: 'unknown', error: null };
    case 'failed':
      return { view: 'form', error: signupErrorKey(outcome.status) };
  }
}

export function verificationView(sent: boolean | undefined | null): SignupView {
  if (sent === true) return 'sent';
  if (sent === false) return 'not_sent';
  return 'unconfirmed';
}

export function signupErrorKey(status: number | null): SignupErrorKey {
  if (status === 409) return 'auth.signup.error.exists';
  if (status === 503) return 'auth.signup.error.unavailable';
  if (status === 400 || status === 422) return 'auth.signup.error.invalid';
  return 'auth.signup.error.server';
}

/** The resend answer in the person's words: sent, not sent, or unknown. */
export type ResendState = 'idle' | 'sending' | 'sent' | 'not_sent' | 'failed' | 'unknown';

export function resendState(outcome: WriteOutcome<ResendResponse | null> | null): ResendState {
  if (!outcome) return 'idle';
  switch (outcome.s) {
    case 'sent':
      return 'sending';
    case 'accepted':
    case 'confirmed':
      return outcome.value?.verification_email_sent === true ? 'sent' : 'not_sent';
    case 'failed':
      return 'failed';
    case 'unknown':
      return 'unknown';
  }
}

export const PASSWORD_REGEX = /^(?=.*[0-9])(?=.*[a-z])(?=.*[A-Z])(?=.*[^A-Za-z0-9])(?=\S+$).{8,}$/;

export type PasswordErrorKey = 'auth.signup.error.password_weak' | 'auth.signup.error.password_mismatch';

/** Which field is wrong, so the error sits next to it and nothing typed is cleared. */
export function passwordErrors(password: string, confirm: string): {
  password: PasswordErrorKey | null;
  confirm: PasswordErrorKey | null;
} {
  return {
    password: PASSWORD_REGEX.test(password) ? null : 'auth.signup.error.password_weak',
    confirm: password === confirm ? null : 'auth.signup.error.password_mismatch',
  };
}

import { Observable, TimeoutError, of, throwError, type OperatorFunction } from 'rxjs';
import { catchError, map, startWith, timeout } from 'rxjs/operators';

/**
 * The state contract every screen follows (plan UI/UX, lot 2a).
 *
 * A read is never collapsed into an empty list, a zero or a default value:
 * it is `loading`, `ready`, `empty` (the server answered, there is nothing),
 * `no-results` (a search or filter matched nothing), `denied` (401/403) or
 * `error`, which keeps the last good value and its date when there is one.
 *
 * A write is never shown as saved before the server confirms it: it is
 * `sent`, `accepted` (the server took it, its effect is still pending),
 * `confirmed`, `failed` (the server refused or broke) or `unknown` (the
 * answer never came back: check before trying again, never resend blindly).
 *
 * Impact's `SourceOutcome`, the runtime slot and Work's `{kind}` results are
 * earlier drafts of the same idea and convert to it (`fromSourceOutcome`).
 */
export type LoadState<T> =
  | { readonly s: 'loading' }
  | { readonly s: 'ready'; readonly value: T; readonly at: number }
  | { readonly s: 'empty'; readonly at: number }
  | { readonly s: 'no-results'; readonly query: string }
  | { readonly s: 'denied'; readonly status: number; readonly code: string | null }
  | {
      readonly s: 'error';
      readonly status: number | null;
      readonly code: string | null;
      readonly last?: { readonly value: T; readonly at: number };
    };

export type LoadStateKind = LoadState<unknown>['s'];

export type WriteOutcome<T = unknown> =
  | { readonly s: 'sent' }
  | { readonly s: 'accepted'; readonly value: T; readonly at: number }
  | { readonly s: 'confirmed'; readonly value: T; readonly at: number }
  | { readonly s: 'failed'; readonly status: number | null; readonly code: string | null; readonly detail: string | null }
  | { readonly s: 'unknown'; readonly status: number | null; readonly code: string | null };

export type WriteOutcomeKind = WriteOutcome['s'];

/** Writes had no client deadline: past this, the answer is "unknown". */
export const WRITE_TIMEOUT_MS = 30_000;

export const LOADING: LoadState<never> = Object.freeze({ s: 'loading' });
export const SENT: WriteOutcome<never> = Object.freeze({ s: 'sent' });

/** What an HTTP failure says, without guessing at what the UI should do. */
export interface FailureFacts {
  readonly status: number | null;
  readonly code: string | null;
  readonly detail: string | null;
  /** The request ran out of time on the client (rxjs `timeout`). */
  readonly timedOut: boolean;
}

export function failureFacts(error: unknown): FailureFacts {
  if (error instanceof TimeoutError || (isObject(error) && (error as { name?: unknown }).name === 'TimeoutError')) {
    return { status: null, code: 'timeout', detail: null, timedOut: true };
  }
  if (!isObject(error)) return { status: null, code: null, detail: null, timedOut: false };
  const raw = (error as { status?: unknown }).status;
  // Angular reports a request that never reached a server as status 0.
  const status = typeof raw === 'number' && raw > 0 ? raw : null;
  const body = (error as { error?: unknown }).error;
  const detail = isObject(body) ? (body as { detail?: unknown }).detail : undefined;
  const code = pickString(isObject(detail) ? (detail as { code?: unknown; error?: unknown }).code : undefined)
    ?? pickString(isObject(detail) ? (detail as { error?: unknown }).error : undefined)
    ?? pickString(isObject(body) ? (body as { code?: unknown }).code : undefined)
    ?? (raw === 0 ? 'network' : null);
  const message = pickString(detail)
    ?? pickString(isObject(detail) ? (detail as { message?: unknown }).message : undefined)
    ?? pickString(isObject(body) ? (body as { message?: unknown }).message : undefined);
  return { status, code, detail: message, timedOut: false };
}

/** The read state of a failure; `last` keeps the data the screen already had. */
export function readFailure<T>(error: unknown, previous?: LoadState<T> | null): LoadState<T> {
  const facts = failureFacts(error);
  if (facts.status === 401 || facts.status === 403) {
    return { s: 'denied', status: facts.status, code: facts.code };
  }
  const last = lastGood(previous);
  return last
    ? { s: 'error', status: facts.status, code: facts.code, last }
    : { s: 'error', status: facts.status, code: facts.code };
}

/**
 * The outcome of a failed write. Only a server answer is a failure: a request
 * that timed out, never reached the server, or died at the gateway (502, 504)
 * may still have been applied, so its result is unknown.
 */
export function writeFailure(error: unknown): WriteOutcome<never> {
  const facts = failureFacts(error);
  if (facts.timedOut || facts.status === null || facts.status === 502 || facts.status === 504) {
    return { s: 'unknown', status: facts.status, code: facts.code };
  }
  return { s: 'failed', status: facts.status, code: facts.code, detail: facts.detail };
}

export interface ReadOptions<T> {
  /** What else counts as empty besides null/undefined. Defaults to an empty array. */
  readonly isEmpty?: (value: NonNullable<T>) => boolean;
  /** Set when the request is a search: nothing found is then `no-results`. */
  readonly query?: string | null;
  /** The state on screen, so a failed refresh keeps its last value. */
  readonly previous?: LoadState<NonNullable<T>> | null;
  readonly now?: () => number;
}

/**
 * Settles a value the server returned into `ready`, `empty` or `no-results`.
 * Null and undefined are always empty, so a `ready` value is never null.
 */
export function readValue<T>(value: T, options: ReadOptions<T> = {}): LoadState<NonNullable<T>> {
  const now = options.now?.() ?? Date.now();
  const isEmpty = options.isEmpty ?? defaultIsEmpty;
  if (value !== null && value !== undefined && !isEmpty(value as NonNullable<T>)) {
    return { s: 'ready', value: value as NonNullable<T>, at: now };
  }
  const query = options.query?.trim();
  return query ? { s: 'no-results', query } : { s: 'empty', at: now };
}

/**
 * Turns a read into a stream of states that never errors: `loading` first,
 * then exactly one settled state. The request must let its error through
 * (`propagateErrors: true` on `CanonicalApiService`).
 */
export function settleRead<T>(
  request: Observable<T>,
  options: ReadOptions<T> = {},
): Observable<LoadState<NonNullable<T>>> {
  return request.pipe(
    map((value) => readValue(value, options)),
    catchError((error: unknown) => of(readFailure<NonNullable<T>>(error, options.previous))),
    startWith(LOADING as LoadState<NonNullable<T>>),
  );
}

export interface WriteOptions<T> {
  /** The server took the write but its effect is still pending. */
  readonly accepted?: (value: T) => boolean;
  /** Client deadline; past it, the outcome is `unknown`. */
  readonly timeoutMs?: number;
  readonly now?: () => number;
}

/**
 * Turns a write into `sent`, then one settled outcome. The request must let
 * its error through; a write is never retried here.
 */
export function settleWrite<T>(request: Observable<T>, options: WriteOptions<T> = {}): Observable<WriteOutcome<T>> {
  return request.pipe(
    timeout({ first: options.timeoutMs ?? WRITE_TIMEOUT_MS }),
    map((value): WriteOutcome<T> => {
      const at = options.now?.() ?? Date.now();
      return options.accepted?.(value) ? { s: 'accepted', value, at } : { s: 'confirmed', value, at };
    }),
    catchError((error: unknown) => of<WriteOutcome<T>>(writeFailure(error))),
    startWith(SENT as WriteOutcome<T>),
  );
}

/**
 * Lets an error through when the caller asked for it, otherwise keeps the
 * historical fallback. Used by `CanonicalApiService` so every method that
 * swallowed its error can opt into the strict contract without changing
 * what existing callers receive.
 */
export function fallbackUnless<T, F>(
  policy: ErrorPolicy | undefined,
  fallback: () => F,
): OperatorFunction<T, T | F> {
  return catchError((error: unknown) => (policy?.propagateErrors ? throwError(() => error) : of(fallback())));
}

export interface ErrorPolicy {
  /** Let the transport error through instead of the historical fallback. */
  readonly propagateErrors?: boolean;
}

export const STRICT: ErrorPolicy = Object.freeze({ propagateErrors: true });

/** Impact's earlier draft of the read contract. */
export function fromSourceOutcome<T>(
  outcome: { readonly ok: true; readonly value: T } | { readonly ok: false; readonly status: number | null },
  options: ReadOptions<T> = {},
): LoadState<NonNullable<T>> {
  return outcome.ok
    ? readValue(outcome.value, options)
    : readFailure<NonNullable<T>>({ status: outcome.status }, options.previous);
}

export function lastGood<T>(state: LoadState<T> | null | undefined): { value: T; at: number } | undefined {
  if (!state) return undefined;
  if (state.s === 'ready') return { value: state.value, at: state.at };
  if (state.s === 'error') return state.last;
  return undefined;
}

/** The value a screen may show: the current one, or the last good one after a failed refresh. */
export function shownValue<T>(state: LoadState<T> | null | undefined): T | undefined {
  return lastGood(state)?.value;
}

export function isSettled(outcome: WriteOutcome | null | undefined): boolean {
  return !!outcome && outcome.s !== 'sent';
}

// --- Availability (report D08) ---------------------------------------------

/**
 * Whether a model, Skill or connector can really be used, one dimension at a
 * time. Each dimension is known true, known false, or `unknown` — never
 * guessed from another one (a delivered model is not callable until it was
 * called).
 */
export const AVAILABILITY_DIMENSIONS = [
  'delivered',
  'configured',
  'selected',
  'compatible',
  'callable',
  'executed',
  'qualified',
] as const;

export type AvailabilityDimension = (typeof AVAILABILITY_DIMENSIONS)[number];
export type AvailabilityValue = boolean | 'unknown';

export interface AvailabilityFact {
  readonly value: AvailabilityValue;
  /** Plain-language reason, already translated, shown next to the value. */
  readonly reason?: string | null;
}

export type Availability = Readonly<Record<AvailabilityDimension, AvailabilityFact>>;

/** Every dimension not given is `unknown`. */
export function availability(known: Partial<Record<AvailabilityDimension, AvailabilityValue | AvailabilityFact>> = {}): Availability {
  const out = {} as Record<AvailabilityDimension, AvailabilityFact>;
  for (const dimension of AVAILABILITY_DIMENSIONS) {
    const fact = known[dimension];
    out[dimension] = fact === undefined
      ? { value: 'unknown' }
      : typeof fact === 'object' ? fact : { value: fact };
  }
  return Object.freeze(out);
}

/** The first dimension that is not known true, in the order of the grammar. */
export function firstGap(value: Availability): AvailabilityDimension | null {
  return AVAILABILITY_DIMENSIONS.find((dimension) => value[dimension].value !== true) ?? null;
}

function defaultIsEmpty(value: unknown): boolean {
  return Array.isArray(value) && value.length === 0;
}

function isObject(value: unknown): value is object {
  return typeof value === 'object' && value !== null;
}

function pickString(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null;
}

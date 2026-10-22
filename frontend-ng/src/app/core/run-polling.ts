import { EMPTY, Observable, defer, expand, filter, fromEvent, of, switchMap, take, timer } from 'rxjs';

/** Run statuses after which nothing changes without a new execution. */
const TERMINAL = new Set(['completed', 'failed', 'cancelled']);
/** Paused on a person: the Run only moves when someone decides. */
const WAITING_ON_PERSON = new Set(['hitl_pending', 'debug_pending']);

export const RUN_POLL_FAST_MS = 2_000;
export const RUN_POLL_SLOW_MS = 5_000;
export const RUN_POLL_WAITING_MS = 30_000;
/** Fast checks for about one minute, then the slower rhythm. */
export const RUN_POLL_FAST_ATTEMPTS = 30;

/**
 * Delay before the next read of a Run, or `null` to stop.
 *
 * A running Run is read quickly at first, then less often; a Run waiting on a
 * human decision is read rarely (the decision may be taken elsewhere); a
 * terminal Run, or a read that returned nothing, is not read again.
 */
export function runPollDelay(status: string | null | undefined, attempt: number): number | null {
  if (!status || TERMINAL.has(status)) return null;
  if (WAITING_ON_PERSON.has(status)) return RUN_POLL_WAITING_MS;
  return attempt < RUN_POLL_FAST_ATTEMPTS ? RUN_POLL_FAST_MS : RUN_POLL_SLOW_MS;
}

function whenVisible(): Observable<unknown> {
  if (typeof document === 'undefined' || !document.hidden) return of(true);
  return fromEvent(document, 'visibilitychange').pipe(
    filter(() => !document.hidden),
    take(1),
  );
}

/**
 * Read a Run now, then again on the rhythm of {@link runPollDelay}, pausing
 * while the tab is hidden. Emits every read; completes when the Run is
 * terminal or a read returns nothing. Errors reach the subscriber.
 */
export function pollRun<T extends { status?: string | null }>(read: () => Observable<T | null>): Observable<T | null> {
  let attempt = 0;
  return defer(read).pipe(
    expand((run) => {
      const delay = runPollDelay(run?.status, attempt++);
      if (delay === null) return EMPTY;
      return timer(delay).pipe(
        switchMap(() => whenVisible()),
        switchMap(() => read()),
      );
    }),
  );
}

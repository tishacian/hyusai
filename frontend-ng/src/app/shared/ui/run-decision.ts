import { Observable, filter, map, of, startWith, switchMap, take, throwError } from 'rxjs';
import type { CanonicalApiService, Run } from '@app/core/canonical-api.service';
import { STRICT, settleRead, settleWrite, type WriteOutcome } from './load-state';

/**
 * A human decision on a paused Run (`POST /runs/{id}/hitl`), under the shared
 * write contract.
 *
 * The server only accepts the decision it is waiting for
 * (`expected_decision_id`) and answers 409 to any other, so sending twice can
 * never record two decisions. What the client must not do is call a lost
 * answer "refused": a timeout, a network cut or a gateway error is `unknown`,
 * and the screen offers to check (`checkDecision`) before deciding again.
 */
export type DecisionAction = 'accept' | 'reject';
export type DecisionBody = Parameters<CanonicalApiService['resolveRunHitl']>[1];
export type DecisionOutcome = WriteOutcome<Run>;

/** What the server holds for a pause after an unknown outcome. */
export type DecisionCheck =
  | { readonly s: 'checking' }
  | { readonly s: 'recorded'; readonly run: Run }
  | { readonly s: 'pending'; readonly run: Run }
  | { readonly s: 'unknown' };

export function decideRun(
  canonical: Pick<CanonicalApiService, 'resolveRunHitl'>,
  runId: string,
  body: DecisionBody,
): Observable<DecisionOutcome> {
  if (!body.expected_decision_id) {
    // Without the decision it saw, the client cannot prove which pause it
    // answers: the server would answer 409 anyway.
    return settleWrite(throwError(() => ({ status: 409, error: { detail: { code: 'no_pending_decision' } } })));
  }
  return settleWrite(canonical.resolveRunHitl(runId, body, STRICT)).pipe(
    // The server always answers with the Run; an empty body proves nothing.
    map((outcome): DecisionOutcome => (outcome.s === 'confirmed' || outcome.s === 'accepted') && !outcome.value
      ? { s: 'unknown', status: null, code: 'empty_answer' }
      : outcome as DecisionOutcome),
  );
}

/** Reconcile the observed pause with its authoritative decision receipt. */
export function checkDecision(
  canonical: Pick<CanonicalApiService, 'getRun' | 'getDecision'>,
  runId: string,
  decisionId: string | null | undefined,
): Observable<DecisionCheck> {
  if (!decisionId) return of<DecisionCheck>({ s: 'unknown' });
  return settleRead(canonical.getRun(runId, STRICT)).pipe(
    filter((state) => state.s !== 'loading'),
    take(1),
    switchMap((state): Observable<DecisionCheck> => {
      if (state.s !== 'ready' || state.value.id !== runId) return of({ s: 'unknown' });
      const run = state.value;
      if (run.status === 'hitl_pending' && run.hitl?.decision_id === decisionId) {
        return of({ s: 'pending', run });
      }
      // A cancelled Run or another pause is not evidence that this decision
      // was recorded. Read the exact receipt, with the server's access checks.
      return settleRead(canonical.getDecision(decisionId, STRICT)).pipe(
        filter((receipt) => receipt.s !== 'loading'),
        take(1),
        map((receipt): DecisionCheck => receipt.s === 'ready'
          && receipt.value.id === decisionId
          && ['accepted', 'rejected', 'applied'].includes(receipt.value.status)
          ? { s: 'recorded', run }
          : { s: 'unknown' }),
      );
    }),
    startWith<DecisionCheck>({ s: 'checking' }),
  );
}

export interface DecisionMessage {
  readonly key: string;
  readonly params?: Record<string, string | number>;
  /** `alert` for a failure or an unknown result, `status` otherwise. */
  readonly role: 'status' | 'alert';
  readonly tone: 'neutral' | 'ok' | 'neg' | 'warn';
}

/** The words for a decision outcome, in `state.decision.*`. */
export function decisionMessage(outcome: WriteOutcome<unknown>, action: DecisionAction): DecisionMessage {
  switch (outcome.s) {
    case 'sent':
      return { key: 'state.decision.sent', role: 'status', tone: 'neutral' };
    case 'accepted':
    case 'confirmed':
      return {
        key: action === 'accept' ? 'state.decision.recorded_accept' : 'state.decision.recorded_reject',
        role: 'status',
        tone: 'ok',
      };
    case 'unknown':
      return { key: 'state.decision.unknown', role: 'alert', tone: 'warn' };
    case 'failed':
      if (outcome.status === 409) return { key: 'state.decision.stale', role: 'alert', tone: 'neg' };
      if (outcome.status === 401 || outcome.status === 403) return { key: 'state.decision.denied', role: 'alert', tone: 'neg' };
      if (outcome.status === 404) return { key: 'state.decision.missing', role: 'alert', tone: 'neg' };
      if (outcome.status !== null && outcome.status < 500) {
        return outcome.detail
          ? { key: 'state.decision.refused_detail', params: { detail: outcome.detail }, role: 'alert', tone: 'neg' }
          : { key: 'state.decision.refused', role: 'alert', tone: 'neg' };
      }
      return { key: 'state.decision.server', params: { status: outcome.status ?? '—' }, role: 'alert', tone: 'neg' };
  }
}

export function checkMessage(check: DecisionCheck): DecisionMessage {
  switch (check.s) {
    case 'checking': return { key: 'state.decision.checking', role: 'status', tone: 'neutral' };
    case 'recorded': return { key: 'state.decision.check_recorded', role: 'status', tone: 'ok' };
    case 'pending': return { key: 'state.decision.check_pending', role: 'status', tone: 'warn' };
    case 'unknown': return { key: 'state.decision.check_unknown', role: 'alert', tone: 'warn' };
  }
}

/** A decision may be sent again only when nothing is in flight and no answer was lost. */
export function canDecideAgain(outcome: DecisionOutcome | null | undefined): boolean {
  return !outcome || outcome.s === 'failed';
}

import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Subject, lastValueFrom, of, throwError, toArray } from 'rxjs';
import type { Run } from '@app/core/canonical-api.service';
import { canDecideAgain, checkDecision, checkMessage, decideRun, decisionMessage } from './run-decision';

const run = { id: 'run-1', status: 'running' } as Run;
const body = { action: 'accept' as const, expected_decision_id: 'd-1' };

test('a decision is sent once with the decision it answers, strictly', async () => {
  const calls: unknown[][] = [];
  const api = { resolveRunHitl: (...args: unknown[]) => { calls.push(args); return of(run); } };
  const outcomes = await lastValueFrom(decideRun(api as never, 'run-1', body).pipe(toArray()));
  assert.deepEqual(outcomes.map((o) => o.s), ['sent', 'confirmed']);
  assert.deepEqual(calls[0].slice(0, 2), ['run-1', body]);
  assert.deepEqual(calls[0][2], { propagateErrors: true });
});

test('without the decision it saw, nothing is sent and the outcome is stale', async () => {
  const api = { resolveRunHitl: () => { throw new Error('must not be called'); } };
  const outcome = await lastValueFrom(decideRun(api as never, 'run-1', { action: 'accept', expected_decision_id: undefined }));
  assert.equal(outcome.s, 'failed');
  assert.equal(decisionMessage(outcome, 'accept').key, 'state.decision.stale');
});

test('each failure says what it is: a lost answer is never a refusal', async () => {
  const cases: Array<[unknown, string]> = [
    [{ status: 0 }, 'state.decision.unknown'],
    [{ status: 504 }, 'state.decision.unknown'],
    [{ status: 409 }, 'state.decision.stale'],
    [{ status: 403 }, 'state.decision.denied'],
    [{ status: 404 }, 'state.decision.missing'],
    [{ status: 422, error: { detail: 'Note required' } }, 'state.decision.refused_detail'],
    [{ status: 500 }, 'state.decision.server'],
  ];
  for (const [error, key] of cases) {
    const api = { resolveRunHitl: () => throwError(() => error) };
    const outcome = await lastValueFrom(decideRun(api as never, 'run-1', body));
    assert.equal(decisionMessage(outcome, 'reject').key, key, JSON.stringify(error));
  }
  const empty = await lastValueFrom(decideRun({ resolveRunHitl: () => of(null) } as never, 'run-1', body));
  assert.equal(empty.s, 'unknown', 'an empty answer proves nothing');
});

test('only a refusal may be decided again without a check', () => {
  assert.equal(canDecideAgain(null), true);
  assert.equal(canDecideAgain({ s: 'failed', status: 500, code: null, detail: null }), true);
  assert.equal(canDecideAgain({ s: 'unknown', status: null, code: 'network' }), false);
  assert.equal(canDecideAgain({ s: 'sent' }), false);
});

test('a check tells a recorded decision from a pause that still waits', async () => {
  const waiting = { id: 'run-1', status: 'hitl_pending', hitl: { decision_id: 'd-1' } } as Run;
  const states = await lastValueFrom(checkDecision({ getRun: () => of(waiting) } as never, 'run-1', 'd-1').pipe(toArray()));
  assert.deepEqual(states.map((s) => s.s), ['checking', 'pending']);
  const other = { ...waiting, hitl: { decision_id: 'd-2' } } as Run;
  const getDecision = () => of({ id: 'd-1', status: 'accepted' });
  assert.equal((await lastValueFrom(checkDecision({ getRun: () => of(other), getDecision } as never, 'run-1', 'd-1'))).s, 'recorded');
  assert.equal((await lastValueFrom(checkDecision({ getRun: () => of(run), getDecision } as never, 'run-1', 'd-1'))).s, 'recorded');
  const failing = new Subject<Run>();
  const pending = lastValueFrom(checkDecision({ getRun: () => failing } as never, 'run-1', 'd-1'));
  failing.error({ status: 500 });
  const check = await pending;
  assert.equal(check.s, 'unknown');
  assert.equal(checkMessage(check).key, 'state.decision.check_unknown');
});

test('a cancelled run or another pause never substitutes for the exact decision receipt', async () => {
  for (const receipt of [null, { id: 'd-1', status: 'proposed' }, { id: 'another', status: 'accepted' }]) {
    const api = { getRun: () => of({ ...run, status: 'cancelled' }), getDecision: () => of(receipt) };
    assert.equal((await lastValueFrom(checkDecision(api as never, 'run-1', 'd-1'))).s, 'unknown');
  }
  const unavailable = { getRun: () => of(run), getDecision: () => throwError(() => ({ status: 403 })) };
  assert.equal((await lastValueFrom(checkDecision(unavailable as never, 'run-1', 'd-1'))).s, 'unknown');
  assert.equal((await lastValueFrom(checkDecision(unavailable as never, 'run-1', null))).s, 'unknown');
});

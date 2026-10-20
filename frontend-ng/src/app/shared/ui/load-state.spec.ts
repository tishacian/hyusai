import assert from 'node:assert/strict';
import { test } from 'node:test';
import { NEVER, firstValueFrom, lastValueFrom, of, throwError, toArray } from 'rxjs';
import {
  AVAILABILITY_DIMENSIONS,
  STRICT,
  availability,
  failureFacts,
  fallbackUnless,
  firstGap,
  fromSourceOutcome,
  readFailure,
  readValue,
  settleRead,
  settleWrite,
  shownValue,
  writeFailure,
  type LoadState,
} from './load-state';

const now = () => 1_000;
const http = (status: number, detail?: unknown) => ({ status, error: detail === undefined ? null : { detail } });

test('a read starts loading and settles once', async () => {
  const states = await lastValueFrom(settleRead(of([1]), { now }).pipe(toArray()));
  assert.deepEqual(states, [{ s: 'loading' }, { s: 'ready', value: [1], at: 1_000 }]);
});

test('only a successful empty answer is empty', async () => {
  assert.deepEqual(readValue([], { now }), { s: 'empty', at: 1_000 });
  assert.deepEqual(readValue(null, { now }), { s: 'empty', at: 1_000 });
  assert.deepEqual(readValue({ items: [] }, { now, isEmpty: (v) => v.items.length === 0 }), { s: 'empty', at: 1_000 });
  const failed = await lastValueFrom(settleRead(throwError(() => http(500)), { now }));
  assert.equal(failed.s, 'error');
});

test('a search that finds nothing is no-results, not empty', () => {
  assert.deepEqual(readValue([], { query: ' invoice ' }), { s: 'no-results', query: 'invoice' });
  assert.equal(readValue([], { query: '  ' }).s, 'empty');
});

test('401 and 403 are denied; every other failure is an error with its status and code', () => {
  assert.deepEqual(readFailure(http(403, { code: 'run.approve' })), { s: 'denied', status: 403, code: 'run.approve' });
  assert.deepEqual(readFailure(http(401)), { s: 'denied', status: 401, code: null });
  assert.deepEqual(readFailure(http(500)), { s: 'error', status: 500, code: null });
  assert.deepEqual(readFailure(http(504)), { s: 'error', status: 504, code: null });
  assert.deepEqual(readFailure({ status: 0 }), { s: 'error', status: null, code: 'network' });
  assert.deepEqual(readFailure(new Error('offline')), { s: 'error', status: null, code: null });
});

test('a failed refresh keeps the last value and its date', () => {
  const previous: LoadState<number[]> = { s: 'ready', value: [1, 2], at: 500 };
  const state = readFailure(http(500), previous);
  assert.deepEqual(state, { s: 'error', status: 500, code: null, last: { value: [1, 2], at: 500 } });
  assert.deepEqual(shownValue(state), [1, 2]);
  assert.deepEqual(readFailure(http(500), state), state, 'a second failure keeps the same last value');
  assert.equal(shownValue({ s: 'empty', at: 1 }), undefined);
});

test('failure facts read the code and message from FastAPI and plain bodies', () => {
  assert.deepEqual(failureFacts(http(409, { code: 'role_changed', message: 'Role changed' })), {
    status: 409, code: 'role_changed', detail: 'Role changed', timedOut: false,
  });
  assert.deepEqual(failureFacts(http(422, 'composite_min must be <= 100')), {
    status: 422, code: null, detail: 'composite_min must be <= 100', timedOut: false,
  });
  assert.deepEqual(failureFacts({ status: 400, error: { code: 'bad', message: 'Bad' } }), {
    status: 400, code: 'bad', detail: 'Bad', timedOut: false,
  });
});

test('a write is sent, then confirmed or accepted from the server answer', async () => {
  const confirmed = await lastValueFrom(settleWrite(of({ id: 'a' }), { now }).pipe(toArray()));
  assert.deepEqual(confirmed, [{ s: 'sent' }, { s: 'confirmed', value: { id: 'a' }, at: 1_000 }]);
  const accepted = await lastValueFrom(settleWrite(of({ status: 'pending' }), { now, accepted: (v) => v.status === 'pending' }));
  assert.equal(accepted.s, 'accepted');
});

test('a write the server refused failed; a write whose answer was lost is unknown', () => {
  assert.deepEqual(writeFailure(http(409, { code: 'conflict' })), { s: 'failed', status: 409, code: 'conflict', detail: null });
  assert.deepEqual(writeFailure(http(500)), { s: 'failed', status: 500, code: null, detail: null });
  assert.deepEqual(writeFailure(http(403)), { s: 'failed', status: 403, code: null, detail: null });
  assert.deepEqual(writeFailure(http(504)), { s: 'unknown', status: 504, code: null });
  assert.deepEqual(writeFailure(http(502)), { s: 'unknown', status: 502, code: null });
  assert.deepEqual(writeFailure({ status: 0 }), { s: 'unknown', status: null, code: 'network' });
});

test('a write past its client deadline is unknown, never failed', async () => {
  const outcome = await lastValueFrom(settleWrite(NEVER, { timeoutMs: 5 }));
  assert.deepEqual(outcome, { s: 'unknown', status: null, code: 'timeout' });
});

test('fallbackUnless keeps the historical fallback unless the caller asks for the error', async () => {
  const error = http(500);
  assert.equal(await firstValueFrom(throwError(() => error).pipe(fallbackUnless(undefined, () => null))), null);
  assert.deepEqual(await firstValueFrom(throwError(() => error).pipe(fallbackUnless({}, () => []))), []);
  await assert.rejects(firstValueFrom(throwError(() => error).pipe(fallbackUnless(STRICT, () => null))), (e) => e === error);
  assert.equal(await firstValueFrom(of(3).pipe(fallbackUnless(STRICT, () => null))), 3);
});

test("Impact's SourceOutcome converts to the shared contract", () => {
  assert.deepEqual(fromSourceOutcome({ ok: true, value: [1] }, { now }), { s: 'ready', value: [1], at: 1_000 });
  assert.deepEqual(fromSourceOutcome({ ok: false, status: 403 }), { s: 'denied', status: 403, code: null });
  assert.deepEqual(fromSourceOutcome({ ok: false, status: null }), { s: 'error', status: null, code: null });
});

test('availability keeps every dimension it was not told as unknown', () => {
  const value = availability({ delivered: true, configured: { value: false, reason: 'No key' } });
  assert.deepEqual(Object.keys(value), [...AVAILABILITY_DIMENSIONS]);
  assert.deepEqual(value.delivered, { value: true });
  assert.deepEqual(value.configured, { value: false, reason: 'No key' });
  assert.deepEqual(value.callable, { value: 'unknown' });
  assert.equal(firstGap(value), 'configured');
  assert.equal(firstGap(availability(Object.fromEntries(AVAILABILITY_DIMENSIONS.map((d) => [d, true])))), null);
});

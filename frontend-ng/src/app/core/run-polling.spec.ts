import assert from 'node:assert/strict';
import { test } from 'node:test';
import { firstValueFrom, of, toArray } from 'rxjs';
import { RUN_POLL_FAST_ATTEMPTS, RUN_POLL_FAST_MS, RUN_POLL_SLOW_MS, RUN_POLL_WAITING_MS, pollRun, runPollDelay } from './run-polling';

test('a terminal Run or an empty read stops the polling', () => {
  for (const status of ['completed', 'failed', 'cancelled', null, undefined, '']) assert.equal(runPollDelay(status, 0), null);
});

test('a Run waiting on a person is read rarely, not every two seconds', () => {
  assert.equal(runPollDelay('hitl_pending', 0), RUN_POLL_WAITING_MS);
  assert.equal(runPollDelay('debug_pending', 99), RUN_POLL_WAITING_MS);
});

test('a running Run is read quickly at first, then less often', () => {
  assert.equal(runPollDelay('running', 0), RUN_POLL_FAST_MS);
  assert.equal(runPollDelay('pending', RUN_POLL_FAST_ATTEMPTS - 1), RUN_POLL_FAST_MS);
  assert.equal(runPollDelay('running', RUN_POLL_FAST_ATTEMPTS), RUN_POLL_SLOW_MS);
});

test('pollRun reads once and completes when the Run is already terminal', async () => {
  let reads = 0;
  const seen = await firstValueFrom(pollRun(() => { reads += 1; return of({ status: 'completed' }); }).pipe(toArray()));
  assert.equal(reads, 1);
  assert.deepEqual(seen, [{ status: 'completed' }]);
});

test('pollRun completes on an empty read instead of looping', async () => {
  const seen = await firstValueFrom(pollRun(() => of(null)).pipe(toArray()));
  assert.deepEqual(seen, [null]);
});

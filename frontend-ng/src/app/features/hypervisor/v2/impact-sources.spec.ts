import assert from 'node:assert/strict';
import { test } from 'node:test';
import { firstValueFrom, of, throwError } from 'rxjs';
import {
  LOADING_SOURCES,
  impactPageProblem,
  impactSourceRequests,
  settleSource,
  withSourceState,
  type SourceOutcome,
} from './impact-sources';

const ok = <T>(value: T): SourceOutcome<T> => ({ ok: true, value });
const failed = (status: number | null = 500): SourceOutcome<never> => ({ ok: false, status });

test('settleSource keeps the value of a successful request', async () => {
  assert.deepEqual(await firstValueFrom(settleSource(of([1, 2]))), { ok: true, value: [1, 2] });
});

test('settleSource turns a failure into an outcome with its HTTP status, never an empty value', async () => {
  const outcome = await firstValueFrom(settleSource(throwError(() => ({ status: 500 }))));
  assert.deepEqual(outcome, { ok: false, status: 500 });
  const network = await firstValueFrom(settleSource(throwError(() => new Error('offline'))));
  assert.deepEqual(network, { ok: false, status: null });
});

test('impactSourceRequests lets errors through and unwraps list payloads', async () => {
  const calls: Array<{ path: string; params?: Record<string, string> }> = [];
  const http = {
    get: <T>(path: string, params?: Record<string, string>) => {
      calls.push({ path, params });
      if (path === '/hypervisor/decisions') return throwError(() => ({ status: 503 }));
      if (path === '/hypervisor/series') return of({ window: '90d' } as T);
      return of({ items: [{ id: path }] } as T);
    },
  };
  const requests = impactSourceRequests(http as never, '90d');
  assert.deepEqual(await firstValueFrom(requests.series()), { window: '90d' });
  assert.deepEqual(await firstValueFrom(requests.bases()), [{ id: '/hypervisor/value-bases' }]);
  assert.deepEqual(await firstValueFrom(requests.recos()), [{ id: '/hypervisor/recommendations' }]);
  assert.deepEqual(await firstValueFrom(settleSource(requests.decisions())), { ok: false, status: 503 });
  assert.deepEqual(calls.find((call) => call.path === '/hypervisor/series')?.params, { window: '90d' });
  assert.deepEqual(calls.find((call) => call.path === '/hypervisor/decisions')?.params, { limit: '20' });
});

test('one failed source is not a page problem', () => {
  assert.equal(impactPageProblem({ series: failed(), bases: ok([]), decisions: ok([]), recos: ok([]) }), null);
  assert.equal(impactPageProblem({ series: ok(null), bases: ok([]), decisions: failed(), recos: failed() }), null);
});

test('a denied series or a total outage is a page problem', () => {
  assert.equal(
    impactPageProblem({ series: failed(403), bases: ok([]), decisions: ok([]), recos: ok([]) }),
    'experience.adoption.access_denied',
  );
  assert.equal(
    impactPageProblem({ series: failed(), bases: failed(), decisions: failed(null), recos: failed() }),
    'experience.adoption.load_failed',
  );
});

test('withSourceState changes one source and keeps the others', () => {
  const next = withSourceState(LOADING_SOURCES, 'decisions', 'unavailable');
  assert.equal(next.decisions, 'unavailable');
  assert.equal(next.series, 'loading');
  assert.equal(LOADING_SOURCES.decisions, 'loading');
  assert.equal(withSourceState(next, 'decisions', 'unavailable'), next);
});

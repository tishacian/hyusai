import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { computed, Injector, signal } from '@angular/core';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Subject } from 'rxjs';
import { WorkspaceService } from '@app/core/workspace.service';
import { ModelRuntimeComponent } from './model-runtime.component';
import { ModelRuntimeService } from './model-runtime.service';
import { runtimeActions, type RuntimeState } from './model-runtime.vm';

function runtime(overrides: Partial<RuntimeState> = {}): RuntimeState {
  return {
    model_id: 'm1', version: 1, status: 'requalification_required', supported: true, reason: null,
    producer_runtime: { 'scikit-learn': '1.9.0' }, reader_runtime: { 'scikit-learn': '1.10.0' },
    differences: [{ package: 'scikit-learn', producer: '1.9.0', reader: '1.10.0' }],
    reference: { status: 'stored', rows: 256 }, can_capture: false, can_requalify: true,
    attestations: [], jobs: {},
    tolerances: { max_label_disagreements: 0, proba_atol: 1e-6, regression_atol: 1e-9, regression_rtol: 1e-6 },
    ...overrides,
  };
}

function harness(allowed = true, initial = runtime()) {
  const calls: unknown[] = [];
  let finish!: (value: unknown) => void, fail!: (error: unknown) => void;
  const pending = () => new Promise((resolve, reject) => { finish = resolve; fail = reject; });
  const state = signal<RuntimeState | null>(initial), busy = signal(false), canRequalify = signal(allowed);
  const component = Object.assign(Object.create(ModelRuntimeComponent.prototype), {
    modelId: () => 'm1', canRequalify, generation: 0, polls: 0, timer: null,
    state, busy, error: signal(''),
    actions: computed(() => runtimeActions(state(), canRequalify(), busy())),
    api: {
      capture: (id: string) => { calls.push(['capture', id]); return pending(); },
      requalify: (id: string) => { calls.push(['requalify', id]); return pending(); },
      revoke: (id: string, attestation: string) => { calls.push(['revoke', id, attestation]); return pending(); },
      state: () => Promise.resolve(state()),
    },
  }) as any;
  return { component, calls, finish: (value: unknown) => finish(value), fail: (error: unknown) => fail(error) };
}

test('no request leaves the card without the M1 requalify capability', async () => {
  const h = harness(false, runtime({ can_capture: true }));
  await h.component.requalify(); await h.component.capture(); await h.component.revoke('a1');
  assert.deepEqual(h.calls, []);
});

test('requalify submits once and adopts the server state, then polls while work is pending', async () => {
  const h = harness();
  const first = h.component.requalify(); await h.component.requalify();
  assert.deepEqual(h.calls, [['requalify', 'm1']]);
  const queued = runtime({ jobs: { ml_requalification: { id: 'j1', kind: 'ml_requalification', status: 'queued', error: null, updated_at: null } } });
  h.finish({ job: queued.jobs.ml_requalification, started: true, runtime: queued });
  await first;
  assert.equal(h.component.state().jobs.ml_requalification.status, 'queued');
  assert.equal(h.component.busy(), false);
  assert.notEqual(h.component.timer, null);
  h.component.reset();
  assert.equal(h.component.timer, null);
  assert.equal(h.component.state(), null);
});

test('a reply that arrives after a workspace or model reset is dropped', async () => {
  const h = harness();
  const pending = h.component.requalify();
  h.component.reset();
  h.finish({ runtime: runtime({ status: 'attested' }) });
  await pending;
  assert.equal(h.component.state(), null);
});

test('a refusal shows its coded message, never a raw server detail', async () => {
  const h = harness();
  const pending = h.component.requalify();
  h.fail(new HttpErrorResponse({ status: 409, error: { detail: { code: 'ML_REFERENCE_MISSING', message: 'raw' } } }));
  await pending;
  assert.equal(h.component.error(), 'models.runtime.error.ml_reference_missing');
  assert.equal(h.component.busy(), false);
});

test('only the active attestation of this reader can be revoked', async () => {
  const attestation = {
    id: 'a1', verdict: 'qualified', error_code: null, active: true, applies_to_reader: true,
    reader_runtime: {}, producer_runtime: {}, rows_compared: 3, metrics: {}, tolerances: {},
    actor: 'u', created_at: null, revoked_at: null, revoked_by: null,
  } as const;
  const h = harness(true, runtime({ status: 'attested', can_requalify: false, attestations: [attestation] }));
  await h.component.revoke('another');
  assert.deepEqual(h.calls, []);
  const pending = h.component.revoke('a1');
  h.finish({ attestation: { ...attestation, active: false }, runtime: runtime() });
  await pending;
  assert.deepEqual(h.calls, [['revoke', 'm1', 'a1']]);
  assert.equal(h.component.state().status, 'requalification_required');
});

test('the service encodes ids and drops replies from a previous workspace', async () => {
  let current = true;
  const reply = new Subject<unknown>(), requests: unknown[] = [];
  const injector = Injector.create({ providers: [ModelRuntimeService,
    { provide: WorkspaceService, useValue: { captureRequestScope: () => 'ws', isRequestScopeCurrent: () => current } },
    { provide: HttpClient, useValue: {
      get: (url: string) => { requests.push(['GET', url]); return reply; },
      post: (url: string, body: unknown) => { requests.push(['POST', url, body]); return reply; },
      delete: (url: string) => { requests.push(['DELETE', url]); return reply; },
    } },
  ] });
  const service = injector.get(ModelRuntimeService);
  const read = service.state('a/b');
  reply.next(runtime());
  assert.equal((await read)?.status, 'requalification_required');
  const revoke = service.revoke('m 1', 'x/y');
  current = false; reply.next({ runtime: runtime() });
  assert.equal(await revoke, null);
  const unanswered = [service.requalify('m1'), service.capture('m1')].map(call => call.catch(() => 'no reply'));
  assert.deepEqual(requests, [
    ['GET', '/api/v1/ml-models/a%2Fb/runtime'],
    ['DELETE', '/api/v1/ml-models/m%201/runtime/attestations/x%2Fy'],
    ['POST', '/api/v1/ml-models/m1/runtime/requalify', {}],
    ['POST', '/api/v1/ml-models/m1/runtime/reference', {}],
  ]);
  reply.complete();
  assert.deepEqual(await Promise.all(unanswered), ['no reply', 'no reply']);
});

import '@angular/compiler';
import { Injector, runInInjectionContext, signal } from '@angular/core';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Subject, lastValueFrom, of, throwError } from 'rxjs';
import { HttpErrorResponse } from '@angular/common/http';
import { ApiService } from '@app/core/api.service';
import { CanonicalApiService, type Run } from '@app/core/canonical-api.service';
import { I18nService } from '@app/core/i18n.service';
import { EXPERIENCE_EN, EXPERIENCE_FR } from '@app/core/i18n/experience.dict';
import { NavigationProfileService } from '@app/core/navigation-profile.service';
import { NavigationResolverService } from '@app/core/navigation-resolver.service';
import { ZoomContextService } from '@app/core/zoom-context.service';
import { ExperienceRuntimeService, type RuntimePhase } from './experience-runtime.service';
import type { RuntimeNodeContext } from './model';
import { RuntimeSlotComponent, RuntimeStatusBlock } from './runtime-blocks';
import { runtimeFailureKind, runtimeFailureRunId } from './runtime-failure';

const ERROR = 'node_error_policy:forecast.predict:ml_forecast_failed: ML_ARTIFACT_LEGACY_UNSUPPORTED: private diagnostic';
const CONTEXT: RuntimeNodeContext = {
  experienceSlug: 'service', pageId: 'forecast', componentId: 'status',
  stateKey: 'status', sourceStateKey: 'forecast-action', mode: 'live',
};

function setup() {
  const run = signal<Run | null>({ id: 'failed-run', system_id: 'system', status: 'failed', error: ERROR });
  const error = signal<string | null>(ERROR);
  const phase = signal<RuntimePhase>('error');
  const profile = signal({ active: false, advancedAccess: 'hidden', admin: false });
  const blocked = signal(false);
  const context = signal(CONTEXT);
  const resolved: string[] = [];
  const injector = Injector.create({ providers: [
    { provide: ExperienceRuntimeService, useValue: {
      run: (key: string) => key === 'forecast-action' ? run() : null,
      lastError: error, phase,
    } },
    { provide: I18nService, useValue: { t: (key: string) => (EXPERIENCE_EN as Record<string, string>)[key] ?? key } },
    { provide: NavigationProfileService, useValue: { effective: profile } },
    { provide: ZoomContextService, useValue: { resolveLink: (link: { ref: string }) => ({ url: `/runs/${link.ref}?lens=operate` }) } },
    { provide: NavigationResolverService, useValue: { resolve: (url: string) => { resolved.push(url); return blocked() ? { resolvedRoute: '/work' } : null; } } },
  ] });
  const block = runInInjectionContext(injector, () => new RuntimeStatusBlock());
  Object.defineProperty(block, 'context', { value: context });
  Object.defineProperty(block, 'node', { value: () => ({ type: 'runtime_status' }) });
  return { block, run, error, phase, profile, blocked, context, resolved };
}

test('a failed model action explains the remedy without exposing diagnostics and links its producing execution', () => {
  const { block, resolved } = setup();
  assert.equal(block.label(), 'Error');
  assert.match(block.failureDescription(), /retrain it or select a compatible version/);
  assert.doesNotMatch(block.failureDescription(), /private diagnostic|ML_ARTIFACT|forecast.predict/);
  assert.equal(block.failureRunId(), 'failed-run');
  assert.equal(block.inspectableRunId(), 'failed-run');
  assert.deepEqual(resolved, ['/runs/failed-run?lens=operate']);
});

test('dependent results wait for model repair rather than recommending a blind retry in both languages', () => {
  for (const dictionary of [EXPERIENCE_EN, EXPERIENCE_FR]) {
    const injector = Injector.create({ providers: [
      { provide: I18nService, useValue: { t: (key: string) => (dictionary as Record<string, string>)[key] ?? key } },
    ] });
    const slot = runInInjectionContext(injector, () => new RuntimeSlotComponent());
    const detail = signal(ERROR);
    Object.defineProperty(slot, 'detail', { value: detail });
    for (const error of [ERROR, 'ml_predict_failed:ML_ARTIFACT_RUNTIME_MISMATCH: private diagnostic', 'ML_RUNTIME_MISSING: private diagnostic']) {
      detail.set(error);
      assert.equal(slot.errorDescription(), dictionary['experience.runtime.error.model_dependency']);
      assert.doesNotMatch(slot.errorDescription() ?? '', /try again|réessayez|private diagnostic|ML_ARTIFACT|ML_RUNTIME/i);
    }
    detail.set('unknown private diagnostic');
    assert.equal(slot.errorDescription(), dictionary['experience.runtime.error.body']);
    detail.set('');
    assert.equal(slot.errorDescription(), undefined);
  }
});

test('hidden or redirected run routes leave a reference without an inaccessible link', () => {
  const { block, profile, blocked, context } = setup();
  blocked.set(true);
  assert.equal(block.inspectableRunId(), null);
  assert.equal(block.failureRunId(), 'failed-run');
  blocked.set(false);
  profile.set({ active: true, advancedAccess: 'hidden', admin: true });
  assert.equal(block.inspectableRunId(), null);
  profile.set({ active: true, advancedAccess: 'admin_only', admin: false });
  assert.equal(block.inspectableRunId(), null);
  profile.set({ active: true, advancedAccess: 'link', admin: false });
  assert.equal(block.inspectableRunId(), 'failed-run');
  context.set({ ...CONTEXT, mode: 'preview' });
  assert.equal(block.failureRunId(), null);
  assert.equal(block.inspectableRunId(), null);
});

test('failed submissions do not reuse a previous result or misleadingly remain completed', () => {
  const { block, run, error, phase } = setup();
  run.set({ id: 'previous-success', system_id: 'system', status: 'completed' });
  error.set('http_403');
  assert.equal(block.vocab(), 'error');
  assert.match(block.failureDescription(), /current access/);
  assert.equal(block.failureRunId(), null);
  error.set('unrecognised private error');
  assert.match(block.failureDescription(), /no processing reference/);
  assert.doesNotMatch(block.failureDescription(), /private error/);
  phase.set('loading');
  assert.equal(block.vocab(), 'running');
});

test('a monitoring timeout keeps the execution inspectable without declaring that it failed', () => {
  const { block, run, error } = setup();
  run.set({ id: 'still-running', system_id: 'system', status: 'running' });
  error.set('timeout');
  assert.equal(block.label(), 'Status unavailable');
  assert.equal(block.tone(), 'warn');
  assert.match(block.failureDescription(), /may still be running/);
  assert.equal(block.inspectableRunId(), 'still-running');
});

test('only recognised codes get model-specific advice, and unrelated errors do not claim an older failure', () => {
  assert.equal(runtimeFailureKind('ML_ARTIFACT_RUNTIME_MISMATCH: versions'), 'model_incompatible');
  assert.equal(runtimeFailureKind('ml_predict_failed: ML_RUNTIME_MISSING: runtime'), 'model_unavailable');
  assert.equal(runtimeFailureKind('User text mentions ML_ARTIFACT_LEGACY_UNSUPPORTED'), 'failed');
  assert.equal(runtimeFailureKind('ML_ARTIFACT_LEGACY_UNSUPPORTED_NEW'), 'failed');
  assert.equal(runtimeFailureRunId({ id: 'older', status: 'failed', error: 'older failure' }, 'http_403'), null);
});

test('rejecting a new invocation preserves history without attaching the previous run to its error', () => {
  let reject = false;
  const injector = Injector.create({ providers: [
    { provide: ApiService, useValue: { post: () => reject
      ? throwError(() => new HttpErrorResponse({ status: 403 }))
      : of({ id: 'previous-run', system_id: 'system', status: 'completed' }) } },
    { provide: CanonicalApiService, useValue: {} },
  ] });
  const runtime = runInInjectionContext(injector, () => new ExperienceRuntimeService());
  runtime.invoke(CONTEXT, 'forecast', {}).subscribe();
  assert.equal(runtime.run(CONTEXT.stateKey)?.id, 'previous-run');
  reject = true;
  runtime.invoke(CONTEXT, 'forecast', {}).subscribe();
  assert.equal(runtime.phase(CONTEXT.stateKey), 'error');
  assert.equal(runtime.lastError(CONTEXT.stateKey), 'http_403');
  assert.equal(runtime.run(CONTEXT.stateKey), null);
  assert.equal(runtime.state(CONTEXT.stateKey).history[0].id, 'previous-run');
});

const ACTION_CONTEXT: RuntimeNodeContext = {
  ...CONTEXT, componentId: 'forecast-action', stateKey: 'forecast-action',
  releaseId: 'published-release',
};
const COMPLETED: Run = { id: 'stored-run', system_id: 'system', status: 'completed', output_ref: { dataset_id: 'produced-dataset' } };

function restorationSetup(options: { lookup?: () => any; canonical?: () => any } = {}) {
  const reads: Array<{ path: string; query: unknown }> = [], runs: string[] = [], writes: string[] = [];
  const injector = Injector.create({ providers: [
    { provide: ApiService, useValue: {
      get: (path: string, query: unknown) => { reads.push({ path, query }); return options.lookup?.() ?? of({ run: { id: COMPLETED.id } }); },
      post: (path: string) => { writes.push(path); return of({ id: 'new-click', system_id: 'system', status: 'pending' }); },
    } },
    { provide: CanonicalApiService, useValue: { getRun: (id: string) => { runs.push(id); return options.canonical?.() ?? of(COMPLETED); } } },
  ] });
  const runtime = runInInjectionContext(injector, () => new ExperienceRuntimeService());
  return { runtime, reads, runs, writes };
}

test('a fresh runtime recovers the authorised released action without submitting or enabling retry', () => {
  for (let reload = 0; reload < 2; reload++) {
    const { runtime, reads, runs, writes } = restorationSetup();
    runtime.restore(ACTION_CONTEXT, 'forecast').subscribe();
    assert.deepEqual(reads, [{
      path: '/work/service/bindings/forecast/runs/latest',
      query: { page_id: 'forecast', component_id: 'forecast-action', release_id: 'published-release' },
    }]);
    assert.deepEqual(runs, ['stored-run']);
    assert.deepEqual(writes, []);
    assert.deepEqual(runtime.run('forecast-action'), COMPLETED);
    assert.equal(runtime.phase('forecast-action'), 'idle');
    assert.equal(runtime.state('forecast-action').lastInvoke, null);
    runtime.retry(ACTION_CONTEXT).subscribe();
    assert.deepEqual(writes, []);
  }
});

test('restoration is a read and never says an action is running while locating its result', () => {
  const pending = new Subject<{ run: null }>();
  const { runtime } = restorationSetup({ lookup: () => pending });
  runtime.restore(ACTION_CONTEXT, 'forecast').subscribe();
  assert.equal(runtime.phase('forecast-action'), 'restoring');
  const { block, phase, run, error } = setup();
  phase.set('restoring'); run.set(null); error.set(null);
  assert.equal(block.label(), 'Loading the last result');
  pending.next({ run: null }); pending.complete();
  assert.equal(runtime.phase('forecast-action'), 'idle');
  assert.equal(runtime.run('forecast-action'), null);
});

test('late lookup cannot overwrite a new action or start polling an older result', () => {
  const pending = new Subject<{ run: { id: string } }>();
  const { runtime, runs, writes } = restorationSetup({ lookup: () => pending });
  runtime.restore(ACTION_CONTEXT, 'forecast').subscribe();
  runtime.invoke(ACTION_CONTEXT, 'forecast', {}).subscribe();
  pending.next({ run: { id: 'stored-run' } }); pending.complete();
  assert.equal(runtime.run('forecast-action')?.id, 'new-click');
  assert.deepEqual(runs, []);
  assert.equal(writes.length, 1);
});

test('workspace reset fences both a pending lookup and a pending canonical read', () => {
  for (const stage of ['lookup', 'canonical']) {
    const pending = new Subject<any>();
    const { runtime } = restorationSetup(stage === 'lookup' ? { lookup: () => pending } : { canonical: () => pending });
    runtime.restore(ACTION_CONTEXT, 'forecast').subscribe();
    runtime.reset();
    pending.next(stage === 'lookup' ? { run: { id: 'stored-run' } } : COMPLETED);
    pending.complete();
    assert.equal(runtime.run('forecast-action'), null);
    assert.equal(runtime.phase('forecast-action'), 'idle');
    assert.deepEqual(runtime.runs(), []);
  }
});

test('a newer restore for the same component rejects an older release response', () => {
  const pending = new Subject<any>();
  let lookup = 0;
  const { runtime, runs } = restorationSetup({ lookup: () => ++lookup === 1 ? pending : of({ run: null }) });
  runtime.restore(ACTION_CONTEXT, 'forecast').subscribe();
  runtime.restore({ ...ACTION_CONTEXT, releaseId: 'next-release' }, 'forecast').subscribe();
  pending.next({ run: { id: 'old-release-run' } }); pending.complete();
  assert.equal(runtime.run('forecast-action'), null);
  assert.deepEqual(runs, []);
});

test('reauthorisation clears cached history when the current release has no readable result', () => {
  let found = true;
  const { runtime } = restorationSetup({ lookup: () => of({ run: found ? { id: 'stored-run' } : null }) });
  runtime.restore(ACTION_CONTEXT, 'forecast').subscribe();
  assert.equal(runtime.state('forecast-action').history.length, 1);
  found = false;
  runtime.restore({ ...ACTION_CONTEXT, releaseId: 'next-release' }, 'forecast').subscribe();
  assert.deepEqual(runtime.state('forecast-action').history, []);
  assert.deepEqual(runtime.runs(), []);
});

test('in-progress restoration polls the existing Run to completion without replaying the action', async () => {
  let called = 0;
  const { runtime, writes, runs } = restorationSetup({
    canonical: () => of(++called === 1 ? { ...COMPLETED, status: 'running' } : COMPLETED),
  });
  await lastValueFrom(runtime.restore(ACTION_CONTEXT, 'forecast'));
  assert.deepEqual(runs, ['stored-run', 'stored-run']);
  assert.deepEqual(writes, []);
  assert.equal(runtime.run('forecast-action')?.status, 'completed');
});

test('restoring a failed Run preserves its failure instead of selecting an older success', () => {
  const { runtime, writes } = restorationSetup({ canonical: () => of({ ...COMPLETED, status: 'failed', error: ERROR }) });
  runtime.restore(ACTION_CONTEXT, 'forecast').subscribe();
  assert.equal(runtime.phase('forecast-action'), 'error');
  assert.equal(runtime.lastError('forecast-action'), ERROR);
  assert.deepEqual(writes, []);
});

test('lookup failures and revoked canonical access never look like no prior activity', () => {
  for (const options of [
    { lookup: () => throwError(() => new HttpErrorResponse({ status: 503 })) },
    { lookup: () => throwError(() => new HttpErrorResponse({ status: 409 })) },
    { canonical: () => of(null) },
  ]) {
    const { runtime, writes } = restorationSetup(options);
    runtime.restore(ACTION_CONTEXT, 'forecast').subscribe();
    assert.equal(runtime.phase('forecast-action'), 'error');
    assert.equal(runtime.lastError('forecast-action'), 'network');
    assert.equal(runtime.run('forecast-action'), null);
    assert.deepEqual(writes, []);
  }
});

test('a changed published release asks for reload and blocks even a pending confirmation or remount', () => {
  const { runtime, reads, writes } = restorationSetup({
    lookup: () => throwError(() => new HttpErrorResponse({ status: 409, error: { detail: { code: 'WORK_RELEASE_CHANGED' } } })),
  });
  runtime.restore(ACTION_CONTEXT, 'forecast').subscribe();
  assert.equal(runtime.lastError('forecast-action'), 'release_changed');
  runtime.restore(ACTION_CONTEXT, 'forecast').subscribe();
  assert.equal(reads.length, 1, 'remounting the obsolete release does not clear its block');
  runtime.invoke(ACTION_CONTEXT, 'forecast', {}, true).subscribe();
  assert.deepEqual(writes, []);
  assert.equal(runtimeFailureKind(runtime.lastError('forecast-action')), 'release_changed');
  const { block, run, error, phase } = setup();
  run.set(null); error.set('release_changed'); phase.set('error');
  assert.match(block.failureDescription(), /Reload the page/);
  assert.match(EXPERIENCE_FR['experience.runtime.failure.release_changed'], /Rechargez la page/);
});

test('previews and hosts without an immutable release never restore live activity', () => {
  const { runtime, reads } = restorationSetup();
  runtime.restore({ ...ACTION_CONTEXT, mode: 'preview' }, 'forecast').subscribe();
  runtime.restore({ ...ACTION_CONTEXT, releaseId: undefined }, 'forecast').subscribe();
  assert.deepEqual(reads, []);
});

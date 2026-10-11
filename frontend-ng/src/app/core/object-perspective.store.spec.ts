import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { HttpErrorResponse } from '@angular/common/http';
import { Injector, runInInjectionContext } from '@angular/core';
import { firstValueFrom, of, Subject, throwError } from 'rxjs';
import { CanonicalApiService } from './canonical-api.service';
import type { ObjectLens } from './navigation.catalog';
import {
  ObjectPerspectiveContractError,
  ObjectPerspectiveGateRevokedError,
  ObjectPerspectiveRequestSupersededError,
  ObjectPerspectiveStore,
  type ObjectPerspectiveRequest,
} from './object-perspective.store';
import {
  AuthenticationRequestInvalidatedError,
  AuthStore,
  type AuthenticationRequestScope,
} from '../store/auth.store';
import {
  WorkspaceRequestInvalidatedError,
  WorkspaceService,
  type WorkspaceRequestScope,
} from './workspace.service';
import type {
  ObjectPerspectiveFact,
  ObjectPerspectiveIdentity,
  ObjectPerspectiveResponse,
} from '@app/shared/cockpit/object-perspective.models';

type ResetCallback = () => void;

class WorkspaceScopeStub {
  slug = 'showcase';
  workspaceId = 'workspace-showcase';
  epoch = 3;
  readonly revokedFeatures: string[] = [];
  refreshes = 0;
  private readonly resetters = new Set<ResetCallback>();

  readonly currentSlug = () => this.slug;
  readonly contextEpoch = () => this.epoch;
  readonly current = () => ({
    id: this.workspaceId,
    effective_features: {
      capability_360_projection_v1: !this.revokedFeatures.includes(
        'capability_360_projection_v1',
      ),
    },
  });

  captureRequestScope(): WorkspaceRequestScope {
    return Object.freeze({
      workspaceSlug: this.slug,
      workspaceId: this.workspaceId,
      epoch: this.epoch,
    });
  }

  isRequestScopeCurrent(scope: WorkspaceRequestScope): boolean {
    return scope.workspaceSlug === this.slug
      && scope.workspaceId === this.workspaceId
      && scope.epoch === this.epoch;
  }

  registerContextReset(resetter: ResetCallback): () => void {
    this.resetters.add(resetter);
    return () => this.resetters.delete(resetter);
  }

  revokeEffectiveFeature(key: string): void {
    this.revokedFeatures.push(key);
  }

  refreshCurrentWorkspace() {
    this.refreshes += 1;
    return of(null);
  }

  advanceEpoch(slug = this.slug, notify = true): void {
    if (notify) this.resetters.forEach((resetter) => resetter());
    this.slug = slug;
    this.workspaceId = `workspace-${slug}`;
    this.epoch += 1;
  }

  replaceIdentity(workspaceId: string): void {
    this.workspaceId = workspaceId;
  }
}

class AuthenticationScopeStub {
  epoch = 5;
  private readonly resetters = new Set<ResetCallback>();

  readonly authEpoch = () => this.epoch;

  captureRequestScope(): AuthenticationRequestScope {
    return Object.freeze({ epoch: this.epoch });
  }

  isRequestScopeCurrent(scope: AuthenticationRequestScope): boolean {
    return scope.epoch === this.epoch;
  }

  registerContextReset(resetter: ResetCallback): () => void {
    this.resetters.add(resetter);
    return () => this.resetters.delete(resetter);
  }

  changePrincipal(notify = true): void {
    if (notify) this.resetters.forEach((resetter) => resetter());
    this.epoch += 1;
  }

  logout(): void {
    this.changePrincipal();
  }

  loginNewPrincipal(): void {
    this.changePrincipal();
  }
}

const FACETS = {
  capability: ['overview', 'systems', 'outcomes', 'policies'],
  run: ['overview', 'invocations', 'payloads', 'checkpoints'],
  skill_invocation: ['overview', 'io', 'runtime', 'governance'],
} as const;

function fact(value: unknown = 'ready'): ObjectPerspectiveFact {
  return {
    key: 'status',
    label: 'Status',
    state: 'available',
    value,
    source: 'test.status',
    as_of: '2026-07-22T00:00:00Z',
    sample_count: 1,
  };
}

function response(
  lens: ObjectLens,
  request: ObjectPerspectiveRequest = {
    objectType: 'capability',
    objectId: 'capability-1',
  },
  workspaceId = 'workspace-showcase',
): ObjectPerspectiveResponse {
  const identity: ObjectPerspectiveIdentity = {
    workspace_id: workspaceId,
    object_type: request.objectType,
    object_id: request.objectId,
    name: 'Contract Risk',
  };
  if (request.objectType === 'capability') identity.capability_id = request.objectId;
  if (request.objectType === 'run') identity.run_id = request.objectId;
  if (request.objectType === 'skill_invocation') {
    identity.run_id = request.runId;
    identity.skill_invocation_id = request.objectId;
  }
  return {
    schema_version: 1,
    snapshot_id: `snapshot-${request.objectType}-${request.objectId}`,
    generated_at: '2026-07-22T00:00:00Z',
    window: request.window ?? '30d',
    identity,
    header: { status: fact() },
    lens,
    facets: Object.fromEntries(
      FACETS[request.objectType].map((facet) => [facet, { blocks: [] }]),
    ),
  };
}

function createStore(
  api: Record<string, unknown>,
  workspace = new WorkspaceScopeStub(),
  auth = new AuthenticationScopeStub(),
): {
  store: ObjectPerspectiveStore;
  workspace: WorkspaceScopeStub;
  auth: AuthenticationScopeStub;
} {
  const injector = Injector.create({
    providers: [
      ObjectPerspectiveStore,
      { provide: CanonicalApiService, useValue: api },
      { provide: WorkspaceService, useValue: workspace },
      { provide: AuthStore, useValue: auth },
    ],
  });
  return {
    store: runInInjectionContext(injector, () => injector.get(ObjectPerspectiveStore)),
    workspace,
    auth,
  };
}

function gateRevocationError(objectType = 'capability'): HttpErrorResponse {
  return new HttpErrorResponse({
    status: 410,
    error: {
      detail: {
        code: 'OBJECT_PROJECTION_REVOKED',
        object_type: objectType,
      },
    },
  });
}

test('ObjectPerspectiveStore validates, preloads and caches one invariant four-lens bundle', async () => {
  const calls: Array<{ objectId: string; lens: ObjectLens; window: string }> = [];
  const request = { objectType: 'capability' as const, objectId: 'capability-1' };
  const { store } = createStore({
    getCapabilityPerspective: (objectId: string, lens: ObjectLens, window: string) => {
      calls.push({ objectId, lens, window });
      return of(response(lens, request));
    },
  });

  const first = await firstValueFrom(store.loadAll(request));
  const second = await firstValueFrom(store.loadAll(request));

  assert.deepEqual(calls.map((call) => call.lens), ['build', 'operate', 'steer', 'govern']);
  assert.ok(first.build && first.operate && first.steer && first.govern);
  assert.equal(second.build, first.build, 'same workspace epoch reuses the cached snapshot');
});

test('a late server gate revocation purges the projection and refreshes workspace authority', async () => {
  const workspace = new WorkspaceScopeStub();
  const request = { objectType: 'capability' as const, objectId: 'capability-1' };
  const { store } = createStore(
    {
      getCapabilityPerspective: () => throwError(() => gateRevocationError()),
    },
    workspace,
  );

  await assert.rejects(
    firstValueFrom(store.loadAll(request)),
    (error: unknown) => error instanceof ObjectPerspectiveGateRevokedError,
  );

  assert.deepEqual(workspace.revokedFeatures, ['capability_360_projection_v1']);
  assert.equal(workspace.current().effective_features.capability_360_projection_v1, false);
  assert.equal(workspace.refreshes, 1);
});

test('concurrent non-force loads share one authoritative four-lens request', async () => {
  const subjects = new Map<ObjectLens, Subject<ObjectPerspectiveResponse>>();
  let calls = 0;
  const request = { objectType: 'capability' as const, objectId: 'capability-1' };
  const { store } = createStore({
    getCapabilityPerspective: (_objectId: string, lens: ObjectLens) => {
      calls += 1;
      const pending = new Subject<ObjectPerspectiveResponse>();
      subjects.set(lens, pending);
      return pending;
    },
  });

  const first = firstValueFrom(store.loadAll(request));
  const second = firstValueFrom(store.loadAll(request));
  assert.equal(calls, 4, 'both subscribers join the same four reads');

  for (const lens of ['build', 'operate', 'steer', 'govern'] as const) {
    subjects.get(lens)!.next(response(lens, request));
    subjects.get(lens)!.complete();
  }

  const [firstBundle, secondBundle] = await Promise.all([first, second]);
  assert.equal(secondBundle.build, firstBundle.build, 'shareReplay returns the same validated bundle');
  assert.equal(calls, 4);
});

test('a newer force refresh wins even when it completes before the older request', async () => {
  const batches: Array<Map<ObjectLens, Subject<ObjectPerspectiveResponse>>> = [];
  let calls = 0;
  const request = { objectType: 'capability' as const, objectId: 'capability-1' };
  const { store } = createStore({
    getCapabilityPerspective: (_objectId: string, lens: ObjectLens) => {
      const batchIndex = Math.floor(calls / 4);
      calls += 1;
      const pending = new Subject<ObjectPerspectiveResponse>();
      const batch = batches[batchIndex] ?? new Map<ObjectLens, Subject<ObjectPerspectiveResponse>>();
      batch.set(lens, pending);
      batches[batchIndex] = batch;
      return pending;
    },
  });

  const first = firstValueFrom(store.loadAll(request, { forceRefresh: true }));
  const firstRejected = assert.rejects(
    first,
    (error: unknown) => error instanceof ObjectPerspectiveRequestSupersededError,
  );
  const second = firstValueFrom(store.loadAll(request, { forceRefresh: true }));

  for (const lens of ['build', 'operate', 'steer', 'govern'] as const) {
    const payload = response(lens, request);
    payload.snapshot_id = 'snapshot-refresh-2';
    payload.header = { status: fact('refresh-2') };
    batches[1].get(lens)!.next(payload);
    batches[1].get(lens)!.complete();
  }
  const secondBundle = await second;

  for (const lens of ['build', 'operate', 'steer', 'govern'] as const) {
    const payload = response(lens, request);
    payload.snapshot_id = 'snapshot-refresh-1';
    payload.header = { status: fact('refresh-1') };
    batches[0].get(lens)!.next(payload);
    batches[0].get(lens)!.complete();
  }
  await firstRejected;

  const cached = await firstValueFrom(store.loadAll(request));
  assert.equal(calls, 8, 'the obsolete completion does not evict or replace the winning cache');
  assert.equal(cached.build, secondBundle.build);
  assert.equal(cached.build.header['status'].value, 'refresh-2');
});

test('one snapshot mismatch retries all four reads once in the same request generation', async () => {
  let calls = 0;
  const request = { objectType: 'capability' as const, objectId: 'capability-1' };
  const { store } = createStore({
    getCapabilityPerspective: (_objectId: string, lens: ObjectLens) => {
      const attempt = Math.floor(calls / 4);
      calls += 1;
      const payload = response(lens, request);
      if (attempt === 0 && lens === 'operate') {
        payload.snapshot_id = 'snapshot-observed-between-reads';
      }
      return of(payload);
    },
  });

  const recovered = await firstValueFrom(store.loadAll(request));
  assert.equal(calls, 8, 'the complete four-lens bundle is read exactly one more time');
  assert.equal(recovered.build.snapshot_id, recovered.govern.snapshot_id);

  const cached = await firstValueFrom(store.loadAll(request));
  assert.equal(calls, 8, 'only the coherent retry result enters the cache');
  assert.equal(cached.build, recovered.build);
});

test('a persistent snapshot mismatch fails after one complete retry', async () => {
  let calls = 0;
  const request = { objectType: 'capability' as const, objectId: 'capability-1' };
  const { store } = createStore({
    getCapabilityPerspective: (_objectId: string, lens: ObjectLens) => {
      const attempt = Math.floor(calls / 4);
      calls += 1;
      const payload = response(lens, request);
      if (lens === 'operate') payload.snapshot_id = `snapshot-mismatch-${attempt}`;
      return of(payload);
    },
  });

  await assert.rejects(
    firstValueFrom(store.loadAll(request)),
    (error: unknown) => error instanceof ObjectPerspectiveContractError
      && error.violation === 'snapshot_id changes across lenses',
  );
  assert.equal(calls, 8, 'a persistent divergence never triggers a third read');
});

test('cache TTL is finite and forceRefresh atomically invalidates a fresh bundle', async () => {
  const originalNow = Date.now;
  let now = 1_000_000;
  Date.now = () => now;
  try {
    let calls = 0;
    const request = { objectType: 'capability' as const, objectId: 'capability-1' };
    const { store } = createStore({
      getCapabilityPerspective: (_objectId: string, lens: ObjectLens) => {
        calls += 1;
        return of(response(lens, request));
      },
    });

    await firstValueFrom(store.loadAll(request));
    await firstValueFrom(store.loadAll(request));
    assert.equal(calls, 4, 'fresh entries are reused');

    await firstValueFrom(store.loadAll(request, { forceRefresh: true }));
    assert.equal(calls, 8, 'refresh bypasses and replaces the complete bundle');

    now += 30_001;
    await firstValueFrom(store.loadAll(request));
    assert.equal(calls, 12, 'the bounded TTL cannot retain a stale snapshot');
  } finally {
    Date.now = originalNow;
  }
});

test('the cache key includes workspace epoch even before a reset notification', async () => {
  let calls = 0;
  const workspace = new WorkspaceScopeStub();
  const request = { objectType: 'run' as const, objectId: 'run-1' };
  const { store } = createStore({
    getRunPerspective: (_objectId: string, lens: ObjectLens) => {
      calls += 1;
      return of(response(lens, request));
    },
  }, workspace);

  await firstValueFrom(store.loadAll(request));
  workspace.advanceEpoch('showcase', false);
  await firstValueFrom(store.loadAll(request));

  assert.equal(calls, 8, 'a new epoch never reuses the previous workspace snapshot');
});

test('the cache key includes workspace identity when a slug is recreated in the same epoch', async () => {
  let calls = 0;
  const workspace = new WorkspaceScopeStub();
  const request = { objectType: 'run' as const, objectId: 'run-1' };
  const { store } = createStore({
    getRunPerspective: (_objectId: string, lens: ObjectLens) => {
      calls += 1;
      return of(response(lens, request, workspace.workspaceId));
    },
  }, workspace);

  const first = await firstValueFrom(store.loadAll(request));
  workspace.replaceIdentity('workspace-showcase-recreated');
  const recreated = await firstValueFrom(store.loadAll(request));

  assert.equal(calls, 8, 'same-slug recreation cannot reuse the old tenant cache');
  assert.equal(first.build.identity.workspace_id, 'workspace-showcase');
  assert.equal(recreated.build.identity.workspace_id, 'workspace-showcase-recreated');
});

test('logout and a new principal cannot reuse the previous principal cache', async () => {
  let calls = 0;
  const auth = new AuthenticationScopeStub();
  const request = { objectType: 'capability' as const, objectId: 'capability-1' };
  const { store } = createStore({
    getCapabilityPerspective: (_objectId: string, lens: ObjectLens) => {
      calls += 1;
      const payload = response(lens, request);
      payload.header = { status: fact(`principal-epoch-${auth.epoch}`) };
      return of(payload);
    },
  }, new WorkspaceScopeStub(), auth);

  const principalA = await firstValueFrom(store.loadAll(request));
  await firstValueFrom(store.loadAll(request));
  assert.equal(calls, 4, 'principal A reuses only its own bundle');

  auth.logout();
  auth.loginNewPrincipal();
  const principalB = await firstValueFrom(store.loadAll(request));

  assert.equal(calls, 8, 'principal B issues four new reads for the same workspace/object');
  assert.equal(principalA.build.header['status'].value, 'principal-epoch-5');
  assert.equal(principalB.build.header['status'].value, 'principal-epoch-7');
  assert.notEqual(principalB.build, principalA.build);
});

test('a late response from principal A is rejected after principal B logs in', async () => {
  const batches: Array<Map<ObjectLens, Subject<ObjectPerspectiveResponse>>> = [];
  let calls = 0;
  const auth = new AuthenticationScopeStub();
  const request = { objectType: 'capability' as const, objectId: 'capability-1' };
  const { store } = createStore({
    getCapabilityPerspective: (_objectId: string, lens: ObjectLens) => {
      const batchIndex = Math.floor(calls / 4);
      calls += 1;
      const pending = new Subject<ObjectPerspectiveResponse>();
      const batch = batches[batchIndex] ?? new Map<ObjectLens, Subject<ObjectPerspectiveResponse>>();
      batch.set(lens, pending);
      batches[batchIndex] = batch;
      return pending;
    },
  }, new WorkspaceScopeStub(), auth);

  const principalA = firstValueFrom(store.loadAll(request));
  const principalARejected = assert.rejects(
    principalA,
    (error: unknown) => error instanceof AuthenticationRequestInvalidatedError,
  );
  auth.changePrincipal();
  const principalB = firstValueFrom(store.loadAll(request));

  for (const lens of ['build', 'operate', 'steer', 'govern'] as const) {
    const payload = response(lens, request);
    payload.header = { status: fact('principal-b') };
    batches[1].get(lens)!.next(payload);
    batches[1].get(lens)!.complete();
  }
  const principalBBundle = await principalB;

  for (const lens of ['build', 'operate', 'steer', 'govern'] as const) {
    const payload = response(lens, request);
    payload.header = { status: fact('late-principal-a') };
    batches[0].get(lens)!.next(payload);
    batches[0].get(lens)!.complete();
  }
  await principalARejected;

  const cached = await firstValueFrom(store.loadAll(request));
  assert.equal(calls, 8, 'late principal A cannot evict or replace principal B cache');
  assert.equal(cached.build, principalBBundle.build);
  assert.equal(cached.build.header['status'].value, 'principal-b');
});

test('a late 410 from principal A cannot revoke the projection for principal B', async () => {
  const subjects = new Map<ObjectLens, Subject<ObjectPerspectiveResponse>>();
  const workspace = new WorkspaceScopeStub();
  const auth = new AuthenticationScopeStub();
  const request = { objectType: 'capability' as const, objectId: 'capability-1' };
  const { store } = createStore({
    getCapabilityPerspective: (_objectId: string, lens: ObjectLens) => {
      const pending = new Subject<ObjectPerspectiveResponse>();
      subjects.set(lens, pending);
      return pending;
    },
  }, workspace, auth);

  const stale = firstValueFrom(store.loadAll(request));
  const rejected = assert.rejects(
    stale,
    (error: unknown) => error instanceof AuthenticationRequestInvalidatedError,
  );
  auth.changePrincipal();
  subjects.get('build')!.error(gateRevocationError());
  await rejected;

  assert.deepEqual(workspace.revokedFeatures, []);
  assert.equal(workspace.refreshes, 0);
});

test('a workspace reset rejects late responses and cannot repopulate the cache', async () => {
  const subjects = new Map<ObjectLens, Subject<ObjectPerspectiveResponse>>();
  let calls = 0;
  const workspace = new WorkspaceScopeStub();
  const request = { objectType: 'capability' as const, objectId: 'capability-1' };
  const { store } = createStore({
    getCapabilityPerspective: (_objectId: string, lens: ObjectLens) => {
      calls += 1;
      const pending = new Subject<ObjectPerspectiveResponse>();
      subjects.set(lens, pending);
      return pending;
    },
  }, workspace);

  const late = firstValueFrom(store.loadAll(request));
  workspace.advanceEpoch('sentinel-ci');
  for (const lens of ['build', 'operate', 'steer', 'govern'] as const) {
    subjects.get(lens)!.next(response(lens, request));
    subjects.get(lens)!.complete();
  }

  await assert.rejects(late, (error: unknown) => error instanceof WorkspaceRequestInvalidatedError);

  const fresh = firstValueFrom(store.loadAll(request));
  for (const lens of ['build', 'operate', 'steer', 'govern'] as const) {
    const pending = subjects.get(lens)!;
    pending.next(response(lens, request, 'workspace-sentinel-ci'));
    pending.complete();
  }
  await fresh;

  assert.equal(calls, 8, 'all four lenses are fetched again after the atomic reset');
});

test('a late 410 from workspace A cannot revoke the projection in workspace B', async () => {
  const subjects = new Map<ObjectLens, Subject<ObjectPerspectiveResponse>>();
  const workspace = new WorkspaceScopeStub();
  const request = { objectType: 'capability' as const, objectId: 'capability-1' };
  const { store } = createStore({
    getCapabilityPerspective: (_objectId: string, lens: ObjectLens) => {
      const pending = new Subject<ObjectPerspectiveResponse>();
      subjects.set(lens, pending);
      return pending;
    },
  }, workspace);

  const stale = firstValueFrom(store.loadAll(request));
  const rejected = assert.rejects(
    stale,
    (error: unknown) => error instanceof WorkspaceRequestInvalidatedError,
  );
  workspace.advanceEpoch('sentinel-ci');
  subjects.get('build')!.error(gateRevocationError());
  await rejected;

  assert.deepEqual(workspace.revokedFeatures, []);
  assert.equal(workspace.refreshes, 0);
});

test('schema and cross-lens invariant violations never populate the cache', async () => {
  const cases: Array<{
    name: string;
    request: ObjectPerspectiveRequest;
    corrupt: (payload: Record<string, unknown>) => void;
  }> = [
    {
      name: 'schema version',
      request: { objectType: 'capability', objectId: 'capability-1' },
      corrupt: (payload) => { payload['schema_version'] = 2; },
    },
    {
      name: 'declared lens',
      request: { objectType: 'capability', objectId: 'capability-1' },
      corrupt: (payload) => { payload['lens'] = 'build'; },
    },
    {
      name: 'window',
      request: { objectType: 'capability', objectId: 'capability-1' },
      corrupt: (payload) => { payload['window'] = '7d'; },
    },
    {
      name: 'object type',
      request: { objectType: 'capability', objectId: 'capability-1' },
      corrupt: (payload) => {
        payload['identity'] = { ...(payload['identity'] as object), object_type: 'run' };
      },
    },
    {
      name: 'object id',
      request: { objectType: 'capability', objectId: 'capability-1' },
      corrupt: (payload) => {
        payload['identity'] = { ...(payload['identity'] as object), object_id: 'other' };
      },
    },
    {
      name: 'SkillInvocation run parent',
      request: { objectType: 'skill_invocation', objectId: 'invocation-1', runId: 'run-1' },
      corrupt: (payload) => {
        payload['identity'] = { ...(payload['identity'] as object), run_id: 'run-2' };
      },
    },
    {
      name: 'identity invariance',
      request: { objectType: 'capability', objectId: 'capability-1' },
      corrupt: (payload) => {
        payload['identity'] = { ...(payload['identity'] as object), name: 'Another name' };
      },
    },
    {
      name: 'header invariance',
      request: { objectType: 'capability', objectId: 'capability-1' },
      corrupt: (payload) => { payload['header'] = { status: fact('changed') }; },
    },
    {
      name: 'required facets',
      request: { objectType: 'capability', objectId: 'capability-1' },
      corrupt: (payload) => { payload['facets'] = {}; },
    },
  ];

  for (const contractCase of cases) {
    let calls = 0;
    let invalid = true;
    const apiMethod = contractCase.request.objectType === 'capability'
      ? 'getCapabilityPerspective'
      : contractCase.request.objectType === 'run'
        ? 'getRunPerspective'
        : 'getSkillInvocationPerspective';
    const { store } = createStore({
      [apiMethod]: (...args: unknown[]) => {
        calls += 1;
        const lens = args[contractCase.request.objectType === 'skill_invocation' ? 2 : 1] as ObjectLens;
        const payload = response(lens, contractCase.request) as unknown as Record<string, unknown>;
        if (invalid && lens === 'operate') contractCase.corrupt(payload);
        return of(payload as unknown as ObjectPerspectiveResponse);
      },
    });

    await assert.rejects(
      firstValueFrom(store.loadAll(contractCase.request)),
      (error: unknown) => error instanceof ObjectPerspectiveContractError,
      contractCase.name,
    );
    invalid = false;
    await firstValueFrom(store.loadAll(contractCase.request));
    assert.equal(calls, 8, `${contractCase.name}: invalid responses were not cached`);
  }
});

test('a SkillInvocation request without its parent Run fails before an API call', async () => {
  let calls = 0;
  const { store } = createStore({
    getSkillInvocationPerspective: () => {
      calls += 1;
      return of(null);
    },
  });

  await assert.rejects(
    firstValueFrom(store.loadAll({ objectType: 'skill_invocation', objectId: 'invocation-1' })),
    (error: unknown) => error instanceof ObjectPerspectiveContractError,
  );
  assert.equal(calls, 0);
});

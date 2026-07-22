import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  Injector,
  ɵChangeDetectionScheduler as ChangeDetectionScheduler,
  ɵEffectScheduler as EffectScheduler,
} from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Subject, lastValueFrom, toArray } from 'rxjs';
import { ApiService } from './api.service';
import { HelpService, type HelpContentIndex } from './help.service';
import {
  MaritimeTrackingService,
  type MaritimeVesselsSnapshot,
} from './maritime-tracking.service';
import { PermissionsService, type IamMatrix } from './permissions.service';
import { RagPresetService, type RagPreset } from './rag-preset.service';
import { RuntimeHealthService } from './runtime-health.service';
import {
  SystemsStore,
  type SystemAgent,
} from '../features/systems/systems.store';
import {
  WorkspaceRequestInvalidatedError,
  WorkspaceService,
  type WorkspaceContextTransition,
  type WorkspaceRequestScope,
} from './workspace.service';

class WorkspaceStub {
  private slug = 'andritz';
  private epoch = 1;
  private readonly resetters = new Set<(transition: WorkspaceContextTransition) => void>();

  readonly currentSlug = () => this.slug;
  readonly workspaces = () => [
    { id: 'workspace-a', name: 'Andritz', slug: 'andritz', role: 'admin' },
    { id: 'workspace-b', name: 'Sentinel', slug: 'sentinel-ci', role: 'admin' },
  ];

  captureRequestScope(): WorkspaceRequestScope {
    return Object.freeze({ workspaceSlug: this.slug, workspaceId: `workspace-${this.slug}`, epoch: this.epoch });
  }

  isRequestScopeCurrent(scope: WorkspaceRequestScope): boolean {
    return scope.workspaceSlug === this.slug && scope.epoch === this.epoch;
  }

  registerContextReset(resetter: (transition: WorkspaceContextTransition) => void): () => void {
    this.resetters.add(resetter);
    return () => this.resetters.delete(resetter);
  }

  switchWorkspace(): void {
    const transition: WorkspaceContextTransition = {
      previousSlug: this.slug,
      nextSlug: 'sentinel-ci',
      previousEpoch: this.epoch,
      nextEpoch: this.epoch + 1,
    };
    for (const resetter of [...this.resetters]) resetter(transition);
    this.slug = transition.nextSlug;
    this.epoch = transition.nextEpoch;
  }
}

class MemoryStorage implements Storage {
  private readonly values = new Map<string, string>();

  get length(): number {
    return this.values.size;
  }

  clear(): void {
    this.values.clear();
  }

  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }

  key(index: number): string | null {
    return [...this.values.keys()][index] ?? null;
  }

  removeItem(key: string): void {
    this.values.delete(key);
  }

  setItem(key: string, value: string): void {
    this.values.set(key, String(value));
  }
}

test('a stale preset list rejects instead of triggering a B fallback for an A id', async () => {
  const workspace = new WorkspaceStub();
  const response = new Subject<{ presets: RagPreset[] }>();
  const requestedSlugs: Array<string | null | undefined> = [];
  const api = {
    get: (_path: string, _params?: unknown, options?: { workspaceSlug?: string | null }) => {
      requestedSlugs.push(options?.workspaceSlug);
      return response.asObservable();
    },
  };
  const injector = Injector.create({
    providers: [
      RagPresetService,
      { provide: WorkspaceService, useValue: workspace },
      { provide: ApiService, useValue: api },
    ],
  });
  const pending = injector.get(RagPresetService).list();

  workspace.switchWorkspace();
  response.next({ presets: [] });
  response.complete();

  await assert.rejects(pending, (error: unknown) => (
    error instanceof WorkspaceRequestInvalidatedError
  ));
  assert.deepEqual(requestedSlugs, ['andritz'], 'the completed A request never starts a B detail request');
});

test('a late maritime snapshot completes without reaching public subscribers', async () => {
  const workspace = new WorkspaceStub();
  const response = new Subject<MaritimeVesselsSnapshot>();
  const injector = Injector.create({
    providers: [
      MaritimeTrackingService,
      { provide: WorkspaceService, useValue: workspace },
      { provide: ApiService, useValue: { get: () => response.asObservable() } },
    ],
  });
  const result = lastValueFrom(
    injector.get(MaritimeTrackingService).getSnapshot().pipe(toArray()),
  );

  workspace.switchWorkspace();
  response.next({ vessels: [{ mmsi: 'old', name: 'A vessel', lat: 1, lon: 2 }] });
  response.complete();

  assert.deepEqual(await result, []);
});

test('HelpService pins A and completes a stale public load without replaying it in B', async () => {
  const workspace = new WorkspaceStub();
  const response = new Subject<HelpContentIndex>();
  const requestedSlugs: Array<string | null | undefined> = [];
  const api = {
    get: (_path: string, _params?: unknown, options?: { workspaceSlug?: string | null }) => {
      requestedSlugs.push(options?.workspaceSlug);
      return response.asObservable();
    },
  };
  const injector = Injector.create({
    providers: [
      HelpService,
      { provide: WorkspaceService, useValue: workspace },
      { provide: ApiService, useValue: api },
    ],
  });
  const result = lastValueFrom(injector.get(HelpService).load().pipe(toArray()));

  workspace.switchWorkspace();
  response.next({ version: 'A', personas: [], languages: [], items: [] });
  response.complete();

  assert.deepEqual(await result, []);
  assert.deepEqual(requestedSlugs, ['andritz']);
});

test('RuntimeHealthService pins A and hides a late A response from signals and subscribers', async () => {
  const workspace = new WorkspaceStub();
  const response = new Subject<{
    skills: Record<string, { status: 'bound' }>;
    summary: { bound: number; stub: number; unbound: number; catalog_only: number };
  }>();
  const requestedSlugs: Array<string | null | undefined> = [];
  const api = {
    get: (_path: string, _params?: unknown, options?: { workspaceSlug?: string | null }) => {
      requestedSlugs.push(options?.workspaceSlug);
      return response.asObservable();
    },
  };
  const injector = Injector.create({
    providers: [
      RuntimeHealthService,
      { provide: WorkspaceService, useValue: workspace },
      { provide: ApiService, useValue: api },
    ],
  });
  const service = injector.get(RuntimeHealthService);
  const result = lastValueFrom(service.load().pipe(toArray()));

  workspace.switchWorkspace();
  response.next({
    skills: { private_a: { status: 'bound' } },
    summary: { bound: 1, stub: 0, unbound: 0, catalog_only: 0 },
  });
  response.complete();

  assert.deepEqual(await result, []);
  assert.deepEqual(service.snapshot(), {});
  assert.deepEqual(requestedSlugs, ['andritz']);
});

test('PermissionsService pins A and suppresses a late IAM matrix after A→B', async () => {
  const workspace = new WorkspaceStub();
  const response = new Subject<IamMatrix>();
  const requestedSlugs: Array<string | null> = [];
  const http = {
    get: (_path: string, options?: { headers?: Record<string, string> }) => {
      requestedSlugs.push(options?.headers?.['X-Workspace-Slug'] ?? null);
      return response.asObservable();
    },
  };
  const injector = Injector.create({
    providers: [
      PermissionsService,
      { provide: WorkspaceService, useValue: workspace },
      { provide: HttpClient, useValue: http },
    ],
  });
  const service = injector.get(PermissionsService);
  const result = lastValueFrom(service.refresh().pipe(toArray()));

  workspace.switchWorkspace();
  response.next({
    workspace: { id: 'workspace-a', slug: 'andritz', name: 'Andritz' },
    subject_user_id: 'user-a',
    role_template: 'workspace_admin',
    custom_labels: [],
    role_flags: {},
    enforcement: true,
    permissions: [],
  });
  response.complete();

  assert.deepEqual(await result, []);
  assert.equal(service.matrix(), null);
  assert.equal(service.loading(), false);
  assert.deepEqual(requestedSlugs, ['andritz']);
});

test('SystemsStore pins load/getById to A and exposes no late A system in B', async () => {
  const previousLocalStorage = globalThis.localStorage;
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: new MemoryStorage(),
  });
  try {
    const workspace = new WorkspaceStub();
    const listResponse = new Subject<{ systems: SystemAgent[] }>();
    const detailResponse = new Subject<SystemAgent>();
    const requested: Array<{ path: string; workspaceSlug: string | null | undefined }> = [];
    const api = {
      get: (path: string, _params?: unknown, options?: { workspaceSlug?: string | null }) => {
        requested.push({ path, workspaceSlug: options?.workspaceSlug });
        return path === '/systems' ? listResponse.asObservable() : detailResponse.asObservable();
      },
    };
    const injector = Injector.create({
      providers: [
        SystemsStore,
        { provide: WorkspaceService, useValue: workspace },
        { provide: ApiService, useValue: api },
        {
          provide: ChangeDetectionScheduler,
          useValue: { notify() {}, runningTick: false },
        },
        {
          provide: EffectScheduler,
          useValue: { add() {}, schedule() {}, flush() {}, remove() {} },
        },
      ],
    });
    const store = injector.get(SystemsStore);
    const listResult = lastValueFrom(store.load().pipe(toArray()));
    const detailResult = lastValueFrom(store.getById('private-a').pipe(toArray()));

    workspace.switchWorkspace();
    listResponse.next({
      systems: [{ id: 'private-a', name: 'A system', description: '', status: 'active' }],
    });
    listResponse.complete();
    detailResponse.next({ id: 'private-a', name: 'A system', description: '', status: 'active' });
    detailResponse.complete();

    assert.deepEqual(await listResult, []);
    assert.deepEqual(await detailResult, []);
    assert.deepEqual(store.systems(), []);
    assert.equal(store.loading(), true);
    assert.deepEqual(requested, [
      { path: '/systems', workspaceSlug: 'andritz' },
      { path: '/systems/private-a', workspaceSlug: 'andritz' },
    ]);
  } finally {
    if (previousLocalStorage) {
      Object.defineProperty(globalThis, 'localStorage', {
        configurable: true,
        value: previousLocalStorage,
      });
    } else {
      Reflect.deleteProperty(globalThis, 'localStorage');
    }
  }
});

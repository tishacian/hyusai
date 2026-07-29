import '@angular/compiler';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { HttpClient } from '@angular/common/http';
import { Injector, signal } from '@angular/core';
import { firstValueFrom, of, Subject } from 'rxjs';
import {
  BUSINESS_WORKSPACE_APPS,
  WorkspaceService,
  isWorkspaceAppEntitlement,
  normalizeWorkspaceAppEntitlements,
  toggleWorkspaceAppEntitlement,
  workspaceAppEntitlementOptions,
  type WorkspaceDetail,
  type WorkspaceInfo,
} from './workspace.service';

test('runtime entitlement catalog accepts a future key and keeps the four Andritz labels compatible', () => {
  const options = workspaceAppEntitlementOptions({
    settings: { features: { workspace_app_platform_v1: true } },
    workspace_app_runtime: {
      mode: 'authoritative',
      enabled: true,
      valid: true,
      installations: [
        {
          app_id: 'andritz.chat', version: '1.0.0', manifest_digest: 'chat', category: 'business_app',
          routes: ['/chat'], primary_surface_id: 'chat', default_route: '/chat', branding_namespace: 'andritz',
          api_prefixes: ['/api/v1/chat'], action_packs: [], entitlement_keys: ['chat'],
        },
        {
          app_id: 'andritz.client360-pdr', version: '1.0.0', manifest_digest: 'client360', category: 'business_app',
          routes: ['/client360'], primary_surface_id: 'client360-pdr', default_route: '/client360', branding_namespace: 'andritz',
          api_prefixes: ['/api/v1/client360'], action_packs: [], entitlement_keys: ['client360-pdr'],
        },
        {
          app_id: 'andritz.knowledge-capture', version: '1.0.0', manifest_digest: 'knowledge', category: 'business_app',
          routes: ['/knowledge/capture'], primary_surface_id: 'knowledge-capture', default_route: '/knowledge/capture', branding_namespace: 'andritz',
          api_prefixes: ['/api/v1/knowledge-capture'], action_packs: [], entitlement_keys: ['knowledge-capture', 'fse-reports'],
        },
        {
          app_id: 'future.workspace-surface', version: '2.0.0', manifest_digest: 'future', category: 'business_app',
          routes: ['/future'], primary_surface_id: 'future-surface', default_route: '/future', branding_namespace: 'future',
          api_prefixes: ['/api/v1/future'], action_packs: [], entitlement_keys: ['future-surface'],
          display_name: 'Future Workspace Surface',
        },
      ],
      experience: null,
    },
  });

  assert.deepEqual(options, [
    { key: 'chat', label: 'Recherche', appId: 'andritz.chat' },
    { key: 'client360-pdr', label: 'Client360 PDR', appId: 'andritz.client360-pdr' },
    { key: 'knowledge-capture', label: 'Capture de connaissances', appId: 'andritz.knowledge-capture' },
    { key: 'fse-reports', label: "Rapports d'intervention FSE", appId: 'andritz.knowledge-capture' },
    { key: 'future-surface', label: 'Future Workspace Surface', appId: 'future.workspace-surface' },
  ]);
  assert.equal(isWorkspaceAppEntitlement('future-surface'), true);
  assert.equal(isWorkspaceAppEntitlement('Future Surface'), false);
  assert.deepEqual(
    normalizeWorkspaceAppEntitlements(['future-surface', 'future-surface', '../invalid', '', 7]),
    ['future-surface'],
  );
});

test('toggling a known entitlement preserves valid active keys absent from the runtime catalog', () => {
  const options = BUSINESS_WORKSPACE_APPS.map((item) => ({
    ...item,
    appId: null,
  }));
  assert.deepEqual(
    toggleWorkspaceAppEntitlement(
      ['chat', 'future-surface'],
      'chat',
      false,
      options,
    ),
    ['future-surface'],
  );
  assert.deepEqual(
    toggleWorkspaceAppEntitlement(
      ['future-surface'],
      'client360-pdr',
      true,
      options,
    ),
    ['client360-pdr', 'future-surface'],
  );
});

class MemoryStorage implements Storage {
  private readonly values = new Map<string, string>();
  get length(): number { return this.values.size; }
  clear(): void { this.values.clear(); }
  getItem(key: string): string | null { return this.values.get(key) ?? null; }
  key(index: number): string | null { return [...this.values.keys()][index] ?? null; }
  removeItem(key: string): void { this.values.delete(key); }
  setItem(key: string, value: string): void { this.values.set(key, String(value)); }
}

const WORKSPACES: WorkspaceInfo[] = [
  { id: 'workspace-a', name: 'Andritz', slug: 'andritz', role: 'admin' },
  { id: 'workspace-b', name: 'Sentinel', slug: 'sentinel-ci', role: 'admin' },
];

function installStorage(slug = 'andritz'): () => void {
  const previous = globalThis.localStorage;
  const storage = new MemoryStorage();
  storage.setItem('agentium_workspace_slug', slug);
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: storage });
  return () => {
    if (previous) {
      Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: previous });
    } else {
      Reflect.deleteProperty(globalThis, 'localStorage');
    }
  };
}

test('workspace switch clears registered context before publishing one new slug/epoch', async () => {
  const restoreStorage = installStorage();
  try {
    const injector = Injector.create({
      providers: [
        WorkspaceService,
        { provide: HttpClient, useValue: { get: () => of(WORKSPACES) } },
      ],
    });
    const workspace = injector.get(WorkspaceService);
    let metadataRefreshes = 0;
    workspace.contextRefresh$.subscribe(() => metadataRefreshes += 1);
    await firstValueFrom(workspace.loadWorkspaces());
    assert.equal(metadataRefreshes, 1, 'same-slug membership hydration publishes settings');

    const selectedSystem = signal<string | null>('system-from-andritz');
    const overlayOpen = signal(true);
    const observations: Array<{ slug: string | null; epoch: number }> = [];
    workspace.registerContextReset(() => {
      observations.push({ slug: workspace.currentSlug(), epoch: workspace.contextEpoch() });
      selectedSystem.set(null);
    });
    workspace.registerContextReset(() => overlayOpen.set(false));

    const oldScope = workspace.captureRequestScope();
    assert.equal(Object.isFrozen(oldScope), true);
    assert.equal(workspace.switchWorkspace('sentinel-ci'), true);

    assert.deepEqual(observations, [{ slug: 'andritz', epoch: 0 }]);
    assert.equal(selectedSystem(), null);
    assert.equal(overlayOpen(), false);
    assert.equal(workspace.currentSlug(), 'sentinel-ci');
    assert.equal(workspace.contextEpoch(), 1);
    assert.equal(localStorage.getItem('agentium_workspace_slug'), 'sentinel-ci');
    assert.equal(workspace.isRequestScopeCurrent(oldScope), false);
    assert.equal(workspace.switchWorkspace('sentinel-ci'), false);
    assert.equal(observations.length, 1, 'a no-op switch does not reset context twice');
  } finally {
    restoreStorage();
  }
});

test('workspace app platform authority enables member entitlement administration without the legacy flag', async () => {
  const restoreStorage = installStorage();
  try {
    const workspaces: WorkspaceInfo[] = [{
      ...WORKSPACES[0],
      settings: { features: { workspace_app_platform_v1: true } },
    }];
    const injector = Injector.create({
      providers: [
        WorkspaceService,
        { provide: HttpClient, useValue: { get: () => of(workspaces) } },
      ],
    });
    const workspace = injector.get(WorkspaceService);
    await firstValueFrom(workspace.loadWorkspaces());

    assert.equal(workspace.appEntitlementsEnabled(), true);
  } finally {
    restoreStorage();
  }
});

test('same-slug workspace recreation invalidates the old identity atomically', async () => {
  const restoreStorage = installStorage();
  try {
    const recreated = WORKSPACES.map((workspace) => workspace.slug === 'andritz'
      ? { ...workspace, id: 'workspace-a-recreated', name: 'Andritz recreated' }
      : workspace);
    let reads = 0;
    const injector = Injector.create({
      providers: [
        WorkspaceService,
        {
          provide: HttpClient,
          useValue: { get: () => of(reads++ === 0 ? WORKSPACES : recreated) },
        },
      ],
    });
    const workspace = injector.get(WorkspaceService);
    await firstValueFrom(workspace.loadWorkspaces());
    const oldScope = workspace.captureRequestScope();
    const resetObservations: Array<{
      id: string | undefined;
      slug: string | null;
      epoch: number;
    }> = [];
    workspace.registerContextReset(() => resetObservations.push({
      id: workspace.current()?.id,
      slug: workspace.currentSlug(),
      epoch: workspace.contextEpoch(),
    }));

    await firstValueFrom(workspace.loadWorkspaces(true));

    assert.deepEqual(resetObservations, [{
      id: 'workspace-a',
      slug: 'andritz',
      epoch: 0,
    }], 'old tenant state is cleared before the recreated identity is published');
    assert.equal(workspace.currentSlug(), 'andritz');
    assert.equal(workspace.current()?.id, 'workspace-a-recreated');
    assert.equal(workspace.contextEpoch(), 1);
    assert.equal(workspace.isRequestScopeCurrent(oldScope), false);
    assert.deepEqual(workspace.captureRequestScope(), {
      workspaceSlug: 'andritz',
      workspaceId: 'workspace-a-recreated',
      epoch: 1,
    });
  } finally {
    restoreStorage();
  }
});

test('a late workspace response cannot repopulate context after a switch', async () => {
  const restoreStorage = installStorage();
  try {
    const detail = new Subject<WorkspaceDetail>();
    const http = {
      get: (url: string) => url === '/api/v1/auth/workspaces' ? of(WORKSPACES) : detail,
    };
    const injector = Injector.create({
      providers: [WorkspaceService, { provide: HttpClient, useValue: http }],
    });
    const workspace = injector.get(WorkspaceService);
    await firstValueFrom(workspace.loadWorkspaces());

    const emissions: Array<WorkspaceDetail | null> = [];
    const refresh = new Promise<void>((resolve, reject) => {
      workspace.refreshCurrentWorkspace().subscribe({
        next: (value) => emissions.push(value),
        error: reject,
        complete: resolve,
      });
    });
    workspace.switchWorkspace('sentinel-ci');
    detail.next({
      id: 'workspace-a',
      name: 'Late Andritz payload',
      slug: 'andritz',
      role: 'admin',
      is_active: true,
      member_count: 1,
      created_at: '2026-01-01T00:00:00Z',
    });
    detail.complete();
    await refresh;

    assert.deepEqual(emissions, [], 'late A detail is not exposed to public subscribers');
    assert.equal(workspace.currentSlug(), 'sentinel-ci');
    assert.equal(workspace.workspaces().find((item) => item.slug === 'andritz')?.name, 'Andritz');
  } finally {
    restoreStorage();
  }
});

test('workspace settings writes can pin an explicit workspace header', async () => {
  const restoreStorage = installStorage();
  try {
    const seen: Array<{
      url: string;
      body: unknown;
      workspaceSlug: string | undefined;
    }> = [];
    const updated: WorkspaceDetail = {
      id: 'workspace-a',
      name: 'Andritz',
      slug: 'andritz',
      role: 'admin',
      is_active: true,
      member_count: 1,
      created_at: '2026-01-01T00:00:00Z',
      settings: { chat: { title: 'Pinned' } },
    };
    const http = {
      patch: (
        url: string,
        body: unknown,
        options?: { headers?: Record<string, string> },
      ) => {
        seen.push({
          url,
          body,
          workspaceSlug: options?.headers?.['X-Workspace-Slug'],
        });
        return of(updated);
      },
    };
    const injector = Injector.create({
      providers: [WorkspaceService, { provide: HttpClient, useValue: http }],
    });
    const workspace = injector.get(WorkspaceService);
    let metadataRefreshes = 0;
    workspace.contextRefresh$.subscribe(() => metadataRefreshes += 1);

    await firstValueFrom(workspace.updateWorkspaceSettings(
      'andritz',
      updated.settings || {},
      { workspaceSlug: 'andritz' },
    ));

    assert.deepEqual(seen, [{
      url: '/api/v1/auth/workspaces/andritz',
      body: { settings: updated.settings },
      workspaceSlug: 'andritz',
    }]);
    assert.equal(metadataRefreshes, 1, 'current workspace feature changes are observable');
  } finally {
    restoreStorage();
  }
});

test('member administration sends an explicit canonical app entitlement decision', async () => {
  const restoreStorage = installStorage();
  try {
    const seen: Array<{ url: string; body: unknown }> = [];
    const http = {
      post: (url: string, body: unknown) => {
        seen.push({ url, body });
        return of({
          status: 'ok',
          user_id: 'user-invitee',
          role: 'member',
          app_entitlements: BUSINESS_WORKSPACE_APPS.map((app) => app.key),
          invitation_email_sent: false,
        });
      },
      put: (url: string, body: unknown) => {
        seen.push({ url, body });
        return of({ status: 'ok', member: { user_id: 'user-member' } });
      },
    };
    const injector = Injector.create({
      providers: [WorkspaceService, { provide: HttpClient, useValue: http }],
    });
    const workspace = injector.get(WorkspaceService);
    const grants = BUSINESS_WORKSPACE_APPS.map((app) => app.key);

    await firstValueFrom(workspace.inviteMember('andritz', 'invitee@example.com', 'member', grants));
    await firstValueFrom(workspace.updateIamMember('user-member', {
      role_template: 'workspace_contributor',
      custom_labels: [],
      app_entitlements: ['chat'],
    }));

    assert.deepEqual(seen, [
      {
        url: '/api/v1/auth/workspaces/andritz/members',
        body: {
          email: 'invitee@example.com',
          role: 'member',
          app_entitlements: grants,
        },
      },
      {
        url: '/api/v1/iam/members/user-member',
        body: {
          role_template: 'workspace_contributor',
          custom_labels: [],
          app_entitlements: ['chat'],
        },
      },
    ]);
  } finally {
    restoreStorage();
  }
});

test('a storage write failure cannot split the workspace transaction', async () => {
  const previous = globalThis.localStorage;
  const storage = {
    length: 1,
    clear: () => undefined,
    getItem: (key: string) => key === 'agentium_workspace_slug' ? 'andritz' : null,
    key: () => 'agentium_workspace_slug',
    removeItem: () => { throw new Error('storage denied'); },
    setItem: () => { throw new Error('storage denied'); },
  } satisfies Storage;
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: storage });

  try {
    const injector = Injector.create({
      providers: [
        WorkspaceService,
        { provide: HttpClient, useValue: { get: () => of(WORKSPACES) } },
      ],
    });
    const workspace = injector.get(WorkspaceService);
    await firstValueFrom(workspace.loadWorkspaces());
    let resetCount = 0;
    workspace.registerContextReset(() => resetCount += 1);

    assert.equal(workspace.switchWorkspace('sentinel-ci'), true);
    assert.equal(resetCount, 1);
    assert.equal(workspace.currentSlug(), 'sentinel-ci');
    assert.equal(workspace.contextEpoch(), 1);
  } finally {
    if (previous) {
      Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: previous });
    } else {
      Reflect.deleteProperty(globalThis, 'localStorage');
    }
  }
});

test('effective feature revocation is synchronous, same-epoch and idempotent', async () => {
  const restoreStorage = installStorage();
  try {
    const workspaces: WorkspaceInfo[] = WORKSPACES.map((workspace) => ({
      ...workspace,
      effective_features: workspace.slug === 'andritz'
        ? { capability_360_projection_v1: true }
        : {},
    }));
    const injector = Injector.create({
      providers: [
        WorkspaceService,
        { provide: HttpClient, useValue: { get: () => of(workspaces) } },
      ],
    });
    const workspace = injector.get(WorkspaceService);
    let refreshes = 0;
    workspace.contextRefresh$.subscribe(() => refreshes += 1);
    await firstValueFrom(workspace.loadWorkspaces());
    const epoch = workspace.contextEpoch();

    workspace.revokeEffectiveFeature('capability_360_projection_v1');

    assert.equal(
      workspace.current()?.effective_features?.['capability_360_projection_v1'],
      false,
    );
    assert.equal(workspace.contextEpoch(), epoch, 'metadata revocation preserves identity');
    assert.equal(refreshes, 2, 'hydration and revocation each emit one metadata refresh');

    workspace.revokeEffectiveFeature('capability_360_projection_v1');
    assert.equal(refreshes, 2, 'repeating the same revocation is a no-op');
  } finally {
    restoreStorage();
  }
});

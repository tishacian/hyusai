import '@angular/compiler';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { HttpClient } from '@angular/common/http';
import { Injector, signal } from '@angular/core';
import { firstValueFrom, of, Subject } from 'rxjs';
import {
  WorkspaceService,
  type WorkspaceDetail,
  type WorkspaceInfo,
} from './workspace.service';

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

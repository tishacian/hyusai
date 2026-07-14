/**
 * Contract tests for the Andritz business navigation profile.
 *
 * The profile is intentionally small: the three actively-used applications
 * must remain present and admins only enter the reduced shell after opting in
 * to preview it.
 */
import '@angular/compiler';
import { afterEach, beforeEach, test } from 'node:test';
import assert from 'node:assert/strict';
import { Injector, computed, signal } from '@angular/core';
import { NavigationProfileService } from './navigation-profile.service';
import { WorkspaceService, type WorkspaceInfo } from './workspace.service';

const ANDRITZ_SURFACES = ['chat', 'client360-pdr', 'knowledge-capture'];

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

class WorkspaceStub {
  readonly workspaces = signal<WorkspaceInfo[]>([]);
  readonly currentSlug = signal<string | null>('andritz');
  readonly current = computed(
    () => this.workspaces().find((workspace) => workspace.slug === this.currentSlug()) ?? null,
  );
  readonly isAdmin = computed(() => {
    const workspace = this.current();
    return workspace?.role === 'admin' || workspace?.role === 'owner';
  });

  setRole(role: 'member' | 'admin'): void {
    this.workspaces.set([
      {
        id: 'workspace-andritz',
        name: 'Andritz',
        slug: 'andritz',
        role,
        settings: {
          navigation_profile: {
            key: 'business_end_user',
            default_route: '/chat',
            primary_surfaces: ANDRITZ_SURFACES,
            advanced_access: 'admin_only',
          },
        },
      },
    ]);
  }
}

let previousLocalStorage: Storage | undefined;

beforeEach(() => {
  previousLocalStorage = globalThis.localStorage;
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: new MemoryStorage(),
  });
});

afterEach(() => {
  if (previousLocalStorage) {
    Object.defineProperty(globalThis, 'localStorage', {
      configurable: true,
      value: previousLocalStorage,
    });
  } else {
    Reflect.deleteProperty(globalThis, 'localStorage');
  }
});

function makeHarness(role: 'member' | 'admin') {
  const workspace = new WorkspaceStub();
  workspace.setRole(role);
  const injector = Injector.create({
    providers: [
      NavigationProfileService,
      { provide: WorkspaceService, useValue: workspace },
    ],
  });
  return {
    workspace,
    profile: injector.get(NavigationProfileService),
  };
}

test('business profile resolves the three Andritz applications in their stable order', () => {
  const { profile } = makeHarness('member');

  assert.deepEqual(profile.effective().primarySurfaces, ANDRITZ_SURFACES);
  assert.equal(profile.effective().defaultRoute, '/chat');
  assert.equal(profile.businessShellActive(), true);
  assert.deepEqual(profile.businessProfileConfig(true), {
    key: 'business_end_user',
    default_route: '/chat',
    primary_surfaces: ANDRITZ_SURFACES,
    advanced_access: 'admin_only',
  });
});

test('admin keeps the full Agentium shell unless business preview is enabled', () => {
  const { profile } = makeHarness('admin');

  assert.equal(profile.effective().configured, true);
  assert.equal(profile.effective().admin, true);
  assert.equal(profile.effective().preview, false);
  assert.equal(profile.businessShellActive(), false);

  profile.setBusinessPreview(true);
  assert.equal(profile.effective().preview, true);
  assert.equal(profile.businessShellActive(), true);

  profile.setBusinessPreview(false);
  assert.equal(profile.effective().preview, false);
  assert.equal(profile.businessShellActive(), false);
});

test('business redirects expose a stable telemetry owner and reason', () => {
  const { profile } = makeHarness('member');

  assert.deepEqual(profile.businessResolutionFor('/systems'), {
    requestedRoute: '/systems',
    resolvedRoute: '/chat',
    owner: 'navigation_profile',
    reason: 'business_profile_disallowed',
  });
  assert.deepEqual(profile.businessResolutionFor('/knowledge'), {
    requestedRoute: '/knowledge',
    resolvedRoute: '/knowledge/capture',
    owner: 'navigation_profile',
    reason: 'business_knowledge_compatibility',
  });
  assert.deepEqual(profile.businessResolutionFor('/systems/system-42/capture'), {
    requestedRoute: '/systems/system-42/capture',
    resolvedRoute: '/knowledge/capture?systemId=system-42',
    owner: 'navigation_profile',
    reason: 'business_system_capture_compatibility',
  });
  assert.equal(profile.businessResolutionFor('/client360/opportunities'), null);
});

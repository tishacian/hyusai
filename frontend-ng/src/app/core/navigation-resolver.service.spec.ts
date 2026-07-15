import '@angular/compiler';
import assert from 'node:assert/strict';
import { afterEach, beforeEach, test } from 'node:test';
import { Injector, computed, signal } from '@angular/core';
import { NavigationProfileService } from './navigation-profile.service';
import { NavigationResolverService } from './navigation-resolver.service';
import type { NavigationRedirectDecision } from './navigation-telemetry.service';
import { WorkspaceService, type WorkspaceInfo, type WorkspaceMode } from './workspace.service';

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
  readonly isDemoMode = computed(() => this.current()?.mode === 'demo');
  readonly switches: string[] = [];

  switchWorkspace(slug: string): boolean {
    if (!this.workspaces().some((workspace) => workspace.slug === slug)) return false;
    if (this.currentSlug() === slug) return false;
    this.switches.push(slug);
    this.currentSlug.set(slug);
    return true;
  }

  configure(options: {
    slug?: string;
    role?: 'member' | 'admin';
    mode?: WorkspaceMode;
    settings?: Record<string, unknown>;
  } = {}): void {
    const slug = options.slug || 'andritz';
    this.currentSlug.set(slug);
    this.workspaces.set([
      {
        id: `workspace-${slug}`,
        name: slug,
        slug,
        role: options.role || 'member',
        mode: options.mode || 'builder',
        settings: options.settings || {},
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

function makeHarness(options: Parameters<WorkspaceStub['configure']>[0] = {}) {
  const workspace = new WorkspaceStub();
  workspace.configure(options);
  const injector = Injector.create({
    providers: [
      NavigationProfileService,
      NavigationResolverService,
      { provide: WorkspaceService, useValue: workspace },
    ],
  });
  return {
    workspace,
    profile: injector.get(NavigationProfileService),
    resolver: injector.get(NavigationResolverService),
  };
}

function expectTerminal(
  resolver: NavigationResolverService,
  decision: NavigationRedirectDecision | null,
): NavigationRedirectDecision {
  assert.ok(decision);
  assert.equal(decision.owner, 'navigation_resolver');
  assert.equal(resolver.resolve(decision.resolvedRoute), null);
  return decision;
}

const BUSINESS_PROFILE = {
  navigation_profile: {
    key: 'business_end_user',
    default_route: '/chat',
    primary_surfaces: ['chat', 'client360-pdr', 'knowledge-capture'],
    advanced_access: 'admin_only',
  },
};

test('business policy matrix is owned once and every destination is terminal', () => {
  const { resolver } = makeHarness({ settings: BUSINESS_PROFILE });

  assert.deepEqual(expectTerminal(resolver, resolver.resolve('/systems')), {
    requestedRoute: '/systems',
    resolvedRoute: '/chat',
    owner: 'navigation_resolver',
    reason: 'business_profile_disallowed',
  });
  assert.deepEqual(expectTerminal(resolver, resolver.resolve('/knowledge')), {
    requestedRoute: '/knowledge',
    resolvedRoute: '/knowledge/capture',
    owner: 'navigation_resolver',
    reason: 'business_knowledge_compatibility',
  });
  assert.deepEqual(expectTerminal(resolver, resolver.resolve('/systems/system 42/capture')), {
    requestedRoute: '/systems/system 42/capture',
    resolvedRoute: '/knowledge/capture?systemId=system%2042',
    owner: 'navigation_resolver',
    reason: 'business_system_capture_compatibility',
  });
  assert.equal(resolver.resolve('/client360/opportunities?customer=private'), null);
});

test('business policy keeps the admin shell until preview is explicitly enabled', () => {
  const { profile, resolver } = makeHarness({ role: 'admin', settings: BUSINESS_PROFILE });

  assert.equal(resolver.resolve('/systems'), null);
  profile.setBusinessPreview(true);
  expectTerminal(resolver, resolver.resolve('/systems'));
});

test('an unsafe or self-referential business default falls back to chat', () => {
  const { resolver } = makeHarness({
    settings: {
      navigation_profile: {
        ...BUSINESS_PROFILE.navigation_profile,
        default_route: '/systems',
      },
    },
  });

  assert.equal(expectTerminal(resolver, resolver.resolve('/runs')).resolvedRoute, '/chat');
});

test('demo hypervisor resolves once to the configured default route', () => {
  const { resolver } = makeHarness({
    mode: 'demo',
    settings: { default_route: '/hypervisor/mission-room/cockpit' },
  });

  assert.deepEqual(expectTerminal(resolver, resolver.resolve('/hypervisor')), {
    requestedRoute: '/hypervisor',
    resolvedRoute: '/hypervisor/mission-room/cockpit',
    owner: 'navigation_resolver',
    reason: 'workspace_default_route',
  });
});

test('demo entry aliases cannot create a self redirect or an Angular alias cycle', () => {
  const { workspace, resolver } = makeHarness({
    mode: 'demo',
    settings: { default_route: '/hypervisor' },
  });

  assert.equal(resolver.resolve('/hypervisor'), null);
  workspace.configure({ mode: 'demo', settings: { default_route: '/' } });
  assert.equal(resolver.resolve('/hypervisor'), null);
});

test('workspace entrypoint resolves once with an encoded active slug', () => {
  const { resolver } = makeHarness({ slug: 'octocity mission-room' });

  assert.deepEqual(expectTerminal(resolver, resolver.resolve('/workspace?source=menu')), {
    requestedRoute: '/workspace?source=menu',
    resolvedRoute: '/workspace/octocity%20mission-room/settings',
    owner: 'navigation_resolver',
    reason: 'workspace_settings_entrypoint',
  });
});

test('workspace deep links activate their tenant before component construction', () => {
  const { workspace, resolver } = makeHarness({ slug: 'andritz' });
  workspace.workspaces.update((list) => [
    ...list,
    { id: 'workspace-sentinel', name: 'Sentinel', slug: 'sentinel-ci', role: 'admin' },
  ]);

  assert.equal(
    resolver.activateWorkspaceFromRoute('/workspace/sentinel-ci/chat?mode=quick'),
    null,
  );

  assert.equal(workspace.currentSlug(), 'sentinel-ci');
  assert.deepEqual(workspace.switches, ['sentinel-ci']);
  assert.equal(resolver.resolve('/workspace/sentinel-ci/chat'), null);
});

test('unknown workspace deep links resolve back to the active workspace', () => {
  const { workspace, resolver } = makeHarness({ slug: 'andritz' });

  assert.deepEqual(
    resolver.activateWorkspaceFromRoute('/workspace/unknown/chat?mode=quick'),
    {
      requestedRoute: '/workspace/unknown/chat?mode=quick',
      resolvedRoute: '/workspace/andritz/settings',
      owner: 'navigation_resolver',
      reason: 'workspace_settings_entrypoint',
    },
  );
  assert.equal(workspace.currentSlug(), 'andritz');
  assert.deepEqual(workspace.switches, []);
});

test('workspace load failure fallback remains owned by the navigation resolver', () => {
  const { resolver } = makeHarness({ slug: 'andritz' });

  assert.deepEqual(resolver.resolveWorkspaceLoadFailure('/workspace?source=menu'), {
    requestedRoute: '/workspace?source=menu',
    resolvedRoute: '/hypervisor',
    owner: 'navigation_resolver',
    reason: 'workspace_settings_entrypoint',
  });
  assert.equal(resolver.resolveWorkspaceLoadFailure('/systems'), null);
});

test('business policy has deterministic precedence over demo and workspace entrypoints', () => {
  const { resolver } = makeHarness({ mode: 'demo', settings: BUSINESS_PROFILE });

  assert.equal(resolver.resolve('/hypervisor')?.reason, 'business_profile_disallowed');
  assert.equal(resolver.resolve('/workspace')?.reason, 'business_profile_disallowed');
});

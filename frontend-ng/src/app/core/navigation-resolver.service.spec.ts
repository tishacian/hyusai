import '@angular/compiler';
import assert from 'node:assert/strict';
import { afterEach, beforeEach, test } from 'node:test';
import { Injector, computed, signal } from '@angular/core';
import { NavigationProfileService } from './navigation-profile.service';
import { NavigationResolverService } from './navigation-resolver.service';
import type { NavigationRedirectDecision } from './navigation-telemetry.service';
import {
  WorkspaceService,
  type WorkspaceAppRuntimeProjection,
  type WorkspaceInfo,
  type WorkspaceMode,
} from './workspace.service';

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
    appEntitlements?: WorkspaceInfo['app_entitlements'];
    appRuntime?: WorkspaceAppRuntimeProjection;
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
        app_entitlements: options.appEntitlements,
        workspace_app_runtime: options.appRuntime,
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

const V2_BUSINESS_PROFILE = {
  ...BUSINESS_PROFILE,
  features: { workspace_experience_v2: true },
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

test('V2 business redirects are executed only by the navigation resolver', () => {
  const { resolver } = makeHarness({ settings: V2_BUSINESS_PROFILE });

  assert.deepEqual(expectTerminal(resolver, resolver.resolve('/systems')), {
    requestedRoute: '/systems',
    resolvedRoute: '/chat',
    owner: 'navigation_resolver',
    reason: 'business_profile_disallowed',
  });
  assert.deepEqual(
    expectTerminal(resolver, resolver.resolve('/systems/system%2042/capture')),
    {
      requestedRoute: '/systems/system%2042/capture',
      resolvedRoute: '/knowledge/capture?systemId=system%2042',
      owner: 'navigation_resolver',
      reason: 'business_system_capture_compatibility',
    },
  );
});

test('enabled Workspace App authority redirects every invalid runtime surface to a terminal unavailable shell', () => {
  const settings = {
    ...BUSINESS_PROFILE,
    default_route: '/hypervisor/mission-room/cockpit',
    mission_room: { enabled: true, profile: 'sentinel_government_v1' },
    features: { workspace_app_platform_v1: true },
  };
  const invalidRuntime: WorkspaceAppRuntimeProjection = {
    schema_version: 1,
    mode: 'authoritative',
    enabled: true,
    valid: false,
    error_code: 'manifest_untrusted',
    installations: [],
    experience: null,
  };
  const { resolver, profile } = makeHarness({ settings, appRuntime: invalidRuntime });

  assert.equal(profile.workspaceExperienceV2Enabled(), false);
  assert.equal(profile.workspaceAppPlatformEnabled(), true);
  assert.equal(profile.workspaceAppUnavailable(), true);
  for (const route of [
    '/hypervisor',
    '/chat',
    '/systems/system-42',
    '/hypervisor/mission-room/cockpit',
    '/governance/audit',
  ]) {
    assert.deepEqual(expectTerminal(resolver, resolver.resolve(route)), {
      requestedRoute: route,
      resolvedRoute: '/workspace-app-unavailable',
      owner: 'navigation_resolver',
      reason: 'workspace_extension_unavailable',
    });
  }
  assert.equal(resolver.resolve('/workspace-app-unavailable'), null);
});

test('invalid runtime exposes the isolated repair route only to workspace admins', () => {
  const settings = { features: { workspace_app_platform_v1: true } };
  const member = makeHarness({ role: 'member', settings }).resolver;
  assert.equal(
    expectTerminal(member, member.resolve('/workspace-app-repair')).resolvedRoute,
    '/workspace-app-unavailable',
  );

  const admin = makeHarness({ role: 'admin', settings }).resolver;
  assert.equal(admin.resolve('/workspace-app-repair'), null);
  assert.equal(
    expectTerminal(admin, admin.resolve('/governance/workspace-apps')).resolvedRoute,
    '/workspace-app-unavailable',
  );
});

test('the unavailable page cannot masquerade as workspace state once platform authority is healthy or disabled', () => {
  const disabled = makeHarness().resolver;
  assert.deepEqual(expectTerminal(disabled, disabled.resolve('/workspace-app-unavailable')), {
    requestedRoute: '/workspace-app-unavailable',
    resolvedRoute: '/hypervisor',
    owner: 'navigation_resolver',
    reason: 'workspace_default_route',
  });

  const healthy = makeHarness({
    settings: { features: { workspace_app_platform_v1: true } },
    appEntitlements: ['client360-pdr'],
    appRuntime: {
      schema_version: 1,
      mode: 'authoritative',
      enabled: true,
      valid: true,
      rollout_phase: 'active',
      rollout_ref: `sha256:${'a'.repeat(64)}`,
      installations: [{
        app_id: 'andritz.client360-pdr',
        version: '1.0.0',
        manifest_digest: 'sha256:client360',
        category: 'business_app',
        routes: ['/client360'],
        primary_surface_id: 'client360-pdr',
        default_route: '/client360',
        branding_namespace: 'andritz',
        api_prefixes: ['/api/v1/client360'],
        action_packs: ['andritz_industrial_v1'],
        entitlement_keys: ['client360-pdr'],
      }],
      experience: {
        shell: 'business',
        routes: ['/client360'],
        primary_surface_ids: ['client360-pdr'],
        default_routes: { 'andritz.client360-pdr': '/client360' },
        branding_namespaces: ['andritz'],
        api_prefixes: ['/api/v1/client360'],
        action_packs: ['andritz_industrial_v1'],
        mission_room: null,
      },
    },
  }).resolver;
  assert.equal(
    expectTerminal(healthy, healthy.resolve('/workspace-app-unavailable')).resolvedRoute,
    '/client360',
  );
});

test('app entitlements redirect denied business surfaces to an entitled terminal route', () => {
  const { resolver } = makeHarness({
    settings: {
      ...V2_BUSINESS_PROFILE,
      features: {
        workspace_experience_v2: true,
        app_entitlements_v1: true,
      },
    },
    appEntitlements: ['client360-pdr'],
  });

  assert.equal(expectTerminal(resolver, resolver.resolve('/chat')).resolvedRoute, '/client360');
  assert.equal(resolver.resolve('/client360/opportunities'), null);
  const deniedCapture = expectTerminal(resolver, resolver.resolve('/systems/system-42/capture'));
  assert.equal(deniedCapture.resolvedRoute, '/client360');
  assert.equal(deniedCapture.reason, 'business_profile_disallowed');

  const failClosed = makeHarness({
    settings: {
      ...V2_BUSINESS_PROFILE,
      features: {
        workspace_experience_v2: true,
        app_entitlements_v1: true,
      },
    },
  }).resolver;
  assert.equal(expectTerminal(failClosed, failClosed.resolve('/chat')).resolvedRoute, '/account/profile');
  assert.equal(failClosed.resolve('/account/profile'), null);
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
    settings: {
      default_route: '/hypervisor/mission-room/cockpit',
      mission_room: { enabled: true },
    },
  });

  assert.deepEqual(expectTerminal(resolver, resolver.resolve('/hypervisor')), {
    requestedRoute: '/hypervisor',
    resolvedRoute: '/hypervisor/mission-room/cockpit',
    owner: 'navigation_resolver',
    reason: 'workspace_default_route',
  });
});

test('axes v4 owns legacy hypervisor object links and keeps Hypervisor at Portfolio', () => {
  const { resolver } = makeHarness({
    mode: 'demo',
    settings: {
      features: { cockpit_router_axes_v4: true },
      default_route: '/hypervisor/mission-room/cockpit',
      mission_room: { enabled: true },
    },
  });

  assert.deepEqual(resolver.resolve('/systems/system-42?lens=hypervisor&facet=runs'), {
    requestedRoute: '/systems/system-42?lens=hypervisor&facet=runs',
    resolvedRoute: '/hypervisor',
    owner: 'navigation_resolver',
    reason: 'legacy_hypervisor_object_lens',
  });
  assert.equal(resolver.resolve('/systems/system-42?lens=operate'), null);
  assert.equal(resolver.resolve('/hypervisor'), null);
});

test('Mission Room fallback and deep links require the workspace extension', () => {
  const disabled = makeHarness({ mode: 'demo' }).resolver;
  assert.equal(disabled.resolve('/hypervisor'), null);
  assert.deepEqual(disabled.resolve('/hypervisor/mission-room/cockpit'), {
    requestedRoute: '/hypervisor/mission-room/cockpit',
    resolvedRoute: '/hypervisor',
    owner: 'navigation_resolver',
    reason: 'workspace_extension_unavailable',
  });

  const enabled = makeHarness({
    mode: 'demo',
    settings: { mission_room: { enabled: true } },
  }).resolver;
  assert.equal(
    expectTerminal(enabled, enabled.resolve('/hypervisor')).resolvedRoute,
    '/hypervisor/mission-room/cockpit',
  );
  assert.equal(enabled.resolve('/hypervisor/mission-room/cockpit'), null);

  const explicit = makeHarness({
    mode: 'demo',
    settings: { default_route: '/intelligence' },
  }).resolver;
  assert.equal(expectTerminal(explicit, explicit.resolve('/hypervisor')).resolvedRoute, '/intelligence');
});

test('a stale Mission Room default cannot loop while the extension is disabled', () => {
  const { resolver } = makeHarness({
    mode: 'demo',
    settings: { default_route: '/hypervisor/mission-room/cockpit' },
  });

  assert.equal(resolver.resolve('/hypervisor'), null);
  assert.equal(
    expectTerminal(resolver, resolver.resolve('/hypervisor/mission-room/cockpit')).resolvedRoute,
    '/hypervisor',
  );
});

test('business policy resolves a Mission Room deep link directly to its terminal surface', () => {
  const { resolver } = makeHarness({ settings: V2_BUSINESS_PROFILE });

  const decision = expectTerminal(
    resolver,
    resolver.resolve('/hypervisor/mission-room/cockpit'),
  );
  assert.equal(decision.resolvedRoute, '/chat');
  assert.equal(decision.reason, 'business_profile_disallowed');
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

test('workspace query on a product route activates that tenant', () => {
  const { workspace, resolver } = makeHarness({ slug: 'andritz' });
  workspace.workspaces.update((list) => [
    ...list,
    { id: 'workspace-nawa', name: 'Nawa', slug: 'nawa', role: 'admin' },
  ]);

  assert.equal(
    resolver.activateWorkspaceFromRoute('/connectors/mcp?workspace=nawa'),
    null,
  );
  assert.equal(workspace.currentSlug(), 'nawa');
  assert.deepEqual(workspace.switches, ['nawa']);
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

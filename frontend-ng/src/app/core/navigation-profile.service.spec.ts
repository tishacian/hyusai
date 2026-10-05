/**
 * Contract tests for the Andritz business navigation profile.
 *
 * The profile is intentionally small: the actively-used applications must
 * remain present and admins only enter the reduced shell after opting in to
 * preview it.
 */
import '@angular/compiler';
import { afterEach, beforeEach, test } from 'node:test';
import assert from 'node:assert/strict';
import { Injector, computed, signal } from '@angular/core';
import { NavigationProfileService } from './navigation-profile.service';
import {
  WorkspaceService,
  type WorkspaceAppRuntimeProjection,
  type WorkspaceInfo,
} from './workspace.service';

const ANDRITZ_SURFACES = ['chat', 'client360-pdr', 'knowledge-capture', 'fse-reports'];

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

  setRole(role: 'member' | 'admin', options: {
    workspaceExperienceV2?: boolean;
    appEntitlementsV1?: boolean;
    workspaceAppPlatformV1?: boolean;
    appEntitlements?: WorkspaceInfo['app_entitlements'];
    appRuntime?: WorkspaceAppRuntimeProjection;
    family?: string | null;
  } = {}): void {
    this.workspaces.set([
      {
        id: 'workspace-andritz',
        name: 'Andritz',
        slug: 'andritz',
        role,
        app_entitlements: options.appEntitlements ?? [],
        workspace_app_runtime: options.appRuntime,
        settings: {
          family: options.family === undefined ? 'andritz' : options.family,
          features: {
            workspace_experience_v2: options.workspaceExperienceV2 === true,
            app_entitlements_v1: options.appEntitlementsV1 === true,
            workspace_app_platform_v1: options.workspaceAppPlatformV1 === true,
          },
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

function makeHarness(
  role: 'member' | 'admin',
  options: Parameters<WorkspaceStub['setRole']>[1] = {},
) {
  const workspace = new WorkspaceStub();
  workspace.setRole(role, options);
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

test('business profile resolves the Andritz applications in their stable order', () => {
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

test('another family is offered the product apps only, flags or not', () => {
  // The historical default listed ANDRITZ's apps for every workspace without
  // entitlement flags, so a generic workspace showed Client360 and FSE.
  for (const family of ['generic', 'sentinel_ci', null]) {
    const { profile } = makeHarness('member', { family });
    assert.deepEqual(profile.effective().primarySurfaces, ['chat', 'knowledge-capture'], String(family));
    assert.equal(profile.businessSurfaceEnabled('client360-pdr'), false);
    assert.equal(profile.businessSurfaceEnabled('fse-reports'), false);
    assert.equal(profile.isBusinessAllowedPath('/client360'), false);
  }
});

test('a partial legacy profile cannot hide an app before the entitlement flag', () => {
  const { workspace, profile } = makeHarness('member');
  workspace.workspaces.update((items) => items.map((item) => ({
    ...item,
    settings: {
      ...item.settings,
      navigation_profile: {
        key: 'business_end_user',
        default_route: '/chat',
        primary_surfaces: ['chat'],
        advanced_access: 'admin_only',
      },
    },
  })));

  assert.equal(profile.appEntitlementsEnabled(), false);
  assert.deepEqual(profile.effective().primarySurfaces, ANDRITZ_SURFACES);
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

test('business allowed paths remain stable inputs for the navigation resolver', () => {
  const { profile } = makeHarness('member');

  assert.equal(profile.isBusinessAllowedPath('/chat'), true);
  assert.equal(profile.isBusinessAllowedPath('/client360/opportunities'), true);
  assert.equal(profile.isBusinessAllowedPath('/knowledge/capture?systemId=system-42'), true);
  assert.equal(profile.isBusinessAllowedPath('/knowledge/interventions'), true);
  assert.equal(profile.isBusinessAllowedPath('/systems'), false);
});

test('V2 produces the business shell policy when its workspace flag is enabled', () => {
  const { profile } = makeHarness('member', {
    workspaceExperienceV2: true,
    appEntitlements: [],
  });

  assert.equal(profile.workspaceExperienceV2Enabled(), true);
  assert.equal(profile.resolveWorkspaceExperience('/systems')?.routeResolution.resolvedRoute, '/chat');
  assert.deepEqual(profile.effective().primarySurfaces, ANDRITZ_SURFACES);
  assert.equal(profile.effective().defaultRoute, '/chat');
  assert.equal(profile.businessShellActive(), true);
});

test('app entitlements filter both legacy and V2 profiles and missing grants fail closed', () => {
  for (const workspaceExperienceV2 of [false, true]) {
    const { profile } = makeHarness('member', {
      workspaceExperienceV2,
      appEntitlementsV1: true,
      appEntitlements: ['client360-pdr'],
    });
    assert.deepEqual(profile.effective().primarySurfaces, ['client360-pdr']);
    assert.equal(profile.effective().defaultRoute, '/client360');
    assert.equal(profile.businessSurfaceEnabled('chat'), false);
    assert.equal(profile.businessSurfaceEnabled('client360-pdr'), true);
    assert.equal(profile.isBusinessAllowedPath('/chat'), false);
    assert.equal(profile.isBusinessAllowedPath('/client360/opportunities'), true);
  }

  const { profile: missing } = makeHarness('member', {
    workspaceExperienceV2: true,
    appEntitlementsV1: true,
  });
  assert.deepEqual(missing.effective().primarySurfaces, []);
  assert.equal(missing.effective().defaultRoute, '/account/profile');
  assert.equal(missing.isBusinessAllowedPath('/chat'), false);
  assert.equal(missing.isBusinessAllowedPath('/account/profile'), true);
});

test('NavigationProfile consumes installed app authority when the platform gate is active', () => {
  const appRuntime: WorkspaceAppRuntimeProjection = {
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
  };
  const { profile } = makeHarness('member', {
    workspaceAppPlatformV1: true,
    appEntitlements: ['client360-pdr'],
    appRuntime,
  });

  assert.equal(profile.workspaceExperienceV2Enabled(), false);
  assert.equal(profile.workspaceAppPlatformEnabled(), true);
  assert.equal(profile.appEntitlementsEnabled(), true);
  assert.equal(profile.resolveWorkspaceExperience('/chat')?.routeResolution.resolvedRoute, '/client360');
  assert.deepEqual(profile.effective().primarySurfaces, ['client360-pdr']);
  assert.equal(profile.effective().defaultRoute, '/client360');
});

test('platform authority never exposes an installed business app without a member grant', () => {
  const appRuntime: WorkspaceAppRuntimeProjection = {
    schema_version: 1,
    mode: 'authoritative',
    enabled: true,
    valid: true,
    rollout_phase: 'active',
    rollout_ref: `sha256:${'b'.repeat(64)}`,
    installations: [{
      app_id: 'andritz.chat',
      version: '1.0.0',
      manifest_digest: 'sha256:chat',
      category: 'business_app',
      routes: ['/chat'],
      primary_surface_id: 'chat',
      default_route: '/chat',
      branding_namespace: 'andritz',
      api_prefixes: ['/api/v1/chat', '/api/v1/sessions'],
      action_packs: ['andritz_industrial_v1'],
      entitlement_keys: ['chat'],
    }],
    experience: {
      shell: 'business',
      routes: ['/chat'],
      primary_surface_ids: ['chat'],
      default_routes: { 'andritz.chat': '/chat' },
      branding_namespaces: ['andritz'],
      api_prefixes: ['/api/v1/chat', '/api/v1/sessions'],
      action_packs: ['andritz_industrial_v1'],
      mission_room: null,
    },
  };
  const { profile } = makeHarness('member', {
    workspaceAppPlatformV1: true,
    appRuntime,
  });

  assert.equal(profile.appEntitlementsEnabled(), true);
  assert.deepEqual(profile.effective().primarySurfaces, []);
  assert.equal(profile.effective().defaultRoute, '/account/profile');
  assert.equal(profile.isBusinessAllowedPath('/chat'), false);
});

test('NavigationProfile never revives the legacy shell when enabled platform authority is invalid', () => {
  const { profile } = makeHarness('admin', {
    workspaceAppPlatformV1: true,
    appRuntime: {
      mode: 'authoritative',
      enabled: true,
      valid: false,
      error_code: 'attestation_missing',
      installations: [],
      experience: null,
    },
  });

  assert.equal(profile.workspaceAppUnavailable(), true);
  assert.equal(profile.businessShellActive(), false);
  assert.equal(profile.effective().defaultRoute, '/workspace-app-unavailable');
  assert.deepEqual(profile.effective().primarySurfaces, []);
});

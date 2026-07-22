import '@angular/compiler';
import assert from 'node:assert/strict';
import test from 'node:test';
import {
  Injector,
  ɵChangeDetectionScheduler as ChangeDetectionScheduler,
  ɵEffectScheduler as EffectScheduler,
} from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { Subject, of } from 'rxjs';
import { ApiService } from '@app/core/api.service';
import {
  WorkspaceService,
  type WorkspaceAppRuntimeMissionRoom,
  type WorkspaceAppRuntimeProjection,
  type WorkspaceContextTransition,
  type WorkspaceRequestScope,
} from '@app/core/workspace.service';
import {
  GENERIC_MISSION_ROOM_COPY,
  GenericMissionRoomComponent,
} from './generic-mission-room.component';
import {
  GENERIC_MISSION_ROOM_PROVIDER_ENDPOINTS,
  GENERIC_MISSION_ROOM_PROVIDER_KIND,
} from './mission-room.extension';

interface ApiCall {
  path: string;
  workspaceSlug?: string | null;
  response: Subject<unknown>;
}

function genericWorkspace(): Record<string, unknown> {
  const mission: WorkspaceAppRuntimeMissionRoom = {
    profile: 'generic',
    assistant_profile: 'default',
    label: 'Mission Room',
    assistant_label: 'Assistant',
    brand_style: 'agentium',
    navigation_keys: ['cockpit', 'strategie', 'securite', 'reputation', 'agenda', 'presse', 'decisions'],
    app_id: 'mission-room.extension',
    version: '1.2.0',
    manifest_digest: 'generic-runtime-digest',
    default_route: '/hypervisor/mission-room/cockpit',
    primary_surface_id: 'mission-room',
    provider_kind: GENERIC_MISSION_ROOM_PROVIDER_KIND,
    provider_endpoints: [...GENERIC_MISSION_ROOM_PROVIDER_ENDPOINTS],
  };
  const runtime: WorkspaceAppRuntimeProjection = {
    schema_version: 1,
    mode: 'authoritative',
    enabled: true,
    valid: true,
    installations: [{
      app_id: mission.app_id,
      version: mission.version,
      manifest_digest: mission.manifest_digest,
      category: 'workspace_extension',
      routes: ['/hypervisor/mission-room'],
      primary_surface_id: 'mission-room',
      default_route: mission.default_route,
      branding_namespace: 'mission-room',
      api_prefixes: ['/api/v1/mission-room'],
      action_packs: ['global_voice_v1'],
      entitlement_keys: [],
    }],
    experience: {
      shell: 'immersive',
      routes: ['/hypervisor/mission-room'],
      primary_surface_ids: ['mission-room'],
      default_routes: { 'mission-room.extension': mission.default_route },
      branding_namespaces: ['mission-room'],
      api_prefixes: ['/api/v1/mission-room'],
      action_packs: ['global_voice_v1'],
      mission_room: mission,
    },
  };
  return {
    id: 'workspace-a',
    slug: 'workspace-a',
    name: 'Board workspace',
    mode: 'demo',
    settings: { features: { workspace_app_platform_v1: true } },
    workspace_app_runtime: runtime,
  };
}

class WorkspaceStub {
  private epoch = 7;
  private slug = 'workspace-a';
  private readonly resetters = new Set<(transition: WorkspaceContextTransition) => void>();
  constructor(private currentWorkspace: Record<string, unknown>) {}

  current = () => this.currentWorkspace;
  currentSlug = () => this.slug;
  captureRequestScope(): WorkspaceRequestScope {
    return { workspaceId: `id-${this.slug}`, workspaceSlug: this.slug, epoch: this.epoch };
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
      nextSlug: 'workspace-b',
      previousEpoch: this.epoch,
      nextEpoch: this.epoch + 1,
    };
    for (const resetter of this.resetters) resetter(transition);
    this.slug = transition.nextSlug;
    this.epoch = transition.nextEpoch;
    this.currentWorkspace = { id: 'workspace-b', slug: 'workspace-b', name: 'Second workspace', settings: {} };
  }
}

function createHarness(view = 'cockpit') {
  const calls: ApiCall[] = [];
  const navigations: unknown[][] = [];
  const workspace = new WorkspaceStub(genericWorkspace());
  const api = {
    get: (path: string, _params?: unknown, options?: { workspaceSlug?: string | null }) => {
      const response = new Subject<unknown>();
      calls.push({ path, workspaceSlug: options?.workspaceSlug, response });
      return response.asObservable();
    },
  };
  const injector = Injector.create({ providers: [
    GenericMissionRoomComponent,
    { provide: WorkspaceService, useValue: workspace },
    { provide: ApiService, useValue: api },
    { provide: ActivatedRoute, useValue: { paramMap: of({ get: (key: string) => key === 'view' ? view : null }) } },
    { provide: Router, useValue: { navigate: (...args: unknown[]) => { navigations.push(args); return Promise.resolve(true); } } },
    { provide: ChangeDetectionScheduler, useValue: { notify() {}, runningTick: false } },
    { provide: EffectScheduler, useValue: { add() {}, schedule() {}, flush() {}, remove() {} } },
  ] });
  return { component: injector.get(GenericMissionRoomComponent), calls, navigations, workspace };
}

test('generic provider renders only neutral copy and calls the exact core contracts', () => {
  const { component, calls } = createHarness();
  component.ngOnInit();

  assert.deepEqual(calls.map((call) => call.path), [
    '/mission-room/navigation',
    '/mission-room/overview',
    '/mission-room/cockpit',
  ]);
  assert.ok(calls.every((call) => call.workspaceSlug === 'workspace-a'));
  assert.doesNotMatch(
    JSON.stringify(GENERIC_MISSION_ROOM_COPY),
    /\bAYA\b|SENTINEL-CI|Abidjan|CEDEAO|Sahel|OCTAVE/,
  );

  calls[0].response.next({ items: [
    { key: 'cockpit', label: 'Overview', route: '/hypervisor/mission-room/cockpit' },
    { key: 'securite', label: 'Controls', route: '/hypervisor/mission-room/securite' },
    { key: 'monitor', label: 'Specialized', route: '/hypervisor/mission-room/securite/monitor' },
  ] });
  calls[0].response.complete();
  calls[1].response.next({ state: 'available', systems: [{ id: 'system-a' }] });
  calls[1].response.complete();
  calls[2].response.next({ state: 'available', priorities: [] });
  calls[2].response.complete();

  assert.deepEqual(component.safeNavigation().map((item) => item.key), ['cockpit', 'securite']);
  assert.match(component.overviewText(), /system-a/);
  assert.equal(component.loading(), false);
  component.ngOnDestroy();
});

test('generic provider purges atomically and rejects every late previous-workspace payload', () => {
  const { component, calls, workspace } = createHarness('decisions');
  component.ngOnInit();
  assert.deepEqual(calls.map((call) => call.path), [
    '/mission-room/navigation',
    '/mission-room/overview',
    '/mission-room/decisions',
  ]);

  workspace.switchWorkspace();
  assert.ok(calls.every((call) => !call.response.observed));
  assert.equal(component.navigation(), null);
  assert.equal(component.overview(), null);
  assert.equal(component.payload(), null);
  assert.equal(component.requestEpoch(), null);

  calls.forEach((call) => {
    call.response.next({ workspace: 'late-workspace-a' });
    call.response.complete();
  });
  assert.equal(component.payload(), null);
  component.ngOnDestroy();
});

test('unknown and specialized views never issue provider requests', async () => {
  const { component, calls, navigations } = createHarness('veille-sociale');
  component.ngOnInit();
  await Promise.resolve();

  assert.deepEqual(calls, []);
  assert.deepEqual(navigations[0]?.[0], ['/hypervisor/mission-room/cockpit']);
  component.ngOnDestroy();
});

import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  Injector,
  ɵChangeDetectionScheduler as ChangeDetectionScheduler,
  ɵEffectScheduler as EffectScheduler,
} from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { Subject, of } from 'rxjs';
import { ApiService } from '@app/core/api.service';
import { AssistantEffectsService } from '@app/core/assistant-effects.service';
import { MaritimeTrackingService } from '@app/core/maritime-tracking.service';
import { WorkspaceExperienceShadowService } from '@app/core/workspace-experience-shadow.service';
import {
  WorkspaceService,
  type WorkspaceAppRuntimeMissionRoom,
  type WorkspaceAppRuntimeProjection,
  type WorkspaceContextTransition,
  type WorkspaceRequestScope,
} from '@app/core/workspace.service';
import { ChatOverlayService } from '@app/features/chat/chat-overlay.service';
import { MissionRailComponent, MissionRoomComponent } from './mission-room.component';
import { OCTOCITY_MISSION_ROOM_PROFILE } from './mission-room.extension';

interface ApiCall {
  path: string;
  options?: { workspaceSlug?: string | null };
  response: Subject<unknown>;
}

class WorkspaceStub {
  private slug = 'sentinel-ci';
  private epoch = 11;
  private readonly resetters = new Set<(transition: WorkspaceContextTransition) => void>();

  constructor(private readonly workspaceContext: Record<string, unknown> = { settings: {} }) {}

  currentSlug = () => this.slug;
  current = () => this.workspaceContext;
  workspaces = () => [
    { id: 'workspace-sentinel-ci', slug: 'sentinel-ci', name: 'Sentinel CI' },
    {
      id: 'workspace-octocity-mission-room',
      slug: 'octocity-mission-room',
      name: 'Octocity Mission Room',
    },
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

  switchWorkspace(nextSlug = 'octocity-mission-room'): boolean {
    if (nextSlug === this.slug || !this.workspaces().some((workspace) => workspace.slug === nextSlug)) {
      return false;
    }
    const transition: WorkspaceContextTransition = {
      previousSlug: this.slug,
      nextSlug,
      previousEpoch: this.epoch,
      nextEpoch: this.epoch + 1,
    };
    for (const resetter of [...this.resetters]) resetter(transition);
    this.slug = transition.nextSlug;
    this.epoch = transition.nextEpoch;
    return true;
  }
}

function createHarness(options: {
  shadowThrows?: boolean;
  workspaceContext?: Record<string, unknown>;
} = {}) {
  const workspace = new WorkspaceStub(options.workspaceContext);
  const postCalls: ApiCall[] = [];
  const patchCalls: ApiCall[] = [];
  const getCalls: ApiCall[] = [];
  const blobCalls: ApiCall[] = [];
  const opens: unknown[] = [];
  const navigations: unknown[][] = [];
  const urlNavigations: string[] = [];
  const missionShadowCalls: Array<{
    navigation: unknown;
    scope: WorkspaceRequestScope;
    installedBeforeObservation: boolean;
  }> = [];
  let componentRef: MissionRoomComponent | null = null;
  const record = (calls: ApiCall[], path: string, options?: ApiCall['options']) => {
    const response = new Subject<unknown>();
    calls.push({ path, options, response });
    return response.asObservable();
  };
  const api = {
    post: (path: string, _body?: unknown, options?: ApiCall['options']) => record(postCalls, path, options),
    patch: (path: string, _body?: unknown, options?: ApiCall['options']) => record(patchCalls, path, options),
    get: (path: string, _params?: Record<string, string>, options?: ApiCall['options']) => record(getCalls, path, options),
    getBlob: (path: string, options?: ApiCall['options']) => record(blobCalls, path, options),
  };
  const paramMap = { get: (name: string) => name === 'view' ? 'cockpit' : null };
  const queryParamMap = { get: () => null };
  const injector = Injector.create({
    providers: [
      MissionRoomComponent,
      { provide: WorkspaceService, useValue: workspace },
      { provide: ApiService, useValue: api },
      { provide: ActivatedRoute, useValue: { paramMap: of(paramMap), queryParamMap: of(queryParamMap) } },
      {
        provide: Router,
        useValue: {
          navigate: (...args: unknown[]) => {
            navigations.push(args);
            return Promise.resolve(true);
          },
          navigateByUrl: (url: string) => {
            urlNavigations.push(url);
            return Promise.resolve(true);
          },
        },
      },
      { provide: ChatOverlayService, useValue: { open: (options: unknown) => opens.push(options) } },
      { provide: AssistantEffectsService, useValue: {} },
      {
        provide: MaritimeTrackingService,
        useValue: {
          selectedVessel: () => null,
          getSnapshot: () => of({ vessels: [] }),
        },
      },
      {
        provide: WorkspaceExperienceShadowService,
        useValue: {
          observeMissionNavigation: (
            navigation: unknown,
            scope: WorkspaceRequestScope,
          ) => {
            missionShadowCalls.push({
              navigation,
              scope,
              installedBeforeObservation: componentRef?.navigation() === navigation,
            });
            if (options.shadowThrows) throw new Error('shadow failed');
          },
        },
      },
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
  const component = injector.get(MissionRoomComponent);
  componentRef = component;
  return {
    component,
    workspace,
    postCalls,
    patchCalls,
    getCalls,
    blobCalls,
    opens,
    navigations,
    urlNavigations,
    missionShadowCalls,
  };
}

function authoritativeMissionContext(
  mission: WorkspaceAppRuntimeMissionRoom,
  actionPacks: string[],
  tamperedSettings: Record<string, unknown>,
): Record<string, unknown> {
  const appId = mission.app_id;
  const brandingNamespace = appId.startsWith('sentinel.') ? 'sentinel' : 'octocity';
  const runtime: WorkspaceAppRuntimeProjection = {
    mode: 'authoritative',
    enabled: true,
    valid: true,
    installations: [{
      app_id: appId,
      version: mission.version,
      manifest_digest: mission.manifest_digest,
      category: 'workspace_extension',
      routes: ['/hypervisor/mission-room'],
      primary_surface_id: 'mission-room',
      default_route: mission.default_route,
      branding_namespace: brandingNamespace,
      api_prefixes: ['/api/v1/mission-room'],
      action_packs: actionPacks,
      entitlement_keys: [],
    }],
    experience: {
      shell: 'immersive',
      routes: ['/hypervisor/mission-room'],
      primary_surface_ids: ['mission-room'],
      default_routes: { [appId]: mission.default_route },
      branding_namespaces: [brandingNamespace],
      api_prefixes: ['/api/v1/mission-room'],
      action_packs: actionPacks,
      mission_room: mission,
    },
  };
  return {
    mode: 'demo',
    settings: {
      ...tamperedSettings,
      features: { workspace_app_platform_v1: true },
    },
    workspace_app_runtime: runtime,
  };
}

function installTestWindow(): () => void {
  const previousWindow = globalThis.window;
  Object.defineProperty(globalThis, 'window', {
    configurable: true,
    value: new EventTarget(),
  });
  return () => {
    if (previousWindow) {
      Object.defineProperty(globalThis, 'window', {
        configurable: true,
        value: previousWindow,
      });
    } else {
      Reflect.deleteProperty(globalThis, 'window');
    }
  };
}

test('MissionRoom presentation uses runtime authority over crossed legacy settings', () => {
  const restoreWindow = installTestWindow();
  const sentinel: WorkspaceAppRuntimeMissionRoom = {
    profile: 'sentinel_government_v1',
    assistant_profile: 'vigie_executive',
    label: 'SENTINEL-CI',
    assistant_label: 'AYA',
    brand_style: 'sentinel',
    navigation_keys: ['cockpit'],
    app_id: 'sentinel.mission-room',
    version: '1.0.0',
    manifest_digest: 'sentinel-digest',
    default_route: '/hypervisor/mission-room/cockpit',
    primary_surface_id: 'mission-room',
  };
  const octocity: WorkspaceAppRuntimeMissionRoom = {
    profile: 'octocity_institutional_v1',
    assistant_profile: 'octave_executive',
    label: 'Octocity Mission Room',
    assistant_label: 'OCTAVE',
    brand_style: 'agentium',
    navigation_keys: ['cockpit'],
    app_id: 'octocity.mission-room',
    version: '1.0.0',
    manifest_digest: 'octocity-digest',
    default_route: '/hypervisor/mission-room/cockpit',
    primary_surface_id: 'mission-room',
  };
  const cases = [
    {
      mission: sentinel,
      actionPacks: ['global_voice_v1', 'sentinel_ci_aya_v1'],
      tampered: {
        demo_profile: 'octocity_mission_room',
        assistant_profile_default: 'octave_executive',
        workspace_app_label: 'Octocity Mission Room',
        workspace_app_brand: { label: 'Octocity Mission Room', style: 'agentium' },
        mission_room: { enabled: true, profile: 'octocity_institutional_v1', assistant_label: 'OCTAVE' },
      },
    },
    {
      mission: octocity,
      actionPacks: ['global_voice_v1', 'octave_mission_room_v1'],
      tampered: {
        demo_profile: 'government_mission_room',
        assistant_profile_default: 'vigie_executive',
        workspace_app_label: 'SENTINEL-CI',
        workspace_app_brand: { label: 'SENTINEL-CI', style: 'sentinel' },
        mission_room: { enabled: true, profile: 'sentinel_government_v1', assistant_label: 'AYA' },
      },
    },
  ];

  try {
    for (const current of cases) {
      const harness = createHarness({
        workspaceContext: authoritativeMissionContext(
          current.mission,
          current.actionPacks,
          current.tampered,
        ),
      });
      try {
        assert.equal(harness.component.missionExtension().authority, 'workspace_app_runtime');
        assert.equal(harness.component.missionExtension().profile, current.mission.profile);
        assert.equal(harness.component.assistantName(), current.mission.assistant_label);
        assert.equal(harness.component.assistantProfileKey(), current.mission.assistant_profile);
        assert.equal(harness.component.missionBrandLabel(), current.mission.label);
        assert.equal(harness.component.missionBrandStyle(), current.mission.brand_style);
        assert.deepEqual(harness.component.missionExtension().actionPacks, current.actionPacks);
      } finally {
        harness.component.ngOnDestroy();
      }
    }
  } finally {
    restoreWindow();
  }
});

test('MissionRoom direct construction stays neutral when enabled runtime authority is invalid', () => {
  const restoreWindow = installTestWindow();
  const harness = createHarness({
    workspaceContext: {
      mode: 'demo',
      settings: {
        features: { workspace_app_platform_v1: true },
        demo_profile: 'government_mission_room',
        workspace_app_label: 'SENTINEL-CI',
        assistant_profile_default: 'vigie_executive',
        mission_room: { enabled: true, profile: 'sentinel_government_v1', assistant_label: 'AYA' },
      },
      workspace_app_runtime: {
        mode: 'authoritative',
        enabled: true,
        valid: false,
        installations: [],
        experience: null,
      },
    },
  });
  try {
    assert.equal(harness.component.missionExtension().authority, 'fail_closed');
    assert.equal(harness.component.missionExtension().enabled, false);
    assert.equal(harness.component.assistantName(), 'Assistant');
    assert.equal(harness.component.assistantProfileKey(), 'default');
    assert.equal(harness.component.missionBrandLabel(), 'Mission Room');
    assert.equal(harness.component.missionBrandStyle(), 'agentium');
    assert.equal(harness.component.octocityProfile(), false);
    assert.equal(harness.component.newsEyebrowLabel(), 'Alerte presse');
    assert.equal(harness.component.missionRoomRoleLabel(), 'Mission Room · Vice Premier Ministre');
    assert.equal(harness.component.strategicMapEyebrowLabel(), 'Carte strategique');
    assert.equal(harness.component.ministerialRisk('critical'), 'prioritaire');
  } finally {
    harness.component.ngOnDestroy();
    restoreWindow();
  }
});

test('MissionRoom observes the authoritative navigation payload only after installing it unchanged', () => {
  const previousWindow = globalThis.window;
  Object.defineProperty(globalThis, 'window', {
    configurable: true,
    value: new EventTarget(),
  });
  const harness = createHarness();
  const { component, getCalls, missionShadowCalls } = harness;
  const navigation = {
    workspace: { id: 'workspace-sentinel', slug: 'sentinel-ci', name: 'SENTINEL-CI' },
    app: {
      label: 'SENTINEL-CI',
      assistant_label: 'AYA',
      shell: 'immersive',
      default_route: '/hypervisor/mission-room/cockpit',
      default_view: 'cockpit',
      profile: 'sentinel_government_v1',
    },
    items: [{
      key: 'cockpit',
      label: 'Cockpit',
      glyph: 'ledger',
      route: '/hypervisor/mission-room/cockpit',
      api: '/api/v1/mission-room/cockpit',
      object: 'Workbench',
      workbench: 'Workbench',
    }],
    exit_routes: [],
  };

  try {
    (component as unknown as { loadAll(showSpinner?: boolean): void }).loadAll(false);
    assert.deepEqual(getCalls.map((call) => call.options?.workspaceSlug), [
      'sentinel-ci',
      'sentinel-ci',
    ]);

    getCalls[0].response.next(navigation);
    getCalls[0].response.complete();
    getCalls[1].response.next({ briefing_status: 'ready' });
    getCalls[1].response.complete();

    assert.equal(component.navigation(), navigation);
    assert.equal(missionShadowCalls.length, 1);
    assert.equal(missionShadowCalls[0].navigation, navigation);
    assert.deepEqual(missionShadowCalls[0].scope, {
      workspaceSlug: 'sentinel-ci',
      workspaceId: 'workspace-sentinel-ci',
      epoch: 11,
    });
    assert.equal(missionShadowCalls[0].installedBeforeObservation, true);
  } finally {
    component.ngOnDestroy();
    if (previousWindow) {
      Object.defineProperty(globalThis, 'window', {
        configurable: true,
        value: previousWindow,
      });
    } else {
      Reflect.deleteProperty(globalThis, 'window');
    }
  }
});

test('MissionRoom neither installs nor observes a navigation response invalidated by A -> B', () => {
  const previousWindow = globalThis.window;
  Object.defineProperty(globalThis, 'window', {
    configurable: true,
    value: new EventTarget(),
  });
  const harness = createHarness();
  const { component, workspace, getCalls, missionShadowCalls } = harness;

  try {
    (component as unknown as { loadAll(showSpinner?: boolean): void }).loadAll(false);
    workspace.switchWorkspace();
    assert.ok(getCalls.every((call) => !call.response.observed));

    getCalls[0].response.next({ items: [{ key: 'late-a' }] });
    getCalls[0].response.complete();
    getCalls[1].response.next({ briefing_status: 'late-a' });
    getCalls[1].response.complete();

    assert.equal(component.navigation(), null);
    assert.deepEqual(missionShadowCalls, []);
  } finally {
    component.ngOnDestroy();
    if (previousWindow) {
      Object.defineProperty(globalThis, 'window', {
        configurable: true,
        value: previousWindow,
      });
    } else {
      Reflect.deleteProperty(globalThis, 'window');
    }
  }
});

test('MissionRoom direct rail switch purges tenant state before publishing the next epoch', () => {
  const previousWindow = globalThis.window;
  Object.defineProperty(globalThis, 'window', {
    configurable: true,
    value: new EventTarget(),
  });
  const harness = createHarness();
  const { component, workspace, urlNavigations } = harness;
  const resetSnapshots: Array<{
    scope: WorkspaceRequestScope;
    navigation: unknown;
    draft: unknown;
  }> = [];

  try {
    component.navigation.set({ items: [{ key: 'tenant-a' }] } as never);
    component.draft.set({ id: 'tenant-a-draft' } as never);
    const before = workspace.captureRequestScope();
    const unregisterObservation = workspace.registerContextReset(() => {
      resetSnapshots.push({
        scope: workspace.captureRequestScope(),
        navigation: component.navigation(),
        draft: component.draft(),
      });
    });

    component.selectWorkspace('octocity-mission-room');
    unregisterObservation();

    assert.deepEqual(resetSnapshots, [{
      scope: before,
      navigation: null,
      draft: null,
    }], 'MissionRoom state is purged while the old workspace identity is still authoritative');
    assert.deepEqual(workspace.captureRequestScope(), {
      workspaceSlug: 'octocity-mission-room',
      workspaceId: 'workspace-octocity-mission-room',
      epoch: before.epoch + 1,
    });
    assert.deepEqual(urlNavigations, ['/'], 'the root resolver remains the destination owner');
  } finally {
    component.ngOnDestroy();
    if (previousWindow) {
      Object.defineProperty(globalThis, 'window', {
        configurable: true,
        value: previousWindow,
      });
    } else {
      Reflect.deleteProperty(globalThis, 'window');
    }
  }
});

test('MissionRoom continues the legacy payload flow when shadow observation throws', () => {
  const previousWindow = globalThis.window;
  Object.defineProperty(globalThis, 'window', {
    configurable: true,
    value: new EventTarget(),
  });
  const harness = createHarness({ shadowThrows: true });
  const { component, getCalls, missionShadowCalls } = harness;
  const navigation = {
    workspace: { id: 'workspace-sentinel', slug: 'sentinel-ci', name: 'SENTINEL-CI' },
    app: {
      label: 'SENTINEL-CI',
      assistant_label: 'AYA',
      shell: 'immersive',
      default_route: '/hypervisor/mission-room/cockpit',
      default_view: 'cockpit',
    },
    items: [],
    exit_routes: [],
  };
  const cockpit = { briefing_status: 'ready' };

  try {
    (component as unknown as { loadAll(showSpinner?: boolean): void }).loadAll(true);
    getCalls[0].response.next(navigation);
    getCalls[0].response.complete();
    getCalls[1].response.next(cockpit);
    getCalls[1].response.complete();

    assert.equal(missionShadowCalls.length, 1);
    assert.equal(missionShadowCalls[0].installedBeforeObservation, true);
    assert.equal(component.navigation(), navigation);
    assert.equal(component.cockpit(), cockpit);
    assert.equal(component.loading(), false);
    assert.ok(getCalls.length > 2, 'legacy detail loading must continue after the shadow error');
  } finally {
    component.ngOnDestroy();
    if (previousWindow) {
      Object.defineProperty(globalThis, 'window', {
        configurable: true,
        value: previousWindow,
      });
    } else {
      Reflect.deleteProperty(globalThis, 'window');
    }
  }
});

test('MissionRoom cancels the scoped createAction refresh before late A reads can mutate B', () => {
  const previousWindow = globalThis.window;
  Object.defineProperty(globalThis, 'window', {
    configurable: true,
    value: new EventTarget(),
  });
  const harness = createHarness();
  const { component, workspace, postCalls, getCalls, opens } = harness;

  try {
    (component as unknown as { createAction(payload: { title: string }): void })
      .createAction({ title: 'Action A' });
    assert.equal(postCalls[0].options?.workspaceSlug, 'sentinel-ci');

    postCalls[0].response.next({ title: 'Action A' });
    assert.deepEqual(
      getCalls.map((call) => call.path),
      ['/mission-room/navigation', '/mission-room/cockpit'],
    );
    assert.deepEqual(getCalls.map((call) => call.options?.workspaceSlug), ['sentinel-ci', 'sentinel-ci']);
    assert.equal(opens.length, 1);

    workspace.switchWorkspace();
    assert.equal(component.loading(), false);
    assert.ok(getCalls.every((call) => !call.response.observed));

    getCalls[0].response.next({ items: [{ key: 'andritz-private' }] });
    getCalls[0].response.complete();
    getCalls[1].response.next({ kpis: { private_a: 1 } });
    getCalls[1].response.complete();
    assert.equal(component.navigation(), null);
    assert.equal(component.cockpit(), null);
  } finally {
    component.ngOnDestroy();
    if (previousWindow) {
      Object.defineProperty(globalThis, 'window', {
        configurable: true,
        value: previousWindow,
      });
    } else {
      Reflect.deleteProperty(globalThis, 'window');
    }
  }
});

test('MissionRoom cancels action and pending-agenda continuations on A -> B', () => {
  const previousWindow = globalThis.window;
  Object.defineProperty(globalThis, 'window', {
    configurable: true,
    value: new EventTarget(),
  });
  const harness = createHarness();
  const { component, workspace, postCalls, getCalls } = harness;

  try {
    component.completeAction({ id: 'action-complete' } as never);
    component.cancelAction({ id: 'action-cancel' } as never);
    component.selectAgendaEvent({ id: 'meeting-a' } as never);
    component.agendaPendingPatch.set({ id: 'pending-a', agenda_items: [] } as never);
    component.confirmAgendaPendingPatch();
    component.createDraft('target-a', 'project');

    assert.deepEqual(
      postCalls.map((call) => call.options?.workspaceSlug),
      ['sentinel-ci', 'sentinel-ci', 'sentinel-ci', 'sentinel-ci'],
    );
    assert.equal(getCalls[0].options?.workspaceSlug, 'sentinel-ci');

    workspace.switchWorkspace();
    assert.ok(postCalls.every((call) => !call.response.observed));
    assert.equal(getCalls[0].response.observed, false);
    assert.equal(component.selectedAgendaEvent(), null);
    assert.equal(component.agendaPendingPatch(), null);
    assert.equal(component.agendaPatchSubmitting(), false);
    assert.equal(component.draft(), null);

    postCalls.forEach((call) => call.response.next({ status: 'late-a' }));
    getCalls[0].response.next({ pending_agenda_patch: { id: 'late-a' } });
    assert.equal(getCalls.length, 1, 'late action callbacks cannot start a MissionRoom refresh');
    assert.equal(component.agendaPendingPatch(), null);
    assert.equal(component.draft(), null);
  } finally {
    component.ngOnDestroy();
    if (previousWindow) {
      Object.defineProperty(globalThis, 'window', {
        configurable: true,
        value: previousWindow,
      });
    } else {
      Reflect.deleteProperty(globalThis, 'window');
    }
  }
});

test('MissionRoom startMeeting stays pinned to A and cannot navigate after A -> B', () => {
  const previousWindow = globalThis.window;
  Object.defineProperty(globalThis, 'window', {
    configurable: true,
    value: new EventTarget(),
  });
  const harness = createHarness();
  const { component, workspace, postCalls, navigations } = harness;

  try {
    component.startMeeting({ id: 'meeting-a' } as never);
    assert.equal(postCalls[0].path, '/meetings/meeting-a/start');
    assert.equal(postCalls[0].options?.workspaceSlug, 'sentinel-ci');

    workspace.switchWorkspace();
    assert.equal(postCalls[0].response.observed, false);

    postCalls[0].response.next({ status: 'late-a' });
    assert.deepEqual(navigations, []);
  } finally {
    component.ngOnDestroy();
    if (previousWindow) {
      Object.defineProperty(globalThis, 'window', {
        configurable: true,
        value: previousWindow,
      });
    } else {
      Reflect.deleteProperty(globalThis, 'window');
    }
  }
});

test('MissionRoom cancels visual capture and image hydration before Sentinel can leak into Octocity', () => {
  const previousWindow = globalThis.window;
  Object.defineProperty(globalThis, 'window', {
    configurable: true,
    value: new EventTarget(),
  });
  const harness = createHarness();
  const { component, workspace, postCalls, blobCalls, navigations } = harness;
  const internal = component as unknown as {
    captureWorkspaceContinuation(): { scope: WorkspaceRequestScope; generation: number };
    hydrateVisualCaptureImages(
      monitor: unknown,
      continuation: { scope: WorkspaceRequestScope; generation: number },
    ): void;
  };

  try {
    component.captureVisualSource({ id: 'sentinel-source' } as never);
    internal.hydrateVisualCaptureImages(
      { visual: { captures: [{ id: 'sentinel-capture', status: 'captured' }] } },
      internal.captureWorkspaceContinuation(),
    );

    assert.equal(postCalls[0].options?.workspaceSlug, 'sentinel-ci');
    assert.equal(blobCalls[0].options?.workspaceSlug, 'sentinel-ci');

    workspace.switchWorkspace('octocity-mission-room');
    assert.equal(postCalls[0].response.observed, false);
    assert.equal(blobCalls[0].response.observed, false);

    postCalls[0].response.next({ capture: { id: 'late-sentinel-capture' } });
    blobCalls[0].response.next(new Blob(['sentinel-private-image']));

    assert.deepEqual(navigations, []);
    assert.deepEqual(component.visualCaptureImages(), {});
  } finally {
    component.ngOnDestroy();
    if (previousWindow) {
      Object.defineProperty(globalThis, 'window', {
        configurable: true,
        value: previousWindow,
      });
    } else {
      Reflect.deleteProperty(globalThis, 'window');
    }
  }
});

test('MissionRoom cancels every agenda write continuation before Sentinel -> Octocity publication', () => {
  const previousWindow = globalThis.window;
  Object.defineProperty(globalThis, 'window', {
    configurable: true,
    value: new EventTarget(),
  });
  const harness = createHarness();
  const { component, workspace, postCalls, patchCalls, getCalls } = harness;

  try {
    component.newAgendaTitle = 'Sentinel confidential agenda';
    component.createAgendaEvent();
    component.selectedAgendaEvent.set({
      id: 'sentinel-meeting',
      date: '2026-07-22',
      time: '09:00',
      end_time: '09:45',
      metadata: { agenda_items: [] },
    } as never);
    component.moveSelectedAgendaEvent(30);
    component.cancelSelectedAgendaEvent();
    component.addAgendaSubItem();

    assert.deepEqual(
      postCalls.map((call) => [call.path, call.options?.workspaceSlug]),
      [
        ['/calendar/events', 'sentinel-ci'],
        ['/calendar/events/sentinel-meeting/cancel', 'sentinel-ci'],
      ],
    );
    assert.deepEqual(
      patchCalls.map((call) => [call.path, call.options?.workspaceSlug]),
      [
        ['/calendar/events/sentinel-meeting', 'sentinel-ci'],
        ['/calendar/events/sentinel-meeting', 'sentinel-ci'],
      ],
    );

    workspace.switchWorkspace('octocity-mission-room');
    assert.ok(postCalls.every((call) => !call.response.observed));
    assert.ok(patchCalls.every((call) => !call.response.observed));

    postCalls.forEach((call) => call.response.next({ id: 'late-sentinel' }));
    patchCalls.forEach((call) => call.response.next({ id: 'late-sentinel' }));

    assert.equal(component.selectedAgendaEvent(), null);
    assert.equal(component.newAgendaTitle, '');
    assert.equal(getCalls.length, 0, 'late agenda writes cannot refresh the next workspace');
  } finally {
    component.ngOnDestroy();
    if (previousWindow) {
      Object.defineProperty(globalThis, 'window', {
        configurable: true,
        value: previousWindow,
      });
    } else {
      Reflect.deleteProperty(globalThis, 'window');
    }
  }
});

for (const [from, to] of [
  ['sentinel-ci', 'octocity-mission-room'],
  ['octocity-mission-room', 'sentinel-ci'],
] as const) {
  test(`MissionRoom ignores a delayed search response across ${from} -> ${to}`, () => {
    const previousWindow = globalThis.window;
    Object.defineProperty(globalThis, 'window', {
      configurable: true,
      value: new EventTarget(),
    });
    const harness = createHarness();
    const { component, workspace, getCalls } = harness;

    try {
      if (workspace.currentSlug() !== from) workspace.switchWorkspace(from);
      component.searchQueryValue = `${from}-private-query`;
      component.runSearch();
      assert.equal(getCalls[0].options?.workspaceSlug, from);

      workspace.switchWorkspace(to);
      assert.equal(getCalls[0].response.observed, false);
      getCalls[0].response.next({
        total: 1,
        results: [{ id: `${from}-private-result` }],
      });

      assert.equal(component.search(), null);
      assert.equal(component.searchQueryValue, '');
      assert.equal(workspace.currentSlug(), to);
    } finally {
      component.ngOnDestroy();
      if (previousWindow) {
        Object.defineProperty(globalThis, 'window', {
          configurable: true,
          value: previousWindow,
        });
      } else {
        Reflect.deleteProperty(globalThis, 'window');
      }
    }
  });
}

test('generic Agentium branding is not classified as the Octocity presentation', () => {
  const rail = new MissionRailComponent();
  const mapItem = {
    key: 'strategie',
    label: 'Legacy label',
    glyph: 'sliders',
    route: '/hypervisor/mission-room/strategie',
    api: '/mission-room/strategy',
    object: 'Strategy',
    workbench: 'Strategy',
  } as const;

  rail.brandStyle = 'agentium';
  rail.assistantName = 'Assistant';
  rail.missionProfile = 'generic';

  assert.equal(rail.assistantOpenLabel, 'Ouvrir Assistant');
  assert.equal(rail.searchLabel, 'Recherche dossier');
  assert.equal(rail.railSectionLabel, 'Parcours Mission');
  assert.equal(rail.railLabel(mapItem), 'Carte');

  rail.missionProfile = OCTOCITY_MISSION_ROOM_PROFILE;

  assert.equal(rail.assistantOpenLabel, 'Open Assistant');
  assert.equal(rail.searchLabel, 'Search dossier');
  assert.equal(rail.railSectionLabel, 'Mission path');
  assert.equal(rail.railLabel(mapItem), 'Map');
});

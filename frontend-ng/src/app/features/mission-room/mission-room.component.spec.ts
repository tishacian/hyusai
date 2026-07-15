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
  type WorkspaceContextTransition,
  type WorkspaceRequestScope,
} from '@app/core/workspace.service';
import { ChatOverlayService } from '@app/features/chat/chat-overlay.service';
import { MissionRoomComponent } from './mission-room.component';

interface ApiCall {
  path: string;
  options?: { workspaceSlug?: string | null };
  response: Subject<unknown>;
}

class WorkspaceStub {
  private slug = 'sentinel-ci';
  private epoch = 11;
  private readonly resetters = new Set<(transition: WorkspaceContextTransition) => void>();

  currentSlug = () => this.slug;
  current = () => ({ settings: {} });

  captureRequestScope(): WorkspaceRequestScope {
    return Object.freeze({ workspaceSlug: this.slug, epoch: this.epoch });
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
      nextSlug: 'octocity-mission-room',
      previousEpoch: this.epoch,
      nextEpoch: this.epoch + 1,
    };
    for (const resetter of [...this.resetters]) resetter(transition);
    this.slug = transition.nextSlug;
    this.epoch = transition.nextEpoch;
  }
}

function createHarness(options: { shadowThrows?: boolean } = {}) {
  const workspace = new WorkspaceStub();
  const postCalls: ApiCall[] = [];
  const getCalls: ApiCall[] = [];
  const opens: unknown[] = [];
  const navigations: unknown[][] = [];
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
    get: (path: string, _params?: Record<string, string>, options?: ApiCall['options']) => record(getCalls, path, options),
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
          navigateByUrl: () => Promise.resolve(true),
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
    getCalls,
    opens,
    navigations,
    missionShadowCalls,
  };
}

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
      profile: '',
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

import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector, signal } from '@angular/core';
import { ActivatedRoute, Router, convertToParamMap } from '@angular/router';
import { BehaviorSubject, Subject, of } from 'rxjs';
import { CanonicalApiService } from '@app/core/canonical-api.service';
import { I18nService } from '@app/core/i18n.service';
import { LensService } from '@app/core/lens';
import { ObjectPerspectiveStore } from '@app/core/object-perspective.store';
import { WorkspaceService, type WorkspaceRequestScope } from '@app/core/workspace.service';
import { ZoomContextService } from '@app/core/zoom-context.service';
import type { ObjectLens } from '@app/core/navigation.catalog';
import type { ObjectPerspectiveResponse } from '@app/shared/cockpit/object-perspective.models';
import { SkillInvocationViewComponent } from './skill-invocation-view.component';

class WorkspaceStub {
  private readonly projectionsEnabled = signal(true);
  private readonly refreshSubject = new Subject<void>();
  readonly contextRefresh$ = this.refreshSubject.asObservable();
  constructor(projectionsEnabled = true) {
    this.projectionsEnabled.set(projectionsEnabled);
  }
  readonly currentSlug = () => 'showcase';
  readonly contextEpoch = () => 1;
  readonly current = () => ({
    id: 'workspace-showcase',
    settings: { features: { skill_invocation_360_projection_v1: this.projectionsEnabled() } },
    effective_features: { skill_invocation_360_projection_v1: this.projectionsEnabled() },
  });
  captureRequestScope(): WorkspaceRequestScope {
    return Object.freeze({ workspaceSlug: 'showcase', workspaceId: 'workspace-showcase', epoch: 1 });
  }
  isRequestScopeCurrent(scope: WorkspaceRequestScope): boolean {
    return scope.workspaceSlug === 'showcase'
      && scope.workspaceId === 'workspace-showcase'
      && scope.epoch === 1;
  }
  registerContextReset(): () => void { return () => undefined; }
  setProjectionEnabled(enabled: boolean): void {
    this.projectionsEnabled.set(enabled);
    this.refreshSubject.next();
  }
}

function emptyBundle(): Record<ObjectLens, ObjectPerspectiveResponse> {
  return {
    build: {} as ObjectPerspectiveResponse,
    operate: {} as ObjectPerspectiveResponse,
    steer: {} as ObjectPerspectiveResponse,
    govern: {} as ObjectPerspectiveResponse,
  };
}

test('SkillInvocation facets follow validated deep links and preserve query context on tab changes', () => {
  const params = new BehaviorSubject(convertToParamMap({
    runId: 'run-1',
    invocationId: 'invocation-1',
  }));
  const query = new BehaviorSubject(convertToParamMap({
    lens: 'govern',
    facet: 'runtime',
    capabilityId: 'capability-1',
  }));
  const route = {
    paramMap: params.asObservable(),
    queryParamMap: query.asObservable(),
    snapshot: { paramMap: params.value, queryParamMap: query.value },
  };
  const navigations: Array<{ commands: unknown[]; extras: Record<string, unknown> }> = [];
  const router = {
    navigate: (commands: unknown[], extras: Record<string, unknown>) => {
      navigations.push({ commands, extras });
      return Promise.resolve(true);
    },
  };
  const injector = Injector.create({
    providers: [
      SkillInvocationViewComponent,
      { provide: ActivatedRoute, useValue: route },
      { provide: Router, useValue: router },
      { provide: CanonicalApiService, useValue: { getSkillInvocation: () => of(null), getRun: () => of(null) } },
      { provide: WorkspaceService, useValue: new WorkspaceStub() },
      { provide: ObjectPerspectiveStore, useValue: { loadAll: () => of(emptyBundle()) } },
      { provide: LensService, useValue: { lens: () => 'govern' } },
      { provide: I18nService, useValue: { locale: () => 'fr', t: (key: string) => key } },
      { provide: ZoomContextService, useValue: { navV5Enabled: () => false, zoneI18nKey: () => 'nav.operate' } },
    ],
  });
  const view = injector.get(SkillInvocationViewComponent);
  view.ngOnInit();

  assert.equal(view.activeTab(), 'runtime');
  query.next(convertToParamMap({ facet: 'forged' }));
  assert.equal(view.activeTab(), 'overview');
  query.next(convertToParamMap({ facet: 'io' }));
  assert.equal(view.activeTab(), 'io');

  view.onTabChange('governance');
  assert.equal(view.activeTab(), 'governance');
  assert.deepEqual(navigations[0]?.commands, []);
  assert.equal(navigations[0]?.extras['relativeTo'], route);
  assert.deepEqual(navigations[0]?.extras['queryParams'], { facet: 'governance' });
  assert.equal(navigations[0]?.extras['queryParamsHandling'], 'merge');
  view.onTabChange('forged');
  assert.equal(navigations.length, 1);
  view.ngOnDestroy();
});

test('SkillInvocation loads its projection when the effective gate activates in the same workspace epoch', () => {
  const params = new BehaviorSubject(convertToParamMap({
    runId: 'run-1',
    invocationId: 'invocation-1',
  }));
  const query = new BehaviorSubject(convertToParamMap({ lens: 'operate' }));
  const workspace = new WorkspaceStub(false);
  let perspectiveLoads = 0;
  const injector = Injector.create({
    providers: [
      SkillInvocationViewComponent,
      {
        provide: ActivatedRoute,
        useValue: {
          paramMap: params.asObservable(),
          queryParamMap: query.asObservable(),
          snapshot: { paramMap: params.value, queryParamMap: query.value },
        },
      },
      { provide: Router, useValue: { navigate: () => Promise.resolve(true) } },
      { provide: CanonicalApiService, useValue: { getSkillInvocation: () => of(null), getRun: () => of(null) } },
      { provide: WorkspaceService, useValue: workspace },
      {
        provide: ObjectPerspectiveStore,
        useValue: {
          loadAll: () => {
            perspectiveLoads += 1;
            return of(emptyBundle());
          },
        },
      },
      { provide: LensService, useValue: { lens: () => 'operate' } },
      { provide: I18nService, useValue: { locale: () => 'fr', t: (key: string) => key } },
      { provide: ZoomContextService, useValue: { navV5Enabled: () => false, zoneI18nKey: () => 'nav.operate' } },
    ],
  });
  const view = injector.get(SkillInvocationViewComponent);

  view.ngOnInit();
  assert.equal(perspectiveLoads, 0);
  workspace.setProjectionEnabled(true);

  assert.equal(view.projectionEnabled(), true);
  assert.equal(perspectiveLoads, 1, 'same-epoch activation reloads without route navigation');
  view.ngOnDestroy();
});


test('Invocation audit uses only the authorized Run payload when projections are off and clears stale evidence', () => {
  const params = new BehaviorSubject(convertToParamMap({ runId: 'run-1', invocationId: 'inv-1' }));
  const query = new BehaviorSubject(convertToParamMap({ lens: 'operate', systemId: 'system-1' }));
  const workspace = new WorkspaceStub(false);
  const requests: Subject<any>[] = [];
  let projectionLoads = 0;
  let invocationLoads = 0;
  const injector = Injector.create({ providers: [
    SkillInvocationViewComponent,
    { provide: ActivatedRoute, useValue: { paramMap: params, queryParamMap: query } },
    { provide: Router, useValue: { navigate: () => Promise.resolve(true) } },
    { provide: WorkspaceService, useValue: workspace },
    { provide: CanonicalApiService, useValue: {
      getRun: () => { const request = new Subject<any>(); requests.push(request); return request; },
      getSkillInvocation: () => { invocationLoads++; return of({ id: 'inv-2', trace: { projection_only: true } }); },
    } },
    { provide: ObjectPerspectiveStore, useValue: { loadAll: () => { projectionLoads++; return of(emptyBundle()); } } },
    { provide: LensService, useValue: { lens: () => 'operate' } },
    { provide: I18nService, useValue: { locale: () => 'en', t: (key: string) => key } },
    { provide: ZoomContextService, useValue: {} },
  ] });
  const view = injector.get(SkillInvocationViewComponent);
  view.ngOnInit();
  assert.equal(view.loading(), true);
  assert.equal(invocationLoads, 0, 'disabled endpoint is never requested');
  assert.equal(projectionLoads, 0);
  requests[0].next({ id: 'run-1', skill_invocations: [
    { id: 'other', output_ref: { wrong: true } },
    { id: 'inv-1', status: 'completed', latency_ms: 10.6, output_ref: { checked: true, human_validated: false } },
  ] });
  assert.equal(view.invocation()?.id, 'inv-1');
  assert.deepEqual(JSON.parse(view.auditJson()).output_ref, { checked: true, human_validated: false });
  assert.equal(view.kpis()[1].value, '11 ms');
  assert.equal(view.loading(), false);

  params.next(convertToParamMap({ runId: 'run-2', invocationId: 'inv-2' }));
  assert.equal(view.invocation(), null);
  assert.equal(view.auditJson(), '');
  requests[0].next({ id: 'run-1', skill_invocations: [{ id: 'inv-1' }] });
  assert.equal(view.invocation(), null, 'late response cannot restore the previous Run');
  requests[1].next({ id: 'run-2', skill_invocations: [{ id: 'other' }] });
  assert.equal(view.error(), true, 'an absent or permission-filtered invocation stays unavailable');
  assert.equal(view.invocation(), null);
  view.retry();
  requests[2].error(new Error('offline'));
  assert.equal(view.error(), true);
  assert.equal(view.loading(), false);
  view.retry();
  requests[3].next({ id: 'wrong-run', skill_invocations: [{ id: 'inv-2' }] });
  assert.equal(view.invocation(), null, 'an invocation must belong to the requested Run');

  workspace.setProjectionEnabled(true);
  assert.equal(invocationLoads, 1);
  assert.equal(projectionLoads, 1);
  assert.equal(view.invocation()?.trace?.['projection_only'], true);
  workspace.setProjectionEnabled(false);
  assert.equal(view.invocation(), null, 'revocation removes richer evidence before loading the Run audit');
  assert.deepEqual(view.perspectives(), {});
  requests[4].next({ id: 'run-2', skill_invocations: [{ id: 'inv-2', output_ref: {} }] });
  assert.equal(view.invocation()?.id, 'inv-2');
  assert.deepEqual(JSON.parse(view.auditJson()).trace, {}, 'no reconstruction of redacted evidence');
  assert.equal(invocationLoads, 1);
  view.ngOnDestroy();
  assert.equal(view.invocation(), null);
});

test('SkillInvocation shows Depuis la trace {id} when arrival provenance is present', () => {
  const previous = (globalThis as { history?: { state?: unknown } }).history;
  Object.defineProperty(globalThis, 'history', {
    configurable: true,
    value: {
      state: {
        ckArrivalProvenance: {
          kind: 'trace',
          traceId: 'run-trace-9',
          backUrl: '/runs/run-trace-9?facet=trace',
        },
      },
    },
  });
  try {
    const params = new BehaviorSubject(convertToParamMap({
      runId: 'run-trace-9',
      invocationId: 'invocation-1',
    }));
    const query = new BehaviorSubject(convertToParamMap({}));
    const injector = Injector.create({
      providers: [
        SkillInvocationViewComponent,
        {
          provide: ActivatedRoute,
          useValue: {
            paramMap: params.asObservable(),
            queryParamMap: query.asObservable(),
            snapshot: { paramMap: params.value, queryParamMap: query.value },
          },
        },
        { provide: Router, useValue: { navigate: () => Promise.resolve(true), navigateByUrl: () => Promise.resolve(true) } },
        { provide: CanonicalApiService, useValue: { getSkillInvocation: () => of(null), getRun: () => of(null) } },
        { provide: WorkspaceService, useValue: new WorkspaceStub(false) },
        { provide: ObjectPerspectiveStore, useValue: { loadAll: () => of(emptyBundle()) } },
        { provide: LensService, useValue: { lens: () => 'operate' } },
        {
          provide: I18nService,
          useValue: {
            locale: () => 'fr',
            t: (key: string, params?: Record<string, string>) => {
              if (key === 'runs.provenance.from_trace') {
                return `Depuis la trace ${params?.['id']}`;
              }
              if (key === 'nav.provenance.chip') {
                return `↰ ${params?.['from']} · Revenir`;
              }
              return key;
            },
          },
        },
        { provide: ZoomContextService, useValue: { navV5Enabled: () => false, zoneI18nKey: () => 'nav.operate' } },
      ],
    });
    const view = injector.get(SkillInvocationViewComponent);
    view.ngOnInit();
    assert.equal(view.arrivalChipLabel(), '↰ Depuis la trace run-trace-9 · Revenir');
    assert.equal(view.arrivalBackHref(), '/runs/run-trace-9?facet=trace');
    view.ngOnDestroy();
  } finally {
    Object.defineProperty(globalThis, 'history', {
      configurable: true,
      value: previous,
    });
  }
});

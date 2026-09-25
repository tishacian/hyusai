import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector, signal } from '@angular/core';
import { ActivatedRoute, Router, convertToParamMap } from '@angular/router';
import { BehaviorSubject, Subject, of } from 'rxjs';
import { CanonicalApiService } from '@app/core/canonical-api.service';
import { I18nService } from '@app/core/i18n.service';
import { LensService } from '@app/core/lens';
import {
  ObjectPerspectiveStore,
  type ObjectPerspectiveLoadOptions,
} from '@app/core/object-perspective.store';
import { WorkspaceService, type WorkspaceRequestScope } from '@app/core/workspace.service';
import { ZoomContextService } from '@app/core/zoom-context.service';
import type { ObjectLens } from '@app/core/navigation.catalog';
import type { ObjectPerspectiveResponse } from '@app/shared/cockpit/object-perspective.models';
import { RunViewComponent } from './run-view.component';

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
    settings: { features: { run_360_projection_v1: this.projectionsEnabled() } },
    effective_features: {
      run_360_projection_v1: this.projectionsEnabled(),
      skill_invocation_360_projection_v1: true,
    },
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

test('Run facets track history, merge tab changes and refresh can force store invalidation', () => {
  const params = new BehaviorSubject(convertToParamMap({ runId: 'run-1' }));
  const query = new BehaviorSubject(convertToParamMap({
    lens: 'operate',
    facet: 'payloads',
    systemId: 'system-1',
  }));
  const route = {
    paramMap: params.asObservable(),
    queryParamMap: query.asObservable(),
    snapshot: { paramMap: params.value, queryParamMap: query.value },
  };
  const navigations: Array<{ commands: unknown[]; extras?: Record<string, unknown> }> = [];
  const router = {
    navigate: (commands: unknown[], extras?: Record<string, unknown>) => {
      navigations.push({ commands, extras });
      return Promise.resolve(true);
    },
  };
  const loadOptions: ObjectPerspectiveLoadOptions[] = [];
  const store = {
    loadAll: (_request: unknown, options: ObjectPerspectiveLoadOptions = {}) => {
      loadOptions.push(options);
      return of(emptyBundle());
    },
  };
  const injector = Injector.create({
    providers: [
      RunViewComponent,
      { provide: ActivatedRoute, useValue: route },
      { provide: Router, useValue: router },
      { provide: CanonicalApiService, useValue: { getRun: () => of(null) } },
      { provide: WorkspaceService, useValue: new WorkspaceStub() },
      { provide: ObjectPerspectiveStore, useValue: store },
      { provide: LensService, useValue: { lens: () => 'operate' } },
      { provide: ZoomContextService, useValue: {} },
      { provide: I18nService, useValue: { locale: () => 'fr', t: (key: string) => key } },
    ],
  });
  const view = injector.get(RunViewComponent);
  view.ngOnInit();

  assert.equal(view.activePerspectiveTab(), 'payloads');
  query.next(convertToParamMap({ facet: 'forged' }));
  assert.equal(view.activePerspectiveTab(), 'overview');
  query.next(convertToParamMap({ facet: 'checkpoints' }));
  assert.equal(view.activePerspectiveTab(), 'checkpoints');

  view.onPerspectiveTabChange('invocations');
  assert.equal(view.activePerspectiveTab(), 'invocations');
  assert.deepEqual(navigations[0]?.commands, []);
  assert.equal(navigations[0]?.extras?.['relativeTo'], route);
  assert.deepEqual(navigations[0]?.extras?.['queryParams'], { facet: 'invocations' });
  assert.equal(navigations[0]?.extras?.['queryParamsHandling'], 'merge');
  view.onPerspectiveTabChange('forged');
  assert.equal(navigations.length, 1);

  view.refresh(true);
  assert.equal(loadOptions.at(-1)?.forceRefresh, true);
  view.ngOnDestroy();
});

test('Run loads its projection when the effective gate activates in the same workspace epoch', () => {
  const params = new BehaviorSubject(convertToParamMap({ runId: 'run-1' }));
  const query = new BehaviorSubject(convertToParamMap({ lens: 'operate' }));
  const workspace = new WorkspaceStub(false);
  let perspectiveLoads = 0;
  const injector = Injector.create({
    providers: [
      RunViewComponent,
      {
        provide: ActivatedRoute,
        useValue: {
          paramMap: params.asObservable(),
          queryParamMap: query.asObservable(),
          snapshot: { paramMap: params.value, queryParamMap: query.value },
        },
      },
      { provide: Router, useValue: { navigate: () => Promise.resolve(true) } },
      { provide: CanonicalApiService, useValue: { getRun: () => of(null) } },
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
      { provide: ZoomContextService, useValue: {} },
      { provide: I18nService, useValue: { locale: () => 'fr', t: (key: string) => key } },
    ],
  });
  const view = injector.get(RunViewComponent);

  view.ngOnInit();
  assert.equal(perspectiveLoads, 0);
  workspace.setProjectionEnabled(true);

  assert.equal(view.projectionEnabled(), true);
  assert.equal(perspectiveLoads, 1, 'same-epoch activation reloads without route navigation');
  view.ngOnDestroy();
});

test('overview exposes Temps passé to open the trace facet and never embeds the waterfall', () => {
  const params = new BehaviorSubject(convertToParamMap({ runId: 'run-1' }));
  const query = new BehaviorSubject(convertToParamMap({ facet: 'overview' }));
  const navigations: Array<{ extras?: Record<string, unknown> }> = [];
  const injector = Injector.create({
    providers: [
      RunViewComponent,
      {
        provide: ActivatedRoute,
        useValue: {
          paramMap: params.asObservable(),
          queryParamMap: query.asObservable(),
          snapshot: { paramMap: params.value, queryParamMap: query.value },
        },
      },
      {
        provide: Router,
        useValue: {
          navigate: (_commands: unknown[], extras?: Record<string, unknown>) => {
            navigations.push({ extras });
            return Promise.resolve(true);
          },
        },
      },
      {
        provide: CanonicalApiService,
        useValue: {
          getRun: () => of({
            id: 'run-1',
            system_id: 'sys-1',
            status: 'completed',
            duration_ms: 4000,
            skill_invocations: [
              {
                id: 'inv-1',
                skill_slug: 'long-skill',
                latency_ms: 4000,
                started_at: '2026-09-15T10:00:00Z',
                completed_at: '2026-09-15T10:00:04Z',
              },
            ],
          }),
        },
      },
      { provide: WorkspaceService, useValue: new WorkspaceStub(false) },
      { provide: ObjectPerspectiveStore, useValue: { loadAll: () => of(emptyBundle()) } },
      { provide: LensService, useValue: { lens: () => 'operate' } },
      { provide: ZoomContextService, useValue: {} },
      {
        provide: I18nService,
        useValue: {
          locale: () => 'fr',
          t: (key: string, params?: Record<string, string>) =>
            key === 'runs.detail.time_spent_meta'
              ? `${params?.['total']} · ${params?.['longest']}`
              : key,
        },
      },
    ],
  });
  const view = injector.get(RunViewComponent);
  view.ngOnInit();
  assert.equal(view.showingTrace(), false);
  assert.match(view.timeSpentLabel(), /long-skill/);
  view.openTrace();
  assert.equal(view.showingTrace(), true);
  assert.deepEqual(navigations.at(-1)?.extras?.['queryParams'], { facet: 'trace' });
  query.next(convertToParamMap({ facet: 'trace' }));
  assert.equal(view.showingTrace(), true);
  view.ngOnDestroy();
});

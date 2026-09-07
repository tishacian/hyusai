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
      { provide: CanonicalApiService, useValue: { getSkillInvocation: () => of(null) } },
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
      { provide: CanonicalApiService, useValue: { getSkillInvocation: () => of(null) } },
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

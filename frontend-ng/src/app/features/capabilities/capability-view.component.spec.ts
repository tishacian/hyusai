import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector, signal } from '@angular/core';
import { ActivatedRoute, Router, convertToParamMap } from '@angular/router';
import { BehaviorSubject, Subject, of, throwError } from 'rxjs';
import { CanonicalApiService } from '@app/core/canonical-api.service';
import { LensService } from '@app/core/lens';
import {
  ObjectPerspectiveGateRevokedError,
  ObjectPerspectiveStore,
} from '@app/core/object-perspective.store';
import {
  WorkspaceService,
  type WorkspaceRequestScope,
} from '@app/core/workspace.service';
import { CapabilityViewComponent } from './capability-view.component';

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
    settings: { features: { capability_360_projection_v1: this.projectionsEnabled() } },
    effective_features: { capability_360_projection_v1: this.projectionsEnabled() },
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

test('Capability facets follow validated query state and tab changes merge the URL', () => {
  const params = new BehaviorSubject(convertToParamMap({ capabilityId: 'capability-1' }));
  const query = new BehaviorSubject(convertToParamMap({
    lens: 'operate',
    facet: 'systems',
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
      CapabilityViewComponent,
      { provide: ActivatedRoute, useValue: route },
      { provide: Router, useValue: router },
      { provide: CanonicalApiService, useValue: { getCapability: () => of(null) } },
      { provide: WorkspaceService, useValue: new WorkspaceStub() },
      { provide: ObjectPerspectiveStore, useValue: { loadAll: () => of({}) } },
      { provide: LensService, useValue: { lens: () => 'operate' } },
    ],
  });
  const view = injector.get(CapabilityViewComponent);
  view.ngOnInit();

  assert.equal(view.activeTab(), 'systems', 'deep link selects the requested facet');
  query.next(convertToParamMap({ facet: 'not-a-capability-facet' }));
  assert.equal(view.activeTab(), 'overview', 'invalid history entries fail closed to overview');
  query.next(convertToParamMap({ facet: 'policies' }));
  assert.equal(view.activeTab(), 'policies', 'back/forward query changes update the active tab');

  view.onTabChange('outcomes');
  assert.equal(view.activeTab(), 'outcomes');
  assert.deepEqual(navigations[0]?.commands, []);
  assert.equal(navigations[0]?.extras['relativeTo'], route);
  assert.deepEqual(navigations[0]?.extras['queryParams'], { facet: 'outcomes' });
  assert.equal(navigations[0]?.extras['queryParamsHandling'], 'merge');

  view.onTabChange('forged');
  assert.equal(navigations.length, 1, 'a forged tab never enters navigation state');
  view.ngOnDestroy();
});

test('Capability facet routing leaves the historical gate-off behavior unchanged', () => {
  const params = new BehaviorSubject(convertToParamMap({ capabilityId: 'capability-1' }));
  const query = new BehaviorSubject(convertToParamMap({ facet: 'systems' }));
  let navigations = 0;
  const injector = Injector.create({
    providers: [
      CapabilityViewComponent,
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
        useValue: { navigate: () => { navigations += 1; return Promise.resolve(true); } },
      },
      { provide: CanonicalApiService, useValue: { getCapability: () => of(null) } },
      { provide: WorkspaceService, useValue: new WorkspaceStub(false) },
      { provide: ObjectPerspectiveStore, useValue: {} },
      { provide: LensService, useValue: { lens: () => 'build' } },
    ],
  });
  const view = injector.get(CapabilityViewComponent);
  view.ngOnInit();

  assert.equal(view.activeTab(), 'overview', 'legacy deep links do not gain new routing semantics');
  view.onTabChange('systems');
  assert.equal(view.activeTab(), 'systems', 'the historical in-memory tab interaction remains');
  assert.equal(navigations, 0);
  view.ngOnDestroy();
});

test('Capability falls back without an error panel when the server revokes its projection', () => {
  const params = new BehaviorSubject(convertToParamMap({ capabilityId: 'capability-1' }));
  const query = new BehaviorSubject(convertToParamMap({ lens: 'build', facet: 'overview' }));
  const injector = Injector.create({
    providers: [
      CapabilityViewComponent,
      {
        provide: ActivatedRoute,
        useValue: {
          paramMap: params.asObservable(),
          queryParamMap: query.asObservable(),
          snapshot: { paramMap: params.value, queryParamMap: query.value },
        },
      },
      { provide: Router, useValue: { navigate: () => Promise.resolve(true) } },
      { provide: CanonicalApiService, useValue: { getCapability: () => of(null) } },
      { provide: WorkspaceService, useValue: new WorkspaceStub(true) },
      {
        provide: ObjectPerspectiveStore,
        useValue: {
          loadAll: () => throwError(
            () => new ObjectPerspectiveGateRevokedError('capability'),
          ),
        },
      },
      { provide: LensService, useValue: { lens: () => 'build' } },
    ],
  });
  const view = injector.get(CapabilityViewComponent);

  view.ngOnInit();

  assert.equal(view.perspectivesLoading(), false);
  assert.equal(view.perspectivesError(), false);
  view.ngOnDestroy();
});

test('Capability loads its projection when the effective gate activates in the same workspace epoch', () => {
  const params = new BehaviorSubject(convertToParamMap({ capabilityId: 'capability-1' }));
  const query = new BehaviorSubject(convertToParamMap({ lens: 'build', facet: 'overview' }));
  const workspace = new WorkspaceStub(false);
  let perspectiveLoads = 0;
  const injector = Injector.create({
    providers: [
      CapabilityViewComponent,
      {
        provide: ActivatedRoute,
        useValue: {
          paramMap: params.asObservable(),
          queryParamMap: query.asObservable(),
          snapshot: { paramMap: params.value, queryParamMap: query.value },
        },
      },
      { provide: Router, useValue: { navigate: () => Promise.resolve(true) } },
      { provide: CanonicalApiService, useValue: { getCapability: () => of(null) } },
      { provide: WorkspaceService, useValue: workspace },
      {
        provide: ObjectPerspectiveStore,
        useValue: {
          loadAll: () => {
            perspectiveLoads += 1;
            return of({});
          },
        },
      },
      { provide: LensService, useValue: { lens: () => 'build' } },
    ],
  });
  const view = injector.get(CapabilityViewComponent);

  view.ngOnInit();
  assert.equal(perspectiveLoads, 0);
  workspace.setProjectionEnabled(true);

  assert.equal(view.projectionEnabled(), true);
  assert.equal(perspectiveLoads, 1, 'same-epoch activation reloads without route navigation');
  view.ngOnDestroy();
});

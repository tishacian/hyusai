import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { DOCUMENT } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
  Injector, signal,
  ɵChangeDetectionScheduler as ChangeDetectionScheduler,
  ɵEffectScheduler as EffectScheduler,
} from '@angular/core';
import { Router } from '@angular/router';
import { firstValueFrom, of, Subject, throwError } from 'rxjs';
import { ToastrService } from 'ngx-toastr';
import { ApiService } from '@app/core/api.service';
import { CanonicalApiService, type System, type SystemStatus } from '@app/core/canonical-api.service';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { ZoomContextService } from '@app/core/zoom-context.service';
import { SystemHomeService, type SystemHomeCreateInput } from '@app/features/experience/system-home.service';
import { FlowStore } from './flow.store';
import { FlowPersistenceService } from './flow-persistence.service';
import { FlowPublicationPanelComponent } from './flow-publication-panel.component';

function setup(status: SystemStatus = 'draft') {
  let epoch = 1;
  const response = new Subject<System | null>();
  const responses: Array<Subject<System | null>> = [];
  const mutations: unknown[][] = [];
  const applications: SystemHomeCreateInput[] = [];
  const publications: string[] = [];
  const resetters = new Set<() => void>();
  const effects = new Set<{dirty: boolean; run(): void}>();
  const previousElement = globalThis.HTMLElement;
  Object.defineProperty(globalThis, 'HTMLElement', {configurable: true, value: class {}});
  const persistence = {
    systemId: signal<string | null>('system'), systemStatus: signal<SystemStatus | null>(status),
    publishedVersionId: signal<string | null>('version'), publishedContractReady: signal(true),
    publishedExecutionContract: signal<Record<string, unknown> | null>({ ingresses: [{
      ingress_id: 'src', kind: 'manual', input_schema: {type: 'object', properties: {text: {type: 'string'}}},
    }] }),
    systemDisplayName: () => 'PIH', actionsDisabled: signal(false), publishing: signal(false),
    publishReviewOpen: signal(true), canConfirmPublication: () => true,
    publishDraft: (message: string) => publications.push(message), closePublicationReview() {},
  };
  const injector = Injector.create({ providers: [
    { provide: FlowPublicationPanelComponent, useFactory: () => new FlowPublicationPanelComponent() },
    { provide: FlowPersistenceService, useValue: persistence },
    { provide: CanonicalApiService, useValue: { updateSystem: (...args: unknown[]) => {
      mutations.push(args);
      const pending = responses.length ? new Subject<System | null>() : response;
      responses.push(pending); return pending;
    } } },
    { provide: WorkspaceService, useValue: { experienceStudioV1Enabled: () => true,
      captureRequestScope: () => epoch, isRequestScopeCurrent: (scope: number) => scope === epoch,
      registerContextReset: (callback: () => void) => {
        resetters.add(callback); return () => resetters.delete(callback);
      } } },
    { provide: FlowStore, useValue: { snapshot: () => ({nodes: [{id: 'src', kind: 'source'}]}) } },
    { provide: SystemHomeService, useValue: { createDraft: (input: SystemHomeCreateInput) => {
      applications.push(input); return of({id: 'app', slug: 'pih'});
    } } },
    { provide: I18nService, useValue: { t: (key: string) => key, locale: () => 'en' } },
    { provide: Router, useValue: { navigateByUrl: async () => true } },
    { provide: ZoomContextService, useValue: { leafUrl: () => '/create/apps/app' } },
    { provide: ToastrService, useValue: { success() {} } },
    { provide: DOCUMENT, useValue: {activeElement: null} },
    { provide: ChangeDetectionScheduler, useValue: {notify() {}} },
    { provide: EffectScheduler, useValue: {
      add: (effect: any) => effects.add(effect), schedule: (effect: any) => effects.add(effect),
      remove: (effect: any) => effects.delete(effect),
    } },
  ] });
  // Methods are protected only because the template is their production caller.
  const panel = injector.get(FlowPublicationPanelComponent) as any;
  const flush = () => {
    for (let pass = 0; pass < 20; pass++) {
      const dirty = [...effects].filter(effect => effect.dirty);
      if (!dirty.length) return;
      for (const effect of dirty) effect.run();
    }
    throw new Error('effects did not settle');
  };
  flush();
  return {panel, persistence, response, responses, mutations, applications, publications, flush,
    leave: () => { for (const callback of resetters) callback(); epoch++; },
    destroy: () => { injector.destroy();
      Object.defineProperty(globalThis, 'HTMLElement', {configurable: true, value: previousElement}); }};
}

test('publication does not activate; explicit activation enables the existing application handoff', () => {
  const state = setup();
  const {panel, response, mutations, applications, publications, persistence} = state;
  panel.publish(); panel.createHome();
  assert.equal(publications.length, 1);
  assert.equal(mutations.length, 0);
  assert.equal(applications.length, 0);

  panel.activateSystem(); panel.activateSystem(); panel.publish(); panel.createHome();
  assert.deepEqual(mutations, [['system', {status: 'active'}, {
    expected_published_version_id: 'version', propagateErrors: true,
  }]]);
  assert.equal(panel.activating(), true);
  assert.equal(publications.length, 1);
  assert.equal(applications.length, 0);
  response.next({id: 'system', name: 'PIH', status: 'active'});
  assert.equal(persistence.systemStatus(), 'active');
  assert.equal(panel.activating(), false);
  assert.equal(applications.length, 0);
  panel.createHome();
  assert.equal(applications.length, 1);
  assert.equal(applications[0].systemId, 'system');
  assert.equal(applications[0].publishedVersionId, 'version');
  assert.equal(applications[0].ingressId, 'src');
  state.destroy();
});

test('active, unhydrated and unpublished systems cannot request activation', () => {
  const state = setup('active');
  state.panel.activateSystem();
  state.persistence.systemStatus.set(null); state.panel.activateSystem();
  state.persistence.systemStatus.set('draft'); state.persistence.publishedVersionId.set(null);
  state.panel.activateSystem();
  state.persistence.publishedVersionId.set('version'); state.persistence.publishedContractReady.set(false);
  state.panel.activateSystem();
  assert.equal(state.mutations.length, 0);
  state.destroy();
});

test('permission and transport failures keep application creation blocked with an actionable error', () => {
  for (const [status, key] of [[403, 'denied'], [0, 'error']] as const) {
    const state = setup();
    state.panel.activateSystem();
    state.response.error(new HttpErrorResponse({status}));
    assert.equal(state.panel.activationError(), `experience.home.activate.${key}`);
    assert.equal(state.panel.activating(), false);
    state.panel.createHome();
    assert.equal(state.applications.length, 0);
    assert.equal(state.persistence.systemStatus(), 'draft');
    state.destroy();
  }
});

test('an unexpected response cannot report successful activation', () => {
  for (const response of [null, {id: 'other', name: 'Other', status: 'active'},
    {id: 'system', name: 'PIH', status: 'paused'}] as const) {
    const state = setup();
    state.panel.activateSystem(); state.response.next(response);
    assert.equal(state.persistence.systemStatus(), 'draft');
    assert.equal(state.panel.activationError(), 'experience.home.activate.error');
    state.destroy();
  }
});

test('a concurrent publication conflict leaves activation and application creation blocked', () => {
  const state = setup();
  state.panel.activateSystem();
  state.response.error(new HttpErrorResponse({status: 409, error: {detail: {
    code: 'SYSTEM_PUBLISHED_VERSION_MISMATCH',
    message: 'The published Flow changed. Reload and review it before activating the System.',
  }}}));
  assert.equal(state.panel.activationError(), 'experience.home.activate.stale');
  assert.equal(state.panel.activating(), false);
  assert.equal(state.persistence.systemStatus(), 'draft');
  state.panel.createHome();
  assert.equal(state.applications.length, 0);
  state.destroy();
});

test('switching workspace, System or published version cancels activation and leaves the new target usable', () => {
  for (const transition of ['workspace', 'system', 'version'] as const) {
    const state = setup();
    state.panel.activateSystem();
    if (transition === 'workspace') state.leave();
    if (transition === 'version') state.persistence.publishedVersionId.set('version-2');
    else state.persistence.systemId.set('other');
    state.flush();
    assert.equal(state.panel.activating(), false);
    state.panel.activateSystem();
    assert.equal(state.mutations.length, 2);
    state.response.next({id: 'system', name: 'PIH', status: 'active'});
    assert.equal(state.persistence.systemStatus(), 'draft');
    state.responses[1].next({id: state.persistence.systemId()!, name: 'Other', status: 'active'});
    assert.equal(state.persistence.systemStatus(), 'active');
    assert.equal(state.applications.length, 0);
    state.destroy();
  }
});

test('destroying the component cancels activation', () => {
  const state = setup();
  state.panel.activateSystem(); state.destroy();
  state.response.next({id: 'system', name: 'PIH', status: 'active'});
  assert.equal(state.persistence.systemStatus(), 'draft');
  assert.equal(state.panel.activating(), false);
});

test('canonical status updates can propagate errors without changing legacy callers', async () => {
  const failure = new HttpErrorResponse({status: 403});
  const calls: unknown[][] = [];
  const injector = Injector.create({providers: [
    CanonicalApiService,
    {provide: ApiService, useValue: {patch: (...args: unknown[]) => {
      calls.push(args); return throwError(() => failure);
    }}},
  ]});
  const api = injector.get(CanonicalApiService);
  assert.equal(await firstValueFrom(api.updateSystem('system', {status: 'active'})), null);
  await assert.rejects(firstValueFrom(api.updateSystem('system', {status: 'active'}, {
    expected_published_version_id: 'version', propagateErrors: true,
  })),
    error => error === failure);
  assert.deepEqual(calls, [['/systems/system', {status: 'active'}],
    ['/systems/system?expected_published_version_id=version', {status: 'active'}]]);
});

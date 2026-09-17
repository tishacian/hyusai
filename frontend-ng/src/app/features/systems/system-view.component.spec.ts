import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { DefaultUrlSerializer, UrlTree } from '@angular/router';
import { SystemViewComponent } from './system-view.component';

test('all System stage links keep their context outside the router path', () => {
  const serializer = new DefaultUrlSerializer();
  const surface = (id: string) => `/${id}?systemId=system-1&lens=build`;
  const leaf = (id: string) => `/${id}?systemId=system-1&lens=build`;
  for (const family of ['rag', 'translation', 'capture']) {
    const view = Object.assign(Object.create(SystemViewComponent.prototype), {
      systemId: 'system-1',
      isTranslationSuite: () => family === 'translation',
      isExpertKnowledgeCapture: () => family === 'capture',
      i18n: { t: (key: string) => key },
      navigation: {
        surfaceUrl: surface, leafUrl: leaf,
        surfaceUrlTree: (id: string) => serializer.parse(surface(id)),
        leafUrlTree: (id: string) => serializer.parse(leaf(id)),
      },
    }) as SystemViewComponent;
    assert.ok(view.pipelineStages.length > 0);
    for (const stage of view.pipelineStages) {
      assert.ok(stage.route instanceof UrlTree, `${family}/${stage.key} must supply RouterLink a UrlTree`);
      assert.equal(stage.route.queryParams['systemId'], 'system-1');
      assert.equal(stage.route.queryParams['lens'], 'build');
      assert.ok(!serializer.serialize(stage.route).includes('%3F'));
    }
  }
});

import { Injector, signal } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { Subject } from 'rxjs';
import { ToastrService } from 'ngx-toastr';
import { ApiService } from '@app/core/api.service';
import { CanonicalApiService, type System, type SystemFlowState } from '@app/core/canonical-api.service';
import { I18nService } from '@app/core/i18n.service';
import { LensService } from '@app/core/lens';
import { SettingsService } from '@app/core/settings.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { ZoomContextService } from '@app/core/zoom-context.service';
import { WorkApiService } from '@app/features/experience/work/work-api.service';
import { FlowManifestService } from '@app/features/orchestration/flow/flow-manifest.service';
import { SystemsStore } from './systems.store';

function designView() {
  const responses: Subject<SystemFlowState>[] = [];
  const current = signal(true);
  const workspace = signal({ settings: { features: {} as Record<string, boolean> } });
  const injector = Injector.create({ providers: [
    ...[ActivatedRoute, Router, ApiService, SystemsStore, ToastrService, SettingsService,
      LensService, ZoomContextService, WorkApiService].map(provide => ({ provide, useValue: {} })),
    { provide: CanonicalApiService, useValue: { getSystemFlowState: () => {
      const response = new Subject<SystemFlowState>(); responses.push(response); return response;
    } } },
    { provide: WorkspaceService, useValue: {
      current: workspace, captureRequestScope: () => ({}),
      isRequestScopeCurrent: () => current(), registerContextReset: () => () => {},
    } },
    { provide: FlowManifestService, useValue: { manifest: () => null } },
    { provide: I18nService, useValue: { t: (key: string) => key } },
    { provide: SystemViewComponent, useFactory: () => new SystemViewComponent() },
  ] });
  const view = injector.get(SystemViewComponent);
  view.systemId = 'pih';
  view.systemSnapshot.set({ id: 'pih', name: 'PIH', flow_definition: {
    source: 'form', nodes: [{id: 'published', kind: 'source'}], edges: [],
  }, published_flow_version_id: 'v1' } as System);
  return { view, responses, workspace, leave: () => current.set(false) };
}

function draftState(): SystemFlowState {
  return {
    system_id: 'pih', status: 'active',
    draft: { revision: 3, flow_sha256: 'draft-sha', base_published_version_id: 'v1',
      flow_definition: { source: 'flow', nodes: [
        {id: 'request', kind: 'source', type: 'input', label: 'Transaction excerpts'},
        {id: 'summary', kind: 'task', label: 'PIH summary', config: {skill_slug: 'pih-summary'}},
        {id: 'result', kind: 'sink', label: 'Factual summary'},
      ], edges: [{from: 'request', to: 'summary'}, {from: 'summary', to: 'result'}] } },
    published: {version_id: 'v1', version_number: 1, flow_sha256: 'published-sha', flow_definition: {}},
  };
}

test('Design shows the server draft while the published System remains unchanged', () => {
  const { view, responses } = designView();
  const published = view.systemSnapshot();
  assert.equal(view.flowPublicationEnabled(), true, 'matches the graduated server default');
  assert.equal(view.designFlowProfile(), null, 'does not invent a graph before hydration');
  view.loadDesignFlow(); responses[0].next(draftState());
  assert.equal(view.designFlowError(), false);
  assert.deepEqual(view.designFlowProfile()?.steps.map(step => step.nodeId), ['request', 'summary', 'result']);
  assert.deepEqual(view.designFlowProfile()?.skillSlugs, ['pih-summary']);
  assert.equal(view.designFlowProfile()?.publishedVersionId, null, 'draft must not be labelled the published graph');
  assert.equal(view.designFlowState()?.published.version_number, 1);
  assert.equal(view.flowProfile(), null, 'overview still describes the published form');
  assert.equal(view.systemSnapshot(), published);
});

test('Design refuses wrong identity and failed reads, and ignores late workspace responses', () => {
  const { view, responses, leave } = designView();
  view.loadDesignFlow(); responses[0].next({...draftState(), system_id: 'other'});
  assert.equal(view.designFlowError(), true); assert.equal(view.designFlowState(), null);
  view.loadDesignFlow(); responses[1].error(new Error('access denied'));
  assert.equal(view.designFlowError(), true); assert.equal(view.designFlowProfile(), null);
  view.loadDesignFlow(); leave(); responses[2].next(draftState());
  assert.equal(view.designFlowState(), null, 'old workspace response cannot populate Design');
});

test('explicit feature opt-out and specialist/360 surfaces keep their existing projections', () => {
  const { view, workspace } = designView();
  workspace.set({settings: {features: {flow_publication_v1: false}}});
  assert.equal(view.designUsesPublication(), false);
  workspace.set({settings: {features: {}}});
  view.variant.set('expert_knowledge_capture');
  assert.equal(view.designUsesPublication(), false);
  view.variant.set('standard');
  workspace.set({settings: {features: {cockpit_router_axes_v4: true, system_360_projection_v1: true}}});
  view.systemSnapshot.update(system => ({...system!, settings: {experience: {system_360_canary: 'v1'}}}));
  assert.equal(view.designUsesPublication(), false);
});

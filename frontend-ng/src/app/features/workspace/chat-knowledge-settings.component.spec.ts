import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  Injector,
  ɵChangeDetectionScheduler as ChangeDetectionScheduler,
  ɵEffectScheduler as EffectScheduler,
} from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { Observable, Subject, of } from 'rxjs';
import { ToastrService } from 'ngx-toastr';
import {
  ApiService,
  type KnowledgeGuide,
  type KnowledgeGuideList,
  type KnowledgeGuideStatus,
} from '@app/core/api.service';
import {
  WorkspaceService,
  type WorkspaceContextTransition,
  type WorkspaceDetail,
  type WorkspaceRequestOptions,
  type WorkspaceRequestScope,
} from '@app/core/workspace.service';
import { DEFAULT_BRAND_NAME } from '@app/core/platform-brand';
import { I18nService } from '@app/core/i18n.service';
import { ChatKnowledgeSettingsComponent } from './chat-knowledge-settings.component';

const WORKSPACE_A: WorkspaceDetail = {
  id: 'workspace-a',
  name: 'Andritz',
  slug: 'andritz',
  role: 'admin',
  is_active: true,
  member_count: 2,
  created_at: '2026-01-01T00:00:00Z',
  settings: {},
};

class WorkspaceStub {
  private slug = 'andritz';
  private epoch = 8;
  private readonly resetters = new Set<(transition: WorkspaceContextTransition) => void>();

  /** The real I18nService interpolates {brand} on every t() call. */
  brandName = () => DEFAULT_BRAND_NAME;

  readonly settingsWrites: Subject<WorkspaceDetail>[] = [];
  readonly settingsCalls: Array<{
    slug: string;
    settings: Record<string, unknown>;
    workspaceSlug: string | null | undefined;
  }> = [];
  readonly workspaceLoads: Subject<WorkspaceDetail>[] = [];
  readonly workspaceLoadSlugs: Array<string | null | undefined> = [];
  refreshCalls = 0;

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

  updateWorkspaceSettings(
    slug: string,
    settings: Record<string, unknown>,
    options?: WorkspaceRequestOptions,
  ): Observable<WorkspaceDetail> {
    this.settingsCalls.push({ slug, settings, workspaceSlug: options?.workspaceSlug });
    const response = new Subject<WorkspaceDetail>();
    this.settingsWrites.push(response);
    return response.asObservable();
  }

  getWorkspace(_slug: string, options?: WorkspaceRequestOptions): Observable<WorkspaceDetail> {
    this.workspaceLoadSlugs.push(options?.workspaceSlug);
    const response = new Subject<WorkspaceDetail>();
    this.workspaceLoads.push(response);
    return response.asObservable();
  }

  refreshCurrentWorkspace(): Observable<null> {
    this.refreshCalls += 1;
    return of(null);
  }

  switchWorkspace(nextSlug = 'sentinel-ci'): void {
    const transition: WorkspaceContextTransition = {
      previousSlug: this.slug,
      nextSlug,
      previousEpoch: this.epoch,
      nextEpoch: this.epoch + 1,
    };
    for (const resetter of [...this.resetters]) resetter(transition);
    this.slug = nextSlug;
    this.epoch = transition.nextEpoch;
  }

  resetterCount(): number {
    return this.resetters.size;
  }
}

class ApiStub {
  readonly scopeWrites: Subject<unknown>[] = [];
  readonly patchCalls: Array<{
    path: string;
    workspaceSlug: string | null | undefined;
  }> = [];
  readonly reads: Array<{
    path: string;
    workspaceSlug: string | null | undefined;
    response: Subject<unknown>;
  }> = [];
  readonly guideWrites: Subject<KnowledgeGuide>[] = [];
  readonly guideWriteCalls: Array<{
    kind: 'create' | 'update';
    workspaceSlug: string | null | undefined;
  }> = [];
  readonly guideLists: Subject<KnowledgeGuideList>[] = [];
  readonly guideListSlugs: Array<string | null | undefined> = [];

  patch<T>(
    path: string,
    _body?: unknown,
    options?: { workspaceSlug?: string | null },
  ): Observable<T> {
    this.patchCalls.push({ path, workspaceSlug: options?.workspaceSlug });
    const response = new Subject<unknown>();
    this.scopeWrites.push(response);
    return response.asObservable() as Observable<T>;
  }

  get<T>(
    path: string,
    _params?: Record<string, string>,
    options?: { workspaceSlug?: string | null },
  ): Observable<T> {
    const response = new Subject<unknown>();
    this.reads.push({ path, workspaceSlug: options?.workspaceSlug, response });
    return response.asObservable() as Observable<T>;
  }

  createKnowledgeGuide(
    _body: {
      target_type: 'scope' | 'collection';
      target_ref: string;
      title: string;
      markdown: string;
      status?: KnowledgeGuideStatus;
    },
    options?: { workspaceSlug?: string | null },
  ): Observable<KnowledgeGuide> {
    this.guideWriteCalls.push({ kind: 'create', workspaceSlug: options?.workspaceSlug });
    const response = new Subject<KnowledgeGuide>();
    this.guideWrites.push(response);
    return response.asObservable();
  }

  updateKnowledgeGuide(
    _guideKey: string,
    _body: unknown,
    options?: { workspaceSlug?: string | null },
  ): Observable<KnowledgeGuide> {
    this.guideWriteCalls.push({ kind: 'update', workspaceSlug: options?.workspaceSlug });
    const response = new Subject<KnowledgeGuide>();
    this.guideWrites.push(response);
    return response.asObservable();
  }

  listKnowledgeGuides(
    _params?: unknown,
    options?: { workspaceSlug?: string | null },
  ): Observable<KnowledgeGuideList> {
    this.guideListSlugs.push(options?.workspaceSlug);
    const response = new Subject<KnowledgeGuideList>();
    this.guideLists.push(response);
    return response.asObservable();
  }
}

function createHarness(): {
  injector: ReturnType<typeof Injector.create>;
  component: ChatKnowledgeSettingsComponent;
  api: ApiStub;
  workspace: WorkspaceStub;
  successMessages: string[];
} {
  const api = new ApiStub();
  const workspace = new WorkspaceStub();
  const successMessages: string[] = [];
  const injector = Injector.create({
    providers: [
      ChatKnowledgeSettingsComponent,
      // The real service, not a stub: the chat defaults this component previews
      // are rendered from the dictionary, so the assertions below read the
      // actual FR copy a user would see.
      I18nService,
      { provide: ApiService, useValue: api },
      { provide: WorkspaceService, useValue: workspace },
      {
        provide: ActivatedRoute,
        useValue: {
          parent: {
            paramMap: of({ get: (key: string) => key === 'slug' ? 'andritz' : null }),
          },
        },
      },
      {
        provide: ToastrService,
        useValue: {
          success: (message: string) => successMessages.push(message),
          error: () => undefined,
          info: () => undefined,
          warning: () => undefined,
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
  const component = injector.get(ChatKnowledgeSettingsComponent);
  component.detail.set(WORKSPACE_A);
  component.scopes.set([{
    key: 'andritz-private',
    label: 'Andritz private scope',
    description: '',
    collection_slugs_text: 'andritz-private-documents',
    default_mode: 'chah',
    top_k: 5,
    is_default: true,
    table_profile_key: '',
    document_profile_key: '',
  }]);
  return { injector, component, api, workspace, successMessages };
}

test('ChatKnowledge cancels the A write chain before a late response can continue in B', () => {
  const { injector, component, api, workspace, successMessages } = createHarness();
  try {
    component.saveAll();

    assert.equal(component.saving(), true);
    assert.deepEqual(api.patchCalls, [{
      path: '/knowledge/scopes',
      workspaceSlug: 'andritz',
    }]);

    api.scopeWrites[0].next({ status: 'ok' });
    assert.equal(workspace.settingsCalls.length, 1);
    assert.equal(workspace.settingsCalls[0].slug, 'andritz');
    assert.equal(workspace.settingsCalls[0].workspaceSlug, 'andritz');

    workspace.switchWorkspace();

    assert.equal(component.saving(), false);
    assert.equal(component.detail(), null, 'A settings are cleared synchronously before B is published');
    assert.equal(api.scopeWrites[0].observed, false);
    assert.equal(workspace.settingsWrites[0].observed, false);

    workspace.settingsWrites[0].next({
      ...WORKSPACE_A,
      name: 'Late A mutation',
      settings: { chat: { title: 'must not leak' } },
    });

    assert.equal(component.detail(), null);
    assert.deepEqual(successMessages, []);
    assert.deepEqual(api.reads, [], 'a late A settings response cannot launch post-save reads in B');
    assert.equal(workspace.refreshCalls, 0);
  } finally {
    injector.destroy();
  }
  assert.equal(workspace.resetterCount(), 0);
});

test('ChatKnowledge pins and cancels post-save reloads so late A reads cannot repopulate B', () => {
  const { injector, component, api, workspace, successMessages } = createHarness();
  const i18n = injector.get(I18nService);
  try {
    component.saveAll();
    api.scopeWrites[0].next({ status: 'ok' });
    workspace.settingsWrites[0].next({
      ...WORKSPACE_A,
      settings: { chat: { title: 'Saved in A' } },
    });

    assert.deepEqual(successMessages, [i18n.t('workspace.chat_sources.toast.saved')]);
    assert.deepEqual(workspace.workspaceLoadSlugs, ['andritz']);
    assert.deepEqual(
      api.reads.map(({ path, workspaceSlug }) => ({ path, workspaceSlug })),
      [
        { path: '/knowledge/scopes', workspaceSlug: 'andritz' },
        { path: '/documents/collections', workspaceSlug: 'andritz' },
      ],
    );
    assert.deepEqual(api.guideListSlugs, ['andritz']);

    workspace.switchWorkspace();
    assert.equal(workspace.workspaceLoads[0].observed, false);
    assert.equal(api.reads.every(({ response }) => !response.observed), true);
    assert.equal(api.guideLists[0].observed, false);

    workspace.workspaceLoads[0].next({ ...WORKSPACE_A, name: 'Late load A' });
    api.reads[0].response.next({ scopes: [{ key: 'late-a' }] });
    api.reads[1].response.next({ collections: ['late-a-private'] });
    api.guideLists[0].next({
      workspace_id: 'workspace-a',
      workspace_slug: 'andritz',
      items: [],
    });

    assert.equal(component.detail(), null);
    assert.deepEqual(component.scopes(), []);
    assert.deepEqual(component.collections(), []);
    assert.deepEqual(component.knowledgeGuides(), []);
  } finally {
    injector.destroy();
  }
});

test('ChatKnowledge keeps guide writes and their refresh in one cancellable A scope', () => {
  const { injector, component, api, workspace } = createHarness();
  const guide: KnowledgeGuide = {
    id: 'guide-a-v1',
    guide_key: 'andritz-guide',
    workspace_id: 'workspace-a',
    target_type: 'scope',
    target_ref: 'andritz-private',
    title: 'Andritz guide',
    markdown: '# Private A',
    status: 'draft',
    version: 1,
    is_current: true,
  };

  try {
    component.openGuideEditor('andritz-private');
    component.saveGuide();
    assert.deepEqual(api.guideWriteCalls, [{ kind: 'create', workspaceSlug: 'andritz' }]);

    api.guideWrites[0].next(guide);
    assert.deepEqual(api.guideListSlugs, ['andritz']);
    api.guideLists[0].next({
      workspace_id: 'workspace-a',
      workspace_slug: 'andritz',
      items: [guide],
    });
    api.guideLists[0].complete();
    assert.deepEqual(component.knowledgeGuides(), [guide]);

    component.publishGuide(guide);
    assert.deepEqual(api.guideWriteCalls, [
      { kind: 'create', workspaceSlug: 'andritz' },
      { kind: 'update', workspaceSlug: 'andritz' },
    ]);
    api.guideWrites[1].next({ ...guide, status: 'published' });
    assert.deepEqual(api.guideListSlugs, ['andritz', 'andritz']);

    workspace.switchWorkspace();
    assert.equal(api.guideWrites[1].observed, false);
    assert.equal(api.guideLists[1].observed, false);

    api.guideLists[1].next({
      workspace_id: 'workspace-a',
      workspace_slug: 'andritz',
      items: [{ ...guide, title: 'Late A guide' }],
    });
    assert.deepEqual(component.knowledgeGuides(), []);
    assert.equal(component.detail(), null);
  } finally {
    injector.destroy();
  }
});

test('L22: collection matrix toggles produce the same collection_slugs payload', () => {
  const { injector, component } = createHarness();
  try {
    component.collections.set(['alpha', 'beta', 'gamma']);
    component.scopes.set([{
      key: 'scope-a',
      label: 'Scope A',
      description: '',
      collection_slugs_text: 'alpha',
      default_mode: 'chah',
      top_k: 5,
      is_default: true,
      table_profile_key: '',
      document_profile_key: '',
    }]);
    const scope = component.scopes()[0]!;
    assert.equal(component.scopeHasCollection(scope, 'alpha'), true);
    assert.equal(component.scopeHasCollection(scope, 'beta'), false);
    component.toggleScopeCollection(scope, 'beta', { target: { checked: true } } as unknown as Event);
    component.toggleScopeCollection(component.scopes()[0]!, 'alpha', { target: { checked: false } } as unknown as Event);
    assert.equal(component.scopes()[0]!.collection_slugs_text, 'beta');
    assert.deepEqual(
      component.scopes()[0]!.collection_slugs_text.split(',').map((s) => s.trim()).filter(Boolean),
      ['beta'],
    );
  } finally {
    injector.destroy();
  }
});

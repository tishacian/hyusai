import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  ChangeDetectorRef,
  Injector,
  signal,
  ɵChangeDetectionScheduler as ChangeDetectionScheduler,
  ɵEffectScheduler as EffectScheduler,
} from '@angular/core';
import { Router } from '@angular/router';
import { Subject, NEVER, of } from 'rxjs';
import { ToastrService } from 'ngx-toastr';
import { ApiService } from '@app/core/api.service';
import { CanonicalApiService } from '@app/core/canonical-api.service';
import { RuntimeHealthService } from '@app/core/runtime-health.service';
import { SseService } from '@app/core/sse.service';
import { SettingsService } from '@app/core/settings.service';
import { VoiceSessionService } from '@app/core/voice-session.service';
import { VoiceLoopControllerFactory } from '@app/core/voice-loop-controller.service';
import { VoiceTtsPlaybackService } from '@app/core/voice-tts-playback.service';
import {
  WorkspaceService,
  type WorkspaceContextTransition,
  type WorkspaceRequestScope,
} from '@app/core/workspace.service';
import { DEFAULT_BRAND_NAME } from '@app/core/platform-brand';
import { PermissionsService } from '@app/core/permissions.service';
import { AssistantEffectsService } from '@app/core/assistant-effects.service';
import { I18nService } from '@app/core/i18n.service';
import { navigationObjectUrl, navigationSurfaceUrl } from '@app/core/navigation.catalog';
import type { HierarchyObjectType } from '@app/core/navigation.catalog';
import { ZoomContextService } from '@app/core/zoom-context.service';
import { REGISTERED_LUCIDE_ICONS } from '@app/shared/ui/icon-registry';
import { ChatPanelComponent } from './chat-panel.component';

class WorkspaceStub {
  private slug = 'andritz';
  private epoch = 2;
  private readonly resetters = new Set<(transition: WorkspaceContextTransition) => void>();

  current = () => ({ slug: this.slug, name: this.slug, settings: {} });
  currentSlug = () => this.slug;
  /** Screen copy reads the brand; a workspace without one answers Agentium. */
  brandName = () => DEFAULT_BRAND_NAME;
  contextEpoch = () => this.epoch;
  isDemoSafeMode = () => false;

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

  switchWorkspace(): void {
    const transition: WorkspaceContextTransition = {
      previousSlug: this.slug,
      nextSlug: 'sentinel-ci',
      previousEpoch: this.epoch,
      nextEpoch: this.epoch + 1,
    };
    for (const resetter of [...this.resetters]) resetter(transition);
    this.slug = transition.nextSlug!;
    this.epoch = transition.nextEpoch;
  }
}

class ApiStub {
  sessionList: Array<Record<string, unknown>> = [];
  readonly sessionCreates: Array<Subject<Record<string, unknown>>> = [];
  readonly sessionCreateOptions: unknown[] = [];
  readonly sessionDetails: Array<Subject<Record<string, unknown>>> = [];
  readonly sessionDetailOptions: unknown[] = [];
  readonly sessionDetailPaths: string[] = [];
  readonly deepPolls: Array<Subject<Record<string, unknown>>> = [];
  readonly deepPollOptions: unknown[] = [];

  get(path: string, _params?: unknown, options?: unknown) {
    if (path === '/reasoning/templates') return of({ templates: [] });
    if (path.startsWith('/sessions?')) return of({ sessions: this.sessionList });
    if (path.startsWith('/sessions/')) {
      const request = new Subject<Record<string, unknown>>();
      this.sessionDetails.push(request);
      this.sessionDetailOptions.push(options);
      this.sessionDetailPaths.push(path);
      return request.asObservable();
    }
    if (path.startsWith('/workspace-jobs/')) {
      const request = new Subject<Record<string, unknown>>();
      this.deepPolls.push(request);
      this.deepPollOptions.push(options);
      return request.asObservable();
    }
    return of({});
  }

  post(path: string, _body: unknown, options?: unknown) {
    if (path === '/sessions') {
      const request = new Subject<Record<string, unknown>>();
      this.sessionCreates.push(request);
      this.sessionCreateOptions.push(options);
      return request.asObservable();
    }
    return of({});
  }

  listVoiceRuntimes() {
    return of({
      default_provider: 'cascade_openai',
      fallback_providers: [],
      allowed_providers: ['cascade_openai'],
      providers: [],
    });
  }
}

class CanonicalStub {
  readonly evalRequests: Array<Subject<Record<string, unknown>>> = [];
  readonly evalOptions: unknown[] = [];

  getEvaluationByRun(_runId: string, options?: unknown) {
    const request = new Subject<Record<string, unknown>>();
    this.evalRequests.push(request);
    this.evalOptions.push(options);
    return request.asObservable();
  }
}

function makeHarness() {
  const workspace = new WorkspaceStub();
  const api = new ApiStub();
  const canonical = new CanonicalStub();
  const warnings: unknown[][] = [];
  const voiceLoop = {
    hardStop: (hooks?: { disableRearm?: () => void; cancelTts?: () => void }) => {
      hooks?.disableRearm?.();
      hooks?.cancelTts?.();
    },
    dispose: () => undefined,
  };
  const tts = {
    state: signal('idle'),
    reset: () => undefined,
    destroy: () => undefined,
  };
  const injector = Injector.create({
    providers: [
      ChatPanelComponent,
      { provide: WorkspaceService, useValue: workspace },
      { provide: ApiService, useValue: api },
      { provide: CanonicalApiService, useValue: canonical },
      { provide: SseService, useValue: { stream: () => NEVER } },
      {
        provide: ToastrService,
        useValue: {
          success: () => ({ onTap: NEVER }),
          warning: (...args: unknown[]) => { warnings.push(args); return { onTap: NEVER }; },
          error: () => undefined,
          info: () => undefined,
        },
      },
      { provide: Router, useValue: { navigate: () => undefined, navigateByUrl: () => undefined } },
      {
        provide: ZoomContextService,
        useValue: {
          surfaceUrl: (id: string) => navigationSurfaceUrl(id),
          objectUrl: (type: HierarchyObjectType, ref: string) => navigationObjectUrl(type, ref),
        },
      },
      { provide: RuntimeHealthService, useValue: { load: () => of(null), presetStatus: () => null } },
      { provide: VoiceSessionService, useValue: { open: () => Promise.reject(new Error('unused')) } },
      { provide: VoiceLoopControllerFactory, useValue: { create: () => voiceLoop } },
      { provide: VoiceTtsPlaybackService, useValue: { createController: () => tts } },
      {
        provide: SettingsService,
        useValue: {
          refresh: () => undefined,
          settings: () => ({
            temperature: 0.1,
            maxTokens: 256,
            ragTopK: 5,
            ragSynthesisK: 5,
            ragSourceDisplayK: 5,
            ragCandidatePoolK: 20,
            ragSimilarityThreshold: 0,
            ragPipelineMode: 'auto',
            defaultModel: 'test',
            defaultProvider: 'test',
          }),
        },
      },
      { provide: PermissionsService, useValue: { refresh: () => of(null), can: () => false } },
      { provide: AssistantEffectsService, useValue: { handleActionEffect: () => undefined } },
      { provide: I18nService, useValue: { locale: () => 'fr', t: (key: string) => key } },
      { provide: ChangeDetectorRef, useValue: { markForCheck: () => undefined } },
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
  const component = injector.get(ChatPanelComponent);
  return { injector, component, workspace, api, canonical, warnings };
}

test('voice oracle timeline only uses registered Lucide icons', () => {
  const { injector, component } = makeHarness();
  try {
    for (const step of component.voiceOracleTimeline()) {
      const providerKey = step.icon.replace(
        /(\w)([a-z0-9]*)(_|-|\s*)/g,
        (_match, first: string, rest: string) => first.toUpperCase() + rest.toLowerCase(),
      );
      assert.ok(
        Object.prototype.hasOwnProperty.call(REGISTERED_LUCIDE_ICONS, providerKey),
        `missing Lucide provider for ${step.icon}`,
      );
    }
  } finally {
    injector.destroy();
  }
});

test('a late session create from A cannot select, store or render the A session in B', async () => {
  const { injector, component, workspace, api } = makeHarness();
  try {
    await Promise.resolve();
    component.messages.set([{ id: 'message-a', role: 'user', content: 'private A' }]);
    component.createNewChat();
    assert.deepEqual(api.sessionCreateOptions[0], { workspaceSlug: 'andritz' });

    workspace.switchWorkspace();
    api.sessionCreates[0].next({ id: 'session-a', title: 'Andritz private session' });
    await Promise.resolve();

    assert.equal(component.activeChatSessionId(), null);
    assert.deepEqual(component.messages(), []);
    assert.equal(component.chatSessions().some((session) => session.id === 'session-a'), false);
  } finally {
    injector.destroy();
  }
});

test('a late open-session response from A cannot restore its messages in B', async () => {
  const { injector, component, workspace, api } = makeHarness();
  try {
    await Promise.resolve();
    component.openChatSession('session-a');
    assert.deepEqual(api.sessionDetailOptions[0], { workspaceSlug: 'andritz' });

    workspace.switchWorkspace();
    api.sessionDetails[0].next({
      id: 'session-a',
      messages: [{ id: 'message-a', role: 'assistant', content: 'private A' }],
      jobs: [],
    });
    await Promise.resolve();

    assert.equal(component.activeChatSessionId(), null);
    assert.deepEqual(component.messages(), []);
    assert.equal(api.sessionDetails[0].observed, false);
  } finally {
    injector.destroy();
  }
});

test('evaluation and Deep Search poll responses from A cannot mutate B', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const { injector, component, workspace, api, canonical, warnings } = makeHarness();
  try {
    await Promise.resolve();
    component.messages.set([{
      id: 'deep-a',
      role: 'assistant',
      content: 'A answer',
      retrievalInfo: {
        deepJobId: 'job-a',
        deepStatus: 'queued',
      },
    } as never]);
    const pollable = component as unknown as {
      startEvalPolling(runId: string): void;
      startDeepRetrievalPolling(messageId: string, jobId: string): void;
    };
    pollable.startEvalPolling('run-a');
    pollable.startDeepRetrievalPolling('deep-a', 'job-a');
    t.mock.timers.tick(2000);

    assert.deepEqual(canonical.evalOptions[0], { workspaceSlug: 'andritz' });
    assert.deepEqual(api.deepPollOptions[0], { workspaceSlug: 'andritz' });

    workspace.switchWorkspace();
    canonical.evalRequests[0].next({
      run_id: 'run-a',
      status: 'completed',
      breach: true,
      reasons: [{ metric: 'private-a' }],
    });
    api.deepPolls[0].next({
      status: 'completed',
      result: { answer: 'private A completed answer' },
    });
    t.mock.timers.tick(10_000);
    await Promise.resolve();

    assert.deepEqual(component.messages(), []);
    assert.deepEqual(warnings, []);
    assert.equal(api.deepPolls.length, 1, 'no A polling timer survives the reset');
    assert.equal(canonical.evalRequests.length, 1, 'no A evaluation timer survives the reset');
  } finally {
    injector.destroy();
  }
});

test('HITL message polling is unique per session and Run, then refreshes the pending bubble', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const { injector, component, api } = makeHarness();
  try {
    await Promise.resolve();
    (component as unknown as { focusComposer(): void }).focusComposer = () => undefined;
    component.openChatSession('session-a');
    api.sessionDetails[0].next({
      id: 'session-a',
      messages: [{
        id: 'message-a',
        role: 'assistant',
        content: 'Validation requise',
        meta_data: { route: 'agentic_review', run_id: 'run-a' },
      }],
      jobs: [],
    });
    const pollable = component as unknown as {
      startHitlMessagePolling(runId: string): void;
      activeHitlMessagePolls: Set<string>;
    };

    pollable.startHitlMessagePolling('run-a');
    t.mock.timers.tick(1500);
    assert.equal(api.sessionDetails.length, 2, 'duplicate starts share one session poll');
    assert.deepEqual([...pollable.activeHitlMessagePolls], ['session-a:run-a']);

    api.sessionDetails[1].next({
      id: 'session-a',
      messages: [{
        id: 'message-a',
        role: 'assistant',
        content: 'Réponse validée [1].',
        meta_data: {
          route: 'agentic',
          run_id: 'run-a',
          resumed_after_hitl: true,
          sources: [{ title: 'Notice P-101' }],
        },
      }],
    });

    assert.equal(component.messages()[0]?.content, 'Réponse validée [1].');
    assert.equal(component.messages()[0]?.sources?.[0]?.title, 'Notice P-101');
    assert.equal(pollable.activeHitlMessagePolls.size, 0, 'success releases the poll key');
  } finally {
    injector.destroy();
  }
});

test('a HITL poll from a conversation left behind cannot mutate the active conversation', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const { injector, component, api, canonical } = makeHarness();
  try {
    await Promise.resolve();
    (component as unknown as { focusComposer(): void }).focusComposer = () => undefined;
    component.openChatSession('session-a');
    api.sessionDetails[0].next({
      id: 'session-a',
      messages: [{
        id: 'message-a',
        role: 'assistant',
        content: 'Validation A',
        meta_data: { route: 'agentic_review', run_id: 'run-a' },
      }],
      jobs: [],
    });
    t.mock.timers.tick(1500);
    assert.equal(api.sessionDetails.length, 2);

    component.openChatSession('session-b');
    api.sessionDetails[2].next({
      id: 'session-b',
      messages: [{ id: 'message-b', role: 'assistant', content: 'Réponse B' }],
      jobs: [],
    });
    api.sessionDetails[1].next({
      id: 'session-a',
      messages: [{
        id: 'message-a',
        role: 'assistant',
        content: 'Réponse privée A validée',
        meta_data: {
          route: 'agentic',
          run_id: 'run-a',
          resumed_after_hitl: true,
        },
      }],
    });
    t.mock.timers.tick(10_000);

    assert.deepEqual(component.messages().map((message) => message.content), ['Réponse B']);
    assert.equal(canonical.evalRequests.length, 0);
    assert.equal(api.sessionDetails.length, 3, 'the abandoned session schedules no further poll');
    const pollable = component as unknown as { activeHitlMessagePolls: Set<string> };
    assert.equal(pollable.activeHitlMessagePolls.size, 0);
  } finally {
    injector.destroy();
  }
});


test('spreadsheet citations preserve the sheet and cell range in the source preview request', () => {
  const { injector, component } = makeHarness();
  try {
    component.previewSource({
      document_id: 'history', collection: 'workbook', filename: 'history.xlsx',
      metadata: { sheet_name: 'Interventions & notes', cell_range: 'N830:O831' },
    });
    const url = new URL(component.sourcePreviewUrl()!, 'https://example.test');
    assert.equal(url.searchParams.get('sheet_name'), 'Interventions & notes');
    assert.equal(url.searchParams.get('cell_range'), 'N830:O831');
    assert.equal(component.sourcePreviewOpen(), true);
    component.previewSource({ document_id: 'history', collection: 'workbook', cell_range: 'N830' });
    // Preserve incomplete provenance so the server refuses it, rather than opening sheet 1.
    assert.equal(new URL(component.sourcePreviewUrl()!, 'https://example.test').searchParams.get('cell_range'), 'N830');
    component.closeSourcePreview();
    component.previewSource({ document_id: 'manual', collection: 'workbook', filename: 'manual.pdf', page: 2 });
    assert.equal(component.sourcePreviewUrl()!.includes('cell_range'), false);
    assert.equal(component.sourcePreviewPage(), 2);
    component.previewSource({ document_id: 'scan', metadata: { collection_name: 'manuals', page_number: '12' } });
    assert.equal(component.sourcePreviewPage(), 12);
    assert.equal(component.sourceLocator({ metadata: { page_number: '12' } })?.label, 'chat.source.locator_page');
    component.previewSource({ document_id: 'scan', collection: 'manuals', page: '12oops' });
    assert.equal(component.sourcePreviewPage(), null);
  } finally { injector.destroy(); }
});


test('a fresh publication conversation ignores stored history but can select its newly created session', () => {
  const {injector,component,api}=makeHarness();
  try {
    api.sessionList=[{id:'old-session',title:'Previous interview'},{id:'new-session',title:'New question'}];
    Object.defineProperty(component,'freshSession',{value:()=>true});
    Object.defineProperty(component,'loadSelectedSessionId',{value:()=> 'old-session'});
    component.loadChatSessions();
    assert.equal(api.sessionDetails.length,0);
    assert.equal(component.activeChatSessionId(),null);
    assert.deepEqual(component.messages(),[]);
    component.loadChatSessions('new-session');
    assert.equal(api.sessionDetails.length,1);
    assert.equal(api.sessionDetailPaths[0],'/sessions/new-session?include_messages=true&include_jobs=true');
  } finally {injector.destroy();}
});

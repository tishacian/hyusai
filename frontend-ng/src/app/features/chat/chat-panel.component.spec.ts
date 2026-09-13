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
import { SIGNAL, signalSetFn } from '@angular/core/primitives/signals';
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
import {
  ProductTelemetryService,
  type ProductActivationMilestone,
  type ProductActivationOptions,
} from '@app/core/product-telemetry.service';
import { I18nService } from '@app/core/i18n.service';
import { navigationObjectUrl, navigationSurfaceUrl } from '@app/core/navigation.catalog';
import type { HierarchyObjectType } from '@app/core/navigation.catalog';
import { ZoomContextService } from '@app/core/zoom-context.service';
import { REGISTERED_LUCIDE_ICONS } from '@app/shared/ui/icon-registry';
import { ChatPanelComponent } from './chat-panel.component';

/**
 * Records activation milestones the way the real service would: `recordOnce`
 * is deduplicated, `recordOccurrence` is deduplicated by its local key. The
 * `dedupeKey` is kept here only so the tests can prove it never travels.
 */
class ActivationTelemetryStub {
  readonly calls: Array<{
    milestone: ProductActivationMilestone;
    options: ProductActivationOptions;
  }> = [];
  private readonly seen = new Set<string>();

  recordOnce(milestone: ProductActivationMilestone, options: ProductActivationOptions = {}): void {
    if (this.seen.has(milestone)) return;
    this.seen.add(milestone);
    this.calls.push({ milestone, options });
  }

  recordOccurrence(
    milestone: ProductActivationMilestone,
    options: ProductActivationOptions & { dedupeKey: string },
  ): void {
    const key = `${milestone}:${options.dedupeKey}`;
    if (this.seen.has(key)) return;
    this.seen.add(key);
    this.calls.push({ milestone, options });
  }

  milestones(): ProductActivationMilestone[] {
    return this.calls.map((call) => call.milestone);
  }
}

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
  readonly sessionCreates: Array<Subject<Record<string, unknown>>> = [];
  readonly sessionCreateOptions: unknown[] = [];
  readonly sessionDetails: Array<Subject<Record<string, unknown>>> = [];
  readonly sessionDetailOptions: unknown[] = [];
  readonly deepPolls: Array<Subject<Record<string, unknown>>> = [];
  readonly deepPollOptions: unknown[] = [];

  readonly readinessRequests: Array<Subject<Record<string, unknown>>> = [];
  readonly readinessOptions: unknown[] = [];

  get(path: string, _params?: unknown, options?: unknown) {
    if (path === '/reasoning/templates') return of({ templates: [] });
    if (path === '/models/readiness') {
      const request = new Subject<Record<string, unknown>>();
      this.readinessRequests.push(request);
      this.readinessOptions.push(options);
      return request.asObservable();
    }
    if (path.startsWith('/sessions?')) return of({ sessions: [] });
    if (path.startsWith('/sessions/')) {
      const request = new Subject<Record<string, unknown>>();
      this.sessionDetails.push(request);
      this.sessionDetailOptions.push(options);
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

  getModelReadiness(options?: unknown) {
    return this.get('/models/readiness', undefined, options);
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

/**
 * Controllable chat stream. `stream()` hands back a Subject the test drives
 * chunk by chunk, so a provider failure can be delivered exactly as the SSE
 * endpoint would deliver it.
 */
class SseStub {
  readonly streams: Array<Subject<Record<string, unknown>>> = [];
  readonly payloads: unknown[] = [];

  stream(_path: string, payload?: unknown) {
    const subject = new Subject<Record<string, unknown>>();
    this.streams.push(subject);
    this.payloads.push(payload);
    return subject.asObservable();
  }

  /** The stream for the most recent turn. */
  last(): Subject<Record<string, unknown>> {
    return this.streams[this.streams.length - 1];
  }
}

/**
 * Write to a signal input from outside a template.
 *
 * The panel is instantiated through a bare `Injector`, not a fixture, so there
 * is no `ComponentRef.setInput`. Inputs are ordinary signal nodes underneath,
 * and the signals primitives package is the supported way to reach one.
 */
function setInput<T>(inputSignal: unknown, value: T): void {
  const node = (inputSignal as Record<symbol, unknown>)[SIGNAL];
  signalSetFn(node as never, value);
}

function makeHarness(options?: { can?: boolean }) {
  const workspace = new WorkspaceStub();
  const api = new ApiStub();
  const sse = new SseStub();
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
  const activation = new ActivationTelemetryStub();
  const injector = Injector.create({
    providers: [
      ChatPanelComponent,
      { provide: WorkspaceService, useValue: workspace },
      { provide: ApiService, useValue: api },
      { provide: CanonicalApiService, useValue: canonical },
      { provide: SseService, useValue: sse },
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
      {
        provide: PermissionsService,
        useValue: { refresh: () => of(null), can: () => options?.can ?? false },
      },
      { provide: AssistantEffectsService, useValue: { handleActionEffect: () => undefined } },
      { provide: ProductTelemetryService, useValue: activation },
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
  return { injector, component, workspace, api, sse, canonical, warnings, activation };
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

// ---------------------------------------------------------------------------
// Quick Ask: what the simple view hides, and what standard chat keeps.
// ---------------------------------------------------------------------------

test('Quick Ask hides the advanced controls, expert details, voice and correction', () => {
  const { injector, component } = makeHarness({ can: true });
  try {
    setInput(component.viewMode, 'simple');

    assert.equal(component.simpleMode(), true);
    assert.equal(component.showAdvancedChatControls(), false, 'runtime chip, retrieval mode, reasoning template');
    assert.equal(component.showExpertDetails(), false, 'trace, fact-check, evaluation score');
    assert.equal(component.showVoiceControls(), false, 'dictation, capture and transport controls');
    assert.equal(component.canCorrectInChat(), false, 'expert correction is not a Quick Ask affordance');
  } finally {
    injector.destroy();
  }
});

test('standard chat keeps every control Quick Ask hides', () => {
  const { injector, component } = makeHarness({ can: true });
  try {
    // `standard` is the default: no input is set here on purpose.
    assert.equal(component.simpleMode(), false);
    assert.equal(component.showAdvancedChatControls(), true);
    assert.equal(component.showExpertDetails(), true);
    assert.equal(component.showVoiceControls(), true);
    assert.equal(component.canCorrectInChat(), true, 'permission still decides in standard chat');
  } finally {
    injector.destroy();
  }
});

test('standard chat still hides expert correction without the permission', () => {
  const { injector, component } = makeHarness();
  try {
    assert.equal(component.canCorrectInChat(), false);
  } finally {
    injector.destroy();
  }
});

// ---------------------------------------------------------------------------
// Model readiness.
// ---------------------------------------------------------------------------

test('readiness is requested workspace-scoped and drives the banner state', () => {
  const { injector, component, api } = makeHarness();
  try {
    setInput(component.viewMode, 'simple');
    component.refreshModelReadiness();

    assert.equal(api.readinessRequests.length, 1);
    assert.deepEqual(api.readinessOptions[0], { workspaceSlug: 'andritz' });
    assert.equal(component.modelReadinessLoading(), true);

    api.readinessRequests[0].next({
      provider: 'openai',
      model: 'gpt-4o-mini',
      source: 'workspace',
      status: 'needs_setup',
      reason: 'provider_not_configured',
      message: 'No model is configured for this workspace.',
      retryable: false,
    });

    assert.equal(component.modelReadinessLoading(), false);
    assert.equal(component.modelReadiness()?.status, 'needs_setup');
  } finally {
    injector.destroy();
  }
});

test('a failed readiness probe clears the banner instead of blaming the model', () => {
  const { injector, component, api } = makeHarness();
  try {
    setInput(component.viewMode, 'simple');
    component.refreshModelReadiness();
    api.readinessRequests[0].error(new Error('network'));

    // Silence, not a false "unavailable" verdict — the composer stays usable.
    assert.equal(component.modelReadiness(), null);
    assert.equal(component.modelReadinessLoading(), false);
  } finally {
    injector.destroy();
  }
});

test("a late readiness answer from A cannot describe B's model", () => {
  const { injector, component, workspace, api } = makeHarness();
  try {
    setInput(component.viewMode, 'simple');
    component.refreshModelReadiness();

    workspace.switchWorkspace();
    api.readinessRequests[0].next({
      provider: 'private-a',
      model: 'a-only',
      source: 'workspace',
      status: 'ready',
      reason: 'ready',
      message: '',
      retryable: false,
    });

    assert.equal(component.modelReadiness(), null);
    assert.equal(component.modelReadinessLoading(), false);
  } finally {
    injector.destroy();
  }
});

// ---------------------------------------------------------------------------
// Structured provider failures in the thread.
// ---------------------------------------------------------------------------

/** Drive a turn up to the point where the stream is open, then return it. */
function startTurn(
  harness: ReturnType<typeof makeHarness>,
  query: string,
): Subject<Record<string, unknown>> {
  const { component, api, sse } = harness;
  (component as unknown as { focusComposer(): void }).focusComposer = () => undefined;
  (component as unknown as { persistLastEvalContext(q: string, r: string): void })
    .persistLastEvalContext = () => undefined;
  component.userInput = query;
  component.send();
  // The first send creates the session, then re-enters and opens the stream.
  api.sessionCreates[api.sessionCreates.length - 1].next({ id: 'session-1', title: query });
  return sse.last();
}

test('a structured provider error becomes a failure message, not warning text', () => {
  const harness = makeHarness();
  const { injector, component } = harness;
  try {
    const stream = startTurn(harness, 'Quel est le délai de livraison ?');

    stream.next({ chunk_type: 'text', content: 'Le délai observé est' });
    stream.next({
      chunk_type: 'error',
      code: 'CHAT_STREAM_ERROR',
      content: 'The assistant could not answer.',
      recoverable: true,
      is_final: true,
      error: {
        code: 'provider_unreachable',
        message: 'The model service is not responding.',
        retryable: true,
      },
    });
    stream.next({ type: 'done' });

    const answer = component.messages()[1];
    assert.equal(answer.role, 'assistant');
    assert.deepEqual(answer.failure, {
      code: 'provider_unreachable',
      message: 'The model service is not responding.',
      retryable: true,
      needsSetup: false,
    });
    // The partial answer is preserved, and untouched by the failure copy.
    assert.equal(answer.content, 'Le délai observé est');
    assert.equal(answer.content.includes('⚠'), false);
    assert.equal(answer.content.includes('not responding'), false);
    assert.equal(answer.failedQuery, 'Quel est le délai de livraison ?');
  } finally {
    injector.destroy();
  }
});

test('a legacy error chunk falls back to neutral copy carrying no backend text', () => {
  const harness = makeHarness();
  const { injector, component } = harness;
  try {
    const stream = startTurn(harness, 'Question');

    stream.next({
      chunk_type: 'error',
      code: 'CHAT_STREAM_ERROR',
      content: "ConnectionError: HTTPSConnectionPool(host='api.internal', port=443)",
      recoverable: true,
    });
    stream.next({ type: 'done' });

    const answer = component.messages()[1];
    assert.equal(answer.failure?.code, 'generation_failed');
    assert.equal(answer.failure?.message, '', 'no exception text reaches the thread');
    assert.equal(answer.failure?.retryable, true);
    assert.equal(answer.content, '');
  } finally {
    injector.destroy();
  }
});

test('a dropped connection also renders as a failure and keeps the partial answer', () => {
  const harness = makeHarness();
  const { injector, component } = harness;
  try {
    const stream = startTurn(harness, 'Question');

    stream.next({ chunk_type: 'text', content: 'Partial' });
    stream.error(new Error('socket hang up'));

    const answer = component.messages()[1];
    assert.equal(answer.failure?.code, 'generation_failed');
    assert.equal(answer.failure?.message, '');
    assert.equal(answer.content, 'Partial');
    assert.equal(component.streaming(), false);
  } finally {
    injector.destroy();
  }
});

test('retry resends the failed question without leaving the failed turn behind', () => {
  const harness = makeHarness();
  const { injector, component, sse } = harness;
  try {
    const stream = startTurn(harness, 'Quel est le délai ?');
    stream.next({
      chunk_type: 'error',
      error: { code: 'rate_limited', message: 'Throttled.', retryable: true },
    });
    stream.next({ type: 'done' });

    assert.equal(component.messages().length, 2, 'the question and the failure card');
    const failed = component.messages()[1];

    component.retryFailedTurn(failed);

    // The failed turn and the question that produced it are gone; the retry
    // asks the same question once, not a transcript of the outage.
    assert.equal(sse.streams.length, 2, 'a second turn was streamed');
    assert.deepEqual(
      component.messages().map((message) => [message.role, message.content]),
      [['user', 'Quel est le délai ?']],
    );
    assert.equal(component.messages().some((message) => message.failure), false);
  } finally {
    injector.destroy();
  }
});

test('retry re-probes readiness in Quick Ask', () => {
  const harness = makeHarness();
  const { injector, component, api } = harness;
  try {
    setInput(component.viewMode, 'simple');
    const stream = startTurn(harness, 'Question');
    stream.next({
      chunk_type: 'error',
      error: { code: 'provider_unreachable', message: 'Down.', retryable: true },
    });
    stream.next({ type: 'done' });

    // The failed turn itself refreshes the banner, so it cannot keep claiming
    // the model is ready while the thread says otherwise.
    assert.equal(api.readinessRequests.length, 1, 'the failure re-probes readiness');

    component.retryFailedTurn(component.messages()[1]);
    assert.equal(api.readinessRequests.length, 2, 'retry re-probes readiness again');
  } finally {
    injector.destroy();
  }
});

test('standard chat does not probe readiness on a failed turn', () => {
  const harness = makeHarness();
  const { injector, component, api } = harness;
  try {
    const stream = startTurn(harness, 'Question');
    stream.next({
      chunk_type: 'error',
      error: { code: 'provider_unreachable', message: 'Down.', retryable: true },
    });
    stream.next({ type: 'done' });

    assert.equal(api.readinessRequests.length, 0, 'the banner is a Quick Ask surface only');
  } finally {
    injector.destroy();
  }
});

// ---------------------------------------------------------------------------
// Activation funnel (P2.3).
// ---------------------------------------------------------------------------

test('a ready readiness probe records model ready once, without a new setup', () => {
  const { injector, component, api, activation } = makeHarness();
  try {
    setInput(component.viewMode, 'simple');
    component.refreshModelReadiness();
    api.readinessRequests[0].next({
      provider: 'openai',
      model: 'gpt-4o-mini',
      source: 'workspace',
      status: 'ready',
      reason: 'ok',
      message: '',
      retryable: false,
    });

    assert.deepEqual(activation.milestones(), ['model_ready']);
    assert.equal(
      JSON.stringify(activation.calls).includes('gpt-4o-mini'),
      false,
      'the provider and model never travel with the milestone',
    );

    // Re-probing the same ready workspace is not a second activation.
    component.refreshModelReadiness();
    api.readinessRequests[1].next({
      provider: 'openai',
      model: 'gpt-4o-mini',
      source: 'workspace',
      status: 'ready',
      reason: 'ok',
      message: '',
      retryable: false,
    });

    assert.deepEqual(activation.milestones(), ['model_ready']);
  } finally {
    injector.destroy();
  }
});

test('a probe that is not ready, or that fails, records nothing', () => {
  const { injector, component, api, activation } = makeHarness();
  try {
    setInput(component.viewMode, 'simple');
    component.refreshModelReadiness();
    api.readinessRequests[0].next({
      provider: 'openai',
      model: 'gpt-4o-mini',
      source: 'workspace',
      status: 'needs_setup',
      reason: 'provider_not_configured',
      message: 'No model is configured for this workspace.',
      retryable: false,
    });
    assert.deepEqual(activation.milestones(), []);

    component.refreshModelReadiness();
    api.readinessRequests[1].error(new Error('network'));

    assert.deepEqual(activation.milestones(), []);
  } finally {
    injector.destroy();
  }
});

test('a ready answer for the workspace the user left records nothing', () => {
  const { injector, component, api, workspace, activation } = makeHarness();
  try {
    setInput(component.viewMode, 'simple');
    component.refreshModelReadiness();
    workspace.switchWorkspace();
    api.readinessRequests[0].next({
      provider: 'openai',
      model: 'gpt-4o-mini',
      source: 'workspace',
      status: 'ready',
      reason: 'ok',
      message: '',
      retryable: false,
    });

    assert.deepEqual(activation.milestones(), []);
  } finally {
    injector.destroy();
  }
});

test('a successful turn records the first question and the first answer once', () => {
  const harness = makeHarness();
  const { injector, component, sse, activation } = harness;
  try {
    const stream = startTurn(harness, 'Quel est le délai de livraison ?');
    assert.deepEqual(activation.milestones(), ['first_question_sent']);

    stream.next({ chunk_type: 'text', content: 'Le délai observé est de six semaines.' });
    stream.next({ type: 'done' });

    assert.deepEqual(activation.milestones(), ['first_question_sent', 'first_answer_completed']);

    // A second turn is not a first anything.
    component.userInput = 'Et pour la France ?';
    component.send();
    const second = sse.last();
    second.next({ chunk_type: 'text', content: 'Quatre semaines.' });
    second.next({ type: 'done' });

    assert.deepEqual(activation.milestones(), ['first_question_sent', 'first_answer_completed']);
  } finally {
    injector.destroy();
  }
});

test('activation details never carry the question or the answer', () => {
  const harness = makeHarness();
  const { injector, activation } = harness;
  try {
    const stream = startTurn(harness, 'Quel est le tarif confidentiel Andritz ?');
    stream.next({ chunk_type: 'text', content: 'Le tarif confidentiel est 42 EUR.' });
    stream.next({ type: 'done' });

    const serialized = JSON.stringify(activation.calls);
    assert.equal(serialized.includes('confidentiel'), false);
    assert.equal(serialized.includes('42 EUR'), false);
    for (const call of activation.calls) {
      for (const key of Object.keys(call.options)) {
        assert.ok(
          ['dedupeKey', 'recoveryKind', 'elapsedMs'].includes(key),
          `unexpected activation option ${key}`,
        );
      }
    }
  } finally {
    injector.destroy();
  }
});

test('a failed turn records the question but never an answer', () => {
  const harness = makeHarness();
  const { injector, activation } = harness;
  try {
    const stream = startTurn(harness, 'Question');
    stream.next({ chunk_type: 'text', content: 'Partiel' });
    stream.next({
      chunk_type: 'error',
      error: { code: 'provider_unreachable', message: 'Down.', retryable: true },
    });
    stream.next({ type: 'done' });

    assert.deepEqual(activation.milestones(), ['first_question_sent']);
  } finally {
    injector.destroy();
  }
});

test('an empty non-failed turn is not an answer', () => {
  const harness = makeHarness();
  const { injector, activation } = harness;
  try {
    const stream = startTurn(harness, 'Question');
    stream.next({ type: 'done' });

    assert.deepEqual(activation.milestones(), ['first_question_sent']);
  } finally {
    injector.destroy();
  }
});

test('a retry that succeeds records a chat recovery, a retry that fails does not', () => {
  const harness = makeHarness();
  const { injector, component, sse, activation } = harness;
  try {
    const stream = startTurn(harness, 'Quel est le délai ?');
    stream.next({
      chunk_type: 'error',
      error: { code: 'provider_unreachable', message: 'Down.', retryable: true },
    });
    stream.next({ type: 'done' });

    component.retryFailedTurn(component.messages()[1]);
    const firstRetry = sse.last();
    firstRetry.next({
      chunk_type: 'error',
      error: { code: 'provider_unreachable', message: 'Still down.', retryable: true },
    });
    firstRetry.next({ type: 'done' });
    assert.equal(
      activation.milestones().includes('failure_recovered'),
      false,
      'a retry that failed again is not a recovery',
    );

    component.retryFailedTurn(component.messages()[1]);
    const secondRetry = sse.last();
    secondRetry.next({ chunk_type: 'text', content: 'Six semaines.' });
    secondRetry.next({ type: 'done' });

    const recovery = activation.calls.find((call) => call.milestone === 'failure_recovered');
    assert.equal(recovery?.options.recoveryKind, 'chat_retry');
  } finally {
    injector.destroy();
  }
});

test('a plain question after a failed turn is not reported as a recovery', () => {
  const harness = makeHarness();
  const { injector, component, sse, activation } = harness;
  try {
    const stream = startTurn(harness, 'Question');
    stream.next({
      chunk_type: 'error',
      error: { code: 'provider_unreachable', message: 'Down.', retryable: true },
    });
    stream.next({ type: 'done' });

    component.userInput = 'Une autre question';
    component.send();
    const next = sse.last();
    next.next({ chunk_type: 'text', content: 'Une réponse.' });
    next.next({ type: 'done' });

    assert.equal(activation.milestones().includes('failure_recovered'), false);
  } finally {
    injector.destroy();
  }
});

test('opening a resolvable source records it; an unresolvable one records nothing', () => {
  const harness = makeHarness();
  const { injector, component, activation } = harness;
  try {
    component.previewSource({ title: 'Contrat 2026' } as never);
    assert.equal(activation.milestones().includes('source_opened'), false);

    component.previewSource({
      document_id: '3f2a1b4c-5d6e-4f70-8192-a3b4c5d6e7f8',
      collection_name: 'documents',
      filename: 'contrat-confidentiel.pdf',
      title: 'Contrat 2026',
    } as never);

    assert.deepEqual(activation.milestones(), ['source_opened']);
    assert.equal(JSON.stringify(activation.calls).includes('contrat-confidentiel'), false);
  } finally {
    injector.destroy();
  }
});

/**
 * Unit tests for `FlowRunService` — the run/debug/replay orchestrator.
 *
 * Exercised headless through a real Angular `Injector` (the service shares a
 * real `FlowStore` + `FlowSerializerService`, with `CanonicalApiService` and
 * `RunStreamService` swapped for controllable mocks). No live backend, no
 * browser, no zone — `@angular/compiler` is imported first so ngrx's
 * partially-compiled `signalStore` can JIT-compile in Node.
 *
 * Coverage (plan §"TESTS"):
 *   - status transitions: idle → running → paused/done/error
 *   - HITL pending handling (accept / reject resolves + restarts stream)
 *   - debug step / continue / stop
 *   - breakpoint set add / remove + debug-mode cycle
 *   - pre-run validation gating + scratchpad (no systemId) gating
 *   - client-side simulate + checkpoint replay (no backend)
 *
 * Run with `npm run test:unit`.
 */
import '@angular/compiler';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { HttpErrorResponse } from '@angular/common/http';
import { Injector, signal } from '@angular/core';
import { Subject, of } from 'rxjs';
import {
  CanonicalApiService,
  type FlowExecutionRuntimeMode,
  type FlowRuntimeManifest,
  type FlowValidationResponse,
  type Run,
  type RunTriggerRequest,
} from '@app/core/canonical-api.service';
import {
  RunStreamService,
  type RunStreamEvent,
} from '@app/core/run-stream.service';
import { FlowSerializerService, type CanonicalFlow } from '@app/core/flow-serializer.service';
import {
  WorkspaceService,
  type WorkspaceContextTransition,
  type WorkspaceRequestScope,
} from '@app/core/workspace.service';
import { I18nService } from '@app/core/i18n.service';
import { FLOW_EN } from '@app/core/i18n/flow.dict';
import { FlowStore } from './flow.store';
import {
  FlowManifestService,
  manifestRuntimeMode,
  runtimeModeKey,
} from './flow-manifest.service';
import { FlowPersistenceService } from './flow-persistence.service';
import {
  draftTestIngressOptions,
  FlowRunService,
  parseRunInputRef,
  selectDraftTestIngress,
} from './flow-run.service';

type Store = InstanceType<typeof FlowStore>;
type Svc = InstanceType<typeof FlowRunService>;

function mkRun(status: Run['status'], extra: Partial<Run> = {}): Run {
  return { id: 'run-abcdef1234', system_id: 'sys-1', status, ...extra };
}

/** A graph that passes `validateFlow` (source → sink, no error-level issues). */
function validFlow(): CanonicalFlow {
  return {
    source: 'flow',
    schema_version: 2,
    nodes: [
      { id: 's', type: 'source', kind: 'source', label: 'Start', outputs: [{ name: 'goal', schema: 'string' }] },
      { id: 'o', type: 'sink', kind: 'sink', label: 'Out', inputs: [{ name: 'result', schema: 'object' }] },
    ],
    edges: [{ from: 's', to: 'o', kind: 'data' }],
  };
}

/** A graph with an error-level diagnostic (edge to a non-existent node). */
function invalidFlow(): CanonicalFlow {
  return {
    source: 'flow',
    schema_version: 2,
    nodes: [{ id: 's', type: 'source', kind: 'source', label: 'Start' }],
    edges: [{ from: 's', to: 'ghost', kind: 'data' }],
  };
}

class MockApi {
  triggerRunCalls = 0;
  triggerPayloads: RunTriggerRequest[] = [];
  draftTestRunCalls: Array<{
    systemId: string;
    payload: {
      input_ref: Record<string, unknown>;
      expected_draft_revision: number;
      expected_flow_sha256: string;
      ingress_id?: string;
      kind?: 'manual' | 'chat' | 'http' | 'schedule' | 'event';
    };
  }> = [];
  stepRunCalls: Array<{ action: string; breakpoints?: string[] }> = [];
  resolveHitlCalls: Array<{ action: string; expected_decision_id?: string }> = [];
  getRunCalls = 0;

  triggerResult: Run | null = mkRun('running');
  getRunResult: Run | null = mkRun('completed');
  resolveResult: Run | null = mkRun('running');
  stepResult: Run | null = mkRun('running');
  triggerSubject: Subject<Run | null> | null = null;
  resolveSubject: Subject<Run | null> | null = null;
  stepSubject: Subject<Run | null> | null = null;
  getRunSubject: Subject<Run | null> | null = null;

  triggerRun(_id: string, payload: RunTriggerRequest) {
    this.triggerRunCalls++;
    this.triggerPayloads.push(payload);
    return this.triggerSubject?.asObservable() ?? of(this.triggerResult);
  }
  triggerSystemFlowDraftTestRun(
    systemId: string,
    payload: {
      input_ref: Record<string, unknown>;
      expected_draft_revision: number;
      expected_flow_sha256: string;
      ingress_id?: string;
      kind?: 'manual' | 'chat' | 'http' | 'schedule' | 'event';
    },
  ) {
    this.draftTestRunCalls.push({ systemId, payload });
    return this.triggerSubject?.asObservable() ?? of(this.triggerResult);
  }
  getRun(_id: string) {
    this.getRunCalls++;
    return this.getRunSubject?.asObservable() ?? of(this.getRunResult);
  }
  resolveRunHitl(_id: string, body: { action: 'accept' | 'reject' }) {
    this.resolveHitlCalls.push(body);
    return this.resolveSubject?.asObservable() ?? of(this.resolveResult);
  }
  stepRun(_id: string, body: { action: 'step' | 'continue' | 'stop'; breakpoints?: string[] }) {
    this.stepRunCalls.push(body);
    return this.stepSubject?.asObservable() ?? of(this.stepResult);
  }
}

class PersistenceStub {
  readonly hydrationReady = signal(true);
  readonly actionsDisabled = signal(false);
  readonly publicationMode = signal(false);
  readonly draftRevision = signal<number | null>(null);
  readonly savedFlowSha256 = signal<string | null>('sha-flow');
  readonly serverValidation = signal<FlowValidationResponse | null>({
    flow_sha256: 'sha-flow',
    analyzer_version: 'flow-analyzer/1',
    runtime_mode: 'dag_strict' as const,
    valid: true,
    issues: [] as Array<{ level: 'error' | 'warn'; code: string; message: string }>,
  });
  readonly serverValidationState = signal<'idle' | 'scheduled' | 'validating' | 'ready' | 'error'>('ready');
  readonly saveState = signal<'saved' | 'unsaved' | 'saving' | 'error'>('saved');
  revisionConflicts: string[] = [];
  markRevisionConflict(message: string): void {
    this.revisionConflicts.push(message);
  }
}

class ManifestStub {
  readonly manifest = signal<FlowRuntimeManifest | null>({
    system_id: 'sys-1',
    system_name: 'System 1',
    flow_sha256: 'sha-flow',
    runtime_mode: 'dag_strict',
  });
  readonly runtimeMode = signal<FlowExecutionRuntimeMode | null>('dag_strict');
  readonly runtimeModeLabel = signal('flow.runtime.mode.dag_strict');
}

class WorkspaceStub {
  private slug = 'andritz';
  private epoch = 1;
  private readonly resetters = new Set<(transition: WorkspaceContextTransition) => void>();

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
    this.slug = transition.nextSlug;
    this.epoch = transition.nextEpoch;
  }
}

class MockStream {
  last: Subject<RunStreamEvent> | null = null;
  streamRun(_runId: string) {
    this.last = new Subject<RunStreamEvent>();
    return this.last.asObservable();
  }
  emit(event: RunStreamEvent): void {
    this.last?.next(event);
  }
}

interface Harness {
  svc: Svc;
  store: Store;
  api: MockApi;
  stream: MockStream;
  persistence: PersistenceStub;
  manifest: ManifestStub;
}

function makeHarness(workspace?: WorkspaceStub): Harness {
  const api = new MockApi();
  const stream = new MockStream();
  const persistence = new PersistenceStub();
  const manifest = new ManifestStub();
  const injector = Injector.create({
    providers: [
      FlowSerializerService,
      FlowStore as never,
      FlowRunService as never,
      { provide: CanonicalApiService, useValue: api },
      { provide: RunStreamService, useValue: stream },
      { provide: FlowPersistenceService, useValue: persistence },
      { provide: FlowManifestService, useValue: manifest },
      {
        provide: I18nService,
        useValue: {
          locale: signal('en'),
          setLocale: () => undefined,
          // Resolve the real EN copy so the log assertions below keep reading
          // the words an operator sees rather than the key that carries them.
          t: (key: string, params?: Record<string, string | number>) => {
            const value = (FLOW_EN as Record<string, string>)[key] ?? key;
            return params
              ? value.replace(/\{(\w+)\}/g, (match, name: string) =>
                  name in params ? String(params[name]) : match,
                )
              : value;
          },
        },
      },
      ...(workspace ? [{ provide: WorkspaceService, useValue: workspace }] : []),
    ],
  });
  return {
    svc: injector.get(FlowRunService) as Svc,
    store: injector.get(FlowStore) as Store,
    api,
    stream,
    persistence,
    manifest,
  };
}

test('workspace reset rejects late trigger, HITL, step and nested getRun responses', () => {
  {
    const workspace = new WorkspaceStub();
    const { svc, store, api, stream } = makeHarness(workspace);
    api.triggerSubject = new Subject<Run | null>();
    store.load(validFlow());
    svc.bindSystem('sys-1');
    svc.executeOnBackend();

    workspace.switchWorkspace();
    api.triggerSubject.next(mkRun('running'));

    assert.equal(svc.currentRun(), null);
    assert.equal(svc.status(), 'idle');
    assert.equal(stream.last, null, 'a late trigger cannot open a stream in the new workspace');
  }

  {
    const workspace = new WorkspaceStub();
    const { svc, api, stream } = makeHarness(workspace);
    api.resolveSubject = new Subject<Run | null>();
    svc.currentRun.set(mkRun('hitl_pending', { hitl: { node_id: 'gate' } }));
    svc.resolveHitl('accept');

    workspace.switchWorkspace();
    api.resolveSubject.next(mkRun('running'));

    assert.equal(svc.currentRun(), null);
    assert.equal(svc.status(), 'idle');
    assert.equal(stream.last, null, 'a late HITL response cannot resume the old run');
  }

  {
    const workspace = new WorkspaceStub();
    const { svc, api, stream } = makeHarness(workspace);
    api.stepSubject = new Subject<Run | null>();
    svc.currentRun.set(mkRun('debug_pending', { debug: { node_id: 'n1' } }));
    svc.debugAction('step');

    workspace.switchWorkspace();
    api.stepSubject.next(mkRun('running'));

    assert.equal(svc.currentRun(), null);
    assert.equal(svc.status(), 'idle');
    assert.equal(stream.last, null, 'a late step response cannot resume the old run');
  }

  {
    const workspace = new WorkspaceStub();
    const { svc, api } = makeHarness(workspace);
    api.getRunSubject = new Subject<Run | null>();
    api.stepResult = mkRun('cancelled');
    svc.currentRun.set(mkRun('debug_pending', { debug: { node_id: 'n1' } }));
    svc.debugAction('stop');

    workspace.switchWorkspace();
    api.getRunSubject.next(mkRun('completed'));

    assert.equal(svc.currentRun(), null, 'a nested late getRun cannot restore the old run');
    assert.equal(svc.status(), 'idle');
  }
});

test('status: idle → running → done across a clean backend run', () => {
  const { svc, store, api, stream } = makeHarness();
  store.load(validFlow());
  svc.bindSystem('sys-1');
  assert.equal(svc.status(), 'idle');

  svc.executeOnBackend();
  assert.equal(api.triggerRunCalls, 1, 'triggers exactly one run');
  assert.deepEqual(api.triggerPayloads[0], {
    trigger: 'manual',
    input_ref: {},
    expected_flow_sha256: 'sha-flow',
  });
  assert.equal(svc.status(), 'running');
  assert.equal(svc.executing(), true);

  stream.emit({ event: 'node_start', data: { node_id: 's', label: 'Start' } });
  assert.ok(svc.log().some((e) => e.text.includes('Start')), 'logs node_start');
  assert.equal(svc.activeNodeId(), 's', 'tracks the active node');

  stream.emit({ event: 'run_end', data: { status: 'completed' } });
  assert.equal(svc.status(), 'done');
  assert.equal(svc.activeNodeId(), null);
});

test('publication Builder executes the saved server draft, never the published Run endpoint', () => {
  const { svc, store, api, persistence, manifest } = makeHarness();
  store.load(validFlow());
  svc.bindSystem('sys-1');
  persistence.publicationMode.set(true);
  persistence.draftRevision.set(7);
  // The published manifest may legitimately point at another hash. A draft
  // test-run compiles/freezes the draft independently and must not use it.
  manifest.manifest.set({
    system_id: 'sys-1',
    system_name: 'System 1',
    flow_sha256: 'sha-published',
    runtime_mode: 'dag_strict',
  });

  svc.executeOnBackend({ ticket: 'INC-42' });

  assert.equal(api.triggerRunCalls, 0);
  assert.deepEqual(api.draftTestRunCalls, [
    {
      systemId: 'sys-1',
      payload: {
        input_ref: { ticket: 'INC-42' },
        expected_draft_revision: 7,
        expected_flow_sha256: 'sha-flow',
        ingress_id: 's',
        kind: 'manual',
      },
    },
  ]);
  assert.equal(svc.executionSurfaceLabel(), FLOW_EN['flow.runtime.surface.draft']);
});

test('multiple draft ingresses stay ambiguous until the operator chooses one', () => {
  const flow = validFlow();
  flow.nodes.unshift({
    id: 'webhook',
    type: 'source.webhook',
    kind: 'source',
    label: 'Webhook',
  });

  assert.equal(selectDraftTestIngress(flow), null);
  assert.deepEqual(draftTestIngressOptions(flow), [
    { ingress_id: 'webhook', kind: 'http', label: 'Webhook' },
    { ingress_id: 's', kind: 'manual', label: 'Start' },
  ]);
  assert.deepEqual(selectDraftTestIngress(flow, 's'), {
    ingress_id: 's',
    kind: 'manual',
  });
});

test('draft test ingress selection supports a sole non-manual adapter', () => {
  const flow = validFlow();
  flow.nodes = flow.nodes.filter((node) => node.id !== 's');
  flow.nodes.unshift({
    id: 'webhook',
    type: 'source.webhook',
    kind: 'source',
    label: 'Webhook',
  });

  assert.deepEqual(selectDraftTestIngress(flow), {
    ingress_id: 'webhook',
    kind: 'http',
  });
});

test('draft input modal blocks an ambiguous Flow until a real ingress is selected', () => {
  const { svc, store, api, persistence } = makeHarness();
  const flow = validFlow();
  flow.nodes.unshift({
    id: 'webhook',
    type: 'source.webhook',
    kind: 'source',
    label: 'Webhook',
  });
  flow.nodes.push({
    id: 'webhook.out',
    type: 'sink',
    kind: 'sink',
    label: 'Webhook result',
  });
  flow.edges.push({ from: 'webhook', to: 'webhook.out', kind: 'data' });
  store.load(flow);
  svc.bindSystem('sys-1');
  persistence.publicationMode.set(true);
  persistence.draftRevision.set(7);

  svc.openInputEditor();

  assert.equal(svc.inputEditorOpen(), true);
  assert.equal(svc.selectedDraftIngressId(), '');
  assert.equal(svc.canSubmitInput(), false);
  assert.match(svc.draftIngressSelectionError() ?? '', /Choose one of the 2/);
  svc.submitInputEditor();
  assert.equal(api.draftTestRunCalls.length, 0, 'ambiguous Submit is fail-closed');

  svc.chooseDraftTestIngress('webhook');
  assert.equal(svc.canSubmitInput(), true);
  svc.submitInputEditor();

  assert.equal(api.triggerRunCalls, 0);
  assert.deepEqual(api.draftTestRunCalls[0]?.payload, {
    input_ref: {},
    expected_draft_revision: 7,
    expected_flow_sha256: 'sha-flow',
    ingress_id: 'webhook',
    kind: 'http',
  });
});

test('Decision terminal renders explicit resolution and branch label without values', () => {
  const { svc, store, stream } = makeHarness();
  store.load(validFlow());
  svc.bindSystem('sys-1');
  svc.executeOnBackend();

  stream.emit({
    event: 'decision_resolution',
    data: {
      node_id: 'route',
      resolution: 'matched',
      chosen_branch: 'eligible',
      evaluations: [{ label: 'eligible', matched: true, value: 'must-not-render' }],
    },
  });
  const line = svc.log().find((entry) => entry.tag === 'DECISION');
  assert.equal(line?.text, 'Decision route · matched → eligible');
  assert.doesNotMatch(line?.text ?? '', /must-not-render/);

  for (const resolution of ['defaulted', 'no_match', 'unroutable', 'error'] as const) {
    stream.emit({
      event: 'decision_resolution',
      data: { node_id: 'route', resolution, chosen_branch: 'fallback' },
    });
  }
  const decisionLines = svc.log().filter((entry) => entry.tag === 'DECISION');
  assert.ok(decisionLines.some((entry) => entry.text.includes('default → fallback')));
  assert.ok(decisionLines.some((entry) => entry.text.includes('no matching branch')));
  assert.ok(decisionLines.some((entry) => entry.text.includes('unroutable → fallback')));
  assert.ok(decisionLines.some((entry) => entry.text.includes('evaluation error')));
});

test('status: trigger failure → error', () => {
  const { svc, store, api } = makeHarness();
  store.load(validFlow());
  svc.bindSystem('sys-1');
  api.triggerResult = null;

  svc.executeOnBackend();
  assert.equal(svc.status(), 'error');
  assert.equal(svc.executing(), false);
});

test('HITL: pause → accept resolves and restarts the stream', () => {
  const { svc, store, api, stream } = makeHarness();
  store.load(validFlow());
  svc.bindSystem('sys-1');
  api.getRunResult = mkRun('hitl_pending', { hitl: { node_id: 'gate', prompt: 'Approve?', decision_id: 'observed-gate' } });

  svc.executeOnBackend();
  stream.emit({ event: 'hitl_pause', data: { node_id: 'gate' } });
  assert.equal(svc.status(), 'paused');
  assert.ok(svc.pendingHitl(), 'HITL payload is exposed while paused');
  assert.equal(svc.pendingHitl()?.node_id, 'gate');

  api.resolveResult = mkRun('running');
  svc.resolveHitl('accept');
  assert.equal(api.resolveHitlCalls.length, 1);
  assert.equal(api.resolveHitlCalls[0].action, 'accept');
  assert.equal(api.resolveHitlCalls[0].expected_decision_id, 'observed-gate');
  assert.equal(svc.status(), 'running', 'resume puts the run back to running');
  assert.equal(svc.hitlResolving(), false);
});

test('HITL: a refused decision does not log an approval or resume', () => {
  const { svc, store, api, stream } = makeHarness();
  store.load(validFlow());
  svc.bindSystem('sys-1');
  api.getRunResult = mkRun('hitl_pending', { hitl: { decision_id: 'old-gate' } });
  svc.executeOnBackend();
  stream.emit({ event: 'hitl_pause', data: { node_id: 'gate' } });
  const before = svc.log().length;
  api.resolveResult = null;
  svc.resolveHitl('accept');
  assert.equal(svc.status(), 'paused');
  assert.equal(svc.hitlResolving(), false);
  assert.ok(svc.log().slice(before).some(entry => entry.tag === 'ERR'));
  assert.ok(!svc.log().slice(before).some(entry => entry.tag === 'HITL'));
});

test('HITL: reject is forwarded; ignored when no pending gate', () => {
  const { svc, store, api, stream } = makeHarness();
  store.load(validFlow());
  svc.bindSystem('sys-1');
  api.getRunResult = mkRun('hitl_pending', { hitl: { node_id: 'gate' } });
  svc.executeOnBackend();
  stream.emit({ event: 'hitl_pause', data: { node_id: 'gate' } });

  api.resolveResult = mkRun('running');
  svc.resolveHitl('reject');
  assert.equal(api.resolveHitlCalls[0].action, 'reject');

  // After resume there is no pending gate → a second resolve is a no-op.
  const before = api.resolveHitlCalls.length;
  svc.resolveHitl('accept');
  assert.equal(api.resolveHitlCalls.length, before, 'no pending HITL → ignored');
});

test('debug: step then stop drives the debugger', () => {
  const { svc, store, api, stream } = makeHarness();
  store.load(validFlow());
  svc.bindSystem('sys-1');
  svc.debugMode.set('step');
  api.getRunResult = mkRun('debug_pending', { debug: { node_id: 'n2', debug_mode: 'step' } });

  svc.executeOnBackend();
  assert.equal(api.triggerRunCalls, 1, 'debug run uses the canonical triggerRun');
  assert.deepEqual(api.triggerPayloads[0].input_ref['_debug'], {
    mode: 'step',
    breakpoints: [],
  });

  stream.emit({ event: 'debug_pause', data: { node_id: 'n2' } });
  assert.equal(svc.status(), 'paused');
  assert.ok(svc.pendingDebug(), 'debug payload exposed while paused');

  api.stepResult = mkRun('debug_pending', { debug: { node_id: 'n3' } });
  svc.debugAction('step');
  assert.equal(api.stepRunCalls.length, 1);
  assert.equal(api.stepRunCalls[0].action, 'step');
  assert.equal(svc.status(), 'running', 'step resumes the walker');

  api.stepResult = mkRun('cancelled');
  svc.debugAction('stop');
  assert.equal(api.stepRunCalls.length, 2);
  assert.equal(api.stepRunCalls[1].action, 'stop');
  assert.equal(svc.status(), 'done', 'stop ends the run');
});

test('debug: continue forwards the live breakpoint set', () => {
  const { svc, store, api, stream } = makeHarness();
  store.load(validFlow());
  svc.bindSystem('sys-1');
  svc.debugMode.set('breakpoints');
  svc.toggleBreakpoint('n2');
  api.getRunResult = mkRun('debug_pending', { debug: { node_id: 'n2' } });

  svc.executeOnBackend();
  assert.deepEqual(api.triggerPayloads[0].input_ref['_debug'], {
    mode: 'breakpoints',
    breakpoints: ['n2'],
  });

  stream.emit({ event: 'debug_pause', data: { node_id: 'n2' } });
  api.stepResult = mkRun('debug_pending', { debug: { node_id: 'n5' } });
  svc.debugAction('continue');
  assert.equal(api.stepRunCalls[0].action, 'continue');
  assert.deepEqual(api.stepRunCalls[0].breakpoints, ['n2']);
});

test('breakpoint debug cannot execute without a selected node', () => {
  const { svc, store, api } = makeHarness();
  store.load(validFlow());
  svc.bindSystem('sys-1');
  svc.debugMode.set('breakpoints');

  assert.equal(svc.canExecute(), false);
  assert.match(svc.executionBlockReason() ?? '', /requires at least one selected node/);
  svc.executeOnBackend();
  assert.equal(api.triggerRunCalls, 0);
});

test('breakpoints: add / remove + debug-mode cycle', () => {
  const { svc, store } = makeHarness();
  store.load(validFlow());
  svc.bindSystem('sys-1');
  assert.equal(svc.isBreakpoint('n1'), false);

  svc.toggleBreakpoint('n1');
  assert.equal(svc.isBreakpoint('n1'), true);
  assert.deepEqual(svc.breakpoints(), ['n1']);

  svc.toggleBreakpoint('n2');
  assert.equal(svc.breakpoints().length, 2);

  svc.toggleBreakpoint('n1');
  assert.equal(svc.isBreakpoint('n1'), false);
  assert.deepEqual(svc.breakpoints(), ['n2']);

  assert.equal(svc.debugMode(), 'off');
  assert.equal(svc.cycleDebugMode(), 'step');
  assert.equal(svc.cycleDebugMode(), 'breakpoints');
  assert.equal(svc.cycleDebugMode(), 'off');
});

test('gating: invalid flow blocks the backend launch', () => {
  const { svc, store, api } = makeHarness();
  store.load(invalidFlow());
  svc.bindSystem('sys-1');

  svc.executeOnBackend();
  assert.equal(api.triggerRunCalls, 0, 'never reaches the backend with errors');
  assert.equal(svc.status(), 'error');
  assert.ok(svc.log().some((e) => e.tag === 'ERR'), 'surfaces the validation error');
});

test('gating: scratchpad (no systemId) cannot Execute', () => {
  const { svc, store, api } = makeHarness();
  store.load(validFlow());
  svc.bindSystem(null);
  assert.equal(svc.canExecute(), false);

  svc.executeOnBackend();
  assert.equal(api.triggerRunCalls, 0);
  assert.equal(svc.status(), 'idle', 'status untouched on the scratchpad');
  assert.ok(svc.log().some((e) => e.text.includes('scratchpad')));
});

test('input editor accepts only JSON objects and reserves _debug', () => {
  assert.deepEqual(parseRunInputRef('{"case_id":"A-17"}'), {
    ok: true,
    value: { case_id: 'A-17' },
  });
  assert.equal(parseRunInputRef('not-json').ok, false);
  assert.equal(parseRunInputRef('[]').ok, false);
  assert.equal(parseRunInputRef('null').ok, false);
  const reserved = parseRunInputRef('{"_debug":{"mode":"step"}}');
  assert.equal(reserved.ok, false);
  if (!reserved.ok) assert.equal(reserved.messageKey, 'flow.run.input.error.debug_reserved');
});

test('service-owned debug metadata cannot be injected through a direct Execute call', () => {
  const { svc, store, api } = makeHarness();
  store.load(validFlow());
  svc.bindSystem('sys-1');
  svc.executeOnBackend({ _debug: { mode: 'step' } });
  assert.equal(api.triggerRunCalls, 0);
  assert.match(svc.dispatchError() ?? '', /reserved/);
});

test('runtime badge accepts the three server modes and only falls back when canonical mode is absent', () => {
  assert.equal(manifestRuntimeMode({
    system_id: 's',
    system_name: 'S',
    runtime_mode: 'dag_strict',
  }), 'dag_strict');
  assert.equal(manifestRuntimeMode({
    system_id: 's',
    system_name: 'S',
    execution_mode: 'dag_overlay',
  }), 'dag_overlay');
  assert.equal(manifestRuntimeMode({
    system_id: 's',
    system_name: 'S',
    runtime_mode: 'historical_unknown',
    execution_mode: 'dag_strict',
  }), null, 'an invalid canonical field cannot be masked by the fallback');
  assert.equal(runtimeModeKey('dag_strict'), 'flow.runtime.mode.dag_strict');
  assert.equal(runtimeModeKey('dag_overlay'), 'flow.runtime.mode.dag_overlay');
  assert.equal(runtimeModeKey('sequential_legacy'), 'flow.runtime.mode.sequential_legacy');
  assert.equal(runtimeModeKey(null), 'flow.runtime.mode.unknown');
});

test('gating: dirty, saving, save error, missing hash and stale manifest all fail closed', () => {
  const { svc, store, api, persistence, manifest } = makeHarness();
  store.load(validFlow());
  svc.bindSystem('sys-1');
  assert.equal(svc.canExecute(), true, 'clean hydrated matching contract is executable');

  store.addNode({ type: 'task', label: 'Unsaved' });
  assert.equal(svc.canExecute(), false);
  assert.match(svc.executionBlockReason() ?? '', /Save the current Flow/);
  store.load(validFlow());

  persistence.saveState.set('saving');
  assert.equal(svc.canExecute(), false);
  persistence.saveState.set('error');
  assert.match(svc.executionBlockReason() ?? '', /last save failed/);
  persistence.saveState.set('saved');

  persistence.savedFlowSha256.set(null);
  assert.match(svc.executionBlockReason() ?? '', /no authoritative hash/);
  persistence.savedFlowSha256.set('sha-flow');

  manifest.manifest.set({
    system_id: 'sys-1',
    system_name: 'System 1',
    flow_sha256: 'sha-old',
    runtime_mode: 'dag_strict',
  });
  assert.match(svc.executionBlockReason() ?? '', /runtime contract refreshes/);
  svc.executeOnBackend();
  assert.equal(api.triggerRunCalls, 0);
});

test('Execute consumes only a current server validation for the saved hash', () => {
  const { svc, store, api, persistence } = makeHarness();
  store.load(validFlow());
  svc.bindSystem('sys-1');

  persistence.serverValidation.set(null);
  persistence.serverValidationState.set('validating');
  assert.match(svc.executionBlockReason() ?? '', /current Flow is validated/);

  persistence.serverValidationState.set('error');
  assert.match(svc.executionBlockReason() ?? '', /could not be validated/);

  persistence.serverValidation.set({
    flow_sha256: 'sha-old',
    analyzer_version: 'flow-analyzer/1',
    runtime_mode: 'dag_strict',
    valid: true,
    issues: [],
  });
  assert.match(svc.executionBlockReason() ?? '', /saved Flow hash/);

  persistence.serverValidation.set({
    flow_sha256: 'sha-flow',
    analyzer_version: 'flow-analyzer/1',
    runtime_mode: 'dag_strict',
    valid: false,
    issues: [{ level: 'error', code: 'cycle_detected', message: 'Cycle.' }],
  });
  assert.match(svc.executionBlockReason() ?? '', /current server validation errors/);
  svc.executeOnBackend();
  assert.equal(api.triggerRunCalls, 0);
});

test('debug is blocked in sequential legacy while normal Execute stays available', () => {
  const { svc, store, api, manifest } = makeHarness();
  store.load(validFlow());
  svc.bindSystem('sys-1');
  manifest.runtimeMode.set('sequential_legacy');
  manifest.runtimeModeLabel.set('flow.runtime.mode.sequential_legacy');
  manifest.manifest.set({
    system_id: 'sys-1',
    system_name: 'System 1',
    flow_sha256: 'sha-flow',
    runtime_mode: 'sequential_legacy',
  });

  assert.equal(svc.canExecute(), true, 'normal legacy execution remains available');
  assert.equal(svc.canDebug(), false);
  svc.debugMode.set('step');
  assert.equal(svc.canExecute(), false);
  assert.equal(
    svc.executionBlockReason(),
    FLOW_EN['flow.run.debug.unavailable.sequential'],
  );
  svc.executeOnBackend();
  assert.equal(api.triggerRunCalls, 0);
});

test('403/409/422 trigger errors stay distinct and keep operator input open', () => {
  for (const [status, expected] of [
    [403, /permission/],
    [409, /changed/],
    [422, /invalid/],
  ] as const) {
    const { svc, store, api } = makeHarness();
    store.load(validFlow());
    svc.bindSystem('sys-1');
    api.triggerSubject = new Subject<Run | null>();
    svc.updateInputText('{"ticket":"INC-42"}');
    svc.openInputEditor();
    svc.submitInputEditor();
    api.triggerSubject.error(new HttpErrorResponse({ status }));

    assert.equal(svc.inputEditorOpen(), true, `HTTP ${status} keeps the editor open`);
    assert.equal(svc.inputText(), '{"ticket":"INC-42"}');
    assert.match(svc.dispatchError() ?? '', expected);
  }
});

test('authoritative hydration releases a 409 Execute latch even at the same Flow hash', () => {
  const { svc, store, api, persistence } = makeHarness();
  store.load(validFlow());
  svc.bindSystem('sys-1');
  api.triggerSubject = new Subject<Run | null>();

  svc.executeOnBackend();
  api.triggerSubject.error(new HttpErrorResponse({ status: 409 }));

  assert.equal(persistence.savedFlowSha256(), 'sha-flow');
  assert.equal(svc.canExecute(), false);
  assert.match(svc.executionBlockReason() ?? '', /Reload the authoritative Flow/);

  // Strict hydration may attest a newer revision/pointer with identical graph
  // bytes. Hash inequality is therefore not a valid release condition.
  svc.acknowledgeAuthoritativeHydration();
  assert.equal(persistence.savedFlowSha256(), 'sha-flow');
  assert.equal(svc.canExecute(), true);
  assert.equal(svc.dispatchError(), null);
});

test('simulate: client-side dry run works without a System and skips the backend', () => {
  const { svc, store, api } = makeHarness();
  store.load(validFlow());
  svc.bindSystem(null);

  svc.simulate();
  assert.equal(api.triggerRunCalls, 0, 'simulate never calls the backend');
  assert.ok(svc.terminalOpen(), 'simulate opens the terminal');
  assert.ok(svc.log().some((e) => e.tag === 'DONE'), 'reports a finished dry run');
});

test('replay: re-emits the current run checkpoints into the terminal', () => {
  const { svc } = makeHarness();
  svc.currentRun.set(
    mkRun('completed', {
      checkpoints: [
        { kind: 'run_start' },
        { kind: 'node_start', node_id: 'a', label: 'Alpha' },
        { kind: 'run_end', status: 'completed' },
      ],
    }),
  );
  assert.equal(svc.canReplay(), true);

  svc.replayRun();
  assert.ok(svc.log().some((e) => e.tag === 'REPLAY' && e.text.includes('Replaying')));
  assert.ok(svc.log().some((e) => e.text.includes('Alpha')), 'replays node checkpoints');
});

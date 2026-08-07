import '@angular/compiler';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  Injector,
  ɵChangeDetectionScheduler as ChangeDetectionScheduler,
  ɵEffectScheduler as EffectScheduler,
} from '@angular/core';
import { Subject, of } from 'rxjs';
import {
  CanonicalApiService,
  type FlowValidationResponse,
  type FlowWorkbenchRun,
  type Run,
  type SystemFlowWorkbenchGoldenRunRequest,
  type SystemFlowWorkbenchGoldenRunResponse,
  type SystemFlowWorkbenchNodeRunRequest,
  type SystemFlowWorkbenchPreviewRunRequest,
} from '@app/core/canonical-api.service';
import { FlowSerializerService, type CanonicalFlow } from '@app/core/flow-serializer.service';
import {
  WorkspaceService,
  type WorkspaceContextTransition,
  type WorkspaceRequestScope,
} from '@app/core/workspace.service';
import { FlowStore } from './flow.store';
import {
  buildFlowWorkbenchChatInput,
  FLOW_WORKBENCH_GOLDEN_POLL_POLICY,
  FLOW_WORKBENCH_INTERACTIVE_POLL_POLICY,
  FlowWorkbenchService,
  matchesGoldenExpected,
} from './flow-workbench.service';
import { flowValidationFingerprint } from './flow-validation.service';

const SOURCE_SHA = 'a'.repeat(64);
const ISOLATED_SHA = 'b'.repeat(64);

type Store = InstanceType<typeof FlowStore>;

interface ScheduledEffect {
  dirty: boolean;
  run(): void;
}

class ManualEffectScheduler {
  private readonly effects = new Set<ScheduledEffect>();

  add(effect: ScheduledEffect): void {
    this.effects.add(effect);
  }

  schedule(effect: ScheduledEffect): void {
    this.effects.add(effect);
  }

  remove(effect: ScheduledEffect): void {
    this.effects.delete(effect);
  }

  flush(): void {
    for (let pass = 0; pass < 20; pass += 1) {
      const dirty = [...this.effects].filter((effect) => effect.dirty);
      if (dirty.length === 0) return;
      for (const effect of dirty) effect.run();
    }
    throw new Error('effect scheduler did not settle');
  }
}

function validFlow(multipleIngresses = false): CanonicalFlow {
  const nodes: CanonicalFlow['nodes'] = [
    {
      id: 'source.request',
      type: 'input',
      kind: 'source',
      label: 'Chat',
      config: { ingress_kind: 'chat' },
    },
    {
      id: 'skill.answer',
      type: 'skill.answer',
      kind: 'task',
      label: 'Answer',
      config: { skill_slug: 'answer' },
    },
    { id: 'sink.result', type: 'sink', kind: 'sink', label: 'Result' },
  ];
  const edges: CanonicalFlow['edges'] = [
    { from: 'source.request', to: 'skill.answer', kind: 'data' },
    { from: 'skill.answer', to: 'sink.result', kind: 'data' },
  ];
  if (multipleIngresses) {
    nodes.unshift({
      id: 'source.manual',
      type: 'source.manual',
      kind: 'source',
      label: 'Manual',
      config: { ingress_kind: 'manual' },
    });
    edges.unshift({ from: 'source.manual', to: 'skill.answer', kind: 'data' });
  }
  return {
    source: 'flow',
    schema_version: 3,
    io_mode: 'strict',
    nodes,
    edges,
  };
}

function validation(extra: Partial<FlowValidationResponse> = {}): FlowValidationResponse {
  return {
    flow_sha256: SOURCE_SHA,
    analyzer_version: 'flow-analyzer/1',
    runtime_mode: 'dag_strict',
    valid: true,
    issues: [],
    ...extra,
  };
}

function workbenchRun(
  surface: FlowWorkbenchRun['execution_surface'],
  status: Run['status'],
  extra: Partial<FlowWorkbenchRun> = {},
): FlowWorkbenchRun {
  const sourceSha = SOURCE_SHA;
  const flowSha = surface === 'node_preview' ? ISOLATED_SHA : SOURCE_SHA;
  return {
    id: `run-${surface}`,
    system_id: 'sys-1',
    status,
    execution_surface: surface,
    flow_sha256: flowSha,
    source_flow_sha256: sourceSha,
    runtime_mode: 'dag_strict',
    input_ref: {
      execution: {
        execution_surface: surface,
        flow_sha256: flowSha,
        source_flow_sha256: sourceSha,
        runtime_mode: 'dag_strict',
      },
    },
    output_ref: {},
    ...extra,
  };
}

class ApiStub {
  validationCalls: Array<{ systemId: string; flow: Record<string, unknown> }> = [];
  previewCalls: Array<{ systemId: string; body: SystemFlowWorkbenchPreviewRunRequest }> = [];
  nodeCalls: Array<{ systemId: string; body: SystemFlowWorkbenchNodeRunRequest }> = [];
  goldenCalls: Array<{ systemId: string; body: SystemFlowWorkbenchGoldenRunRequest }> = [];
  getRunCalls = 0;
  validationSubject: Subject<FlowValidationResponse> | null = null;
  validationResult = validation();
  previewResult = workbenchRun('builder_preview', 'pending');
  nodeResult = workbenchRun('node_preview', 'pending');
  goldenResult: SystemFlowWorkbenchGoldenRunResponse = {
    batch_id: 'batch-1',
    flow_sha256: SOURCE_SHA,
    runs: [],
  };
  runs = new Map<string, Run>();

  validateSystemFlow(systemId: string, flow: Record<string, unknown>) {
    this.validationCalls.push({ systemId, flow });
    return this.validationSubject?.asObservable() ?? of(this.validationResult);
  }

  triggerSystemFlowWorkbenchPreviewRun(
    systemId: string,
    body: SystemFlowWorkbenchPreviewRunRequest,
  ) {
    this.previewCalls.push({ systemId, body });
    return of(this.previewResult);
  }

  triggerSystemFlowWorkbenchNodeRun(
    systemId: string,
    body: SystemFlowWorkbenchNodeRunRequest,
  ) {
    this.nodeCalls.push({ systemId, body });
    return of(this.nodeResult);
  }

  triggerSystemFlowWorkbenchGoldenRuns(
    systemId: string,
    body: SystemFlowWorkbenchGoldenRunRequest,
  ) {
    this.goldenCalls.push({ systemId, body });
    return of(this.goldenResult);
  }

  getRun(id: string) {
    this.getRunCalls += 1;
    return of(this.runs.get(id) ?? null);
  }
}

class WorkspaceStub {
  private slug = 'andritz';
  private epoch = 1;
  private readonly resetters = new Set<(transition: WorkspaceContextTransition) => void>();

  captureRequestScope(): WorkspaceRequestScope {
    return Object.freeze({
      workspaceSlug: this.slug,
      workspaceId: `workspace-${this.slug}`,
      epoch: this.epoch,
    });
  }

  isRequestScopeCurrent(scope: WorkspaceRequestScope): boolean {
    return scope.workspaceSlug === this.slug
      && scope.workspaceId === `workspace-${this.slug}`
      && scope.epoch === this.epoch;
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

function harness(flow = validFlow()) {
  const api = new ApiStub();
  const workspace = new WorkspaceStub();
  const effects = new ManualEffectScheduler();
  const injector = Injector.create({
    providers: [
      FlowSerializerService,
      FlowStore as never,
      FlowWorkbenchService,
      { provide: CanonicalApiService, useValue: api },
      { provide: WorkspaceService, useValue: workspace },
      {
        provide: ChangeDetectionScheduler,
        useValue: { notify() {}, runningTick: false },
      },
      { provide: EffectScheduler, useValue: effects },
    ],
  });
  const store = injector.get(FlowStore) as Store;
  store.load(flow);
  const service = injector.get(FlowWorkbenchService);
  effects.flush();
  service.bindSystem('sys-1');
  return { api, workspace, store, service, effects };
}

test('golden matcher is recursive object-partial and array-exact', () => {
  assert.equal(matchesGoldenExpected(
    { answer: { text: 'ok' }, citations: [{ id: 1 }] },
    { answer: { text: 'ok', confidence: 0.9 }, citations: [{ id: 1 }], trace: true },
  ), true);
  assert.equal(matchesGoldenExpected({ answer: { text: 'ok' } }, { answer: { text: 'no' } }), false);
  assert.equal(matchesGoldenExpected([1], [1, 2]), false, 'arrays do not accept hidden extras');
});

test('chat input follows the selected ingress schema without synthetic aliases', () => {
  const flow = validFlow();
  flow.nodes[0].config = {
    ingress_kind: 'chat',
    input_schema: {
      type: 'object',
      properties: {
        prompt: { type: 'string' },
        locale: { type: 'string' },
      },
      required: ['prompt', 'locale'],
      additionalProperties: false,
    },
  };

  assert.deepEqual(
    buildFlowWorkbenchChatInput(flow, 'source.request', 'Hello', { locale: 'fr' }),
    {
      ok: true,
      messageField: 'prompt',
      value: { locale: 'fr', prompt: 'Hello' },
    },
  );
  const unknown = buildFlowWorkbenchChatInput(flow, 'source.request', 'Hello', { ticket: 42 });
  assert.equal(unknown.ok, false);
  if (!unknown.ok) assert.match(unknown.message, /does not accept: ticket/);
  const missing = buildFlowWorkbenchChatInput(flow, 'source.request', 'Hello', {});
  assert.equal(missing.ok, false);
  if (!missing.ok) assert.match(missing.message, /also requires: locale/);
});

test('real side-effect acknowledgement is required before validation or dispatch', async () => {
  const { api, service } = harness();

  assert.equal(await service.runChat('Do not dispatch'), null);
  assert.equal(api.validationCalls.length, 0);
  assert.equal(api.previewCalls.length, 0);
  assert.match(service.error() ?? '', /Acknowledge.*real Skills.*side effects/i);
});

test('chat validates and hash-binds the exact dirty snapshot without saving it', async () => {
  const { api, store, service, effects } = harness();
  store.patchNode('skill.answer', { label: 'Unsaved answer' });
  effects.flush();
  assert.equal(store.dirty(), true);
  const snapshotFingerprint = flowValidationFingerprint(store.snapshot());
  api.runs.set(api.previewResult.id, {
    ...api.previewResult,
    status: 'completed',
    output_ref: { answer: 'Preview answer', evidence: { local: true } },
  });

  const result = await service.runChat('What changed?', { ticket: 'INC-42' }, true);

  assert.equal(result?.status, 'completed');
  assert.equal(api.validationCalls.length, 1);
  assert.equal(flowValidationFingerprint(api.validationCalls[0].flow), snapshotFingerprint);
  assert.equal(api.previewCalls.length, 1);
  assert.equal(flowValidationFingerprint(api.previewCalls[0].body.flow_definition), snapshotFingerprint);
  assert.equal(api.previewCalls[0].body.expected_flow_sha256, SOURCE_SHA);
  assert.equal(api.previewCalls[0].body.acknowledge_real_side_effects, true);
  assert.deepEqual(api.previewCalls[0].body.input_ref, {
    query: 'What changed?',
    ticket: 'INC-42',
  });
  assert.deepEqual(
    { ingress_id: api.previewCalls[0].body.ingress_id, kind: api.previewCalls[0].body.kind },
    { ingress_id: 'source.request', kind: 'chat' },
  );
  assert.equal(store.dirty(), true, 'preview never marks an unsaved Flow as saved');
  assert.equal(service.chatMessages().at(-1)?.content, 'Preview answer');
  assert.equal(service.runtimeMode(), 'dag_strict');
});

test('a graph edit during validation fences the request before dispatch', async () => {
  const { api, store, service, effects } = harness();
  api.validationSubject = new Subject<FlowValidationResponse>();
  const pending = service.runChat('Fence me', {}, true);
  assert.equal(api.validationCalls.length, 1);

  store.patchNode('skill.answer', { label: 'Edited after validation started' });
  effects.flush();
  api.validationSubject.next(validation());
  api.validationSubject.complete();
  const result = await pending;

  assert.equal(result, null);
  assert.equal(api.previewCalls.length, 0);
  assert.equal(service.error(), null, 'revision invalidation removes stale operation errors');
  assert.deepEqual(service.chatMessages(), [], 'revision invalidation removes stale chat evidence');
});

test('multiple ingresses require an explicit stable selection', async () => {
  const { api, service } = harness(validFlow(true));
  const rejected = await service.runChat('Ambiguous', {}, true);
  assert.equal(rejected, null);
  assert.equal(api.previewCalls.length, 0);
  assert.match(service.error() ?? '', /Choose one of the 2 Flow ingresses/);

  service.selectedIngressId.set('source.request');
  api.runs.set(api.previewResult.id, { ...api.previewResult, status: 'completed' });
  await service.runChat('Explicit', {}, true);
  assert.equal(api.previewCalls[0].body.ingress_id, 'source.request');
  assert.equal(api.previewCalls[0].body.kind, 'chat');
});

test('isolated node execution keeps source hash evidence and projects its result', async () => {
  const { api, service } = harness();
  api.validationResult = validation({
    valid: false,
    issues: [{
      level: 'error',
      code: 'edge_target_missing',
      message: 'An unrelated dirty branch is incomplete.',
    }],
  });
  api.runs.set(api.nodeResult.id, {
    ...api.nodeResult,
    status: 'completed',
    output_ref: { prompt: 'works', score: 1 },
  });

  const run = await service.runSelectedNode(
    'skill.answer',
    { prompt: 'hello', context: { locale: 'en' } },
    true,
  );

  assert.equal(run?.status, 'completed');
  assert.equal(api.nodeCalls.length, 1, 'full-graph diagnostics do not block the isolated projection');
  assert.deepEqual(api.nodeCalls[0], {
    systemId: 'sys-1',
    body: {
      acknowledge_real_side_effects: true,
      flow_definition: api.validationCalls[0].flow,
      expected_flow_sha256: SOURCE_SHA,
      node_id: 'skill.answer',
      input_ref: { prompt: 'hello', context: { locale: 'en' } },
    },
  });
  assert.equal(service.nodeResult()?.successful, true);
  assert.deepEqual(service.nodeResult()?.output, { prompt: 'works', score: 1 });
  assert.equal(service.nodeResult()?.run.source_flow_sha256, SOURCE_SHA);
  assert.equal(service.nodeResult()?.run.flow_sha256, ISOLATED_SHA);
});

test('golden batch maps server-owned case ids and scores expected output', async () => {
  const { api, service } = harness();
  const first = workbenchRun('golden_preview', 'pending', {
    id: 'golden-1',
    input_ref: { execution: { golden_case_id: 'case-pass', source_flow_sha256: SOURCE_SHA } },
  });
  const second = workbenchRun('golden_preview', 'pending', {
    id: 'golden-2',
    input_ref: { execution: { golden_case_id: 'case-fail', source_flow_sha256: SOURCE_SHA } },
  });
  api.goldenResult = {
    batch_id: 'batch-1',
    flow_sha256: SOURCE_SHA,
    runs: [second, first],
  };
  api.runs.set(first.id, { ...first, status: 'completed', output_ref: { answer: 'yes', extra: true } });
  api.runs.set(second.id, { ...second, status: 'completed', output_ref: { answer: 'no' } });

  const results = await service.runGoldenSet([
    { id: 'case-pass', input_ref: { query: 'one' }, expected: { answer: 'yes' } },
    { id: 'case-fail', input_ref: { query: 'two' }, expected: { answer: 'yes' } },
  ], true);

  assert.equal(api.goldenCalls.length, 1);
  assert.equal(api.goldenCalls[0].body.expected_flow_sha256, SOURCE_SHA);
  assert.equal(api.goldenCalls[0].body.acknowledge_real_side_effects, true);
  assert.deepEqual(
    results?.map((item) => ({ id: item.caseId, passed: item.passed })),
    [{ id: 'case-fail', passed: false }, { id: 'case-pass', passed: true }],
  );
  assert.deepEqual(service.goldenSummary(), {
    total: 2,
    completed: 2,
    pending: 0,
    passed: 1,
    failed: 1,
  });
  assert.deepEqual(results?.find((item) => item.caseId === 'case-pass')?.expected, { answer: 'yes' });
  assert.deepEqual(results?.find((item) => item.caseId === 'case-pass')?.actual, {
    answer: 'yes',
    extra: true,
  });
});

test('golden polling follows the server queue instead of polling every case concurrently', async () => {
  const { api, service } = harness();
  const first = workbenchRun('golden_preview', 'pending', {
    id: 'golden-first',
    input_ref: { execution: { golden_case_id: 'first', source_flow_sha256: SOURCE_SHA } },
  });
  const second = workbenchRun('golden_preview', 'pending', {
    id: 'golden-second',
    input_ref: { execution: { golden_case_id: 'second', source_flow_sha256: SOURCE_SHA } },
  });
  api.goldenResult = {
    batch_id: 'batch-serial',
    flow_sha256: SOURCE_SHA,
    runs: [first, second],
  };
  const firstPoll = new Subject<Run | null>();
  const polledIds: string[] = [];
  api.getRun = (id: string) => {
    api.getRunCalls += 1;
    polledIds.push(id);
    return id === first.id
      ? firstPoll.asObservable()
      : of({ ...second, status: 'completed' as const, output_ref: { answer: 'second' } });
  };

  const pending = service.runGoldenSet([
    { id: 'first', input_ref: { query: 'one' } },
    { id: 'second', input_ref: { query: 'two' } },
  ], true);
  for (let spin = 0; polledIds.length === 0 && spin < 20; spin += 1) await Promise.resolve();

  assert.deepEqual(polledIds, [first.id]);
  firstPoll.next({ ...first, status: 'completed', output_ref: { answer: 'first' } });
  firstPoll.complete();
  const results = await pending;

  assert.deepEqual(polledIds, [first.id, second.id]);
  assert.deepEqual(results?.map((item) => item.passed), [true, true]);
});

test('sequential legacy validation fails closed before any workbench endpoint', async () => {
  const { api, service } = harness();
  api.validationResult = validation({ runtime_mode: 'sequential_legacy' });

  assert.equal(await service.runChat('Legacy', {}, true), null);
  assert.equal(api.previewCalls.length, 0);
  assert.equal(service.runtimeMode(), 'sequential_legacy');
  assert.match(service.error() ?? '', /requires a DAG runtime.*LEGACY.*SEQUENTIAL/i);
});

test('golden polling has a distinct one-hour budget without changing interactive polling', async (t) => {
  assert.deepEqual(FLOW_WORKBENCH_INTERACTIVE_POLL_POLICY, {
    intervalMs: 500,
    maxAttempts: 240,
    timeoutLabel: 'The workbench Run',
  });
  assert.equal(
    FLOW_WORKBENCH_GOLDEN_POLL_POLICY.intervalMs
      * FLOW_WORKBENCH_GOLDEN_POLL_POLICY.maxAttempts,
    60 * 60 * 1_000,
  );

  t.mock.timers.enable({ apis: ['setInterval', 'setTimeout'] });
  const { api, service } = harness();
  const queued = workbenchRun('golden_preview', 'pending', {
    id: 'golden-never-finishes',
    input_ref: {
      execution: {
        golden_case_id: 'slow-case',
        source_flow_sha256: SOURCE_SHA,
      },
    },
  });
  api.goldenResult = {
    batch_id: 'batch-slow',
    flow_sha256: SOURCE_SHA,
    runs: [queued],
  };

  const pending = service.runGoldenSet([
    { id: 'slow-case', input_ref: { query: 'wait' } },
  ], true);
  for (let attempt = 0; attempt < FLOW_WORKBENCH_GOLDEN_POLL_POLICY.maxAttempts; attempt += 1) {
    for (let spin = 0; api.getRunCalls < attempt + 1 && spin < 100; spin += 1) {
      await Promise.resolve();
    }
    assert.equal(api.getRunCalls, attempt + 1, `poll ${attempt + 1} was scheduled`);
    for (let spin = 0; spin < 10; spin += 1) await Promise.resolve();
    t.mock.timers.tick(FLOW_WORKBENCH_GOLDEN_POLL_POLICY.intervalMs);
  }
  for (let spin = 0; service.busy() && spin < 100; spin += 1) await Promise.resolve();

  assert.equal(await pending, null);
  assert.equal(api.getRunCalls, FLOW_WORKBENCH_GOLDEN_POLL_POLICY.maxAttempts);
  assert.match(service.error() ?? '', /golden Run did not finish within 60 minutes/i);
});

test('every Flow revision invalidates completed workbench evidence', async () => {
  const { api, store, service, effects } = harness();
  api.runs.set(api.previewResult.id, {
    ...api.previewResult,
    status: 'completed',
    output_ref: { answer: 'Evidence for the old revision' },
  });
  await service.runChat('Capture', {}, true);
  assert.equal(service.chatMessages().length, 2);
  assert.equal(service.runtimeMode(), 'dag_strict');

  store.patchNode('skill.answer', { label: 'A new revision' });
  effects.flush();

  assert.deepEqual(service.chatMessages(), []);
  assert.equal(service.nodeResult(), null);
  assert.deepEqual(service.goldenResults(), []);
  assert.equal(service.runtimeMode(), null);
});

test('workspace reset clears workbench evidence and rejects a late validation', async () => {
  const { api, workspace, service } = harness();
  api.validationSubject = new Subject<FlowValidationResponse>();
  const pending = service.runChat('Old tenant', {}, true);
  workspace.switchWorkspace();
  api.validationSubject.next(validation());
  api.validationSubject.complete();

  assert.equal(await pending, null);
  assert.equal(api.previewCalls.length, 0);
  assert.equal(service.systemId(), null);
  assert.deepEqual(service.chatMessages(), []);
  assert.equal(service.error(), null);
});

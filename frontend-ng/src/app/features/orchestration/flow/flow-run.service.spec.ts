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
import { Injector } from '@angular/core';
import { Subject, of } from 'rxjs';
import {
  CanonicalApiService,
  type Run,
} from '@app/core/canonical-api.service';
import {
  RunStreamService,
  type RunStreamEvent,
} from '@app/core/run-stream.service';
import { FlowSerializerService, type CanonicalFlow } from '@app/core/flow-serializer.service';
import { FlowStore } from './flow.store';
import { FlowRunService } from './flow-run.service';

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
  triggerRunDebugCalls: Array<{ mode: string; breakpoints?: string[] }> = [];
  stepRunCalls: Array<{ action: string; breakpoints?: string[] }> = [];
  resolveHitlCalls: Array<{ action: string }> = [];
  getRunCalls = 0;

  triggerResult: Run | null = mkRun('running');
  getRunResult: Run | null = mkRun('completed');
  resolveResult: Run | null = mkRun('running');
  stepResult: Run | null = mkRun('running');

  triggerRun(_id: string, _payload?: Record<string, unknown>) {
    this.triggerRunCalls++;
    return of(this.triggerResult);
  }
  triggerRunDebug(_id: string, options: { mode: string; breakpoints?: string[] }) {
    this.triggerRunDebugCalls.push(options);
    return of(this.triggerResult);
  }
  getRun(_id: string) {
    this.getRunCalls++;
    return of(this.getRunResult);
  }
  resolveRunHitl(_id: string, body: { action: 'accept' | 'reject' }) {
    this.resolveHitlCalls.push(body);
    return of(this.resolveResult);
  }
  stepRun(_id: string, body: { action: 'step' | 'continue' | 'stop'; breakpoints?: string[] }) {
    this.stepRunCalls.push(body);
    return of(this.stepResult);
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
}

function makeHarness(): Harness {
  const api = new MockApi();
  const stream = new MockStream();
  const injector = Injector.create({
    providers: [
      FlowSerializerService,
      FlowStore as never,
      FlowRunService as never,
      { provide: CanonicalApiService, useValue: api },
      { provide: RunStreamService, useValue: stream },
    ],
  });
  return {
    svc: injector.get(FlowRunService) as Svc,
    store: injector.get(FlowStore) as Store,
    api,
    stream,
  };
}

test('status: idle → running → done across a clean backend run', () => {
  const { svc, store, api, stream } = makeHarness();
  store.load(validFlow());
  svc.bindSystem('sys-1');
  assert.equal(svc.status(), 'idle');

  svc.executeOnBackend();
  assert.equal(api.triggerRunCalls, 1, 'triggers exactly one run');
  assert.equal(svc.status(), 'running');
  assert.equal(svc.executing(), true);

  stream.emit({ event: 'node_start', data: { node_id: 's', label: 'Start' } });
  assert.ok(svc.log().some((e) => e.text.includes('Start')), 'logs node_start');
  assert.equal(svc.activeNodeId(), 's', 'tracks the active node');

  stream.emit({ event: 'run_end', data: { status: 'completed' } });
  assert.equal(svc.status(), 'done');
  assert.equal(svc.activeNodeId(), null);
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
  api.getRunResult = mkRun('hitl_pending', { hitl: { node_id: 'gate', prompt: 'Approve?' } });

  svc.executeOnBackend();
  stream.emit({ event: 'hitl_pause', data: { node_id: 'gate' } });
  assert.equal(svc.status(), 'paused');
  assert.ok(svc.pendingHitl(), 'HITL payload is exposed while paused');
  assert.equal(svc.pendingHitl()?.node_id, 'gate');

  api.resolveResult = mkRun('running');
  svc.resolveHitl('accept');
  assert.equal(api.resolveHitlCalls.length, 1);
  assert.equal(api.resolveHitlCalls[0].action, 'accept');
  assert.equal(svc.status(), 'running', 'resume puts the run back to running');
  assert.equal(svc.hitlResolving(), false);
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
  assert.equal(api.triggerRunDebugCalls.length, 1, 'debug run uses triggerRunDebug');
  assert.equal(api.triggerRunDebugCalls[0].mode, 'step');

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
  assert.deepEqual(api.triggerRunDebugCalls[0].breakpoints, ['n2']);

  stream.emit({ event: 'debug_pause', data: { node_id: 'n2' } });
  api.stepResult = mkRun('debug_pending', { debug: { node_id: 'n5' } });
  svc.debugAction('continue');
  assert.equal(api.stepRunCalls[0].action, 'continue');
  assert.deepEqual(api.stepRunCalls[0].breakpoints, ['n2']);
});

test('breakpoints: add / remove + debug-mode cycle', () => {
  const { svc } = makeHarness();
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
  assert.ok(svc.log().some((e) => e.text.includes('Scratchpad')));
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

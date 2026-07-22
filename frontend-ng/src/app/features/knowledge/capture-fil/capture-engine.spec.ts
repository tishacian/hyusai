import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { DestroyRef, Injector } from '@angular/core';
import { NEVER, Subject, of, type Observable } from 'rxjs';
import { ApiService } from '@app/core/api.service';
import { CanonicalApiService } from '@app/core/canonical-api.service';
import { LiveKitConversationService } from '@app/core/livekit-conversation.service';
import { VoiceSessionService } from '@app/core/voice-session.service';
import {
  WorkspaceService,
  type WorkspaceContextTransition,
  type WorkspaceRequestScope,
} from '@app/core/workspace.service';
import { CaptureEngine } from './capture-engine';

class WorkspaceStub {
  private slug = 'andritz';
  private epoch = 1;
  private readonly resetters = new Set<(transition: WorkspaceContextTransition) => void>();

  readonly current = () => ({ slug: this.slug, settings: {} });

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

class DestroyRefStub {
  private readonly callbacks = new Set<() => void>();

  onDestroy(callback: () => void): () => void {
    this.callbacks.add(callback);
    return () => this.callbacks.delete(callback);
  }

  destroy(): void {
    for (const callback of [...this.callbacks]) callback();
    this.callbacks.clear();
  }
}

class RealtimeConnectionStub {
  readonly events$ = NEVER;
  startCalls = 0;
  closeCalls = 0;
  captureFinishCalls = 0;

  start(): void {
    this.startCalls += 1;
  }

  close(): void {
    this.closeCalls += 1;
  }

  captureScene(): void {}

  captureFinish(): void {
    this.captureFinishCalls += 1;
  }
}

interface Deferred<T> {
  readonly promise: Promise<T>;
  readonly resolve: (value: T) => void;
  readonly reject: (error: unknown) => void;
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

interface HarnessOptions {
  readonly feed$: Observable<any>;
  readonly livekitOpen?: (sessionId: string) => Promise<RealtimeConnectionStub>;
  readonly proposalList$?: Observable<any>;
}

function createHarness(options: HarnessOptions) {
  const workspace = new WorkspaceStub();
  const destroyRef = new DestroyRefStub();
  const backendConnections: RealtimeConnectionStub[] = [];
  let livekitOpenCalls = 0;
  let createProposalCalls = 0;
  const api = {
    getCaptureFeed: () => options.feed$,
    getCaptureHintQueue: () => of({ hints: [] }),
    listCaptureProposals: () => options.proposalList$ ?? of({ proposals: [] }),
    createCaptureProposal: () => {
      createProposalCalls += 1;
      return of({ id: 'proposal-bad-fallback' });
    },
  };
  const voiceSession = {
    open: () => {
      const connection = new RealtimeConnectionStub();
      backendConnections.push(connection);
      return connection;
    },
  };
  const livekit = {
    open: (sessionId: string) => {
      livekitOpenCalls += 1;
      return options.livekitOpen
        ? options.livekitOpen(sessionId)
        : Promise.reject(new Error('LiveKit unavailable'));
    },
  };
  const injector = Injector.create({
    providers: [
      CaptureEngine,
      { provide: ApiService, useValue: api },
      { provide: VoiceSessionService, useValue: voiceSession },
      { provide: LiveKitConversationService, useValue: livekit },
      { provide: WorkspaceService, useValue: workspace },
      { provide: CanonicalApiService, useValue: { getSystem: () => of({ settings: {} }) } },
      { provide: DestroyRef, useValue: destroyRef },
    ],
  });
  return {
    engine: injector.get(CaptureEngine),
    workspace,
    destroyRef,
    backendConnections,
    livekitOpenCalls: () => livekitOpenCalls,
    createProposalCalls: () => createProposalCalls,
  };
}

async function flushUntil(predicate: () => boolean): Promise<void> {
  for (let attempt = 0; attempt < 20 && !predicate(); attempt += 1) {
    await Promise.resolve();
  }
  assert.equal(predicate(), true, 'expected async operation to reach the requested checkpoint');
}

test('workspace reset synchronously purges Capture tenant signals before B is published', () => {
  const harness = createHarness({ feed$: of({ feed: [] }) });
  harness.engine.setSession({
    id: 'session-a',
    title: 'Andritz private capture',
    status: 'active',
    system_id: 'system-a',
  });
  harness.engine.revisitTarget.set('event-a');
  harness.engine.setFilLayout('transcript');

  harness.workspace.switchWorkspace();

  assert.equal(harness.engine.sessionId(), null);
  assert.equal(harness.engine.session(), null);
  assert.equal(harness.engine.systemId(), null);
  assert.equal(harness.engine.revisitTarget(), null);
  assert.equal(harness.engine.filLayout(), 'documents');
  assert.equal(harness.engine.connectionState(), 'idle');
  harness.destroyRef.destroy();
});

test('workspace reset during feed hydration neither mutates B nor opens session A transport', async () => {
  const feed = new Subject<any>();
  const harness = createHarness({ feed$: feed.asObservable() });
  const connecting = harness.engine.connect('session-a', { transport: 'backend_ws' });

  harness.workspace.switchWorkspace();
  feed.next({
    feed: [{
      id: 'a-only',
      kind: 'speak',
      channel: 'voice',
      speaker: 'expert',
      text: 'secret A',
      ts_ms: 1,
    }],
  });
  feed.complete();
  await connecting;

  assert.deepEqual(harness.engine.feed(), []);
  assert.equal(harness.backendConnections.length, 0);
  assert.equal(harness.livekitOpenCalls(), 0);
  assert.equal(harness.engine.connectionState(), 'idle');
  harness.destroyRef.destroy();
});

test('a LiveKit connection created after A→B is immediately closed and never falls back', async () => {
  const lateLiveKit = deferred<RealtimeConnectionStub>();
  const harness = createHarness({
    feed$: of({ feed: [] }),
    livekitOpen: () => lateLiveKit.promise,
  });
  const connecting = harness.engine.connect('session-a', { transport: 'livekit' });
  await flushUntil(() => harness.livekitOpenCalls() === 1);

  harness.workspace.switchWorkspace();
  const connection = new RealtimeConnectionStub();
  lateLiveKit.resolve(connection);
  await connecting;

  assert.equal(connection.closeCalls, 1);
  assert.equal(harness.backendConnections.length, 0, 'stale LiveKit completion cannot open fallback WS');
  assert.equal(harness.engine.connectionState(), 'idle');
  harness.destroyRef.destroy();
});

test('a rejected LiveKit open after A→B cannot enter the backend fallback', async () => {
  const lateLiveKit = deferred<RealtimeConnectionStub>();
  const harness = createHarness({
    feed$: of({ feed: [] }),
    livekitOpen: () => lateLiveKit.promise,
  });
  const connecting = harness.engine.connect('session-a', { transport: 'livekit' });
  await flushUntil(() => harness.livekitOpenCalls() === 1);

  harness.workspace.switchWorkspace();
  lateLiveKit.reject(new Error('late A failure'));
  await connecting;

  assert.equal(harness.backendConnections.length, 0);
  assert.equal(harness.engine.lastError(), null);
  assert.equal(harness.engine.connectionState(), 'idle');
  harness.destroyRef.destroy();
});

test('workspace reset invalidates an in-flight finalize recovery before its HTTP POST fallback', async () => {
  const proposalList = new Subject<any>();
  const harness = createHarness({
    feed$: of({ feed: [] }),
    proposalList$: proposalList.asObservable(),
  });
  await harness.engine.connect('session-a', { transport: 'backend_ws' });
  assert.equal(harness.backendConnections.length, 1);

  const finalized = harness.engine.finalize();
  assert.equal(harness.backendConnections[0].captureFinishCalls, 1);
  harness.engine.disconnect();
  harness.workspace.switchWorkspace();
  proposalList.next({ proposals: [] });
  proposalList.complete();

  assert.equal(await finalized, null);
  assert.equal(harness.createProposalCalls(), 0, 'stale recovery must never POST under workspace B');
  assert.equal(harness.engine.proposal(), null);
  harness.destroyRef.destroy();
});

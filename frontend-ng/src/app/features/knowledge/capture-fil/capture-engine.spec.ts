import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { DestroyRef, Injector } from '@angular/core';
import { BehaviorSubject, NEVER, Subject, of, throwError, type Observable } from 'rxjs';
import { ApiService } from '@app/core/api.service';
import { CanonicalApiService } from '@app/core/canonical-api.service';
import { LiveKitConversationService } from '@app/core/livekit-conversation.service';
import { FR_DICT } from '@app/core/i18n.dict';
import { I18nService } from '@app/core/i18n.service';
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
  readonly publication$?: Observable<any>;
}

function createHarness(options: HarnessOptions) {
  const workspace = new WorkspaceStub();
  const destroyRef = new DestroyRefStub();
  const backendConnections: RealtimeConnectionStub[] = [];
  let livekitOpenCalls = 0;
  let createProposalCalls = 0;
  let publishCalls = 0;
  let reviewCalls = 0;
  const api = {
    getCaptureFeed: () => options.feed$,
    getCaptureHintQueue: () => of({ hints: [] }),
    listCaptureProposals: () => options.proposalList$ ?? of({ proposals: [] }),
    publishCaptureProposal: () => {
      publishCalls += 1;
      return options.publication$ ?? of(null);
    },
    reviewCaptureProposal: () => { reviewCalls += 1; return of(null); },
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
      // The real service opens a localStorage effect this bare injector has no
      // scheduler for; the engine only needs the FR lookup t() performs.
      {
        provide: I18nService,
        useValue: {
          t: (key: string) => (FR_DICT as Record<string, string>)[key] ?? key,
        },
      },
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
    publishCalls: () => publishCalls,
    reviewCalls: () => reviewCalls,
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

const retainedPublication = {
  document_id: 'doc-a', collection_slug: 'reviewed-knowledge', final_title: 'Reviewed report',
  export_urls: { raw_url: '/api/v1/documents/doc-a/raw?collection_name=reviewed-knowledge' },
};
function proposalFor(status: string) {
  return { id: 'proposal-a', session_id: 'session-a', status,
    proposal: { publication: retainedPublication } };
}

test('publication requires an explicit accepted state, never triggers review', async () => {
  for (const status of ['pending_review', 'changes_requested', 'rejected', '']) {
    const harness = createHarness({ feed$: of({ feed: [] }),
      proposalList$: of({ proposals: [proposalFor(status)] }) });
    harness.engine.setSession({ id: 'session-a', status: 'completed' });
    await harness.engine.loadProposal();
    assert.equal(harness.engine.publication(), null);
    assert.equal(await harness.engine.publish({}), null);
    assert.equal(harness.reviewCalls(), 0);
    assert.equal(harness.publishCalls(), 0);
    assert.ok(harness.engine.lastError());
    harness.destroyRef.destroy();
  }
});

test('a loaded publication restores its receipt and clears on session change', async () => {
  const harness = createHarness({ feed$: of({ feed: [] }),
    proposalList$: of({ proposals: [proposalFor('published')] }) });
  harness.engine.setSession({ id: 'session-a', status: 'completed' });
  await harness.engine.loadProposal();
  assert.equal(harness.engine.publication()?.document_id, 'doc-a');
  assert.equal(harness.engine.publication()?.collection, 'reviewed-knowledge');
  assert.equal((await harness.engine.publish({}))?.document_id, 'doc-a');
  assert.equal(harness.publishCalls(), 0);
  harness.engine.setSession({ id: 'session-b', status: 'completed' });
  assert.equal(harness.engine.publication(), null);
  assert.equal(harness.engine.proposalId(), null);
  harness.destroyRef.destroy();
});

test('a lost publication reply recovers the stored receipt without a second POST', async () => {
  const proposals = new BehaviorSubject({ proposals: [proposalFor('accepted')] });
  const harness = createHarness({ feed$: of({ feed: [] }), proposalList$: proposals,
    publication$: throwError(() => new Error('Connection lost')) });
  harness.engine.setSession({ id: 'session-a', status: 'completed' });
  await harness.engine.loadProposal();
  proposals.next({ proposals: [proposalFor('published')] });
  assert.equal((await harness.engine.publish({}))?.document_id, 'doc-a');
  assert.equal(harness.engine.lastError(), null);
  assert.equal(harness.publishCalls(), 1);
  assert.equal(harness.reviewCalls(), 0);
  harness.destroyRef.destroy();
});

test('late publication replies cannot restore another workspace receipt', async () => {
  const reply = new Subject<any>();
  const harness = createHarness({ feed$: of({ feed: [] }), publication$: reply,
    proposalList$: of({ proposals: [proposalFor('accepted')] }) });
  harness.engine.setSession({ id: 'session-a', status: 'completed' });
  await harness.engine.loadProposal();
  const publishing = harness.engine.publish({});
  harness.workspace.switchWorkspace();
  reply.next({ status: 'success', document_id: 'doc-a', collection: 'reviewed-knowledge' });
  reply.complete();
  assert.equal(await publishing, null);
  assert.equal(harness.engine.publication(), null);
  assert.equal(harness.engine.proposal(), null);
  assert.equal(harness.engine.lastError(), null);
  harness.destroyRef.destroy();
});

test('a proposal from another session cannot restore a publication', async () => {
  const harness = createHarness({ feed$: of({ feed: [] }),
    proposalList$: of({ proposals: [{ ...proposalFor('published'), session_id: 'session-other' }] }) });
  harness.engine.setSession({ id: 'session-a', status: 'completed' });
  assert.equal(await harness.engine.loadProposal(), null);
  assert.equal(harness.engine.publication(), null);
  assert.equal(harness.engine.proposalId(), null);
  harness.destroyRef.destroy();
});

test('a successful publication stores the canonical receipt without an implicit review', async () => {
  const harness = createHarness({ feed$: of({ feed: [] }),
    proposalList$: of({ proposals: [proposalFor('accepted')] }),
    publication$: of({ status: 'success', document_id: 'new-doc', collection: 'new-collection',
      export_urls: { preview_url: '/api/v1/documents/new-doc/rich-preview?collection_name=new-collection' } }) });
  harness.engine.setSession({ id: 'session-a', status: 'completed' });
  await harness.engine.loadProposal();
  const result = await harness.engine.publish({});
  assert.equal(result?.document_id, 'new-doc');
  assert.equal(harness.engine.proposal()?.status, 'published');
  assert.equal(harness.engine.proposal()?.proposal?.publication?.collection_slug, 'new-collection');
  assert.equal(harness.engine.publication()?.export_urls?.preview_url, result?.export_urls?.preview_url);
  assert.equal(harness.reviewCalls(), 0);
  assert.equal(harness.publishCalls(), 1);
  harness.destroyRef.destroy();
});

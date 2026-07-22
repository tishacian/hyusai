import '@angular/compiler';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { Injector } from '@angular/core';
import { Subject } from 'rxjs';
import type { Room as LiveKitRoom } from 'livekit-client';
import { ApiService } from './api.service';
import {
  LiveKitConversationConnection,
  LiveKitConversationService,
  WorkspaceChangedDuringTransportError,
  type LiveKitConfig,
  type LiveKitTokenResponse,
} from './livekit-conversation.service';
import {
  WorkspaceService,
  type WorkspaceContextTransition,
  type WorkspaceRequestScope,
} from './workspace.service';

class FakeRoom {
  readonly handlers = new Map<string, (...args: any[]) => void>();
  microphoneCalls: boolean[] = [];
  disconnectCalls = 0;
  publishCalls = 0;

  readonly localParticipant: {
    setMicrophoneEnabled: (enabled: boolean) => Promise<void>;
    publishData: () => Promise<void>;
  };

  constructor() {
    this.localParticipant = {
      setMicrophoneEnabled: async (enabled: boolean) => {
        this.microphoneCalls.push(enabled);
      },
      publishData: async () => {
        this.publishCalls += 1;
      },
    };
  }

  on(event: string, handler: (...args: any[]) => void): this {
    this.handlers.set(event, handler);
    return this;
  }

  async disconnect(): Promise<void> {
    this.disconnectCalls += 1;
  }
}

class WorkspaceStub {
  private slug = 'andritz';
  private epoch = 1;
  private readonly resetters = new Set<(transition: WorkspaceContextTransition) => void>();

  currentSlug = (): string => this.slug;

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
    this.slug = transition.nextSlug || '';
    this.epoch = transition.nextEpoch;
  }
}

test('LiveKit workspace invalidation suppresses queued data synchronously', async () => {
  const room = new FakeRoom();
  const token: LiveKitTokenResponse = {
    enabled: true,
    configured: true,
    url: 'wss://livekit.test',
    room_name: 'room-a',
    identity: 'participant-a',
    token: 'opaque',
    metadata: { agentium_session_id: 'session-a' },
  };
  const topics: LiveKitConfig['topics'] = {
    events: 'agentium.events',
    control: 'agentium.control',
    metrics: 'agentium.metrics',
    chat: 'agentium.chat',
  };
  let closed = 0;
  const connection = new LiveKitConversationConnection(
    room as unknown as LiveKitRoom,
    token,
    topics,
    { DataReceived: 'data', Disconnected: 'disconnected' },
    1,
    () => closed += 1,
  );
  const events: unknown[] = [];
  let completed = 0;
  connection.events$.subscribe({
    next: (event) => events.push(event),
    complete: () => completed += 1,
  });
  const staleDataHandler = room.handlers.get('data');
  const staleDisconnectHandler = room.handlers.get('disconnected');

  connection.invalidate();
  staleDataHandler?.(
    new TextEncoder().encode(JSON.stringify({ type: 'text.final', payload: { text: 'old' } })),
    null,
    1,
    topics.events,
  );
  staleDisconnectHandler?.('old-room-closed');
  await Promise.resolve();
  await Promise.resolve();

  assert.deepEqual(events, []);
  assert.equal(completed, 1);
  assert.equal(closed, 1);
  assert.deepEqual(room.microphoneCalls, [false]);
  assert.equal(room.disconnectCalls, 1);
  await connection.sendControl('loop.start');
  assert.equal(room.publishCalls, 0, 'invalidated connections cannot publish into the old room');
});

test('a rejected LiveKit await after A→B is surfaced as workspace cancellation', async () => {
  const workspace = new WorkspaceStub();
  const config = new Subject<LiveKitConfig>();
  const api = {
    get: () => config.asObservable(),
    post: () => {
      throw new Error('token request is not expected');
    },
  };
  const injector = Injector.create({
    providers: [
      LiveKitConversationService,
      { provide: ApiService, useValue: api },
      { provide: WorkspaceService, useValue: workspace },
    ],
  });

  const opening = injector.get(LiveKitConversationService).open('session-a');
  workspace.switchWorkspace();
  config.error(new Error('late config failure from workspace A'));

  await assert.rejects(
    opening,
    (error: unknown) => error instanceof WorkspaceChangedDuringTransportError,
  );
});

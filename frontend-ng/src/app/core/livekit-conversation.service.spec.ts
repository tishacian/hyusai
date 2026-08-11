import '@angular/compiler';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { Injector } from '@angular/core';
import { Subject, of, throwError } from 'rxjs';
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
  readonly published: { topic?: string; event: any }[] = [];

  readonly localParticipant: {
    setMicrophoneEnabled: (enabled: boolean) => Promise<void>;
    publishData: (bytes: Uint8Array, options?: { topic?: string }) => Promise<void>;
  };

  constructor() {
    this.localParticipant = {
      setMicrophoneEnabled: async (enabled: boolean) => {
        this.microphoneCalls.push(enabled);
      },
      publishData: async (bytes: Uint8Array, options?: { topic?: string }) => {
        this.publishCalls += 1;
        this.published.push({
          topic: options?.topic,
          event: JSON.parse(new TextDecoder().decode(bytes)),
        });
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

const TOKEN: LiveKitTokenResponse = {
  enabled: true,
  configured: true,
  url: 'wss://livekit.test',
  room_name: 'room-a',
  identity: 'participant-a',
  token: 'opaque',
  metadata: { agentium_session_id: 'session-a' },
};

const TOPICS: LiveKitConfig['topics'] = {
  events: 'agentium.events',
  control: 'agentium.control',
  metrics: 'agentium.metrics',
  chat: 'agentium.chat',
};

function connect(room: FakeRoom): LiveKitConversationConnection {
  return new LiveKitConversationConnection(
    room as unknown as LiveKitRoom,
    TOKEN,
    TOPICS,
    { DataReceived: 'data', Disconnected: 'disconnected' },
    1,
  );
}

test('session.start carries the mode the caller asked the room for', () => {
  // The gateway switches loops on this field and on nothing else, so losing it
  // between the open options and the control frame leaves a voice session that
  // transcribes and never answers.
  const room = new FakeRoom();
  connect(room).start({ mode: 'assistant', language: 'en' });

  const [frame] = room.published;
  assert.equal(frame.topic, TOPICS.control);
  assert.equal(frame.event.type, 'session.start');
  assert.equal(frame.event.payload.mode, 'assistant');
  assert.equal(frame.event.payload.transport, 'livekit');
});

test('a control frame with no dedicated helper travels with its payload intact', () => {
  // How the session context reaches the gateway: an event type the room knows
  // nothing about, forwarded by the sidecar exactly as it was published.
  const room = new FakeRoom();
  const frame = { seq: 0, total: 2, context_json: '{"service_catalog":' };
  void connect(room).sendControl('assistant.context', frame);

  assert.equal(room.published[0].topic, TOPICS.control);
  assert.equal(room.published[0].event.type, 'assistant.context');
  assert.deepEqual(room.published[0].event.payload, frame);
});

/** Push one data packet at the room the way the sidecar publishes it. */
function receive(room: FakeRoom, type: string, payload: Record<string, unknown>): void {
  room.handlers.get('data')?.(
    new TextEncoder().encode(JSON.stringify({ id: `gw-${type}`, type, payload })),
    null,
    1,
    TOPICS.events,
  );
}

test('a framed answer reaches the surface as one whole event', () => {
  // The gateway cuts the two large outbound events into ordered slices, because
  // one reliable data packet holds 15 KiB and a turn payload does not. The
  // rejoining happens here, at the transport, so no surface — and `audio.out` is
  // shared with Knowledge Capture — has to know that framing exists.
  const room = new FakeRoom();
  const events: any[] = [];
  connect(room).events$.subscribe((event) => events.push(event));

  const whole = { session_id: 'thread-1', answer: 'Réinitialisation lancée.', citations: [] };
  const raw = JSON.stringify(whole);
  const cut = Math.ceil(raw.length / 3);
  const slices = [raw.slice(0, cut), raw.slice(cut, cut * 2), raw.slice(cut * 2)];

  receive(room, 'assistant.answer', { seq: 0, total: 3, payload_json: slices[0] });
  receive(room, 'assistant.answer', { seq: 1, total: 3, payload_json: slices[1] });
  // Nothing is emitted while the payload is incomplete: half an answer rendered
  // is worse than a slow one.
  assert.deepEqual(events, []);

  receive(room, 'assistant.answer', { seq: 2, total: 3, payload_json: slices[2] });
  assert.equal(events.length, 1);
  assert.equal(events[0].type, 'assistant.answer');
  assert.deepEqual(events[0].payload, whole);
});

test('a one-frame payload takes the same path as a large one', () => {
  const room = new FakeRoom();
  const events: any[] = [];
  connect(room).events$.subscribe((event) => events.push(event));

  receive(room, 'audio.out', {
    seq: 0,
    total: 1,
    payload_json: JSON.stringify({ turn_id: 'turn-1', audio_base64: 'bXAz' }),
  });

  assert.equal(events.length, 1);
  assert.deepEqual(events[0].payload, { turn_id: 'turn-1', audio_base64: 'bXAz' });
});

test('an interrupted push is dropped rather than half-delivered', () => {
  const room = new FakeRoom();
  const events: any[] = [];
  connect(room).events$.subscribe((event) => events.push(event));

  // A gap, then a frame claiming to close a push that never started: both lanes
  // deliver in order, so either means the push was interrupted.
  receive(room, 'assistant.answer', { seq: 0, total: 3, payload_json: '{"answer":' });
  receive(room, 'assistant.answer', { seq: 2, total: 3, payload_json: '"x"}' });
  assert.deepEqual(events, []);

  // And the next complete push is delivered normally: a dropped payload does not
  // poison the room.
  receive(room, 'assistant.answer', {
    seq: 0,
    total: 1,
    payload_json: JSON.stringify({ session_id: 's', answer: 'ok' }),
  });
  assert.equal(events.length, 1);
  assert.deepEqual(events[0].payload, { session_id: 's', answer: 'ok' });
});

test('opening a room asks for its mode from the very first hop', async () => {
  // The mode is read by the token endpoint, the agent dispatch and the sidecar
  // before the gateway ever sees it. This pins the first of the three.
  const workspace = new WorkspaceStub();
  const bodies: any[] = [];
  const api = {
    get: () => of({
      enabled: true,
      configured: true,
      url: 'wss://livekit.test',
      transport: 'livekit',
      fallback_transport: 'backend_ws',
      room_ttl_seconds: 300,
      topics: TOPICS,
    } as LiveKitConfig),
    post: (_url: string, body: unknown) => {
      bodies.push(body);
      return throwError(() => new Error('stopped before the transport'));
    },
  };
  const injector = Injector.create({
    providers: [
      LiveKitConversationService,
      { provide: ApiService, useValue: api },
      { provide: WorkspaceService, useValue: workspace },
    ],
  });

  await assert.rejects(
    injector.get(LiveKitConversationService).open('session-a', {
      surface: 'nawa_assistant',
      mode: 'assistant',
    }),
  );

  assert.equal(bodies.length, 1);
  assert.equal(bodies[0].mode, 'assistant');
  assert.equal(bodies[0].surface, 'nawa_assistant');
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

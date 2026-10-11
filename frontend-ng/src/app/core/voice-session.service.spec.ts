import '@angular/compiler';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { Injector } from '@angular/core';
import { TokenStorageService } from './token-storage.service';
import { VoiceSessionConnection, VoiceSessionService } from './voice-session.service';
import { WorkspaceService, type WorkspaceContextTransition } from './workspace.service';

class WorkspaceStub {
  private resetter: ((transition: WorkspaceContextTransition) => void) | null = null;

  captureRequestScope() {
    return Object.freeze({ workspaceSlug: 'andritz', epoch: 3 });
  }

  registerContextReset(resetter: (transition: WorkspaceContextTransition) => void): () => void {
    this.resetter = resetter;
    return () => {
      this.resetter = null;
    };
  }

  reset(): void {
    this.resetter?.({
      previousSlug: 'andritz',
      nextSlug: 'sentinel-ci',
      previousEpoch: 3,
      nextEpoch: 4,
    });
  }
}

class FakeWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;

  readonly url: string;
  readonly frames: any[] = [];
  readyState = FakeWebSocket.CONNECTING;
  closeCalls = 0;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;

  constructor(url: string) {
    this.url = url;
  }

  send(frame: string): void {
    this.frames.push(JSON.parse(frame));
  }

  close(): void {
    this.closeCalls += 1;
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.();
  }
}

test('the direct WebSocket lane carries the assistant mode and its session context', () => {
  // The fallback lane talks to the same gateway with no sidecar in between, so
  // it has to be able to say the same two things: which loop to run, and what
  // context the surface owns. `WebSocket` is read for its readyState constants.
  const previousWebSocket = globalThis.WebSocket;
  Object.defineProperty(globalThis, 'WebSocket', { configurable: true, value: FakeWebSocket });
  try {
    const socket = new FakeWebSocket('wss://agentium.test/api/v1/voice/sessions/session-a');
    socket.readyState = FakeWebSocket.OPEN;
    const connection = new VoiceSessionConnection(socket as unknown as WebSocket);

    connection.start({ mode: 'assistant', language: 'en' });
    connection.sendControl('assistant.context', { seq: 0, total: 1, context_json: '{}' });

    assert.equal(socket.frames[0].type, 'session.start');
    assert.equal(socket.frames[0].payload.mode, 'assistant');
    assert.equal(socket.frames[1].type, 'assistant.context');
    assert.deepEqual(socket.frames[1].payload, { seq: 0, total: 1, context_json: '{}' });
  } finally {
    if (previousWebSocket) {
      Object.defineProperty(globalThis, 'WebSocket', { configurable: true, value: previousWebSocket });
    } else {
      Reflect.deleteProperty(globalThis, 'WebSocket');
    }
  }
});

test('the direct lane rejoins a framed answer exactly as the LiveKit lane does', () => {
  // The gateway frames `assistant.answer` and `audio.out` on every lane, not only
  // the one with a 15 KiB packet limit — one shape, so the code that rejoins them
  // is exercised by every answer instead of only by a large one. A surface that
  // falls back to this transport must therefore see the identical whole event.
  const previousWebSocket = globalThis.WebSocket;
  Object.defineProperty(globalThis, 'WebSocket', { configurable: true, value: FakeWebSocket });
  try {
    const socket = new FakeWebSocket('wss://agentium.test/api/v1/voice/sessions/session-a');
    socket.readyState = FakeWebSocket.OPEN;
    const connection = new VoiceSessionConnection(socket as unknown as WebSocket);
    const events: any[] = [];
    connection.events$.subscribe((event) => events.push(event));

    const whole = { turn_id: 'turn-1', content_type: 'audio/mpeg', audio_base64: 'bXAz' };
    const raw = JSON.stringify(whole);
    const cut = Math.ceil(raw.length / 2);
    const receive = (payload: Record<string, unknown>) =>
      socket.onmessage?.({ data: JSON.stringify({ id: 'gw', type: 'audio.out', payload }) });

    receive({ seq: 0, total: 2, payload_json: raw.slice(0, cut) });
    assert.deepEqual(events, []);
    receive({ seq: 1, total: 2, payload_json: raw.slice(cut) });

    assert.equal(events.length, 1);
    assert.equal(events[0].type, 'audio.out');
    assert.deepEqual(events[0].payload, whole);
  } finally {
    if (previousWebSocket) {
      Object.defineProperty(globalThis, 'WebSocket', { configurable: true, value: previousWebSocket });
    } else {
      Reflect.deleteProperty(globalThis, 'WebSocket');
    }
  }
});

test('voice WebSocket pins the captured workspace query and closes on switch', () => {
  const previousWindow = globalThis.window;
  const previousWebSocket = globalThis.WebSocket;
  const sockets: FakeWebSocket[] = [];
  class TrackingWebSocket extends FakeWebSocket {
    constructor(url: string) {
      super(url);
      sockets.push(this);
    }
  }
  Object.defineProperty(globalThis, 'window', {
    configurable: true,
    value: { location: { protocol: 'https:', host: 'agentium.test' } },
  });
  Object.defineProperty(globalThis, 'WebSocket', {
    configurable: true,
    value: TrackingWebSocket,
  });

  try {
    const workspace = new WorkspaceStub();
    const injector = Injector.create({
      providers: [
        VoiceSessionService,
        { provide: WorkspaceService, useValue: workspace },
        { provide: TokenStorageService, useValue: { getToken: () => 'Bearer token-a' } },
      ],
    });

    const connection = injector.get(VoiceSessionService).open('session/42');
    const events: unknown[] = [];
    let completed = 0;
    connection.events$.subscribe({
      next: (event) => events.push(event),
      complete: () => completed += 1,
    });

    assert.equal(sockets.length, 1);
    const url = new URL(sockets[0].url);
    assert.equal(url.protocol, 'wss:');
    assert.equal(url.pathname, '/api/v1/voice/sessions/session%2F42');
    assert.equal(url.searchParams.get('workspace_slug'), 'andritz');
    assert.equal(url.searchParams.get('token'), 'Bearer token-a');

    const staleMessageHandler = sockets[0].onmessage;
    const staleErrorHandler = sockets[0].onerror;
    workspace.reset();
    assert.equal(sockets[0].closeCalls, 1);
    staleMessageHandler?.({ data: JSON.stringify({ type: 'text.final', payload: { text: 'old' } }) });
    staleErrorHandler?.();
    assert.deepEqual(events, [], 'queued callbacks from the old socket are suppressed');
    assert.equal(completed, 1, 'workspace invalidation completes the connection exactly once');
  } finally {
    if (previousWindow) {
      Object.defineProperty(globalThis, 'window', { configurable: true, value: previousWindow });
    } else {
      Reflect.deleteProperty(globalThis, 'window');
    }
    if (previousWebSocket) {
      Object.defineProperty(globalThis, 'WebSocket', { configurable: true, value: previousWebSocket });
    } else {
      Reflect.deleteProperty(globalThis, 'WebSocket');
    }
  }
});

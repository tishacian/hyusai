import test from 'node:test';
import assert from 'node:assert/strict';
import { Readable } from 'node:stream';
import { createAgentiumLiveKitAgentServer, handleControlEvent, isAudioTrack, startSession } from './agent.mjs';

test('isAudioTrack recognizes the numeric @livekit/rtc-node enum (KIND_AUDIO=1)', () => {
  // Regression: rtc-node delivers kind/source as numeric protobuf enums; the mic
  // track arrived as { kind: 1, source: 2 } and was misclassified as non-audio,
  // so the realtime audio stream never started.
  assert.equal(isAudioTrack({ kind: 1, source: 2 }, { kind: 1, source: 2 }), true);
  assert.equal(isAudioTrack({ kind: 1 }, {}), true);
  // Video track (KIND_VIDEO=2 / SOURCE_CAMERA=1) must stay false.
  assert.equal(isAudioTrack({ kind: 2, source: 1 }, { kind: 2, source: 1 }), false);
  // String-shaped fallback still works.
  assert.equal(isAudioTrack({ kind: 'audio' }, {}), true);
  assert.equal(isAudioTrack({ kind: 'video' }, { source: 'camera' }), false);
  // Honors SDK constants when provided.
  assert.equal(
    isAudioTrack({ kind: 7 }, {}, { TrackKind: { KIND_AUDIO: 7 }, TrackSource: { SOURCE_MICROPHONE: 9 } }),
    true,
  );
});

function request(server, method, url, body = null) {
  return new Promise((resolve, reject) => {
    const handler = server.listeners('request')[0];
    const payload = body === null ? null : Buffer.from(JSON.stringify(body));
    const req = new Readable({
      read() {
        if (payload) this.push(payload);
        this.push(null);
      },
    });
    req.method = method;
    req.url = url;
    const res = {
      status: 0,
      headers: {},
      writeHead(status, headers) {
        this.status = status;
        this.headers = headers;
      },
      end(payload) {
        resolve({ status: this.status, headers: this.headers, body: JSON.parse(String(payload || '{}')) });
      },
    };
    Promise.resolve(handler(req, res)).catch(reject);
  });
}

function waitFor(predicate, timeoutMs = 500) {
  const startedAt = Date.now();
  return new Promise((resolve, reject) => {
    const tick = () => {
      try {
        const value = predicate();
        if (value) {
          resolve(value);
          return;
        }
      } catch (error) {
        reject(error);
        return;
      }
      if (Date.now() - startedAt > timeoutMs) {
        reject(new Error('Timed out waiting for condition'));
        return;
      }
      setTimeout(tick, 5);
    };
    tick();
  });
}

test('sidecar healthz starts without importing LiveKit RTC runtime', async () => {
  const server = createAgentiumLiveKitAgentServer();
  const response = await request(server, 'GET', '/healthz');

  assert.equal(response.status, 200);
  assert.deepEqual(response.body, { status: 'ok', active_sessions: 0 });
});

test('sidecar dispatch validation fails cleanly without creating a session', async () => {
  const server = createAgentiumLiveKitAgentServer();
  const response = await request(server, 'POST', '/dispatch', {
    session_id: 'session-without-room',
  });
  const health = await request(server, 'GET', '/healthz');

  assert.equal(response.status, 500);
  assert.equal(response.body.status, 'error');
  assert.match(response.body.message, /requires session_id, room_name, livekit_url, and token/);
  assert.deepEqual(health.body, { status: 'ok', active_sessions: 0 });
});

test('sidecar removes pending session when LiveKit room connect fails', async () => {
  let connectAttempts = 0;

  class FailingRoom {
    localParticipant = {
      async publishData() {},
    };

    on() {
      return this;
    }

    async connect() {
      connectAttempts += 1;
      throw new Error('simulated livekit connect failure');
    }

    async disconnect() {}
  }

  await assert.rejects(
    () =>
      startSession(
        {
          session_id: 'session-connect-fails',
          room_name: 'agentium-room',
          token: 'token',
          livekit_url: 'ws://agentium-livekit:7880',
        },
        {
          livekitModule: {
            Room: FailingRoom,
            RoomEvent: {
              DataReceived: 'data',
              TrackSubscribed: 'track',
              Disconnected: 'disconnected',
            },
          },
          connectRetry: {
            attempts: 2,
            retryMs: 1,
            maxRetryMs: 1,
          },
        },
      ),
    /simulated livekit connect failure/,
  );

  assert.equal(connectAttempts, 2);
  const server = createAgentiumLiveKitAgentServer();
  const health = await request(server, 'GET', '/healthz');
  assert.deepEqual(health.body, { status: 'ok', active_sessions: 0 });
});

test('sidecar retries LiveKit room connect before accepting a dispatch', async () => {
  const published = [];
  let connectAttempts = 0;
  let disconnects = 0;

  class FlakyRoom {
    localParticipant = {
      async publishData(payload, options) {
        published.push({
          event: JSON.parse(new TextDecoder().decode(payload)),
          options,
        });
      },
    };

    on() {
      return this;
    }

    async connect() {
      connectAttempts += 1;
      if (connectAttempts < 3) {
        throw new Error('livekit not ready yet');
      }
    }

    async disconnect() {
      disconnects += 1;
    }
  }

  const result = await startSession(
    {
      session_id: 'session-connect-retry',
      room_name: 'agentium-room',
      token: 'token',
      livekit_url: 'ws://agentium-livekit:7880',
    },
    {
      livekitModule: {
        Room: FlakyRoom,
        RoomEvent: {
          DataReceived: 'data',
          TrackSubscribed: 'track',
          Disconnected: 'disconnected',
        },
      },
      connectRetry: {
        attempts: 3,
        retryMs: 1,
        maxRetryMs: 1,
      },
    },
  );

  assert.equal(result.reused, false);
  assert.equal(result.connect_attempts, 3);
  assert.equal(connectAttempts, 3);
  const ready = published.find((item) => item.event.type === 'session.ready');
  assert.equal(ready.event.payload.audio_bridge, 'media_observer_ready');
  assert.equal(ready.event.payload.connect_attempts, 3);

  const server = createAgentiumLiveKitAgentServer();
  const shutdown = await request(server, 'POST', '/shutdown-session', { session_id: 'session-connect-retry' });
  const health = await request(server, 'GET', '/healthz');

  assert.equal(shutdown.status, 200);
  assert.equal(disconnects, 1);
  assert.deepEqual(health.body, { status: 'ok', active_sessions: 0 });
});

test('phase 1 sidecar bridge relays a LiveKit audio endpoint through the voice gateway', async () => {
  const published = [];
  const gatewayMessages = [];
  const topics = {
    events: 'agentium.voice.event',
    control: 'agentium.voice.control',
    metrics: 'agentium.voice.metric',
    chat: 'agentium.chat.event',
  };
  let lastRoom = null;
  let disconnects = 0;

  class FakeWebSocket {
    static CONNECTING = 0;
    static OPEN = 1;
    static CLOSED = 3;
    static instances = [];

    constructor(url) {
      this.url = url;
      this.readyState = FakeWebSocket.CONNECTING;
      this.listeners = new Map();
      FakeWebSocket.instances.push(this);
      setTimeout(() => {
        this.readyState = FakeWebSocket.OPEN;
        this.dispatch('open', {});
      }, 0);
    }

    addEventListener(type, callback, options = {}) {
      const listeners = this.listeners.get(type) || [];
      listeners.push({ callback, once: Boolean(options.once) });
      this.listeners.set(type, listeners);
    }

    dispatch(type, event) {
      const listeners = [...(this.listeners.get(type) || [])];
      for (const listener of listeners) {
        listener.callback(event);
      }
      this.listeners.set(
        type,
        (this.listeners.get(type) || []).filter((listener) => !listener.once),
      );
    }

    send(message) {
      const event = JSON.parse(message);
      gatewayMessages.push(event);
      if (event.type === 'session.start') {
        this.emitGatewayEvent('session.ready', { runtime: 'cascade_openai', transport: 'livekit' });
      }
      if (event.type === 'audio.endpoint') {
        this.emitGatewayEvent('text.partial', { turn_id: 'turn-p1', text: 'début capté' });
        this.emitGatewayEvent('text.final', { turn_id: 'turn-p1', text: 'début capté final' });
        this.emitGatewayEvent('conversation.step', {
          turn_id: 'turn-p1',
          intent: 'capture_fact',
          action_taken: 'proposal_updated',
          proposal: { id: 'proposal-p1', title: 'Carte générée' },
        });
      }
    }

    emitGatewayEvent(type, payload) {
      this.dispatch('message', {
        data: JSON.stringify({
          id: `gw-${type}`,
          session_id: 'session-p1',
          type,
          ts_ms: Date.now(),
          sequence: 1,
          payload,
        }),
      });
    }

    close() {
      this.readyState = FakeWebSocket.CLOSED;
      this.dispatch('close', {});
    }
  }

  class FakeRoom {
    constructor() {
      this.handlers = new Map();
      this.localParticipant = {
        async publishData(payload, options) {
          published.push({
            event: JSON.parse(new TextDecoder().decode(payload)),
            options,
          });
        },
      };
      lastRoom = this;
    }

    on(event, handler) {
      this.handlers.set(event, handler);
      return this;
    }

    async connect() {}

    async disconnect() {
      disconnects += 1;
      this.handlers.get('disconnected')?.();
    }

    emit(event, ...args) {
      return this.handlers.get(event)?.(...args);
    }
  }

  class FakeAudioStream {
    constructor(track) {
      this.frames = track.frames || [];
    }

    async *[Symbol.asyncIterator]() {
      for (const frame of this.frames) {
        await Promise.resolve();
        yield frame;
      }
    }
  }

  const result = await startSession(
    {
      session_id: 'session-p1',
      room_name: 'agentium-room-p1',
      token: 'token',
      livekit_url: 'ws://agentium-livekit:7880',
      agent_identity: 'agent-p1',
      destination_identity: 'expert-1',
      topics,
      voice_gateway: {
        url: 'ws://agentium-backend:8000/api/v1/voice/sessions',
        token: 'bridge-token',
        workspace_slug: 'andritz',
        session_start: { runtime: 'cascade_openai', mode: 'conversation_only' },
      },
    },
    {
      WebSocketClass: FakeWebSocket,
      livekitModule: {
        Room: FakeRoom,
        AudioStream: FakeAudioStream,
        RoomEvent: {
          DataReceived: 'data',
          TrackSubscribed: 'track',
          Disconnected: 'disconnected',
        },
      },
      connectRetry: {
        attempts: 1,
        retryMs: 0,
        maxRetryMs: 0,
      },
    },
  );

  assert.equal(result.mode, 'voice_gateway_bridge');
  assert.equal(FakeWebSocket.instances.length, 1);
  assert.match(FakeWebSocket.instances[0].url, /\/api\/v1\/voice\/sessions\/session-p1\?/);
  assert.match(FakeWebSocket.instances[0].url, /token=bridge-token/);
  assert.equal(gatewayMessages[0].type, 'session.start');
  assert.equal(gatewayMessages[0].payload.transport, 'livekit');

  const ready = published.find((item) => item.event.type === 'session.ready' && item.event.payload.agent_identity === 'agent-p1');
  assert.equal(ready.event.payload.audio_bridge, 'voice_gateway_ready');
  assert.deepEqual(ready.options.destination_identities, ['expert-1']);

  lastRoom.emit(
    'track',
    {
      kind: 'audio',
      frames: [{ data: new Int16Array([1, 2, 3, 4]), sampleRate: 8000, channels: 1 }],
    },
    { sid: 'TR_1', name: 'micro' },
    { identity: 'expert-1' },
  );
  await waitFor(() => published.find((item) => item.event.payload?.metric === 'livekit_audio_frames_seen'));

  await lastRoom.emit(
    'data',
    new TextEncoder().encode(
      JSON.stringify({
        type: 'audio.endpoint',
        payload: { turn_id: 'turn-p1', reason: 'manual_stop' },
      }),
    ),
    { identity: 'expert-1' },
    0,
    topics.control,
  );

  await waitFor(() => published.find((item) => item.event.type === 'conversation.step'));

  const frame = gatewayMessages.find((item) => item.type === 'audio.frame');
  const endpoint = gatewayMessages.find((item) => item.type === 'audio.endpoint');
  assert.equal(frame.payload.turn_id, 'turn-p1');
  assert.equal(frame.payload.content_type, 'audio/wav');
  assert.equal(frame.payload.incremental_transcription, false);
  assert.equal(Buffer.from(frame.payload.bytes_b64, 'base64').toString('ascii', 0, 4), 'RIFF');
  assert.equal(endpoint.payload.reason, 'manual_stop');

  const relayedTypes = published.map((item) => item.event.type);
  assert.ok(relayedTypes.includes('text.partial'));
  assert.ok(relayedTypes.includes('text.final'));
  assert.ok(relayedTypes.includes('conversation.step'));
  const conversationStep = published.find((item) => item.event.type === 'conversation.step');
  assert.equal(conversationStep.options.topic, topics.events);
  assert.deepEqual(conversationStep.options.destination_identities, ['expert-1']);
  assert.equal(conversationStep.event.payload.proposal.id, 'proposal-p1');

  await lastRoom.emit(
    'data',
    new TextEncoder().encode(JSON.stringify({ type: 'session.close', payload: { reason: 'user_stop' } })),
    { identity: 'expert-1' },
    0,
    topics.control,
  );
  assert.equal(gatewayMessages.at(-1).type, 'session.close');
  assert.equal(disconnects, 1);

  const server = createAgentiumLiveKitAgentServer();
  const health = await request(server, 'GET', '/healthz');
  assert.deepEqual(health.body, { status: 'ok', active_sessions: 0 });
});

test('sidecar does not forward empty audio endpoints to the voice gateway', async () => {
  const published = [];
  const gatewayMessages = [];
  const topics = {
    events: 'agentium.voice.event',
    control: 'agentium.voice.control',
    metrics: 'agentium.voice.metric',
    chat: 'agentium.chat.event',
  };
  const session = {
    info: { session_id: 'session-empty-audio' },
    topics,
    destinationIdentity: 'expert-1',
    voiceGateway: {
      open: true,
      queue: [],
      socket: {
        readyState: WebSocket.OPEN,
        send(message) {
          gatewayMessages.push(JSON.parse(message));
        },
      },
    },
    room: {
      localParticipant: {
        async publishData(payload, options) {
          published.push({
            event: JSON.parse(new TextDecoder().decode(payload)),
            options,
          });
        },
      },
    },
    audio: {
      chunks: [],
      bytes: 0,
      frameCount: 0,
      sampleRate: 48000,
      channels: 1,
      startedAt: null,
      overflow: false,
    },
  };

  await handleControlEvent(
    session,
    { type: 'audio.endpoint', payload: { reason: 'silence' } },
    { identity: 'expert-1' },
    0,
  );

  const metrics = published.map((item) => item.event.payload.metric).filter(Boolean);
  assert.deepEqual(gatewayMessages, []);
  assert.deepEqual(
    metrics,
    ['livekit_control_event_received', 'livekit_audio_endpoint_without_audio'],
  );
  assert.equal(published[0].options.topic, topics.metrics);
  assert.deepEqual(published[0].options.destination_identities, ['expert-1']);
  assert.equal(published[0].options.destinationIdentities, undefined);
  assert.equal(published[1].options.topic, topics.metrics);
  assert.deepEqual(published[1].options.destination_identities, ['expert-1']);
});

test('sidecar relays a control event it knows nothing about, payload untouched', async () => {
  // How the session context reaches the gateway. `session.start` is rebuilt
  // here from a fixed whitelist, so a field added to it would be dropped; the
  // generic relay below is not filtered, which is why the context travels as
  // its own event instead. Asserted on both lanes: the realtime one returns
  // early, and forgetting the relay there would break voice on exactly the
  // deployment that runs it.
  for (const realtimeSttConfig of [null, { model: 'gpt-realtime-whisper' }]) {
    const published = [];
    const gatewayMessages = [];
    const topics = {
      events: 'agentium.voice.event',
      control: 'agentium.voice.control',
      metrics: 'agentium.voice.metric',
      chat: 'agentium.chat.event',
    };
    const frame = { seq: 1, total: 2, context_json: '{"service_catalog":[{"slug":"vpn-access"}]}' };
    const session = {
      info: { session_id: 'session-assistant-context' },
      topics,
      destinationIdentity: 'expert-1',
      realtimeSttConfig,
      voiceGateway: {
        open: true,
        queue: [],
        socket: {
          readyState: WebSocket.OPEN,
          send(message) {
            gatewayMessages.push(JSON.parse(message));
          },
        },
      },
      room: {
        localParticipant: {
          async publishData(payload, options) {
            published.push({ event: JSON.parse(new TextDecoder().decode(payload)), options });
          },
        },
      },
      audio: {
        chunks: [],
        bytes: 0,
        frameCount: 0,
        browserFrameCount: 0,
        sampleRate: 48000,
        channels: 1,
        startedAt: null,
        overflow: false,
      },
    };

    await handleControlEvent(
      session,
      { type: 'assistant.context', payload: frame },
      { identity: 'expert-1' },
      0,
    );

    assert.equal(gatewayMessages.length, 1);
    assert.equal(gatewayMessages[0].type, 'assistant.context');
    assert.deepEqual(gatewayMessages[0].payload, frame);
    assert.equal(published[0].event.payload.metric, 'livekit_control_event_received');
    assert.equal(published[0].event.payload.control_type, 'assistant.context');
  }
});

test('sidecar forwards browser MediaRecorder frames through the voice gateway', async () => {
  const published = [];
  const gatewayMessages = [];
  const topics = {
    events: 'agentium.voice.event',
    control: 'agentium.voice.control',
    metrics: 'agentium.voice.metric',
    chat: 'agentium.chat.event',
  };
  const browserChunk = Buffer.from('webm-fragment').toString('base64');
  const session = {
    info: { session_id: 'session-browser-audio' },
    topics,
    destinationIdentity: 'expert-1',
    voiceGateway: {
      open: true,
      queue: [],
      socket: {
        readyState: WebSocket.OPEN,
        send(message) {
          gatewayMessages.push(JSON.parse(message));
        },
      },
    },
    room: {
      localParticipant: {
        async publishData(payload, options) {
          published.push({
            event: JSON.parse(new TextDecoder().decode(payload)),
            options,
          });
        },
      },
    },
    audio: {
      chunks: [Buffer.from([0x01, 0x00])],
      bytes: 2,
      frameCount: 1,
      browserFrameCount: 0,
      sampleRate: 8000,
      channels: 1,
      startedAt: Date.now() - 40,
      overflow: false,
    },
  };

  await handleControlEvent(
    session,
    {
      type: 'audio.frame',
      payload: {
        bytes_b64: browserChunk,
        turn_id: 'turn-browser',
        content_type: 'audio/webm',
      },
    },
    { identity: 'expert-1' },
    0,
  );
  await handleControlEvent(
    session,
    { type: 'audio.endpoint', payload: { turn_id: 'turn-browser', reason: 'manual_stop' } },
    { identity: 'expert-1' },
    0,
  );

  assert.equal(gatewayMessages.length, 2);
  assert.equal(gatewayMessages[0].type, 'audio.frame');
  assert.equal(gatewayMessages[0].payload.bytes_b64, browserChunk);
  assert.equal(gatewayMessages[0].payload.content_type, 'audio/webm');
  assert.equal(gatewayMessages[0].payload.livekit_browser_frame_count, 1);
  assert.equal(gatewayMessages[1].type, 'audio.endpoint');
  assert.equal(gatewayMessages[1].payload.reason, 'manual_stop');
  assert.equal(session.audio.bytes, 0);
  assert.equal(session.audio.browserFrameCount, 0);
  const metrics = published.map((item) => item.event.payload.metric).filter(Boolean);
  assert.deepEqual(metrics, [
    'livekit_control_event_received',
    'livekit_browser_audio_frames_forwarded',
    'livekit_control_event_received',
    'livekit_browser_audio_endpoint_forwarded',
  ]);
});

test('sidecar flushes buffered audio as wav before forwarding endpoint', async () => {
  const gatewayMessages = [];
  const topics = {
    events: 'agentium.voice.event',
    control: 'agentium.voice.control',
    metrics: 'agentium.voice.metric',
    chat: 'agentium.chat.event',
  };
  const session = {
    info: { session_id: 'session-audio-flush' },
    topics,
    destinationIdentity: 'expert-1',
    voiceGateway: {
      open: true,
      queue: [],
      socket: {
        readyState: WebSocket.OPEN,
        send(message) {
          gatewayMessages.push(JSON.parse(message));
        },
      },
    },
    room: {
      localParticipant: {
        async publishData() {},
      },
    },
    audio: {
      chunks: [Buffer.from([0x01, 0x00, 0xff, 0x7f])],
      bytes: 4,
      frameCount: 1,
      sampleRate: 8000,
      channels: 1,
      startedAt: Date.now() - 40,
      overflow: false,
    },
  };

  await handleControlEvent(
    session,
    {
      type: 'audio.endpoint',
      payload: {
        turn_id: 'turn-1',
        question_id: 'question-1',
        reason: 'manual_stop',
      },
    },
    { identity: 'expert-1' },
    0,
  );

  assert.equal(gatewayMessages.length, 2);
  assert.equal(gatewayMessages[0].type, 'audio.frame');
  assert.equal(gatewayMessages[0].payload.turn_id, 'turn-1');
  assert.equal(gatewayMessages[0].payload.question_id, 'question-1');
  assert.equal(gatewayMessages[0].payload.content_type, 'audio/wav');
  assert.equal(gatewayMessages[0].payload.incremental_transcription, false);
  const wav = Buffer.from(gatewayMessages[0].payload.bytes_b64, 'base64');
  assert.equal(wav.toString('ascii', 0, 4), 'RIFF');
  assert.equal(wav.toString('ascii', 8, 12), 'WAVE');
  assert.equal(wav.readUInt32LE(24), 8000);
  assert.equal(wav.readUInt32LE(40), 4);
  assert.equal(gatewayMessages[1].type, 'audio.endpoint');
  assert.equal(gatewayMessages[1].payload.reason, 'manual_stop');
  assert.equal(session.audio.bytes, 0);
  assert.deepEqual(session.audio.chunks, []);
});

test('sidecar resets buffered audio on barge-in before forwarding control', async () => {
  const gatewayMessages = [];
  const published = [];
  const session = {
    info: { session_id: 'session-barge-reset' },
    topics: {
      events: 'agentium.voice.event',
      control: 'agentium.voice.control',
      metrics: 'agentium.voice.metric',
      chat: 'agentium.chat.event',
    },
    destinationIdentity: 'expert-1',
    voiceGateway: {
      open: true,
      queue: [],
      socket: {
        readyState: WebSocket.OPEN,
        send(message) {
          gatewayMessages.push(JSON.parse(message));
        },
      },
    },
    room: {
      localParticipant: {
        async publishData(payload, options) {
          published.push({
            event: JSON.parse(new TextDecoder().decode(payload)),
            options,
          });
        },
      },
    },
    audio: {
      chunks: [Buffer.from([0x01, 0x00, 0xff, 0x7f])],
      bytes: 4,
      frameCount: 1,
      sampleRate: 8000,
      channels: 1,
      startedAt: Date.now() - 40,
      overflow: false,
    },
  };

  await handleControlEvent(
    session,
    { type: 'barge_in', payload: { prompt_event_id: 'prompt-1' } },
    { identity: 'expert-1' },
    0,
  );

  assert.equal(session.audio.bytes, 0);
  assert.deepEqual(session.audio.chunks, []);
  assert.equal(session.audio.frameCount, 0);
  assert.equal(gatewayMessages.length, 1);
  assert.equal(gatewayMessages[0].type, 'barge_in');
  assert.equal(gatewayMessages[0].payload.prompt_event_id, 'prompt-1');
  const metrics = published.map((item) => item.event.payload.metric).filter(Boolean);
  assert.deepEqual(metrics, ['livekit_control_event_received', 'livekit_barge_in_audio_reset']);
  assert.equal(published[1].event.payload.audio_bytes_before_reset, 4);
  assert.equal(published[1].event.payload.audio_frame_count_before_reset, 1);
  assert.equal(published[1].event.payload.prompt_event_id, 'prompt-1');
  assert.deepEqual(published[1].options.destination_identities, ['expert-1']);
});

test('sidecar forwards session close then disconnects room', async () => {
  const gatewayMessages = [];
  const disconnects = [];
  const session = {
    info: { session_id: 'session-close' },
    topics: {
      events: 'agentium.voice.event',
      control: 'agentium.voice.control',
      metrics: 'agentium.voice.metric',
      chat: 'agentium.chat.event',
    },
    destinationIdentity: 'expert-1',
    voiceGateway: {
      open: true,
      queue: [],
      socket: {
        readyState: WebSocket.OPEN,
        send(message) {
          gatewayMessages.push(JSON.parse(message));
        },
      },
    },
    room: {
      localParticipant: {
        async publishData() {},
      },
      async disconnect(...args) {
        disconnects.push(args);
      },
    },
    audio: {
      chunks: [],
      bytes: 0,
      frameCount: 0,
      sampleRate: 48000,
      channels: 1,
      startedAt: null,
      overflow: false,
    },
  };

  await handleControlEvent(
    session,
    { type: 'session.close', payload: { reason: 'user_stop' } },
    { identity: 'expert-1' },
    0,
  );

  assert.equal(gatewayMessages.length, 1);
  assert.equal(gatewayMessages[0].type, 'session.close');
  assert.equal(gatewayMessages[0].payload.reason, 'user_stop');
  assert.deepEqual(disconnects, [[]]);
});

/**
 * The ceiling the whole framing exists for. A LiveKit reliable data packet is
 * capped at 15 KiB, and this sidecar republishes every gateway event as exactly
 * one packet — it never splits or repackages anything.
 *
 * Which is why the two large outbound events are cut up on the gateway side, and
 * why this is the test that matters: everything else about the assistant lane is
 * verified against a fake WebSocket, and framing that is never weighed at the
 * real transport would be framing on trust. Here the bytes measured are the
 * bytes `publishData` is handed.
 */
const LIVEKIT_DATA_PACKET_MAX_BYTES = 15 * 1024;

test('the sidecar publishes each assistant frame inside the LiveKit packet ceiling', async () => {
  const published = [];
  const topics = {
    events: 'agentium.voice.event',
    control: 'agentium.voice.control',
    metrics: 'agentium.voice.metric',
    chat: 'agentium.chat.event',
  };
  let gateway = null;

  class FakeWebSocket {
    static OPEN = 1;

    constructor(url) {
      this.url = url;
      this.readyState = FakeWebSocket.OPEN;
      this.listeners = new Map();
      gateway = this;
      setTimeout(() => this.dispatch('open', {}), 0);
    }

    addEventListener(type, callback) {
      const listeners = this.listeners.get(type) || [];
      listeners.push(callback);
      this.listeners.set(type, listeners);
    }

    dispatch(type, event) {
      for (const callback of [...(this.listeners.get(type) || [])]) callback(event);
    }

    send() {}

    close() {
      this.readyState = 3;
      this.dispatch('close', {});
    }

    /** One gateway event, as the backend's `_send` puts it on the wire. */
    async emit(type, payload) {
      const listeners = [...(this.listeners.get('message') || [])];
      for (const callback of listeners) {
        await callback({
          data: JSON.stringify({
            id: `gw-${type}-${payload.seq ?? 0}`,
            session_id: 'session-frames',
            type,
            ts_ms: Date.now(),
            sequence: 1,
            payload,
          }),
        });
      }
    }
  }

  class FakeRoom {
    constructor() {
      this.handlers = new Map();
      this.localParticipant = {
        async publishData(bytes, options) {
          published.push({ bytes, options, event: JSON.parse(new TextDecoder().decode(bytes)) });
        },
      };
    }

    on(event, handler) {
      this.handlers.set(event, handler);
      return this;
    }

    async connect() {}

    async disconnect() {
      this.handlers.get('disconnected')?.();
    }
  }

  await startSession(
    {
      session_id: 'session-frames',
      room_name: 'agentium-room-frames',
      token: 'token',
      livekit_url: 'ws://agentium-livekit:7880',
      topics,
      destination_identity: 'requester-1',
      voice_gateway: {
        url: 'ws://agentium-backend:8000/api/v1/voice/sessions',
        token: 'bridge-token',
        session_start: { runtime: 'cascade_openai', mode: 'assistant' },
      },
    },
    {
      WebSocketClass: FakeWebSocket,
      livekitModule: {
        Room: FakeRoom,
        RoomEvent: { DataReceived: 'data', TrackSubscribed: 'track', Disconnected: 'disconnected' },
      },
      connectRetry: { attempts: 1, retryMs: 0, maxRetryMs: 0 },
    },
  );

  // What the audio half of an answer weighs: ~45 s of speech, which is what the
  // gateway's 600-character cap synthesizes to, base64-encoded.
  const audio = Buffer.alloc(180_000, 0x64).toString('base64');
  const whole = { turn_id: 'turn-1', content_type: 'audio/mpeg', audio_base64: audio };

  // Act one — why the frames exist. Published whole, this is one packet, and it
  // is far past the ceiling. The sidecar does not save anyone here: it relays
  // what it is given.
  await gateway.emit('audio.out', whole);
  const unframed = published.at(-1);
  assert.equal(unframed.event.type, 'audio.out');
  assert.ok(
    unframed.bytes.byteLength > LIVEKIT_DATA_PACKET_MAX_BYTES,
    `a whole audio.out is ${unframed.bytes.byteLength} bytes`,
  );

  // Act two — the frames the gateway sends instead. Six kilobytes of payload
  // each, which is what `_OUTBOUND_FRAME_BYTES` cuts on.
  const raw = JSON.stringify(whole);
  const slices = [];
  for (let at = 0; at < raw.length; at += 6 * 1024) slices.push(raw.slice(at, at + 6 * 1024));
  const before = published.length;
  for (const [seq, payload_json] of slices.entries()) {
    await gateway.emit('audio.out', { seq, total: slices.length, payload_json });
  }

  const frames = published.slice(before);
  assert.equal(frames.length, slices.length);
  assert.ok(frames.length > 1, 'the payload under test fits in one frame');
  for (const frame of frames) {
    assert.ok(
      frame.bytes.byteLength <= LIVEKIT_DATA_PACKET_MAX_BYTES,
      `frame ${frame.event.payload.seq} is ${frame.bytes.byteLength} bytes`,
    );
    // Relayed on the event topic, to the participant that asked for the room,
    // and reliably — ordered delivery is what makes a plain append safe.
    assert.equal(frame.options.topic, topics.events);
    assert.deepEqual(frame.options.destination_identities, ['requester-1']);
    assert.equal(frame.options.reliable, true);
  }
  // And the frames the browser receives rejoin into the payload the gateway
  // sent, byte for byte — the sidecar neither re-encodes nor re-cuts them.
  assert.deepEqual(
    JSON.parse(frames.map((frame) => frame.event.payload.payload_json).join('')),
    whole,
  );

  await gateway.emit('session.close', { reason: 'test_done' });
  const server = createAgentiumLiveKitAgentServer();
  const health = await request(server, 'POST', '/shutdown-session', { session_id: 'session-frames' });
  assert.equal(health.status, 200);
});

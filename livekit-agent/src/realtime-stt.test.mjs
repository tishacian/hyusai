import test from 'node:test';
import assert from 'node:assert/strict';
import { resamplePcm16ToMono } from './bridge-utils.mjs';
import { RealtimeTranscriber } from './realtime-stt.mjs';
import { handleControlEvent, maybeStartRealtimeStt, startSession } from './agent.mjs';

class FakeOpenAIWebSocket {
  static instances = [];

  constructor(url, options) {
    this.url = url;
    this.options = options;
    this.sent = [];
    this.listeners = new Map();
    this.readyState = 0;
    FakeOpenAIWebSocket.instances.push(this);
  }

  addEventListener(type, callback, options = {}) {
    const list = this.listeners.get(type) || [];
    list.push({ callback, once: Boolean(options.once) });
    this.listeners.set(type, list);
  }

  dispatch(type, event) {
    for (const listener of [...(this.listeners.get(type) || [])]) {
      listener.callback(event);
    }
    this.listeners.set(type, (this.listeners.get(type) || []).filter((l) => !l.once));
  }

  send(message) {
    this.sent.push(JSON.parse(message));
  }

  fireOpen() {
    this.readyState = 1;
    this.dispatch('open', {});
  }

  fireMessage(obj) {
    this.dispatch('message', { data: JSON.stringify(obj) });
  }

  close() {
    this.readyState = 3;
    this.dispatch('close', {});
  }
}

async function connectTranscriber(overrides = {}) {
  FakeOpenAIWebSocket.instances.length = 0;
  const partials = [];
  const finals = [];
  const transcriber = new RealtimeTranscriber({
    apiKey: 'sk-test',
    model: 'gpt-realtime-whisper',
    language: 'fr',
    WebSocketClass: FakeOpenAIWebSocket,
    onPartial: (turnId, text) => partials.push({ turnId, text }),
    onFinal: (turnId, text, durationMs) => finals.push({ turnId, text, durationMs }),
    ...overrides,
  });
  const pending = transcriber.connect();
  const socket = FakeOpenAIWebSocket.instances.at(-1);
  socket.fireOpen();
  await pending;
  return { transcriber, socket, partials, finals };
}

test('realtime transcriber sends a transcription session.update on connect', async () => {
  const { socket } = await connectTranscriber();
  assert.match(socket.url, /^wss:\/\/api\.openai\.com\/v1\/realtime\?intent=transcription$/);
  assert.equal(socket.options.headers.Authorization, 'Bearer sk-test');
  const update = socket.sent.find((m) => m.type === 'session.update');
  assert.ok(update);
  assert.equal(update.session.type, 'transcription');
  assert.equal(update.session.audio.input.transcription.model, 'gpt-realtime-whisper');
  assert.equal(update.session.audio.input.transcription.language, 'fr');
  assert.equal(update.session.audio.input.format.rate, 24000);
  assert.equal(update.session.audio.input.turn_detection, null);
});

test('realtime transcriber appends base64 pcm and commits only with enough audio', async () => {
  const metrics = [];
  const { transcriber, socket } = await connectTranscriber({
    onMetric: (metric, extra) => metrics.push({ metric, extra }),
  });
  socket.sent.length = 0;

  // 50 ms at 24 kHz mono pcm16 = 2400 bytes, below the 100 ms (4800) commit floor.
  transcriber.appendPcm(Buffer.alloc(2400, 1));
  const append = socket.sent.find((m) => m.type === 'input_audio_buffer.append');
  assert.ok(append);
  assert.equal(Buffer.from(append.audio, 'base64').length, 2400);

  assert.equal(transcriber.commit(), false);
  assert.ok(metrics.find((m) => m.metric === 'realtime_stt_commit_skipped_short_buffer'));
  assert.equal(socket.sent.find((m) => m.type === 'input_audio_buffer.commit'), undefined);

  // Add enough to cross the floor, then commit succeeds.
  transcriber.appendPcm(Buffer.alloc(4800, 1));
  assert.equal(transcriber.commit(), true);
  assert.ok(socket.sent.find((m) => m.type === 'input_audio_buffer.commit'));
});

test('realtime transcriber auto-commits a turn on sidecar silence VAD', async () => {
  const metrics = [];
  const { transcriber, socket } = await connectTranscriber({
    onMetric: (metric, extra) => metrics.push({ metric, extra }),
    silenceMs: 150,
    minSpeechMs: 200,
    vadThreshold: 100,
    silenceCheckMs: 25,
  });
  socket.sent.length = 0;

  // 3 voiced frames (100 ms each, RMS ~257 > threshold) = 300 ms of speech,
  // then no more audio: after the 150 ms silence window the watcher commits.
  for (let i = 0; i < 3; i += 1) transcriber.appendPcm(Buffer.alloc(4800, 1));
  assert.equal(socket.sent.find((m) => m.type === 'input_audio_buffer.commit'), undefined);

  await new Promise((resolve) => setTimeout(resolve, 320));
  const commits = socket.sent.filter((m) => m.type === 'input_audio_buffer.commit');
  assert.equal(commits.length, 1);
  assert.ok(metrics.find((m) => m.metric === 'realtime_stt_autocommit' && m.extra.reason === 'silence'));
  transcriber.close();
});

test('silence watcher stays quiet when no speech crossed the VAD threshold', async () => {
  const { transcriber, socket } = await connectTranscriber({
    silenceMs: 100,
    minSpeechMs: 200,
    vadThreshold: 5000,
    silenceCheckMs: 25,
  });
  socket.sent.length = 0;
  // Low-energy frames (RMS ~257) never exceed the 5000 threshold -> no turn.
  for (let i = 0; i < 4; i += 1) transcriber.appendPcm(Buffer.alloc(4800, 1));
  await new Promise((resolve) => setTimeout(resolve, 200));
  assert.equal(socket.sent.find((m) => m.type === 'input_audio_buffer.commit'), undefined);
  transcriber.close();
});

test('realtime transcriber maps item ids to turns across delta/completed', async () => {
  const { transcriber, socket, partials, finals } = await connectTranscriber();

  socket.fireMessage({ type: 'conversation.item.input_audio_transcription.delta', item_id: 'it_1', delta: 'je règle ' });
  socket.fireMessage({ type: 'conversation.item.input_audio_transcription.delta', item_id: 'it_1', delta: 'la vitesse' });
  socket.fireMessage({
    type: 'conversation.item.input_audio_transcription.completed',
    item_id: 'it_1',
    transcript: 'je règle la vitesse',
  });
  socket.fireMessage({ type: 'conversation.item.input_audio_transcription.delta', item_id: 'it_2', delta: 'puis je verrouille' });

  assert.equal(partials[0].text, 'je règle');
  assert.equal(partials[1].text, 'je règle la vitesse');
  assert.equal(partials[0].turnId, partials[1].turnId);
  assert.equal(finals.length, 1);
  assert.equal(finals[0].text, 'je règle la vitesse');
  assert.equal(finals[0].turnId, partials[0].turnId);
  // A new OpenAI item opens a fresh Agentium turn.
  assert.notEqual(partials[2].turnId, partials[0].turnId);
  transcriber.close();
});

test('resamplePcm16ToMono halves 48 kHz mono audio to 24 kHz', () => {
  const input = Buffer.alloc(8); // 4 mono samples @ 48k
  input.writeInt16LE(100, 0);
  input.writeInt16LE(200, 2);
  input.writeInt16LE(300, 4);
  input.writeInt16LE(400, 6);
  const out = resamplePcm16ToMono(input, 48000, 1, 24000);
  assert.equal(out.length, 4); // 2 samples
});

test('resamplePcm16ToMono downmixes stereo to mono', () => {
  const input = Buffer.alloc(8); // 2 stereo frames @ 24k
  input.writeInt16LE(100, 0); // L
  input.writeInt16LE(300, 2); // R
  input.writeInt16LE(200, 4); // L
  input.writeInt16LE(400, 6); // R
  const out = resamplePcm16ToMono(input, 24000, 2, 24000);
  assert.equal(out.length, 4); // 2 mono samples
  assert.equal(out.readInt16LE(0), 200); // (100+300)/2
  assert.equal(out.readInt16LE(2), 300); // (200+400)/2
});

class FakeTranscriber {
  static instances = [];
  constructor(opts) {
    this.opts = opts;
    this.sampleRate = opts.sampleRate || 24000;
    this.appended = [];
    this.commits = 0;
    this.cleared = 0;
    this.open = true;
    FakeTranscriber.instances.push(this);
  }
  async connect() {
    return this;
  }
  appendPcm(buffer) {
    this.appended.push(buffer);
    return true;
  }
  commit() {
    this.commits += 1;
    return true;
  }
  clear() {
    this.cleared += 1;
    return true;
  }
  close() {
    this.open = false;
  }
}

test('maybeStartRealtimeStt is disabled without an OpenAI API key', async () => {
  const metrics = [];
  const session = {
    info: { session_id: 's' },
    topics: { events: 'e', control: 'c', metrics: 'm', chat: 'ch' },
    room: { localParticipant: { async publishData(payload) { metrics.push(JSON.parse(new TextDecoder().decode(payload))); } } },
    voiceGateway: { open: true, queue: [], socket: { readyState: 1, send() {} } },
  };
  const result = await maybeStartRealtimeStt(
    session,
    { voice_gateway: { realtime_stt: { enabled: true }, session_start: { language: 'fr' } } },
    { openaiApiKey: '', realtimeTranscriberFactory: (o) => new FakeTranscriber(o) },
  );
  assert.equal(result, null);
  assert.equal(session.realtimeSttConfig, undefined);
  assert.ok(metrics.find((m) => m.payload.metric === 'realtime_stt_unavailable'));
});

test('realtime lane streams the LiveKit track and commits on the VAD endpoint', async () => {
  FakeTranscriber.instances.length = 0;
  const published = [];
  const gatewayMessages = [];
  const topics = {
    events: 'agentium.voice.event',
    control: 'agentium.voice.control',
    metrics: 'agentium.voice.metric',
    chat: 'agentium.chat.event',
  };
  let lastRoom = null;

  class GatewayWebSocket {
    static instances = [];
    constructor(url) {
      this.url = url;
      this.readyState = 0;
      this.listeners = new Map();
      GatewayWebSocket.instances.push(this);
      setTimeout(() => {
        this.readyState = 1;
        this.dispatch('open', {});
      }, 0);
    }
    addEventListener(type, cb, options = {}) {
      const l = this.listeners.get(type) || [];
      l.push({ cb, once: Boolean(options.once) });
      this.listeners.set(type, l);
    }
    dispatch(type, event) {
      for (const item of [...(this.listeners.get(type) || [])]) item.cb(event);
      this.listeners.set(type, (this.listeners.get(type) || []).filter((i) => !i.once));
    }
    send(message) {
      gatewayMessages.push(JSON.parse(message));
    }
    close() {
      this.readyState = 3;
      this.dispatch('close', {});
    }
  }

  class FakeRoom {
    constructor() {
      this.handlers = new Map();
      this.localParticipant = {
        async publishData(payload, options) {
          published.push({ event: JSON.parse(new TextDecoder().decode(payload)), options });
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

  await startSession(
    {
      session_id: 'session-rt',
      room_name: 'agentium-room-rt',
      token: 'token',
      livekit_url: 'ws://agentium-livekit:7880',
      agent_identity: 'agent-rt',
      destination_identity: 'expert-1',
      topics,
      voice_gateway: {
        url: 'ws://agentium-backend:8000/api/v1/voice/sessions',
        token: 'bridge-token',
        workspace_slug: 'andritz',
        session_start: { runtime: 'openai_realtime', mode: 'conversation_only', language: 'fr' },
        realtime_stt: { enabled: true, model: 'gpt-realtime-whisper', language: 'fr', api_base: 'https://api.openai.com/v1', delay: 'low' },
      },
    },
    {
      WebSocketClass: GatewayWebSocket,
      openaiApiKey: 'sk-test',
      realtimeTranscriberFactory: (o) => new FakeTranscriber(o),
      livekitModule: {
        Room: FakeRoom,
        AudioStream: FakeAudioStream,
        RoomEvent: { DataReceived: 'data', TrackSubscribed: 'track', Disconnected: 'disconnected' },
      },
      connectRetry: { attempts: 1, retryMs: 0, maxRetryMs: 0 },
    },
  );

  const transcriber = FakeTranscriber.instances.at(-1);
  assert.ok(transcriber);
  const ready = published.find((item) => item.event.type === 'session.ready');
  assert.equal(ready.event.payload.stt_mode, 'realtime');
  assert.equal(ready.event.payload.realtime_stt, true);

  // Audio track frames stream straight into the realtime transcriber.
  lastRoom.emit(
    'track',
    { kind: 'audio', frames: [{ data: new Int16Array([10, 20, 30, 40]), sampleRate: 48000, channels: 1 }] },
    { sid: 'TR_1', name: 'micro' },
    { identity: 'expert-1' },
  );
  await new Promise((resolve) => setTimeout(resolve, 20));
  assert.ok(transcriber.appended.length >= 1);

  // The model streams a delta + completed; both relay to the voice gateway.
  transcriber.opts.onPartial('rt-turn-1', 'je règle la vitesse');
  transcriber.opts.onFinal('rt-turn-1', 'je règle la vitesse de la ligne', 1234);

  // The client VAD endpoint commits the realtime buffer and is NOT forwarded.
  await lastRoom.emit(
    'data',
    new TextEncoder().encode(JSON.stringify({ type: 'audio.endpoint', payload: { turn_id: 'rt-turn-1', reason: 'silence' } })),
    { identity: 'expert-1' },
    0,
    topics.control,
  );

  assert.equal(transcriber.commits, 1);
  const partial = gatewayMessages.find((m) => m.type === 'text.partial');
  const final = gatewayMessages.find((m) => m.type === 'text.final');
  assert.ok(partial);
  assert.equal(partial.payload.text, 'je règle la vitesse');
  assert.ok(final);
  assert.equal(final.payload.commit, true);
  assert.equal(final.payload.text, 'je règle la vitesse de la ligne');
  // audio.frame / audio.endpoint are never bridged to the gateway in realtime mode.
  assert.equal(gatewayMessages.find((m) => m.type === 'audio.endpoint'), undefined);
  assert.equal(gatewayMessages.find((m) => m.type === 'audio.frame'), undefined);
  assert.ok(published.find((item) => item.event.payload?.metric === 'realtime_stt_commit'));

  await handleControlEvent(
    { info: { session_id: 'session-rt' }, topics, realtimeSttConfig: {}, realtimeTranscriber: transcriber, voiceGateway: { open: true, queue: [], socket: { readyState: 1, send() {} } }, room: lastRoom },
    { type: 'barge_in', payload: {} },
    { identity: 'expert-1' },
    0,
  );
  assert.equal(transcriber.cleared, 1);
});

import http from 'node:http';
import { randomUUID } from 'node:crypto';
import { pathToFileURL } from 'node:url';
import {
  buildVoiceGatewayUrl,
  encodeEvent,
  eventEnvelope,
  frameChannels,
  frameSampleRate,
  frameToPcmBuffer,
  messageDataToString,
  resamplePcm16ToMono,
  topicForEvent,
  topicSet,
  wavFromPcm,
} from './bridge-utils.mjs';
import { RealtimeTranscriber } from './realtime-stt.mjs';

function parseInteger(value, fallback, minimum = 0) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(minimum, Math.floor(parsed));
}

const PORT = parseInteger(process.env.LIVEKIT_AGENT_PORT, 8090, 1);
const HOST = process.env.LIVEKIT_AGENT_HOST || '0.0.0.0';
const MAX_AUDIO_BYTES = parseInteger(process.env.LIVEKIT_AGENT_MAX_AUDIO_BYTES, 24 * 1024 * 1024, 1);
const CONNECT_ATTEMPTS = parseInteger(process.env.LIVEKIT_AGENT_CONNECT_ATTEMPTS, 6, 1);
const CONNECT_RETRY_MS = parseInteger(process.env.LIVEKIT_AGENT_CONNECT_RETRY_MS, 500, 0);
const CONNECT_MAX_RETRY_MS = Math.max(
  CONNECT_RETRY_MS,
  parseInteger(process.env.LIVEKIT_AGENT_CONNECT_MAX_RETRY_MS, 3000, 0),
);
const REALTIME_STT_SAMPLE_RATE = parseInteger(process.env.LIVEKIT_AGENT_REALTIME_STT_SAMPLE_RATE, 24000, 8000);
const OPENAI_API_KEY = process.env.OPENAI_API_KEY || '';
const sessions = new Map();

/**
 * Realtime STT config carried by the backend dispatch (voice_gateway.realtime_stt).
 * Returns null when disabled so the sidecar keeps the buffered-WAV fallback.
 */
function realtimeSttConfigFromDispatch(dispatch) {
  const rt = dispatch?.voice_gateway?.realtime_stt;
  if (!rt || rt.enabled !== true) return null;
  const sessionStart = dispatch?.voice_gateway?.session_start || {};
  return {
    model: rt.model || 'gpt-realtime-whisper',
    language: rt.language || sessionStart.language || 'fr',
    apiBase: rt.api_base || 'https://api.openai.com/v1',
    delay: rt.delay || 'low',
    prompt: rt.prompt || '',
    // Optional silence-VAD tuning (sidecar drives the manual commit). Undefined
    // falls back to the RealtimeTranscriber defaults.
    silenceMs: Number(rt.silence_ms) || undefined,
    vadThreshold: Number(rt.vad_threshold) || undefined,
    maxTurnMs: Number(rt.max_turn_ms) || undefined,
  };
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function json(res, status, body) {
  const payload = JSON.stringify(body);
  res.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'content-length': Buffer.byteLength(payload),
  });
  res.end(payload);
}

async function readJson(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  if (!chunks.length) return {};
  return JSON.parse(Buffer.concat(chunks).toString('utf8'));
}

function isAudioTrack(track, publication) {
  const values = [
    track?.kind,
    track?.source,
    publication?.kind,
    publication?.source,
    publication?.trackInfo?.type,
    publication?.trackInfo?.source,
  ]
    .filter((value) => value !== undefined && value !== null)
    .map((value) => String(value).toLowerCase());
  return values.some((value) => value.includes('audio') || value.includes('microphone'));
}

async function publishEvent(room, topics, event, options = {}) {
  await room.localParticipant.publishData(encodeEvent(event), {
    reliable: true,
    topic: options.topic || topicForEvent(topics, event),
    destination_identities: options.destinationIdentity ? [options.destinationIdentity] : undefined,
  });
  return event;
}

async function publish(session, type, payload = {}, options = {}) {
  const event = eventEnvelope(session.info.session_id, type, payload, options.sequence || 0);
  return publishEvent(session.room, session.topics, event, {
    topic: options.topic,
    destinationIdentity: options.destinationIdentity ?? session.destinationIdentity,
  });
}

function logSidecarWarning(code, error, extra = {}) {
  console.warn(
    JSON.stringify({
      code,
      message: error instanceof Error ? error.message : String(error),
      ...extra,
    }),
  );
}

// TEMP DIAGNOSTIC: realtime STT lifecycle to the container console (docker logs).
// Gated off by default; enable with LIVEKIT_AGENT_DEBUG_RTSTT=1. Remove once the
// "no realtime transcription" investigation is closed.
const DEBUG_RTSTT = String(process.env.LIVEKIT_AGENT_DEBUG_RTSTT || '') === '1';
function dbgRtStt(stage, extra = {}) {
  if (!DEBUG_RTSTT) return;
  console.log(JSON.stringify({ dbg: 'rtstt', stage, ...extra }));
}

async function publishSafely(session, type, payload = {}, options = {}) {
  try {
    await publish(session, type, payload, options);
    return true;
  } catch (error) {
    logSidecarWarning('livekit_publish_data_failed', error, { event_type: type });
    return false;
  }
}

export async function connectRoomWithRetry(room, livekitUrl, token, connectOptions = {}, retryOptions = {}) {
  const attempts = parseInteger(retryOptions.attempts, CONNECT_ATTEMPTS, 1);
  const retryMs = parseInteger(retryOptions.retryMs ?? retryOptions.baseMs, CONNECT_RETRY_MS, 0);
  const maxRetryMs = Math.max(
    retryMs,
    parseInteger(retryOptions.maxRetryMs ?? retryOptions.maxMs, CONNECT_MAX_RETRY_MS, 0),
  );
  let lastError = null;

  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      await room.connect(livekitUrl, token, connectOptions);
      return { attempts: attempt };
    } catch (error) {
      lastError = error;
      if (attempt >= attempts) break;
      const delayMs = Math.min(maxRetryMs, retryMs * attempt);
      if (delayMs > 0) await sleep(delayMs);
    }
  }

  throw lastError || new Error('LiveKit room connect failed');
}

async function connectVoiceGateway(session, dispatch, options = {}) {
  const gateway = dispatch.voice_gateway;
  if (!gateway?.url || !gateway?.token) return null;
  const WebSocketClient = options.WebSocketClass || globalThis.WebSocket;
  if (typeof WebSocketClient !== 'function') {
    throw new Error('Node runtime does not expose a WebSocket client');
  }
  const url = buildVoiceGatewayUrl(gateway.url, session.info.session_id, gateway.token, gateway.workspace_slug);
  const socket = new WebSocketClient(url);
  const bridge = { socket, open: false, openState: WebSocketClient.OPEN ?? 1, queue: [] };

  socket.addEventListener('message', async (message) => {
    try {
      const event = JSON.parse(await messageDataToString(message.data));
      await publishEvent(session.room, session.topics, event, {
        topic: topicForEvent(session.topics, event),
        destinationIdentity: session.destinationIdentity,
      });
    } catch (error) {
      await publishSafely(session, 'session.error', {
        code: 'livekit_voice_gateway_event_relay_failed',
        message: error instanceof Error ? error.message : String(error),
      });
    }
  });
  socket.addEventListener('close', () => {
    bridge.open = false;
  });
  socket.addEventListener('error', async () => {
    await publishSafely(session, 'session.error', {
      code: 'livekit_voice_gateway_transport_error',
      message: 'Voice gateway WebSocket transport error.',
    });
  });

  await new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error('Voice gateway WebSocket open timed out')), 5000);
    socket.addEventListener(
      'open',
      () => {
        clearTimeout(timeout);
        bridge.open = true;
        for (const event of bridge.queue.splice(0)) socket.send(JSON.stringify(event));
        resolve();
      },
      { once: true },
    );
    socket.addEventListener(
      'error',
      () => {
        clearTimeout(timeout);
        reject(new Error('Voice gateway WebSocket connection failed'));
      },
      { once: true },
    );
  });

  const startPayload = gateway.session_start || {};
  sendVoiceGatewayEvent(bridge, 'session.start', {
    runtime: startPayload.runtime || startPayload.provider || 'cascade_openai',
    provider: startPayload.provider || startPayload.runtime || 'cascade_openai',
    model: startPayload.model || null,
    transport: 'livekit',
    mode: startPayload.mode || dispatch.mode || 'conversation_only',
    capability: startPayload.capability || 'voice2voice_interaction',
    tandem_oracle: startPayload.tandem_oracle ?? true,
    oracle: startPayload.oracle || { min_interval_ms: 350, min_delta_chars: 24 },
    context_id: startPayload.context_id || null,
    system_id: startPayload.system_id || null,
    codec: startPayload.codec || { input: 'pcm_wav', channels: session.audio.channels || 1 },
    language: startPayload.language || startPayload.input_language || 'fr',
    output_language: startPayload.output_language || null,
    fallback_policy: startPayload.fallback_policy || 'cascade_openai',
  });
  return bridge;
}

function sendVoiceGatewayEvent(bridge, type, payload = {}) {
  if (!bridge) return false;
  const event = {
    id: `lk-voice-${randomUUID()}`,
    type,
    ts_ms: Date.now(),
    payload,
  };
  const openState = bridge.openState ?? globalThis.WebSocket?.OPEN ?? 1;
  if (bridge.open && bridge.socket.readyState === openState) {
    try {
      bridge.socket.send(JSON.stringify(event));
    } catch (error) {
      bridge.open = false;
      bridge.queue.push(event);
      logSidecarWarning('livekit_voice_gateway_send_failed', error, { event_type: type });
    }
  } else {
    bridge.queue.push(event);
  }
  return true;
}

async function disconnectRoomSafely(room) {
  try {
    await room?.disconnect?.();
  } catch (error) {
    console.warn(
      JSON.stringify({
        code: 'livekit_room_disconnect_ignored',
        message: error instanceof Error ? error.message : String(error),
      }),
    );
  }
}

function appendAudioFrame(session, frame) {
  const pcm = frameToPcmBuffer(frame);
  if (!pcm?.length) return false;
  if (session.audio.bytes + pcm.length > MAX_AUDIO_BYTES) {
    session.audio.overflow = true;
    return false;
  }
  session.audio.sampleRate = frameSampleRate(frame, session.audio.sampleRate);
  session.audio.channels = frameChannels(frame, session.audio.channels);
  session.audio.chunks.push(pcm);
  session.audio.bytes += pcm.length;
  session.audio.frameCount += 1;
  if (!session.audio.startedAt) session.audio.startedAt = Date.now();
  return true;
}

function appendRealtimeFrame(session, frame) {
  const transcriber = session.realtimeTranscriber;
  if (!transcriber || !transcriber.open) {
    if (DEBUG_RTSTT) {
      session._dbgDroppedFrames = (session._dbgDroppedFrames || 0) + 1;
      if (session._dbgDroppedFrames === 1 || session._dbgDroppedFrames % 100 === 0) {
        dbgRtStt('frame_dropped_no_open_transcriber', {
          has_transcriber: Boolean(transcriber),
          open: Boolean(transcriber?.open),
          dropped: session._dbgDroppedFrames,
        });
      }
    }
    return false;
  }
  const pcm = frameToPcmBuffer(frame);
  if (!pcm?.length) return false;
  const inputRate = frameSampleRate(frame, 48000);
  const channels = frameChannels(frame, 1);
  const mono24k = resamplePcm16ToMono(pcm, inputRate, channels, transcriber.sampleRate);
  if (!mono24k.length) return false;
  return transcriber.appendPcm(mono24k);
}

function resetAudio(session) {
  session.audio = {
    chunks: [],
    bytes: 0,
    frameCount: 0,
    browserFrameCount: 0,
    sampleRate: 48000,
    channels: 1,
    startedAt: null,
    overflow: false,
  };
}

function forwardBrowserAudioFrameToVoiceGateway(session, controlEvent) {
  const payload = controlEvent?.payload || {};
  if (!session.voiceGateway || !payload.bytes_b64) return false;
  const turnId = payload.turn_id || payload.client_turn_id || randomUUID();
  if (!session.audio.startedAt) session.audio.startedAt = Date.now();
  session.audio.browserFrameCount = (session.audio.browserFrameCount || 0) + 1;
  sendVoiceGatewayEvent(session.voiceGateway, 'audio.frame', {
    bytes_b64: payload.bytes_b64,
    turn_id: turnId,
    question_id: payload.question_id || null,
    retrieval_event_id: payload.retrieval_event_id || null,
    interruption_of_event_id: payload.interruption_of_event_id || null,
    content_type: payload.content_type || payload.encoding || 'audio/webm',
    encoding: payload.encoding || payload.content_type || 'audio/webm',
    duration_ms: payload.duration_ms || 0,
    incremental_transcription: payload.incremental_transcription,
    livekit_browser_frame_count: session.audio.browserFrameCount,
  });
  return true;
}

async function flushAudioToVoiceGateway(session, controlEvent) {
  const payload = controlEvent?.payload || {};
  if (!session.voiceGateway) {
    return false;
  }
  if (session.audio.overflow) {
    await publishSafely(session, 'session.error', {
      code: 'livekit_audio_buffer_overflow',
      message: `LiveKit audio buffer exceeded ${MAX_AUDIO_BYTES} bytes before endpoint.`,
    });
    resetAudio(session);
    return false;
  }
  if (!session.audio.bytes) {
    await publishSafely(
      session,
      'runtime.metric',
      {
        metric: 'livekit_audio_endpoint_without_audio',
        reason: payload.reason || null,
      },
      { topic: session.topics.metrics },
    );
    return false;
  }
  const wav = wavFromPcm(session.audio.chunks, session.audio.sampleRate, session.audio.channels);
  const durationMs =
    session.audio.startedAt && session.audio.sampleRate
      ? Math.round(((session.audio.bytes / 2 / session.audio.channels) / session.audio.sampleRate) * 1000)
      : null;
  sendVoiceGatewayEvent(session.voiceGateway, 'audio.frame', {
    bytes_b64: wav.toString('base64'),
    turn_id: payload.turn_id || payload.client_turn_id || randomUUID(),
    question_id: payload.question_id || null,
    retrieval_event_id: payload.retrieval_event_id || null,
    interruption_of_event_id: payload.interruption_of_event_id || null,
    content_type: 'audio/wav',
    encoding: 'audio/wav',
    duration_ms: durationMs,
    incremental_transcription: false,
    sample_rate: session.audio.sampleRate,
    channels: session.audio.channels,
    livekit_frame_count: session.audio.frameCount,
  });
  resetAudio(session);
  return true;
}

export async function handleControlEvent(session, event, participant, kind) {
  const type = String(event?.type || '');
  await publishSafely(
    session,
    'runtime.metric',
    {
      metric: 'livekit_control_event_received',
      control_type: type || null,
      from_identity: participant?.identity || null,
      kind,
      bridged_to_voice_gateway: Boolean(session.voiceGateway),
    },
    { topic: session.topics.metrics },
  );
  if (!session.voiceGateway) return;
  if (session.realtimeSttConfig) {
    // Realtime lane owns the audio path: the LiveKit PCM track is streamed
    // straight to OpenAI, so browser WebM frames are ignored and the client VAD
    // endpoint becomes a manual commit. audio.frame / audio.endpoint are NOT
    // forwarded to the gateway (no buffered audio there -> empty_audio).
    if (type === 'audio.frame') {
      return;
    }
    if (type === 'audio.endpoint' || type === 'audio.endpoint.auto') {
      const committed = session.realtimeTranscriber?.commit?.();
      await publishSafely(
        session,
        'runtime.metric',
        {
          metric: 'realtime_stt_commit',
          committed: Boolean(committed),
          reason: event?.payload?.reason || null,
          from_identity: participant?.identity || null,
        },
        { topic: session.topics.metrics },
      );
      return;
    }
    if (type === 'loop.start' || type === 'loop.armed' || type === 'barge_in') {
      session.realtimeTranscriber?.clear?.();
      // barge_in / loop control still needs to reach the gateway (oracle reset,
      // audit), so fall through to the generic forward below.
    }
    if (type === 'session.close') {
      session.realtimeTranscriber?.close?.();
    }
    sendVoiceGatewayEvent(session.voiceGateway, type, event.payload || {});
    if (type === 'session.close') {
      await disconnectRoomSafely(session.room);
    }
    return;
  }
  if (type === 'audio.frame') {
    const forwarded = forwardBrowserAudioFrameToVoiceGateway(session, event);
    if (
      forwarded &&
      (session.audio.browserFrameCount === 1 || session.audio.browserFrameCount % 10 === 0)
    ) {
      await publishSafely(
        session,
        'runtime.metric',
        {
          metric: 'livekit_browser_audio_frames_forwarded',
          from_identity: participant?.identity || null,
          frame_count: session.audio.browserFrameCount,
          bridged_to_voice_gateway: true,
        },
        { topic: session.topics.metrics },
      );
    }
    return;
  }
  if (type === 'loop.start' || type === 'loop.armed' || type === 'barge_in') {
    const resetMetrics = {
      audio_bytes_before_reset: session.audio?.bytes || 0,
      audio_frame_count_before_reset: session.audio?.frameCount || 0,
      browser_audio_frame_count_before_reset: session.audio?.browserFrameCount || 0,
      audio_overflow_before_reset: Boolean(session.audio?.overflow),
    };
    resetAudio(session);
    if (type === 'barge_in') {
      await publishSafely(
        session,
        'runtime.metric',
        {
          metric: 'livekit_barge_in_audio_reset',
          prompt_event_id: event?.payload?.prompt_event_id || null,
          from_identity: participant?.identity || null,
          bridged_to_voice_gateway: true,
          ...resetMetrics,
        },
        { topic: session.topics.metrics },
      );
    }
  }
  if (type === 'audio.endpoint' || type === 'audio.endpoint.auto') {
    const browserFramesForwarded = (session.audio.browserFrameCount || 0) > 0;
    const flushed = browserFramesForwarded || (await flushAudioToVoiceGateway(session, event));
    if (!flushed) return;
    if (browserFramesForwarded) {
      await publishSafely(
        session,
        'runtime.metric',
        {
          metric: 'livekit_browser_audio_endpoint_forwarded',
          from_identity: participant?.identity || null,
          frame_count: session.audio.browserFrameCount,
          bridged_to_voice_gateway: true,
        },
        { topic: session.topics.metrics },
      );
    }
    resetAudio(session);
  }
  sendVoiceGatewayEvent(session.voiceGateway, type, event.payload || {});
  if (type === 'session.close') {
    await disconnectRoomSafely(session.room);
  }
}

async function monitorAudioStream(livekit, session, track, participantIdentity) {
  if (!livekit.AudioStream) {
    await publishSafely(
      session,
      'runtime.metric',
      {
        metric: 'livekit_audio_track_subscribed',
        participant_identity: participantIdentity,
        audio_stream_api: 'unavailable',
      },
      { topic: session.topics.metrics },
    );
    return;
  }

  const startedAt = Date.now();
  const stream = new livekit.AudioStream(track);
  try {
    for await (const frame of stream) {
      if (session.realtimeSttConfig) {
        // Realtime lane: stream the LiveKit PCM track straight into the OpenAI
        // gpt-realtime-whisper session (resampled to 24 kHz mono). No buffering,
        // no WAV, no per-turn re-transcription of a growing WebM blob.
        const appended = appendRealtimeFrame(session, frame);
        if (appended) {
          session.audio.frameCount += 1;
          if (session.audio.frameCount === 1 || session.audio.frameCount % 250 === 0) {
            await publishSafely(
              session,
              'runtime.metric',
              {
                metric: 'livekit_realtime_audio_frames_streamed',
                participant_identity: participantIdentity,
                frame_count: session.audio.frameCount,
                elapsed_ms: Date.now() - startedAt,
                audio_bridge: 'realtime_stt',
              },
              { topic: session.topics.metrics },
            );
          }
        }
        continue;
      }
      const appended = appendAudioFrame(session, frame);
      if (appended && (session.audio.frameCount === 1 || session.audio.frameCount % 100 === 0)) {
        await publishSafely(
          session,
          'runtime.metric',
          {
            metric: 'livekit_audio_frames_seen',
            participant_identity: participantIdentity,
            frame_count: session.audio.frameCount,
            elapsed_ms: Date.now() - startedAt,
            sample_rate: session.audio.sampleRate,
            channels: session.audio.channels,
            audio_bytes: session.audio.bytes,
            audio_bridge: session.voiceGateway ? 'voice_gateway_buffered' : 'media_observed',
          },
          { topic: session.topics.metrics },
        );
      }
    }
  } catch (error) {
    await publishSafely(
      session,
      'session.error',
      {
        code: 'livekit_audio_stream_failed',
        message: error instanceof Error ? error.message : String(error),
      },
      { topic: session.topics.events },
    );
  }
}

export async function maybeStartRealtimeStt(session, dispatch, options = {}) {
  const config = realtimeSttConfigFromDispatch(dispatch);
  dbgRtStt('config_resolved', {
    enabled: Boolean(config),
    model: config?.model,
    language: config?.language,
    silence_ms: config?.silenceMs,
    vad_threshold: config?.vadThreshold,
    max_turn_ms: config?.maxTurnMs,
  });
  if (!config) return null;
  const apiKey = options.openaiApiKey || OPENAI_API_KEY;
  if (!apiKey) {
    await publishSafely(
      session,
      'runtime.metric',
      { metric: 'realtime_stt_unavailable', reason: 'missing_openai_api_key' },
      { topic: session.topics.metrics },
    );
    return null;
  }
  const factory =
    options.realtimeTranscriberFactory ||
    ((opts) => new RealtimeTranscriber(opts));
  const transcriber = factory({
    apiKey,
    model: config.model,
    language: config.language,
    apiBase: config.apiBase,
    delay: config.delay,
    prompt: config.prompt,
    silenceMs: config.silenceMs,
    vadThreshold: config.vadThreshold,
    maxTurnMs: config.maxTurnMs,
    sampleRate: REALTIME_STT_SAMPLE_RATE,
    WebSocketClass: options.OpenAIWebSocketClass,
    onPartial: (turnId, text) => {
      if (!text) return;
      dbgRtStt('partial', { turn_id: turnId, len: text.length, sample: text.slice(0, 60) });
      sendVoiceGatewayEvent(session.voiceGateway, 'text.partial', {
        turn_id: turnId,
        text,
        transcript_state: 'partial',
        provider: 'openai_realtime',
        model: config.model,
        transport: 'livekit',
        incremental_transcription: true,
      });
    },
    onFinal: (turnId, text, durationMs) => {
      dbgRtStt('final', { turn_id: turnId, len: (text || '').length, duration_ms: durationMs, sample: (text || '').slice(0, 60) });
      sendVoiceGatewayEvent(session.voiceGateway, 'text.final', {
        turn_id: turnId,
        text,
        transcript_state: 'final',
        commit: true,
        duration_ms: durationMs,
        provider: 'openai_realtime',
        model: config.model,
        transport: 'livekit',
      });
    },
    onError: (error) => {
      dbgRtStt('error', { message: error instanceof Error ? error.message : String(error) });
      void publishSafely(session, 'session.error', {
        code: 'realtime_stt_error',
        message: error instanceof Error ? error.message : String(error),
      });
    },
    onMetric: (metric, extra = {}) => {
      dbgRtStt('metric', { metric, ...extra });
      void publishSafely(session, 'runtime.metric', { metric, ...extra }, { topic: session.topics.metrics });
    },
  });
  try {
    await transcriber.connect();
    session.realtimeSttConfig = config;
    session.realtimeTranscriber = transcriber;
    dbgRtStt('connected', { model: config.model });
    await publishSafely(
      session,
      'runtime.metric',
      { metric: 'realtime_stt_ready', model: config.model, language: config.language },
      { topic: session.topics.metrics },
    );
    return transcriber;
  } catch (error) {
    dbgRtStt('connect_failed', { message: error instanceof Error ? error.message : String(error) });
    try {
      transcriber.close();
    } catch {
      // best-effort
    }
    await publishSafely(session, 'session.error', {
      code: 'realtime_stt_connect_failed',
      message: error instanceof Error ? error.message : String(error),
      fallback_mode: 'buffered_stt',
    });
    return null;
  }
}

export async function startSession(dispatch, options = {}) {
  const sessionId = String(dispatch.session_id || '');
  const roomName = String(dispatch.room_name || '');
  const token = String(dispatch.token || '');
  const livekitUrl = String(dispatch.livekit_url || '');
  if (!sessionId || !roomName || !token || !livekitUrl) {
    throw new Error('dispatch requires session_id, room_name, livekit_url, and token');
  }

  const existing = sessions.get(sessionId);
  if (existing) {
    return { reused: true, ...existing.info };
  }

  const livekit = options.livekitModule || (await import('@livekit/rtc-node'));
  const topics = topicSet(dispatch.topics);
  const room = new livekit.Room();
  const info = {
    session_id: sessionId,
    room_name: roomName,
    agent_identity: String(dispatch.agent_identity || 'agentium-agent'),
    started_at: new Date().toISOString(),
    mode: dispatch.voice_gateway?.url ? 'voice_gateway_bridge' : 'media_observer',
  };
  const session = {
    room,
    topics,
    info,
    destinationIdentity: dispatch.destination_identity || null,
    voiceGateway: null,
    realtimeSttConfig: null,
    realtimeTranscriber: null,
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
  sessions.set(sessionId, session);

  room
    .on(livekit.RoomEvent.DataReceived, async (payload, participant, kind, topic) => {
      if (topic !== topics.control) return;
      let event = null;
      try {
        event = JSON.parse(new TextDecoder().decode(payload));
      } catch {
        return;
      }
      await handleControlEvent(session, event, participant, kind).catch((error) =>
        logSidecarWarning('livekit_control_event_failed', error, { control_type: event?.type || null }),
      );
    })
    .on(livekit.RoomEvent.TrackSubscribed, (track, publication, participant) => {
      void publishSafely(
        session,
        'runtime.metric',
        {
          metric: 'livekit_track_subscribed',
          participant_identity: participant?.identity || null,
          track_sid: publication?.trackSid || publication?.sid || null,
          track_name: publication?.trackName || publication?.name || null,
          is_audio: isAudioTrack(track, publication),
        },
        { topic: topics.metrics },
      );
      if (isAudioTrack(track, publication)) {
        void monitorAudioStream(livekit, session, track, participant?.identity || null);
      }
    })
    .on(livekit.RoomEvent.Disconnected, () => {
      session.realtimeTranscriber?.close?.();
      if (session.voiceGateway?.socket && session.voiceGateway.open) {
        session.voiceGateway.socket.close(1000, 'livekit-disconnected');
      }
      sessions.delete(sessionId);
    });

  try {
    const connectResult = await connectRoomWithRetry(
      room,
      livekitUrl,
      token,
      { autoSubscribe: true },
      options.connectRetry,
    );
    info.connect_attempts = connectResult.attempts;
  } catch (error) {
    sessions.delete(sessionId);
    await disconnectRoomSafely(room);
    throw error;
  }
  try {
    session.voiceGateway = await connectVoiceGateway(session, dispatch, {
      WebSocketClass: options.WebSocketClass,
    });
  } catch (error) {
    info.mode = 'media_observer';
    await publishSafely(session, 'session.error', {
      code: 'livekit_voice_gateway_connect_failed',
      message: error instanceof Error ? error.message : String(error),
      fallback_mode: 'media_observer',
    });
  }
  if (session.voiceGateway) {
    await maybeStartRealtimeStt(session, dispatch, options);
  }
  info.stt_mode = session.realtimeSttConfig ? 'realtime' : 'batch';
  await publishSafely(session, 'session.ready', {
    agent_identity: info.agent_identity,
    room_name: roomName,
    mode: info.mode,
    audio_bridge: session.voiceGateway ? 'voice_gateway_ready' : 'media_observer_ready',
    stt_mode: info.stt_mode,
    realtime_stt: Boolean(session.realtimeSttConfig),
    connect_attempts: info.connect_attempts,
  });
  await publishSafely(
    session,
    'runtime.metric',
    {
      metric: 'livekit_agent_joined',
      agent_identity: info.agent_identity,
      room_name: roomName,
      mode: info.mode,
      voice_gateway_connected: Boolean(session.voiceGateway),
      connect_attempts: info.connect_attempts,
    },
    { topic: topics.metrics },
  );
  return { reused: false, ...info };
}

export function createAgentiumLiveKitAgentServer() {
  return http.createServer(async (req, res) => {
    try {
      if (req.method === 'GET' && req.url === '/healthz') {
        json(res, 200, { status: 'ok', active_sessions: sessions.size });
        return;
      }
      if (req.method === 'POST' && req.url === '/dispatch') {
        const dispatch = await readJson(req);
        const result = await startSession(dispatch);
        json(res, 202, { status: 'accepted', ...result });
        return;
      }
      if (req.method === 'POST' && req.url === '/shutdown-session') {
        const body = await readJson(req);
        const sessionId = String(body.session_id || '');
        const session = sessions.get(sessionId);
        if (session) {
          session.realtimeTranscriber?.close?.();
          if (session.voiceGateway?.socket && session.voiceGateway.open) {
            session.voiceGateway.socket.close(1000, 'shutdown-session');
          }
          await disconnectRoomSafely(session.room);
          sessions.delete(sessionId);
        }
        json(res, 200, { status: 'ok', session_id: sessionId });
        return;
      }
      json(res, 404, { status: 'not_found' });
    } catch (error) {
      json(res, 500, {
        status: 'error',
        message: error instanceof Error ? error.message : String(error),
      });
    }
  });
}

export function startAgentiumLiveKitAgentServer({ port = PORT, host = HOST } = {}) {
  const server = createAgentiumLiveKitAgentServer();
  server.listen(port, host, () => {
    console.log(`agentium-livekit-agent listening on ${host}:${port}`);
  });
  return server;
}

async function shutdown(server) {
  for (const [sessionId, session] of sessions) {
    try {
      session.realtimeTranscriber?.close?.();
      if (session.voiceGateway?.socket && session.voiceGateway.open) {
        session.voiceGateway.socket.close(1000, 'shutdown');
      }
      await disconnectRoomSafely(session.room);
    } catch {
      // best-effort shutdown
    }
    sessions.delete(sessionId);
  }
  server.close(() => process.exit(0));
}

const isMain = process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href;

if (isMain) {
  const server = startAgentiumLiveKitAgentServer();
  process.on('SIGTERM', () => void shutdown(server));
  process.on('SIGINT', () => void shutdown(server));
}

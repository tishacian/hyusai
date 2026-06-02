import { randomUUID } from 'node:crypto';

export function eventEnvelope(sessionId, type, payload = {}, sequence = 0) {
  return {
    id: `lk-agent-${randomUUID()}`,
    session_id: sessionId,
    type,
    ts_ms: Date.now(),
    sequence,
    payload: {
      provider: 'livekit_agent',
      transport: 'livekit',
      ...payload,
    },
  };
}

export function encodeEvent(event) {
  return new TextEncoder().encode(JSON.stringify(event));
}

export function topicSet(topics = {}) {
  return {
    events: topics.events || 'agentium.voice.event',
    control: topics.control || 'agentium.voice.control',
    metrics: topics.metrics || 'agentium.voice.metric',
    chat: topics.chat || 'agentium.chat.event',
  };
}

export function topicForEvent(topics, event) {
  if (event?.type === 'runtime.metric') return topics.metrics;
  if (String(event?.type || '').startsWith('chat.')) return topics.chat;
  return topics.events;
}

export function buildVoiceGatewayUrl(baseUrl, sessionId, token, workspaceSlug) {
  const replaced = String(baseUrl || '').replace('{session_id}', encodeURIComponent(sessionId));
  const url = new URL(replaced);
  if (!url.pathname.includes(encodeURIComponent(sessionId))) {
    url.pathname = `${url.pathname.replace(/\/$/, '')}/${encodeURIComponent(sessionId)}`;
  }
  url.searchParams.set('token', token);
  if (workspaceSlug) url.searchParams.set('workspace_slug', workspaceSlug);
  return url.toString();
}

export async function messageDataToString(data) {
  if (typeof data === 'string') return data;
  if (data instanceof ArrayBuffer) return Buffer.from(data).toString('utf8');
  if (ArrayBuffer.isView(data)) return Buffer.from(data.buffer, data.byteOffset, data.byteLength).toString('utf8');
  if (data && typeof data.arrayBuffer === 'function') return Buffer.from(await data.arrayBuffer()).toString('utf8');
  return String(data);
}

export function frameToPcmBuffer(frame) {
  const audioFrame = frame?.frame || frame;
  const data = audioFrame?.data || audioFrame?.samples || audioFrame?.pcm || audioFrame?.buffer;
  if (!data) return null;
  if (Buffer.isBuffer(data)) return data;
  if (data instanceof ArrayBuffer) return Buffer.from(data);
  if (ArrayBuffer.isView(data)) {
    if (data instanceof Float32Array || data instanceof Float64Array) {
      const pcm = Buffer.alloc(data.length * 2);
      for (let i = 0; i < data.length; i += 1) {
        const clamped = Math.max(-1, Math.min(1, Number(data[i]) || 0));
        pcm.writeInt16LE(Math.round(clamped * 32767), i * 2);
      }
      return pcm;
    }
    return Buffer.from(data.buffer, data.byteOffset, data.byteLength);
  }
  if (Array.isArray(data)) {
    const pcm = Buffer.alloc(data.length * 2);
    data.forEach((value, index) => pcm.writeInt16LE(Number(value) || 0, index * 2));
    return pcm;
  }
  return null;
}

export function frameSampleRate(frame, fallback = 48000) {
  const audioFrame = frame?.frame || frame;
  return Number(audioFrame?.sampleRate || audioFrame?.sample_rate || frame?.sampleRate || frame?.sample_rate || fallback);
}

export function frameChannels(frame, fallback = 1) {
  const audioFrame = frame?.frame || frame;
  return Number(
    audioFrame?.numChannels ||
      audioFrame?.num_channels ||
      audioFrame?.channels ||
      frame?.numChannels ||
      frame?.channels ||
      fallback,
  );
}

export function wavFromPcm(chunks, sampleRate, channels) {
  const pcm = Buffer.concat(chunks);
  const header = Buffer.alloc(44);
  const byteRate = sampleRate * channels * 2;
  header.write('RIFF', 0);
  header.writeUInt32LE(36 + pcm.length, 4);
  header.write('WAVE', 8);
  header.write('fmt ', 12);
  header.writeUInt32LE(16, 16);
  header.writeUInt16LE(1, 20);
  header.writeUInt16LE(channels, 22);
  header.writeUInt32LE(sampleRate, 24);
  header.writeUInt32LE(byteRate, 28);
  header.writeUInt16LE(channels * 2, 32);
  header.writeUInt16LE(16, 34);
  header.write('data', 36);
  header.writeUInt32LE(pcm.length, 40);
  return Buffer.concat([header, pcm]);
}

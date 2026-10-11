import test from 'node:test';
import assert from 'node:assert/strict';
import {
  buildVoiceGatewayUrl,
  eventEnvelope,
  frameChannels,
  frameSampleRate,
  frameToPcmBuffer,
  messageDataToString,
  topicForEvent,
  topicSet,
  wavFromPcm,
} from './bridge-utils.mjs';

test('buildVoiceGatewayUrl appends session id and bridge query params', () => {
  const url = new URL(buildVoiceGatewayUrl('ws://agentium-backend:8000/api/v1/voice/sessions', 'session 1', 'tok+en', 'andritz'));

  assert.equal(url.protocol, 'ws:');
  assert.equal(url.hostname, 'agentium-backend');
  assert.equal(url.pathname, '/api/v1/voice/sessions/session%201');
  assert.equal(url.searchParams.get('token'), 'tok+en');
  assert.equal(url.searchParams.get('workspace_slug'), 'andritz');
});

test('buildVoiceGatewayUrl preserves placeholder form', () => {
  const url = new URL(buildVoiceGatewayUrl('ws://backend/ws/{session_id}', 'abc/123', 'token', null));

  assert.equal(url.pathname, '/ws/abc%2F123');
  assert.equal(url.searchParams.get('token'), 'token');
  assert.equal(url.searchParams.has('workspace_slug'), false);
});

test('topicForEvent routes metrics and chat separately from voice events', () => {
  const topics = topicSet({ events: 'voice', metrics: 'metrics', chat: 'chat' });

  assert.equal(topicForEvent(topics, { type: 'runtime.metric' }), 'metrics');
  assert.equal(topicForEvent(topics, { type: 'chat.message' }), 'chat');
  assert.equal(topicForEvent(topics, { type: 'text.final' }), 'voice');
});

test('eventEnvelope always marks LiveKit transport/provider', () => {
  const envelope = eventEnvelope('session-1', 'text.partial', { text: 'bonjour' }, 7);

  assert.equal(envelope.session_id, 'session-1');
  assert.equal(envelope.type, 'text.partial');
  assert.equal(envelope.sequence, 7);
  assert.equal(envelope.payload.transport, 'livekit');
  assert.equal(envelope.payload.provider, 'livekit_agent');
  assert.equal(envelope.payload.text, 'bonjour');
});

test('frame helpers extract PCM, sample rate and channels from RTC frame shapes', () => {
  const frame = {
    frame: {
      data: new Float32Array([-1, 0, 1]),
      sampleRate: 16000,
      numChannels: 1,
    },
  };

  const pcm = frameToPcmBuffer(frame);

  assert.equal(frameSampleRate(frame), 16000);
  assert.equal(frameChannels(frame), 1);
  assert.equal(pcm.length, 6);
  assert.equal(pcm.readInt16LE(0), -32767);
  assert.equal(pcm.readInt16LE(2), 0);
  assert.equal(pcm.readInt16LE(4), 32767);
});

test('wavFromPcm creates a valid 16-bit PCM WAV header', () => {
  const wav = wavFromPcm([Buffer.from([0x01, 0x00, 0xff, 0x7f])], 8000, 1);

  assert.equal(wav.toString('ascii', 0, 4), 'RIFF');
  assert.equal(wav.toString('ascii', 8, 12), 'WAVE');
  assert.equal(wav.readUInt16LE(20), 1);
  assert.equal(wav.readUInt16LE(22), 1);
  assert.equal(wav.readUInt32LE(24), 8000);
  assert.equal(wav.readUInt16LE(34), 16);
  assert.equal(wav.toString('ascii', 36, 40), 'data');
  assert.equal(wav.readUInt32LE(40), 4);
  assert.equal(wav.length, 48);
});

test('messageDataToString decodes common WebSocket payload shapes', async () => {
  assert.equal(await messageDataToString('hello'), 'hello');
  assert.equal(await messageDataToString(new Uint8Array(Buffer.from('typed'))), 'typed');
  assert.equal(await messageDataToString(Buffer.from('buffer')), 'buffer');
});

import '@angular/compiler';
import { expect, test } from '@playwright/test';
import { LiveKitConversationConnection } from '../../src/app/core/livekit-conversation.service';
import { VoiceSessionConnection } from '../../src/app/core/voice-session.service';
import type { VoiceFrameMeta } from '../../src/app/core/voice-session.service';

class TestFileReader {
  result: string | null = null;
  error: Error | null = null;
  onerror: (() => void) | null = null;
  onloadend: (() => void) | null = null;

  readAsDataURL(blob: Blob): void {
    blob
      .arrayBuffer()
      .then((buffer) => {
        this.result = `data:${blob.type};base64,${Buffer.from(buffer).toString('base64')}`;
        this.onloadend?.();
      })
      .catch((error) => {
        this.error = error instanceof Error ? error : new Error(String(error));
        this.onerror?.();
      });
  }
}

function withBrowserBlobReader(): () => void {
  const previousFileReader = (globalThis as any).FileReader;
  (globalThis as any).FileReader = TestFileReader;
  return () => {
    if (previousFileReader === undefined) {
      delete (globalThis as any).FileReader;
    } else {
      (globalThis as any).FileReader = previousFileReader;
    }
  };
}

const activeDocumentMeta: VoiceFrameMeta = {
  turn_id: 'turn-voice-doc',
  question_id: 'q-safety-stop',
  document_refs: [
    {
      document_id: 'doc-capture-reference',
      collection_name: 'capture-session-session-andritz-free-smoke',
      filename: 'andritz-capture-reference.pdf',
      page: 1,
      association_mode: 'active_view',
    },
  ],
  visual_context: {
    document_id: 'doc-capture-reference',
    collection_name: 'capture-session-session-andritz-free-smoke',
    filename: 'andritz-capture-reference.pdf',
    page: 1,
    association_mode: 'active_view',
  },
  capture_mode: 'normal',
};

test.describe('voice transport document reference contract', () => {
  test('backend WebSocket audio frames and endpoints carry the active document view', async () => {
    const restoreFileReader = withBrowserBlobReader();
    const previousWebSocket = (globalThis as any).WebSocket;
    (globalThis as any).WebSocket = { OPEN: 1, CONNECTING: 0 };
    const sentFrames: string[] = [];
    const socket = {
      readyState: 1,
      send: (frame: string) => sentFrames.push(frame),
      close: () => undefined,
    };

    try {
      const connection = new VoiceSessionConnection(socket as any);
      await connection.sendAudioFrame(new Blob(['voice-bytes'], { type: 'audio/webm' }), activeDocumentMeta);
      connection.endpoint({ ...activeDocumentMeta, auto: true, reason: 'silence' });

      expect(sentFrames).toHaveLength(2);
      const frame = JSON.parse(sentFrames[0]);
      const endpoint = JSON.parse(sentFrames[1]);
      expect(frame.type).toBe('audio.frame');
      expect(endpoint.type).toBe('audio.endpoint.auto');
      expect(frame.payload).toMatchObject({
        turn_id: 'turn-voice-doc',
        question_id: 'q-safety-stop',
        document_refs: activeDocumentMeta.document_refs,
        visual_context: activeDocumentMeta.visual_context,
      });
      expect(endpoint.payload).toMatchObject({
        turn_id: 'turn-voice-doc',
        question_id: 'q-safety-stop',
        document_refs: activeDocumentMeta.document_refs,
        visual_context: activeDocumentMeta.visual_context,
        auto: true,
        reason: 'silence',
      });
    } finally {
      restoreFileReader();
      if (previousWebSocket === undefined) {
        delete (globalThis as any).WebSocket;
      } else {
        (globalThis as any).WebSocket = previousWebSocket;
      }
    }
  });

  test('LiveKit fallback audio frames and endpoints carry the active document view', async () => {
    const restoreFileReader = withBrowserBlobReader();
    const published: Array<{ topic: string | undefined; event: Record<string, any> }> = [];
    const decoder = new TextDecoder();
    const room = {
      on: () => room,
      localParticipant: {
        publishData: async (bytes: Uint8Array, options: { topic?: string }) => {
          published.push({ topic: options.topic, event: JSON.parse(decoder.decode(bytes)) });
        },
        setMicrophoneEnabled: async () => undefined,
      },
      disconnect: async () => undefined,
    };
    const token = {
      enabled: true,
      configured: true,
      url: 'wss://livekit.example.test',
      room_name: 'room-andritz-voice-doc',
      identity: 'qa-voice-doc',
      token: 'token',
      metadata: { agentium_session_id: 'session-andritz-free-smoke' },
    };
    const topics = { events: 'events', control: 'control', metrics: 'metrics', chat: 'chat' };

    try {
      const connection = new LiveKitConversationConnection(
        room as any,
        token,
        topics,
        { DataReceived: 'dataReceived', Disconnected: 'disconnected' },
        1,
      );
      await connection.sendAudioFrame(new Blob(['voice-bytes'], { type: 'audio/webm' }), activeDocumentMeta);
      connection.endpoint({ ...activeDocumentMeta, auto: true, reason: 'silence' });

      await expect.poll(() => published.length).toBe(2);
      expect(published.map((entry) => entry.topic)).toEqual(['control', 'control']);
      expect(published[0].event).toMatchObject({
        session_id: 'session-andritz-free-smoke',
        type: 'audio.frame',
        payload: {
          turn_id: 'turn-voice-doc',
          question_id: 'q-safety-stop',
          document_refs: activeDocumentMeta.document_refs,
          visual_context: activeDocumentMeta.visual_context,
          transport_note: 'browser_audio_fallback',
        },
      });
      expect(published[1].event).toMatchObject({
        session_id: 'session-andritz-free-smoke',
        type: 'audio.endpoint.auto',
        payload: {
          turn_id: 'turn-voice-doc',
          question_id: 'q-safety-stop',
          document_refs: activeDocumentMeta.document_refs,
          visual_context: activeDocumentMeta.visual_context,
          auto: true,
          reason: 'silence',
        },
      });
    } finally {
      restoreFileReader();
    }
  });
});

import { Injectable, inject } from '@angular/core';
import type { Room as LiveKitRoom } from 'livekit-client';
import { Observable, Subject, firstValueFrom } from 'rxjs';
import { ApiService } from './api.service';
import { VoiceSessionEvent, VoiceSessionEventType, VoiceSessionStartOptions, VoiceFrameMeta } from './voice-session.service';

export interface LiveKitConfig {
  enabled: boolean;
  configured: boolean;
  url?: string | null;
  transport: 'livekit' | string;
  fallback_transport: 'backend_ws' | string;
  room_ttl_seconds: number;
  topics: {
    events: string;
    control: string;
    metrics: string;
    chat: string;
  };
}

export interface LiveKitTokenResponse {
  enabled: boolean;
  configured: boolean;
  url: string;
  room_name: string;
  room_existed?: boolean | null;
  identity: string;
  token: string;
  metadata: Record<string, unknown>;
}

export interface LiveKitOpenOptions extends VoiceSessionStartOptions {
  surface?: string;
  publishMicrophone?: boolean;
  dispatchAgent?: boolean;
  requireVoiceGateway?: boolean;
  participantName?: string | null;
  mockPartialText?: string | null;
  metadata?: Record<string, unknown>;
}

export interface LiveKitAgentDispatchResponse {
  status: string;
  mode: string;
  room_name: string;
  room_existed?: boolean;
  agent_identity: string;
  events: VoiceSessionEvent[];
}

export class LiveKitConversationConnection {
  private readonly eventsSubject = new Subject<VoiceSessionEvent>();
  private readonly encoder = new TextEncoder();
  private readonly decoder = new TextDecoder();
  readonly events$: Observable<VoiceSessionEvent> = this.eventsSubject.asObservable();

  constructor(
    private readonly room: LiveKitRoom,
    private readonly token: LiveKitTokenResponse,
    private readonly topics: LiveKitConfig['topics'],
    private readonly roomEvents: { DataReceived: string; Disconnected: string },
    private readonly reliableDataKind: number,
  ) {
    this.room
      .on(this.roomEvents.DataReceived as any, (payload: Uint8Array, _participant: unknown, kind?: number, topic?: string) => {
        this.handleData(payload, kind, topic);
      })
      .on(this.roomEvents.Disconnected as any, (reason?: unknown) => {
        this.emit('session.close', { reason: reason ?? null, transport: 'livekit' });
        this.eventsSubject.complete();
      });
  }

  get roomName(): string {
    return this.token.room_name;
  }

  get identity(): string {
    return this.token.identity;
  }

  start(options: VoiceSessionStartOptions): void {
    void this.sendControl('session.start', {
      runtime: options.runtime || options.provider || 'cascade_openai',
      provider: options.provider || options.runtime || 'cascade_openai',
      model: options.model || null,
      transport: 'livekit',
      language: options.language || null,
      output_language: options.output_language || null,
      fallback_policy: options.fallback_policy || 'backend_ws',
      tandem_oracle: options.tandem_oracle ?? true,
      oracle: options.oracle || { min_interval_ms: 350, min_delta_chars: 24 },
      capability: options.capability || 'voice2voice_interaction',
      context_id: options.context_id || null,
      system_id: options.system_id || null,
      mode: options.mode || 'conversation_only',
      codec: options.codec || { input: 'opus', channels: 1 },
      room_name: this.roomName,
      identity: this.identity,
    });
  }

  async sendAudioFrame(blob: Blob, meta: VoiceFrameMeta): Promise<void> {
    const bytes_b64 = await this.blobToBase64(blob);
    await this.sendControl('audio.frame', {
      bytes_b64,
      turn_id: meta.turn_id,
      question_id: meta.question_id,
      retrieval_event_id: meta.retrieval_event_id,
      interruption_of_event_id: meta.interruption_of_event_id,
      content_type: meta.content_type || blob.type || 'audio/webm',
      encoding: blob.type || 'audio/webm',
      duration_ms: 0,
      transport_note: 'browser_audio_fallback',
    });
  }

  async enableMicrophone(enabled = true): Promise<void> {
    await this.room.localParticipant.setMicrophoneEnabled(enabled);
    this.emit('runtime.metric', {
      metric: enabled ? 'livekit_microphone_enabled' : 'livekit_microphone_disabled',
      transport: 'livekit',
    });
  }

  endpoint(meta: VoiceFrameMeta = {}): void {
    void this.sendControl(meta.auto ? 'audio.endpoint.auto' : 'audio.endpoint', {
      turn_id: meta.turn_id,
      question_id: meta.question_id,
      retrieval_event_id: meta.retrieval_event_id,
      interruption_of_event_id: meta.interruption_of_event_id,
      auto: Boolean(meta.auto),
      reason: meta.reason || null,
    });
  }

  bargeIn(promptEventId?: string | null): void {
    void this.sendControl('barge_in', { prompt_event_id: promptEventId || null });
  }

  /** Stop sending audio frames locally without ending the turn. No relance. */
  audioPause(payload: Record<string, unknown> = {}): void {
    void this.sendControl('audio.pause', payload);
    void this.room.localParticipant.setMicrophoneEnabled(false).catch(() => undefined);
  }

  sectionSelect(payload: { topic_id?: string | null; subtopic_id?: string | null } & Record<string, unknown> = {}): void {
    void this.sendControl('section.select', payload);
  }

  sectionFinish(payload: { topic_id?: string | null; subtopic_id?: string | null } & Record<string, unknown> = {}): void {
    void this.sendControl('section.finish', payload);
  }

  captureFinish(payload: Record<string, unknown> = {}): void {
    void this.sendControl('capture.finish', payload);
  }

  loopStart(payload: Record<string, unknown> = {}): void {
    void this.sendControl('loop.start', payload);
  }

  loopPause(payload: Record<string, unknown> = {}): void {
    void this.sendControl('loop.pause', payload);
  }

  loopResume(payload: Record<string, unknown> = {}): void {
    void this.sendControl('loop.resume', payload);
  }

  loopStop(payload: Record<string, unknown> = {}): void {
    void this.sendControl('loop.stop', payload);
  }

  voiceCommand(command: string, transcript: string, payload: Record<string, unknown> = {}): void {
    void this.sendControl('voice.command', { command, transcript, ...payload });
  }

  loopArmed(payload: Record<string, unknown> = {}): void {
    void this.sendControl('loop.armed', payload);
  }

  ttsStarted(payload: Record<string, unknown> = {}): void {
    void this.sendControl('tts.started', payload);
  }

  ttsEnded(payload: Record<string, unknown> = {}): void {
    void this.sendControl('tts.ended', payload);
  }

  ttsInterrupted(payload: Record<string, unknown> = {}): void {
    void this.sendControl('tts.interrupted', payload);
  }

  sendControl(type: VoiceSessionEventType | string, payload: Record<string, unknown> = {}): Promise<void> {
    return this.publish(this.topics.control, {
      id: crypto.randomUUID?.() || String(Date.now()),
      session_id: this.token.metadata['agentium_session_id'] || '',
      type,
      ts_ms: Date.now(),
      sequence: 0,
      payload,
    });
  }

  async close(): Promise<void> {
    await this.sendControl('session.close', {}).catch(() => undefined);
    await this.room.localParticipant.setMicrophoneEnabled(false).catch(() => undefined);
    await this.room.disconnect(true);
  }

  private publish(topic: string, event: Record<string, unknown>): Promise<void> {
    const bytes = this.encoder.encode(JSON.stringify(event));
    return this.room.localParticipant.publishData(bytes, {
      reliable: true,
      topic,
    });
  }

  private blobToBase64(blob: Blob): Promise<string> {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onerror = () => reject(reader.error || new Error('Blob read failed'));
      reader.onloadend = () => {
        const value = String(reader.result || '');
        resolve(value.includes(',') ? value.split(',')[1] : value);
      };
      reader.readAsDataURL(blob);
    });
  }

  private handleData(payload: Uint8Array, kind?: number, topic?: string): void {
    if (topic && ![this.topics.events, this.topics.metrics, this.topics.chat].includes(topic)) {
      return;
    }
    try {
      const decoded = JSON.parse(this.decoder.decode(payload)) as VoiceSessionEvent;
      this.eventsSubject.next(decoded);
    } catch {
      this.emit('session.error', {
        code: 'invalid_livekit_event',
        transport: 'livekit',
        topic: topic || null,
        reliable: kind === this.reliableDataKind,
      });
    }
  }

  private emit(type: VoiceSessionEventType, payload: Record<string, unknown>): void {
    this.eventsSubject.next({
      id: crypto.randomUUID?.() || String(Date.now()),
      session_id: String(this.token.metadata['agentium_session_id'] || ''),
      type,
      ts_ms: Date.now(),
      sequence: 0,
      payload,
    });
  }
}

@Injectable({ providedIn: 'root' })
export class LiveKitConversationService {
  private readonly api = inject(ApiService);

  async config(): Promise<LiveKitConfig> {
    return firstValueFrom(this.api.get<LiveKitConfig>('/livekit/config'));
  }

  async open(sessionId: string, options: LiveKitOpenOptions = {}): Promise<LiveKitConversationConnection> {
    const config = await this.config();
    if (!config.enabled || !config.configured || !config.url) {
      throw new Error('LiveKit transport is not enabled for this workspace.');
    }
    const token = await firstValueFrom(
      this.api.post<LiveKitTokenResponse>('/livekit/token', {
        session_id: sessionId,
        surface: options.surface || 'knowledge_capture',
        mode: options.mode || 'conversation_only',
        participant_name: options.participantName || null,
        ensure_room: true,
        metadata: options.metadata || {},
      }),
    );
    const livekit = await import('livekit-client');
    const room = new livekit.Room({ adaptiveStream: false, dynacast: false });
    let connection: LiveKitConversationConnection | null = null;
    try {
      await room.connect(token.url || config.url, token.token, { autoSubscribe: true });
      connection = new LiveKitConversationConnection(
        room,
        token,
        config.topics,
        { DataReceived: livekit.RoomEvent.DataReceived, Disconnected: livekit.RoomEvent.Disconnected },
        livekit.DataPacket_Kind.RELIABLE,
      );
      if (options.publishMicrophone ?? true) {
        await connection.enableMicrophone(true);
      }
      connection.start({ ...options, transport: 'livekit' });
      if (options.dispatchAgent ?? true) {
        const dispatch = await firstValueFrom(
          this.api.post<LiveKitAgentDispatchResponse>(`/livekit/sessions/${encodeURIComponent(sessionId)}/agent/dispatch`, {
            surface: options.surface || 'knowledge_capture',
            mode: options.mode || 'conversation_only',
            destination_identity: token.identity,
            mock_partial_text: options.mockPartialText || null,
            metadata: options.metadata || {},
          }),
        );
        if ((options.requireVoiceGateway ?? true) && dispatch.mode !== 'voice_gateway_bridge') {
          throw new Error(`LiveKit voice gateway bridge is unavailable (${dispatch.mode}).`);
        }
      }
      return connection;
    } catch (error) {
      if (connection) {
        await connection.close().catch(() => undefined);
      } else {
        await room.disconnect(true).catch(() => undefined);
      }
      throw error;
    }
  }
}

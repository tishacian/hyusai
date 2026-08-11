import { Injectable, inject } from '@angular/core';
import type { Room as LiveKitRoom } from 'livekit-client';
import { Observable, Subject, firstValueFrom } from 'rxjs';
import { ApiService } from './api.service';
import { VoiceEventReassembler } from './voice-frame-reassembly';
import { VoiceSessionEvent, VoiceSessionEventType, VoiceSessionStartOptions, VoiceFrameMeta } from './voice-session.service';
import { WorkspaceService, type WorkspaceRequestScope } from './workspace.service';

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

/** Terminal transport error: a caller must not fall back in the new workspace
 * with the session id captured in the previous one. */
export class WorkspaceChangedDuringTransportError extends Error {
  override readonly name = 'WorkspaceChangedDuringTransportError';

  constructor() {
    super('Workspace changed while opening the LiveKit conversation.');
  }
}

export class LiveKitConversationConnection {
  private readonly eventsSubject = new Subject<VoiceSessionEvent>();
  private readonly encoder = new TextEncoder();
  private readonly decoder = new TextDecoder();
  /** Rejoins the events the gateway had to cut up to fit a data packet. */
  private readonly frames = new VoiceEventReassembler();
  readonly events$: Observable<VoiceSessionEvent> = this.eventsSubject.asObservable();
  private closed = false;
  private invalidated = false;

  constructor(
    private readonly room: LiveKitRoom,
    private readonly token: LiveKitTokenResponse,
    private readonly topics: LiveKitConfig['topics'],
    private readonly roomEvents: { DataReceived: string; Disconnected: string },
    private readonly reliableDataKind: number,
    private readonly onClosed: () => void = () => undefined,
  ) {
    this.room
      .on(this.roomEvents.DataReceived as any, (payload: Uint8Array, _participant: unknown, kind?: number, topic?: string) => {
        if (this.invalidated) return;
        this.handleData(payload, kind, topic);
      })
      .on(this.roomEvents.Disconnected as any, (reason?: unknown) => {
        if (this.invalidated) return;
        this.emit('session.close', { reason: reason ?? null, transport: 'livekit' });
        this.markInvalidated();
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
      document_refs: meta.document_refs || [],
      visual_context: meta.visual_context || null,
      content_type: meta.content_type || blob.type || 'audio/webm',
      encoding: blob.type || 'audio/webm',
      duration_ms: 0,
      transport_note: 'browser_audio_fallback',
    });
  }

  async enableMicrophone(enabled = true): Promise<void> {
    if (this.invalidated) return;
    await this.room.localParticipant.setMicrophoneEnabled(enabled);
    if (this.invalidated) {
      if (enabled) {
        await this.room.localParticipant.setMicrophoneEnabled(false).catch(() => undefined);
      }
      return;
    }
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
      document_refs: meta.document_refs || [],
      visual_context: meta.visual_context || null,
      auto: Boolean(meta.auto),
      reason: meta.reason || null,
      capture_mode: meta.capture_mode || null,
      silence_ms: meta.silence_ms ?? null,
      min_speech_ms: meta.min_speech_ms ?? null,
      rms_threshold: meta.rms_threshold ?? null,
      endpoint_grace_ms: meta.endpoint_grace_ms ?? null,
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

  /** Push the current scene (pinned pieces + focused visual context) so the
   * gateway can resolve deictic anchors on realtime voice turns — the continuous
   * mic track never carries per-turn `visual_context` (mirror of section.select). */
  captureScene(payload: { visual_context: unknown; document_refs: unknown[] }): void {
    void this.sendControl('capture.scene', payload);
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

  clientMetric(payload: Record<string, unknown> = {}): void {
    void this.sendControl('client.metric', payload);
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
    if (this.invalidated) return Promise.resolve();
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
    if (this.invalidated) return;
    // Start the graceful close frame while publishing is still allowed, then
    // suppress every inbound callback before awaiting network teardown.
    const closeFrame = this.sendControl('session.close', {}).catch(() => undefined);
    this.markInvalidated();
    try {
      await closeFrame;
      await this.room.localParticipant.setMicrophoneEnabled(false).catch(() => undefined);
      await this.room.disconnect(true);
    } catch {
      // The connection is already terminal locally; teardown is best effort.
    }
  }

  /** Synchronous workspace-boundary teardown. */
  invalidate(): void {
    if (!this.markInvalidated()) return;
    void Promise.allSettled([
      this.room.localParticipant.setMicrophoneEnabled(false),
      this.room.disconnect(true),
    ]);
  }

  private publish(topic: string, event: Record<string, unknown>): Promise<void> {
    if (this.invalidated) return Promise.resolve();
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
    if (this.invalidated) return;
    if (topic && ![this.topics.events, this.topics.metrics, this.topics.chat].includes(topic)) {
      return;
    }
    try {
      const decoded = JSON.parse(this.decoder.decode(payload)) as VoiceSessionEvent;
      // A framed answer or audio payload is rejoined here, so a subscriber never
      // sees a slice of one. Null means the payload is still incomplete.
      const whole = this.frames.accept(decoded);
      if (whole) this.eventsSubject.next(whole);
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
    if (this.invalidated) return;
    this.eventsSubject.next({
      id: crypto.randomUUID?.() || String(Date.now()),
      session_id: String(this.token.metadata['agentium_session_id'] || ''),
      type,
      ts_ms: Date.now(),
      sequence: 0,
      payload,
    });
  }

  private notifyClosed(): void {
    if (this.closed) return;
    this.closed = true;
    this.onClosed();
  }

  private markInvalidated(): boolean {
    if (this.invalidated) return false;
    this.invalidated = true;
    this.frames.reset();
    this.eventsSubject.complete();
    this.notifyClosed();
    return true;
  }
}

@Injectable({ providedIn: 'root' })
export class LiveKitConversationService {
  private readonly api = inject(ApiService);
  private readonly workspace = inject(WorkspaceService);
  private readonly activeConnections = new Set<LiveKitConversationConnection>();

  constructor() {
    this.workspace.registerContextReset(() => {
      const connections = [...this.activeConnections];
      this.activeConnections.clear();
      for (const connection of connections) connection.invalidate();
    });
  }

  async config(workspaceSlug = this.workspace.currentSlug()): Promise<LiveKitConfig> {
    return firstValueFrom(this.api.get<LiveKitConfig>(
      '/livekit/config',
      undefined,
      { workspaceSlug },
    ));
  }

  async open(sessionId: string, options: LiveKitOpenOptions = {}): Promise<LiveKitConversationConnection> {
    const scope = this.workspace.captureRequestScope();
    let room: LiveKitRoom | null = null;
    let connection: LiveKitConversationConnection | null = null;
    try {
      const config = await this.config(scope.workspaceSlug);
      this.assertCurrentScope(scope);
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
        }, { workspaceSlug: scope.workspaceSlug }),
      );
      this.assertCurrentScope(scope);

      const livekit = await import('livekit-client');
      this.assertCurrentScope(scope);
      const connectedRoom = new livekit.Room({ adaptiveStream: false, dynacast: false });
      room = connectedRoom;
      await connectedRoom.connect(token.url || config.url, token.token, { autoSubscribe: true });
      this.assertCurrentScope(scope);
      connection = new LiveKitConversationConnection(
        connectedRoom,
        token,
        config.topics,
        { DataReceived: livekit.RoomEvent.DataReceived, Disconnected: livekit.RoomEvent.Disconnected },
        livekit.DataPacket_Kind.RELIABLE,
        () => {
          if (connection) this.activeConnections.delete(connection);
        },
      );
      this.activeConnections.add(connection);
      // The participant and data handlers must exist before dispatch: the
      // gateway can publish session.ready/runtime.metric immediately.  Mic and
      // session.start remain after dispatch so fallback is still safe if the
      // gateway refuses the bridge.
      if (options.dispatchAgent ?? true) {
        const voiceSessionStart = {
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
        };
        const dispatch = await firstValueFrom(
          this.api.post<LiveKitAgentDispatchResponse>(`/livekit/sessions/${encodeURIComponent(sessionId)}/agent/dispatch`, {
            surface: options.surface || 'knowledge_capture',
            mode: options.mode || 'conversation_only',
            destination_identity: token.identity,
            mock_partial_text: options.mockPartialText || null,
            metadata: options.metadata || {},
            voice_session_start: voiceSessionStart,
          }, { workspaceSlug: scope.workspaceSlug }),
        );
        this.assertCurrentScope(scope);
        if ((options.requireVoiceGateway ?? true) && dispatch.mode !== 'voice_gateway_bridge') {
          throw new Error(`LiveKit voice gateway bridge is unavailable (${dispatch.mode}).`);
        }
      }
      if (options.publishMicrophone ?? true) {
        await connection.enableMicrophone(true);
      }
      this.assertCurrentScope(scope);
      connection.start({ ...options, transport: 'livekit' });
      return connection;
    } catch (error) {
      if (connection) {
        await connection.close().catch(() => undefined);
      } else if (room) {
        await room.disconnect(true).catch(() => undefined);
      }
      // A rejected await skips the success-path assertions above. Normalize
      // every such rejection after teardown as a workspace cancellation so a
      // caller can never interpret an A transport failure as permission to
      // open its backend-WS fallback with the same session id under B.
      if (
        error instanceof WorkspaceChangedDuringTransportError ||
        !this.workspace.isRequestScopeCurrent(scope)
      ) {
        throw error instanceof WorkspaceChangedDuringTransportError
          ? error
          : new WorkspaceChangedDuringTransportError();
      }
      throw error;
    }
  }

  private assertCurrentScope(scope: WorkspaceRequestScope): void {
    if (!this.workspace.isRequestScopeCurrent(scope)) {
      throw new WorkspaceChangedDuringTransportError();
    }
  }
}

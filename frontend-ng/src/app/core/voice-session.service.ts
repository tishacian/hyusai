import { Injectable, inject } from '@angular/core';
import { Observable, Subject } from 'rxjs';
import { TokenStorageService } from './token-storage.service';
import { WorkspaceService } from './workspace.service';

export type VoiceSessionEventType =
  | 'session.ready'
  | 'session.start'
  | 'audio.frame'
  | 'audio.endpoint'
  | 'audio.out'
  | 'text.partial'
  | 'text.final'
  | 'translation.partial'
  | 'translation.final'
  | 'evaluation.delta'
  | 'prompt.next'
  | 'barge_in'
  | 'oracle.action'
  | 'runtime.metric'
  | 'session.error'
  | 'session.close';

export interface VoiceSessionEvent {
  id: string;
  session_id: string;
  type: VoiceSessionEventType | string;
  ts_ms: number;
  sequence: number;
  payload: Record<string, any>;
}

export interface VoiceSessionStartOptions {
  runtime?: string;
  provider?: string;
  model?: string | null;
  transport?: 'backend_ws' | 'webrtc' | string;
  language?: string | null;
  output_language?: string | null;
  fallback_policy?: string | null;
  capability?: string;
  context_id?: string | null;
  system_id?: string | null;
  mode?: 'manual' | 'conversation_only';
  codec?: {
    input: string;
    sample_rate?: number;
    channels?: number;
  };
}

export interface VoiceFrameMeta {
  turn_id?: string | null;
  question_id?: string | null;
  retrieval_event_id?: string | null;
  interruption_of_event_id?: string | null;
  content_type?: string | null;
}

export class VoiceSessionConnection {
  private readonly eventsSubject = new Subject<VoiceSessionEvent>();
  private readonly pending: string[] = [];
  readonly events$: Observable<VoiceSessionEvent> = this.eventsSubject.asObservable();

  constructor(private readonly socket: WebSocket) {
    this.socket.onopen = () => {
      while (this.pending.length && this.socket.readyState === WebSocket.OPEN) {
        this.socket.send(this.pending.shift()!);
      }
    };
    this.socket.onmessage = (message) => {
      try {
        this.eventsSubject.next(JSON.parse(String(message.data)) as VoiceSessionEvent);
      } catch {
        this.eventsSubject.next({
          id: crypto.randomUUID?.() || String(Date.now()),
          session_id: '',
          type: 'session.error',
          ts_ms: Date.now(),
          sequence: 0,
          payload: { code: 'invalid_event', message: String(message.data) },
        });
      }
    };
    this.socket.onerror = () => {
      this.eventsSubject.next({
        id: crypto.randomUUID?.() || String(Date.now()),
        session_id: '',
        type: 'session.error',
        ts_ms: Date.now(),
        sequence: 0,
        payload: { code: 'transport_error', message: 'Voice WebSocket transport error.' },
      });
    };
    this.socket.onclose = () => this.eventsSubject.complete();
  }

  start(options: VoiceSessionStartOptions): void {
    this.send('session.start', {
      runtime: options.runtime || options.provider || 'cascade_openai',
      provider: options.provider || options.runtime || 'cascade_openai',
      model: options.model || null,
      transport: options.transport || 'backend_ws',
      language: options.language || null,
      output_language: options.output_language || null,
      fallback_policy: options.fallback_policy || 'cascade_openai',
      capability: options.capability || 'voice2voice_interaction',
      context_id: options.context_id || null,
      system_id: options.system_id || null,
      mode: options.mode || 'conversation_only',
      codec: options.codec || { input: 'webm', channels: 1 },
    });
  }

  async sendAudioFrame(blob: Blob, meta: VoiceFrameMeta): Promise<void> {
    const bytes_b64 = await this.blobToBase64(blob);
    this.send('audio.frame', {
      bytes_b64,
      turn_id: meta.turn_id,
      question_id: meta.question_id,
      retrieval_event_id: meta.retrieval_event_id,
      interruption_of_event_id: meta.interruption_of_event_id,
      content_type: meta.content_type || blob.type || 'audio/webm',
      encoding: blob.type || 'audio/webm',
      duration_ms: 0,
    });
  }

  endpoint(meta: VoiceFrameMeta): void {
    this.send('audio.endpoint', {
      turn_id: meta.turn_id,
      question_id: meta.question_id,
      retrieval_event_id: meta.retrieval_event_id,
      interruption_of_event_id: meta.interruption_of_event_id,
    });
  }

  bargeIn(promptEventId?: string | null): void {
    this.send('barge_in', { prompt_event_id: promptEventId || null });
  }

  close(): void {
    if (this.socket.readyState === WebSocket.OPEN) {
      this.send('session.close', {});
    }
    this.socket.close();
  }

  private send(type: VoiceSessionEventType, payload: Record<string, any>): void {
    const frame = JSON.stringify({
      id: crypto.randomUUID?.() || String(Date.now()),
      type,
      ts_ms: Date.now(),
      payload,
    });
    if (this.socket.readyState === WebSocket.OPEN) {
      this.socket.send(frame);
    } else if (this.socket.readyState === WebSocket.CONNECTING) {
      this.pending.push(frame);
    }
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
}

@Injectable({ providedIn: 'root' })
export class VoiceSessionService {
  private readonly tokenStorage = inject(TokenStorageService);
  private readonly workspace = inject(WorkspaceService);

  open(sessionId: string): VoiceSessionConnection {
    const token = this.tokenStorage.getToken();
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = new URL(`${protocol}//${window.location.host}/api/v1/voice/sessions/${encodeURIComponent(sessionId)}`);
    if (token) url.searchParams.set('token', token);
    const workspaceSlug = this.workspace.currentSlug();
    if (workspaceSlug) url.searchParams.set('workspace_slug', workspaceSlug);
    return new VoiceSessionConnection(new WebSocket(url.toString()));
  }
}

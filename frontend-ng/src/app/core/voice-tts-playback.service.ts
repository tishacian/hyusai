import { Injectable, inject, signal } from '@angular/core';
import { Subscription } from 'rxjs';
import { ApiService } from './api.service';

export type VoiceTtsLatencyProfile = 'fast' | 'balanced' | 'quality' | string;
export type VoiceTtsState = 'idle' | 'preparing' | 'queued' | 'speaking' | 'paused' | 'interrupted' | 'error';

export interface VoiceOutputConfig {
  latency_profile?: VoiceTtsLatencyProfile | null;
  voice?: string | null;
  flush_first_chars?: number | null;
  flush_next_chars?: number | null;
  flush_timeout_ms?: number | null;
  interrupt_on_user_speech?: boolean | null;
}

export interface VoiceTtsMetric {
  surface: string;
  chars: number;
  latency_profile: VoiceTtsLatencyProfile;
  duration_ms?: number;
  time_to_first_audio_ms?: number;
  fallback?: boolean;
}

export interface VoiceTtsPlaybackOptions {
  surface: string;
  provider?: string | null;
  config?: VoiceOutputConfig | null;
  onState?: (state: VoiceTtsState) => void;
  onStarted?: (metric: VoiceTtsMetric) => void;
  onEnded?: (metric: VoiceTtsMetric) => void;
  onInterrupted?: (reason: string) => void;
  onMetric?: (metric: VoiceTtsMetric) => void;
  onNotice?: (message: string | null, tone?: 'info' | 'warning' | 'error') => void;
}

interface ResolvedVoiceOutputConfig {
  latency_profile: VoiceTtsLatencyProfile;
  voice: string;
  flush_first_chars: number;
  flush_next_chars: number;
  flush_timeout_ms: number;
  interrupt_on_user_speech: boolean;
}

const DEFAULT_VOICE_OUTPUT: ResolvedVoiceOutputConfig = {
  latency_profile: 'fast',
  voice: 'nova',
  flush_first_chars: 24,
  flush_next_chars: 80,
  flush_timeout_ms: 900,
  interrupt_on_user_speech: true,
};

@Injectable({ providedIn: 'root' })
export class VoiceTtsPlaybackService {
  private readonly api = inject(ApiService);

  createController(owner: string): VoiceTtsPlaybackController {
    return new VoiceTtsPlaybackController(owner, this.api);
  }
}

export class VoiceTtsPlaybackController {
  readonly state = signal<VoiceTtsState>('idle');

  private options: VoiceTtsPlaybackOptions = { surface: 'unknown' };
  private config: ResolvedVoiceOutputConfig = { ...DEFAULT_VOICE_OUTPUT };
  private buffer = '';
  private flushedIdx = 0;
  private finishRequested = false;
  private firstFlushDone = false;
  private flushTimer: ReturnType<typeof setTimeout> | null = null;
  private activeAudio: HTMLAudioElement | null = null;
  private audioQueue: HTMLAudioElement[] = [];
  private audioUrls: string[] = [];
  private subscriptions: Subscription[] = [];
  private pendingRequests = 0;
  private playing = false;
  private paused = false;
  private aborted = false;
  private streamStartedAt = 0;
  private firstAudioAt = 0;
  private totalChars = 0;

  constructor(
    readonly owner: string,
    private readonly api: ApiService,
  ) {}

  begin(options: VoiceTtsPlaybackOptions): void {
    this.reset(true);
    this.options = options;
    this.config = this.normalizeConfig(options.config);
    this.streamStartedAt = performance.now();
    this.setState('preparing');
  }

  playText(text: string, options: VoiceTtsPlaybackOptions): void {
    this.begin(options);
    this.finish(text);
  }

  appendBuffer(buffer: string): void {
    if (this.aborted) return;
    this.buffer = buffer || '';
    this.scheduleFirstFlushTimer();
    this.considerFlush(false);
  }

  finish(buffer?: string): void {
    if (typeof buffer === 'string') {
      this.buffer = buffer;
    }
    this.finishRequested = true;
    this.clearFlushTimer();
    this.flushPending(true);
    this.completeIfIdle();
  }

  stop(reason = 'interrupted', emit = true): void {
    this.aborted = true;
    this.clearFlushTimer();
    this.subscriptions.forEach((sub) => sub.unsubscribe());
    this.subscriptions = [];
    this.pendingRequests = 0;
    this.audioQueue = [];
    if (this.activeAudio) {
      try {
        this.activeAudio.pause();
        this.activeAudio.currentTime = 0;
      } catch {
        /* browser cleanup only */
      }
    }
    this.activeAudio = null;
    this.playing = false;
    this.paused = false;
    this.revokeAudioUrls();
    this.setState(emit ? 'interrupted' : 'idle');
    if (emit) {
      this.options.onInterrupted?.(reason);
    }
  }

  reset(silent = true): void {
    this.stop('reset', !silent);
    this.buffer = '';
    this.flushedIdx = 0;
    this.finishRequested = false;
    this.firstFlushDone = false;
    this.aborted = false;
    this.streamStartedAt = 0;
    this.firstAudioAt = 0;
    this.totalChars = 0;
    this.setState('idle');
  }

  pause(): void {
    if (!this.activeAudio || this.paused) return;
    try {
      this.activeAudio.pause();
    } catch {
      /* ignore */
    }
    this.paused = true;
    this.setState('paused');
  }

  resume(): void {
    if (!this.paused) return;
    this.paused = false;
    if (this.activeAudio) {
      this.activeAudio.play().catch(() => {
        this.setState('error');
      });
    }
    this.setState(this.playing ? 'speaking' : 'queued');
    if (!this.playing) this.playNext();
  }

  togglePause(): void {
    if (this.paused) this.resume();
    else this.pause();
  }

  isSpeaking(): boolean {
    return this.playing || this.pendingRequests > 0 || this.audioQueue.length > 0;
  }

  destroy(): void {
    this.reset(true);
  }

  private normalizeConfig(config?: VoiceOutputConfig | null): ResolvedVoiceOutputConfig {
    return {
      latency_profile: String(config?.latency_profile || DEFAULT_VOICE_OUTPUT.latency_profile),
      voice: String(config?.voice || DEFAULT_VOICE_OUTPUT.voice),
      flush_first_chars: this.clampNumber(config?.flush_first_chars, 12, 240, DEFAULT_VOICE_OUTPUT.flush_first_chars),
      flush_next_chars: this.clampNumber(config?.flush_next_chars, 40, 600, DEFAULT_VOICE_OUTPUT.flush_next_chars),
      flush_timeout_ms: this.clampNumber(config?.flush_timeout_ms, 250, 5000, DEFAULT_VOICE_OUTPUT.flush_timeout_ms),
      interrupt_on_user_speech: config?.interrupt_on_user_speech !== false,
    };
  }

  private clampNumber(value: number | null | undefined, min: number, max: number, fallback: number): number {
    const num = Number(value);
    if (!Number.isFinite(num)) return fallback;
    return Math.max(min, Math.min(max, Math.round(num)));
  }

  private scheduleFirstFlushTimer(): void {
    if (this.firstFlushDone || this.flushTimer || this.flushedIdx >= this.buffer.length) return;
    this.flushTimer = setTimeout(() => {
      this.flushTimer = null;
      this.considerFlush(true);
    }, this.config.flush_timeout_ms);
  }

  private clearFlushTimer(): void {
    if (!this.flushTimer) return;
    clearTimeout(this.flushTimer);
    this.flushTimer = null;
  }

  private considerFlush(timerFired: boolean): void {
    if (this.aborted) return;
    const pending = this.buffer.slice(this.flushedIdx);
    if (!pending.trim()) return;
    if (!this.firstFlushDone) {
      const shouldFlush = timerFired || this.hasWeakBoundaryAfter(pending, this.config.flush_first_chars);
      if (pending.trim().length >= this.config.flush_first_chars && shouldFlush) {
        this.flushPending(false, this.config.flush_first_chars, true);
      }
      return;
    }
    if (pending.trim().length < this.config.flush_next_chars) return;
    this.flushPending(false, this.config.flush_next_chars, false);
  }

  private flushPending(force: boolean, minChars = 0, first = false): void {
    const pending = this.buffer.slice(this.flushedIdx);
    if (!pending.trim()) return;
    let length = force ? pending.length : this.findFlushLength(pending, minChars, first);
    if (length <= 0) return;
    length = Math.min(length, pending.length);
    const raw = pending.slice(0, length);
    const text = this.cleanText(raw);
    this.flushedIdx += length;
    if (!text) return;
    this.firstFlushDone = true;
    this.queueChunk(text);
    if (!force) this.scheduleFirstFlushTimer();
  }

  private findFlushLength(pending: string, minChars: number, first: boolean): number {
    const min = Math.max(1, minChars);
    if (pending.length < min) return 0;
    const boundary = first ? this.findWeakBoundary(pending, min) : this.findSentenceBoundary(pending, min);
    if (boundary > 0) return boundary;
    if (!first && pending.length < this.config.flush_next_chars * 2) return 0;
    const target = first ? Math.min(pending.length, Math.max(min, 96)) : Math.min(pending.length, this.config.flush_next_chars);
    return this.wordBoundary(pending, target);
  }

  private findWeakBoundary(text: string, minChars: number): number {
    const boundary = /[.,;:!?…\n]\s*/g;
    let match: RegExpExecArray | null;
    while ((match = boundary.exec(text)) !== null) {
      const end = match.index + match[0].length;
      if (end >= minChars) return end;
    }
    return 0;
  }

  private findSentenceBoundary(text: string, minChars: number): number {
    const sentenceEnd = /[.!?…]["')\]]*(\s|$)/g;
    let last = 0;
    let match: RegExpExecArray | null;
    while ((match = sentenceEnd.exec(text)) !== null) {
      const end = match.index + match[0].length;
      if (end >= minChars) last = end;
    }
    if (last > 0) return last;
    return this.findWeakBoundary(text, minChars);
  }

  private hasWeakBoundaryAfter(text: string, minChars: number): boolean {
    return this.findWeakBoundary(text, minChars) > 0;
  }

  private wordBoundary(text: string, target: number): number {
    const before = text.slice(0, target);
    const idx = before.lastIndexOf(' ');
    if (idx >= Math.max(12, target - 32)) return idx + 1;
    return target;
  }

  private cleanText(text: string): string {
    return text
      .replace(/[#*_`[\]|]/g, '')
      .replace(/\s+/g, ' ')
      .trim()
      .slice(0, 4000);
  }

  private queueChunk(text: string): void {
    if (this.aborted || !text) return;
    const startedAt = performance.now();
    this.pendingRequests += 1;
    this.totalChars += text.length;
    this.setState(this.playing ? 'queued' : 'preparing');
    this.options.onNotice?.(this.playing ? 'Voice chunk queued.' : 'Preparing voice.', 'info');
    const sub = this.api
      .synthesizeSpeech(text, this.config.voice, this.options.provider, {
        latency_profile: String(this.config.latency_profile),
        surface: this.options.surface,
        format: 'mp3',
      })
      .subscribe({
        next: (blob) => {
          this.pendingRequests = Math.max(0, this.pendingRequests - 1);
          if (this.aborted) return;
          const url = URL.createObjectURL(blob);
          this.audioUrls.push(url);
          const audio = new Audio(url);
          audio.onended = () => this.onAudioEnded(audio);
          audio.onerror = () => this.onAudioEnded(audio);
          this.audioQueue.push(audio);
          this.options.onMetric?.({
            surface: this.options.surface,
            chars: text.length,
            latency_profile: this.config.latency_profile,
            duration_ms: Math.round(performance.now() - startedAt),
          });
          if (!this.playing && !this.paused) this.playNext();
          else this.setState('queued');
        },
        error: () => {
          this.pendingRequests = Math.max(0, this.pendingRequests - 1);
          if (!this.aborted) {
            this.options.onNotice?.('Voice synthesis skipped a chunk.', 'warning');
            this.completeIfIdle();
          }
        },
      });
    this.subscriptions.push(sub);
  }

  private playNext(): void {
    if (this.aborted || this.paused) return;
    const next = this.audioQueue.shift();
    if (!next) {
      this.playing = false;
      this.completeIfIdle();
      return;
    }
    this.activeAudio = next;
    this.playing = true;
    this.setState('speaking');
    if (!this.firstAudioAt) {
      this.firstAudioAt = performance.now();
      this.options.onStarted?.({
        surface: this.options.surface,
        chars: this.totalChars,
        latency_profile: this.config.latency_profile,
        time_to_first_audio_ms: Math.round(this.firstAudioAt - this.streamStartedAt),
      });
    }
    next.play().catch(() => {
      this.onAudioEnded(next);
    });
  }

  private onAudioEnded(audio: HTMLAudioElement): void {
    if (this.activeAudio === audio) this.activeAudio = null;
    this.playing = false;
    this.playNext();
  }

  private completeIfIdle(): void {
    if (!this.finishRequested || this.playing || this.pendingRequests > 0 || this.audioQueue.length > 0) {
      if (!this.playing && this.pendingRequests > 0) this.setState('preparing');
      return;
    }
    this.setState('idle');
    this.options.onNotice?.(null);
    this.options.onEnded?.({
      surface: this.options.surface,
      chars: this.totalChars,
      latency_profile: this.config.latency_profile,
      duration_ms: Math.round(performance.now() - this.streamStartedAt),
      time_to_first_audio_ms: this.firstAudioAt ? Math.round(this.firstAudioAt - this.streamStartedAt) : undefined,
    });
    this.revokeAudioUrls();
  }

  private revokeAudioUrls(): void {
    this.audioUrls.forEach((url) => {
      try {
        URL.revokeObjectURL(url);
      } catch {
        /* ignore */
      }
    });
    this.audioUrls = [];
  }

  private setState(state: VoiceTtsState): void {
    this.state.set(state);
    this.options.onState?.(state);
  }
}

import { Injectable, signal } from '@angular/core';

export type VoiceLoopState =
  | 'idle'
  | 'arming'
  | 'listening'
  | 'endpointing'
  | 'transcribing'
  | 'thinking'
  | 'speaking'
  | 'cooldown'
  | 'paused'
  | 'error';

export type VoiceLoopEndpointReason = 'manual' | 'silence' | 'max_turn' | 'no_speech' | 'pause' | 'stop' | 'error';

export interface VoiceLoopTurnConfig {
  autoEndpoint?: boolean;
  mimeType?: string;
  timesliceMs?: number;
  silenceMs?: number;
  minSpeechMs?: number;
  maxTurnMs?: number;
  rmsThreshold?: number;
  stream?: MediaStream | null;
  releaseStreamOnStop?: boolean;
  onChunk?: (blob: Blob) => void;
  onEndpoint?: (blob: Blob, reason: VoiceLoopEndpointReason) => void;
  onSpeechStart?: () => void;
  onNotice?: (message: string | null) => void;
  onState?: (state: VoiceLoopState) => void;
  onError?: (message: string) => void;
}

const DEFAULT_SILENCE_MS = 1200;
const DEFAULT_MIN_SPEECH_MS = 350;
const DEFAULT_MAX_TURN_MS = 45000;
const DEFAULT_RMS_THRESHOLD = 0.018;

export class VoiceLoopController {
  readonly state = signal<VoiceLoopState>('idle');
  readonly recording = signal(false);

  private recorder: MediaRecorder | null = null;
  private chunks: Blob[] = [];
  private stream: MediaStream | null = null;
  private releaseStreamOnStop = true;
  private endpointReason: VoiceLoopEndpointReason = 'manual';
  private raf: number | null = null;
  private audioContext: AudioContext | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private speechDetected = false;
  private lastVoiceAt = 0;
  private startedAt = 0;
  private emitEndpointOnStop = true;

  constructor(id: string) {
    void id;
  }

  async startTurn(config: VoiceLoopTurnConfig): Promise<boolean> {
    if (this.recording() || this.state() === 'arming') return false;
    if (typeof MediaRecorder === 'undefined') {
      config.onError?.('Audio recording is unavailable in this browser.');
      this.setState('error', config);
      return false;
    }

    this.setState('arming', config);
    this.endpointReason = 'manual';
    this.emitEndpointOnStop = true;
    this.chunks = [];

    try {
      this.stream = config.stream || await navigator.mediaDevices.getUserMedia({ audio: true });
      this.releaseStreamOnStop = config.releaseStreamOnStop ?? !config.stream;
      const recorder = this.createRecorder(this.stream, config.mimeType || 'audio/webm');
      this.recorder = recorder;
      recorder.ondataavailable = (event) => {
        if (event.data.size <= 0) return;
        this.chunks.push(event.data);
        config.onChunk?.(event.data);
      };
      recorder.onstop = () => {
        this.stopEndpointMonitor();
        if (this.releaseStreamOnStop) this.releaseStream();
        const blob = new Blob(this.chunks, { type: config.mimeType || 'audio/webm' });
        this.recording.set(false);
        if (this.emitEndpointOnStop) {
          this.setState('endpointing', config);
          config.onEndpoint?.(blob, this.endpointReason);
        } else {
          this.setState(this.endpointReason === 'pause' ? 'paused' : 'idle', config);
        }
      };
      if (config.timesliceMs && config.timesliceMs > 0) {
        recorder.start(config.timesliceMs);
      } else {
        recorder.start();
      }
      this.recording.set(true);
      this.setState('listening', config);
      if (config.autoEndpoint) this.startEndpointMonitor(config);
      return true;
    } catch {
      this.cleanupAfterFailure();
      config.onError?.('Microphone capture failed. Check the input device, then retry.');
      this.setState('error', config);
      return false;
    }
  }

  stopTurn(reason: VoiceLoopEndpointReason = 'manual', emitEndpoint = true): void {
    this.endpointReason = reason;
    this.emitEndpointOnStop = emitEndpoint;
    if (this.recorder?.state === 'recording') {
      this.recorder.stop();
      return;
    }
    this.stopEndpointMonitor();
    if (this.releaseStreamOnStop) this.releaseStream();
    this.recording.set(false);
  }

  pause(): void {
    this.stopTurn('pause', false);
    this.state.set('paused');
  }

  stopLoop(): void {
    this.stopTurn('stop', false);
    this.state.set('idle');
  }

  /**
   * Explicit, always-available hard stop for the continuous voice experience.
   * Distinct from the per-turn endpoint (`stopTurn`): it (a) cancels any
   * in-flight TTS via the supplied hook, (b) tears down the active recording
   * without emitting an endpoint so the captured audio is discarded, and
   * (c) disables auto-rearm via the supplied hook so the loop terminates and
   * does not re-listen.
   */
  hardStop(hooks: { cancelTts?: () => void; disableRearm?: () => void } = {}): void {
    hooks.disableRearm?.();
    hooks.cancelTts?.();
    this.stopTurn('stop', false);
    this.state.set('idle');
  }

  dispose(): void {
    this.stopEndpointMonitor();
    if (this.recorder?.state === 'recording') this.recorder.stop();
    this.releaseStream();
    this.recording.set(false);
    this.state.set('idle');
  }

  private createRecorder(stream: MediaStream, mimeType: string): MediaRecorder {
    try {
      if (MediaRecorder.isTypeSupported?.(mimeType)) {
        return new MediaRecorder(stream, { mimeType });
      }
    } catch {
      /* fallback below */
    }
    return new MediaRecorder(stream);
  }

  private startEndpointMonitor(config: VoiceLoopTurnConfig): void {
    this.stopEndpointMonitor();
    const AudioContextCtor = window.AudioContext || (window as any).webkitAudioContext;
    if (!AudioContextCtor || !this.stream) {
      config.onNotice?.('Auto endpoint unavailable');
      return;
    }

    try {
      const context = new AudioContextCtor() as AudioContext;
      const analyser = context.createAnalyser();
      analyser.fftSize = 1024;
      analyser.smoothingTimeConstant = 0.18;
      this.source = context.createMediaStreamSource(this.stream);
      this.source.connect(analyser);
      this.audioContext = context;
      this.speechDetected = false;
      this.startedAt = performance.now();
      this.lastVoiceAt = this.startedAt;
      config.onNotice?.('Auto endpoint listening');

      const data = new Uint8Array(analyser.fftSize);
      const silenceMs = config.silenceMs ?? DEFAULT_SILENCE_MS;
      const minSpeechMs = config.minSpeechMs ?? DEFAULT_MIN_SPEECH_MS;
      const maxTurnMs = config.maxTurnMs ?? DEFAULT_MAX_TURN_MS;
      const threshold = config.rmsThreshold ?? DEFAULT_RMS_THRESHOLD;

      const tick = () => {
        if (this.recorder?.state !== 'recording') return;
        analyser.getByteTimeDomainData(data);
        let sum = 0;
        for (const sample of data) {
          const normalized = (sample - 128) / 128;
          sum += normalized * normalized;
        }
        const rms = Math.sqrt(sum / data.length);
        const now = performance.now();
        const elapsed = now - this.startedAt;
        if (rms >= threshold) {
          if (!this.speechDetected) config.onSpeechStart?.();
          this.speechDetected = true;
          this.lastVoiceAt = now;
        }
        const reachedSilence = this.speechDetected && elapsed >= minSpeechMs && now - this.lastVoiceAt >= silenceMs;
        const reachedMax = elapsed >= maxTurnMs;
        const reachedNoSpeech = reachedMax && !this.speechDetected;
        if (reachedSilence || reachedMax) {
          config.onNotice?.(
            reachedNoSpeech
              ? 'No speech detected'
              : reachedSilence
                ? 'Silence detected'
                : 'Max voice turn reached',
          );
          this.stopTurn(reachedNoSpeech ? 'no_speech' : reachedSilence ? 'silence' : 'max_turn');
          return;
        }
        this.raf = requestAnimationFrame(tick);
      };

      this.raf = requestAnimationFrame(tick);
    } catch {
      this.stopEndpointMonitor();
      config.onNotice?.('Auto endpoint unavailable');
    }
  }

  private stopEndpointMonitor(): void {
    if (this.raf !== null) {
      cancelAnimationFrame(this.raf);
      this.raf = null;
    }
    try {
      this.source?.disconnect();
    } catch {
      /* ignore */
    }
    const context = this.audioContext;
    this.source = null;
    this.audioContext = null;
    this.speechDetected = false;
    if (context && context.state !== 'closed') void context.close().catch(() => undefined);
  }

  private releaseStream(): void {
    this.stream?.getTracks().forEach((track) => track.stop());
    this.stream = null;
  }

  private cleanupAfterFailure(): void {
    this.stopEndpointMonitor();
    this.releaseStream();
    this.recorder = null;
    this.recording.set(false);
  }

  private setState(state: VoiceLoopState, config: VoiceLoopTurnConfig): void {
    this.state.set(state);
    config.onState?.(state);
  }
}

@Injectable({ providedIn: 'root' })
export class VoiceLoopControllerFactory {
  create(id: string): VoiceLoopController {
    return new VoiceLoopController(id);
  }
}

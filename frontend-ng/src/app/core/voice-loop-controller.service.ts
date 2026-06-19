import { Injectable, signal } from '@angular/core';
import { VoiceCaptureMode } from './voice-capture-config';

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
  captureMode?: VoiceCaptureMode;
  endpointGraceMs?: number;
  vadHangoverMs?: number;
  vadCalibrationMs?: number;
  vadMinSilenceFramesMs?: number;
  stream?: MediaStream | null;
  releaseStreamOnStop?: boolean;
  onChunk?: (blob: Blob) => void;
  onEndpoint?: (blob: Blob, reason: VoiceLoopEndpointReason) => void;
  onSpeechStart?: () => void;
  onMetric?: (payload: Record<string, unknown>) => void;
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
  private lastChunkAt = 0;
  private lastVadMetricAt = 0;
  private noiseFloor = 0;
  private speechAboveSince = 0;
  private silenceBelowSince = 0;
  private endpointCandidateTimer: ReturnType<typeof setTimeout> | null = null;
  private endpointCandidateReason: VoiceLoopEndpointReason | null = null;
  private endpointCandidateStartedAt = 0;

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
    this.lastChunkAt = 0;

    try {
      this.stream = config.stream || await navigator.mediaDevices.getUserMedia({ audio: true });
      this.releaseStreamOnStop = config.releaseStreamOnStop ?? !config.stream;
      const recorder = this.createRecorder(this.stream, config.mimeType || 'audio/webm');
      this.recorder = recorder;
      recorder.ondataavailable = (event) => {
        if (event.data.size <= 0) return;
        const chunkAt = performance.now();
        if (this.lastChunkAt > 0) {
          config.onMetric?.({
            metric: 'chunk_gap_ms',
            value_ms: Math.round(chunkAt - this.lastChunkAt),
            chunk_gap_ms: Math.round(chunkAt - this.lastChunkAt),
            chunk_size: event.data.size,
            capture_mode: config.captureMode || 'normal',
          });
        }
        this.lastChunkAt = chunkAt;
        config.onMetric?.({
          metric: 'chunk_size',
          value: event.data.size,
          chunk_size: event.data.size,
          capture_mode: config.captureMode || 'normal',
        });
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

  disableAutoEndpoint(): void {
    this.stopEndpointMonitor();
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
      this.lastVadMetricAt = 0;
      this.noiseFloor = 0;
      this.speechAboveSince = 0;
      this.silenceBelowSince = 0;
      config.onNotice?.('Auto endpoint listening');

      const data = new Uint8Array(analyser.fftSize);
      const silenceMs = config.silenceMs ?? DEFAULT_SILENCE_MS;
      const minSpeechMs = config.minSpeechMs ?? DEFAULT_MIN_SPEECH_MS;
      const maxTurnMs = config.maxTurnMs ?? DEFAULT_MAX_TURN_MS;
      const threshold = config.rmsThreshold ?? DEFAULT_RMS_THRESHOLD;
      const captureMode = config.captureMode || 'normal';
      const endpointGraceMs = Math.max(0, config.endpointGraceMs ?? 0);
      const vadHangoverMs = Math.max(0, config.vadHangoverMs ?? 0);
      const vadCalibrationMs = Math.max(0, config.vadCalibrationMs ?? 300);
      const vadMinSilenceFramesMs = Math.max(0, config.vadMinSilenceFramesMs ?? 0);

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
        const calibrating = elapsed <= vadCalibrationMs && !this.speechDetected;
        this.updateNoiseFloor(rms, calibrating || !this.speechDetected);
        const speechThreshold = Math.max(threshold, this.noiseFloor * 2.6 + 0.004);
        const silenceThreshold = Math.max(this.noiseFloor * 1.7 + 0.002, speechThreshold * 0.62);
        if (rms >= speechThreshold) {
          if (this.speechAboveSince <= 0) this.speechAboveSince = now;
          this.silenceBelowSince = 0;
        } else {
          this.speechAboveSince = 0;
          if (rms <= silenceThreshold) {
            if (this.silenceBelowSince <= 0) this.silenceBelowSince = now;
          } else {
            this.silenceBelowSince = 0;
          }
        }
        const speechStable = this.speechAboveSince > 0 && now - this.speechAboveSince >= 80;
        if (speechStable) {
          if (this.endpointCandidateReason) {
            this.cancelEndpointCandidate(config, 'voice_resumed');
          }
          if (!this.speechDetected) config.onSpeechStart?.();
          this.speechDetected = true;
          this.lastVoiceAt = now;
        }
        if (now - this.lastVadMetricAt >= 1000) {
          this.lastVadMetricAt = now;
          config.onMetric?.({
            metric: 'rms',
            value: Number(rms.toFixed(5)),
            rms: Number(rms.toFixed(5)),
            noise_floor: Number(this.noiseFloor.toFixed(5)),
            threshold: Number(speechThreshold.toFixed(5)),
            capture_mode: captureMode,
          });
        }
        const silenceStable =
          this.silenceBelowSince > 0 && now - this.silenceBelowSince >= vadMinSilenceFramesMs;
        const reachedSilence =
          this.speechDetected &&
          elapsed >= minSpeechMs &&
          silenceStable &&
          now - this.lastVoiceAt >= silenceMs + vadHangoverMs;
        const reachedMax = elapsed >= maxTurnMs;
        const reachedNoSpeech = reachedMax && !this.speechDetected;
        if (reachedMax) {
          config.onNotice?.(
            reachedNoSpeech
              ? 'No speech detected'
              : 'Max voice turn reached',
          );
          this.requestRecorderData();
          this.stopTurn(reachedNoSpeech ? 'no_speech' : 'max_turn');
          return;
        }
        if (reachedSilence && !this.endpointCandidateReason) {
          config.onNotice?.('Silence detected');
          this.scheduleEndpointCandidate(config, endpointGraceMs, {
            since_voice_ms: Math.round(now - this.lastVoiceAt),
            rms: Number(rms.toFixed(5)),
            threshold: Number(speechThreshold.toFixed(5)),
          });
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
    this.clearEndpointCandidate();
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
    this.noiseFloor = 0;
    this.speechAboveSince = 0;
    this.silenceBelowSince = 0;
    if (context && context.state !== 'closed') void context.close().catch(() => undefined);
  }

  private scheduleEndpointCandidate(
    config: VoiceLoopTurnConfig,
    endpointGraceMs: number,
    details: Record<string, unknown>,
  ): void {
    this.endpointCandidateReason = 'silence';
    this.endpointCandidateStartedAt = performance.now();
    config.onMetric?.({
      metric: 'endpoint_candidate',
      capture_mode: config.captureMode || 'normal',
      endpoint_reason: 'silence',
      silence_ms: config.silenceMs ?? DEFAULT_SILENCE_MS,
      min_speech_ms: config.minSpeechMs ?? DEFAULT_MIN_SPEECH_MS,
      endpoint_grace_ms: endpointGraceMs,
      ...details,
    });
    this.requestRecorderData();
    if (endpointGraceMs <= 0) {
      this.confirmEndpointCandidate(config);
      return;
    }
    this.endpointCandidateTimer = setTimeout(() => this.confirmEndpointCandidate(config), endpointGraceMs);
  }

  private confirmEndpointCandidate(config: VoiceLoopTurnConfig): void {
    if (!this.endpointCandidateReason || this.recorder?.state !== 'recording') return;
    const reason = this.endpointCandidateReason;
    const elapsed = Math.round(performance.now() - this.endpointCandidateStartedAt);
    this.clearEndpointCandidate();
    this.requestRecorderData();
    config.onMetric?.({
      metric: 'endpoint_confirmed',
      capture_mode: config.captureMode || 'normal',
      endpoint_reason: reason,
      endpoint_grace_ms: elapsed,
    });
    this.stopTurn(reason);
  }

  private cancelEndpointCandidate(config: VoiceLoopTurnConfig, reason: string): void {
    if (!this.endpointCandidateReason) return;
    const elapsed = Math.round(performance.now() - this.endpointCandidateStartedAt);
    this.clearEndpointCandidate();
    config.onMetric?.({
      metric: 'endpoint_cancelled',
      capture_mode: config.captureMode || 'normal',
      endpoint_reason: reason,
      endpoint_grace_ms: elapsed,
      cancelled: true,
    });
  }

  private clearEndpointCandidate(): void {
    if (this.endpointCandidateTimer !== null) {
      clearTimeout(this.endpointCandidateTimer);
      this.endpointCandidateTimer = null;
    }
    this.endpointCandidateReason = null;
    this.endpointCandidateStartedAt = 0;
  }

  private requestRecorderData(): void {
    const recorder = this.recorder as (MediaRecorder & { requestData?: () => void }) | null;
    if (!recorder || recorder.state !== 'recording' || typeof recorder.requestData !== 'function') return;
    try {
      recorder.requestData();
    } catch {
      /* best-effort flush before endpoint */
    }
  }

  private updateNoiseFloor(rms: number, preferFastAdapt: boolean): void {
    if (!Number.isFinite(rms)) return;
    if (this.noiseFloor <= 0) {
      this.noiseFloor = rms;
      return;
    }
    const alpha = preferFastAdapt ? 0.12 : 0.025;
    this.noiseFloor = this.noiseFloor * (1 - alpha) + rms * alpha;
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

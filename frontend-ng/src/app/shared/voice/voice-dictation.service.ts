/**
 * Push-to-talk dictation: hold the microphone, release, get text back.
 *
 * The pattern already existed, but privately, inside the cockpit chat panel's
 * correction composer. Extracting it here is what let the NAWA assistant speak
 * without carrying nine hundred lines of chat-panel voice orchestration with it.
 *
 * This is deliberately the *small* half of voice. The realtime stack — LiveKit
 * rooms, the agent sidecar, server-side streaming transcription with barge-in —
 * exists and is deployed, but its gateway drives the knowledge-capture state
 * machine (scenes, sections, grounded questions), not a question-answering
 * assistant. Until that gateway grows a second surface, a recorder and one POST
 * are the honest way to give an assistant a voice.
 */
import { inject, Injectable, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '@app/core/api.service';

export type DictationState = 'idle' | 'listening' | 'transcribing';

/** Why a dictation could not happen, in words a business user can act on. */
export class DictationUnavailable extends Error {
  constructor(
    readonly reason: 'unsupported' | 'denied' | 'silent' | 'failed',
    message: string,
  ) {
    super(message);
  }
}

@Injectable({ providedIn: 'root' })
export class VoiceDictationService {
  private readonly api = inject(ApiService);

  readonly state = signal<DictationState>('idle');

  private recorder: MediaRecorder | null = null;
  private stream: MediaStream | null = null;
  private chunks: Blob[] = [];
  /** Resolved by `MediaRecorder.onstop`, which is the only reliable end signal. */
  private closed: Promise<void> | null = null;

  /** False on browsers without `MediaRecorder` or a microphone API. */
  supported(): boolean {
    return typeof MediaRecorder !== 'undefined' && !!navigator.mediaDevices?.getUserMedia;
  }

  async start(): Promise<void> {
    if (this.state() !== 'idle') return;
    if (!this.supported()) {
      throw new DictationUnavailable('unsupported', 'This browser cannot record audio.');
    }
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      throw new DictationUnavailable('denied', 'Microphone access was declined.');
    }

    this.chunks = [];
    // Safari has historically refused the explicit mime type it advertises, so
    // the second form is a real fallback rather than defensive noise.
    let recorder: MediaRecorder;
    try {
      recorder = MediaRecorder.isTypeSupported('audio/webm')
        ? new MediaRecorder(this.stream, { mimeType: 'audio/webm' })
        : new MediaRecorder(this.stream);
    } catch {
      recorder = new MediaRecorder(this.stream);
    }

    this.closed = new Promise<void>((resolve) => {
      recorder.onstop = () => resolve();
    });
    recorder.ondataavailable = (event) => {
      if (event.data?.size) this.chunks.push(event.data);
    };
    recorder.start();
    this.recorder = recorder;
    this.state.set('listening');
  }

  /**
   * Stop recording and return what was said. Throws `DictationUnavailable` when
   * nothing was captured, so the caller can say so instead of silently sending
   * an empty question.
   */
  async stop(language = 'en'): Promise<string> {
    const recorder = this.recorder;
    if (!recorder || this.state() !== 'listening') return '';

    if (recorder.state !== 'inactive') recorder.stop();
    await this.closed;
    this.release();

    const chunks = this.chunks;
    this.chunks = [];
    if (!chunks.length) {
      this.state.set('idle');
      throw new DictationUnavailable('silent', 'Nothing was picked up by the microphone.');
    }

    this.state.set('transcribing');
    try {
      const blob = new Blob(chunks, { type: 'audio/webm' });
      const result = await firstValueFrom(
        this.api.transcribeAudio(blob, 'assistant-dictation.webm', null, language),
      );
      return (result?.text || '').trim();
    } catch {
      throw new DictationUnavailable('failed', 'The dictation could not be transcribed.');
    } finally {
      this.state.set('idle');
    }
  }

  /** Abandon a recording in progress; nothing is sent anywhere. */
  cancel(): void {
    if (this.recorder && this.recorder.state !== 'inactive') this.recorder.stop();
    this.release();
    this.chunks = [];
    this.state.set('idle');
  }

  /** Stopping the recorder is not enough: the tracks hold the recording indicator. */
  private release(): void {
    this.stream?.getTracks().forEach((track) => track.stop());
    this.stream = null;
    this.recorder = null;
  }
}

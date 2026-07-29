/**
 * Push-to-talk dictation that shows its work: the words appear while you speak,
 * then the release settles them.
 *
 * The pattern already existed, but privately, inside the cockpit chat panel's
 * correction composer. Extracting it here is what let the NAWA assistant speak
 * without carrying nine hundred lines of chat-panel voice orchestration with it.
 *
 * This is deliberately the *small* half of voice. The realtime stack — LiveKit
 * rooms, the agent sidecar, server-side streaming transcription with barge-in —
 * exists and is deployed, but its gateway drives the knowledge-capture state
 * machine (scenes, sections, grounded questions), not a question-answering
 * assistant. Until that gateway grows a second surface, a recorder and a few
 * POSTs are the honest way to give an assistant a voice.
 *
 * The live text is those few POSTs: the recorder hands over a slice every
 * PARTIAL_MS, and each slice triggers one transcription of everything captured
 * so far, which measured at ~0.8s for six seconds of speech. Re-reading the
 * whole recording is what lets the model revise its own earlier guesses, so
 * displayed words can change as context arrives — the same behaviour a
 * streaming recogniser shows through its interim results. One request is in
 * flight at a time, so a slow answer costs freshness rather than a queue.
 */
import { inject, Injectable, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '@app/core/api.service';

export type DictationState = 'idle' | 'listening' | 'transcribing';

/** How often the recorder hands over audio, and so how often the text refreshes. */
const PARTIAL_MS = 1500;

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
  /** What has been heard so far, refreshed while listening. Empty when idle. */
  readonly partial = signal('');

  private recorder: MediaRecorder | null = null;
  private stream: MediaStream | null = null;
  private chunks: Blob[] = [];
  /** Resolved by `MediaRecorder.onstop`, which is the only reliable end signal. */
  private closed: Promise<void> | null = null;
  /** One partial at a time: a slow answer should cost freshness, not pile up. */
  private drafting = false;

  /** False on browsers without `MediaRecorder` or a microphone API. */
  supported(): boolean {
    return typeof MediaRecorder !== 'undefined' && !!navigator.mediaDevices?.getUserMedia;
  }

  async start(language = 'en'): Promise<void> {
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
    this.partial.set('');
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
      if (!event.data?.size) return;
      this.chunks.push(event.data);
      void this.draftPartial(language);
    };
    // The timeslice is what turns one blob at the end into a running transcript.
    recorder.start(PARTIAL_MS);
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
      const said = (result?.text || '').trim();
      return said || this.partial();
    } catch {
      // The words already on screen were read from this same recording, so
      // losing the closing pass is no reason to lose the sentence.
      const shown = this.partial();
      if (shown) return shown;
      throw new DictationUnavailable('failed', 'The dictation could not be transcribed.');
    } finally {
      this.partial.set('');
      this.state.set('idle');
    }
  }

  /**
   * Transcribe everything captured so far, for display only. Skipped while a
   * previous pass is unanswered, and discarded if the recording ended meanwhile.
   */
  private async draftPartial(language: string): Promise<void> {
    if (this.drafting || this.state() !== 'listening' || !this.chunks.length) return;
    this.drafting = true;
    try {
      const blob = new Blob(this.chunks, { type: 'audio/webm' });
      const result = await firstValueFrom(
        this.api.transcribeAudio(blob, 'assistant-dictation-partial.webm', null, language),
      );
      const heard = (result?.text || '').trim();
      if (heard && this.state() === 'listening') this.partial.set(heard);
    } catch {
      // A dropped partial is invisible: the next slice asks again, and the
      // closing pass in `stop` is what the answer is actually built from.
    } finally {
      this.drafting = false;
    }
  }

  /** Abandon a recording in progress; nothing is sent anywhere. */
  cancel(): void {
    if (this.recorder && this.recorder.state !== 'inactive') this.recorder.stop();
    this.release();
    this.chunks = [];
    this.partial.set('');
    this.state.set('idle');
  }

  /** Stopping the recorder is not enough: the tracks hold the recording indicator. */
  private release(): void {
    this.stream?.getTracks().forEach((track) => track.stop());
    this.stream = null;
    this.recorder = null;
  }
}

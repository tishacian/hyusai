import { DestroyRef, Injectable, computed, inject, signal } from '@angular/core';
import { firstValueFrom, type Observable, type Subscription } from 'rxjs';
import {
  ApiService,
  type CaptureAnchorStatus,
  type CapturePinnedView,
  type CaptureSessionDocument,
  type CaptureShareLevelItem,
  type CaptureTurnRequest,
  type CaptureViewReference,
  type CaptureViewUpdateRequest,
} from '@app/core/api.service';
import {
  VoiceSessionService,
  type VoiceFrameMeta,
  type VoiceSessionConnection,
  type VoiceSessionEvent,
} from '@app/core/voice-session.service';
import {
  LiveKitConversationService,
  type LiveKitConversationConnection,
  type LiveKitOpenOptions,
} from '@app/core/livekit-conversation.service';

/**
 * CaptureEngine — the headless brain of the cockpit "Le Fil" capture
 * experience (Phase 1, D0). It owns the realtime connection lifecycle (reusing
 * the existing {@link VoiceSessionService} / {@link LiveKitConversationService})
 * and the HTTP turn/finalize plumbing (reusing {@link ApiService}), and
 * projects backend events into a set of **typed signals** that the disjoint
 * `capture-fil/` UI components bind to.
 *
 * The signal/method surface below is the stable contract for downstream agents
 * (Phases 2-6). Some method bodies are intentionally minimal or stubbed in
 * Phase 1 — but the shape must not change so the UI can bind today.
 *
 * Provided at the {@link CaptureFilShellComponent} level (not root), so the
 * engine and all surfaces share one instance scoped to the capture experience.
 */

/** A single timeline entry projected from the backend event ledger. */
export type CaptureFeedKind = 'speak' | 'note' | 'anchor';

export interface CaptureFeedItem {
  /** Stable client id (de-dupes partial→final upserts). */
  id: string;
  kind: CaptureFeedKind;
  /** `voice` (dictated / TTS) vs `text` (composer) — the two append-only channels (D3). */
  channel: 'voice' | 'text';
  speaker: 'expert' | 'system' | 'operator' | null;
  text: string;
  /** True while a streaming transcript is still partial. */
  partial: boolean;
  ts_ms: number;
  /** Backend ledger position (hydrated entries only); tiebreaks equal `ts_ms`. */
  seq?: number | null;
  turn_id?: string | null;
  /** Present when `kind === 'anchor'`: the journaled deictic reference. */
  view?: CaptureViewReference;
}

/** A calm, non-blocking Oracle suggestion (keep / ignore). */
export interface CaptureOracleItem {
  id: string;
  text: string;
  status: 'active' | 'open' | 'answered' | 'dismissed' | 'deferred';
  ts_ms: number;
}

/** Realtime connection lifecycle. */
export type CaptureConnectionState =
  | 'idle'
  | 'connecting'
  | 'connected'
  | 'reconnecting'
  | 'error'
  | 'closed';

/** End-of-capture finalize / background-index lifecycle (D5). */
export type CaptureFinalizeStage =
  | 'idle'
  | 'pending'
  | 'running'
  | 'indexing'
  | 'done'
  | 'failed';

export interface CaptureFinalizeState {
  stage: CaptureFinalizeStage;
  processed: number;
  total: number;
  message: string | null;
}

export interface CaptureConnectOptions {
  /** Transport for the realtime leg. Defaults to the backend WebSocket. */
  transport?: 'backend_ws' | 'livekit';
  /** Forwarded to LiveKit / voice session start. */
  livekit?: LiveKitOpenOptions;
  /** Open the mic on connect (voice capture). Default false (text-first). */
  publishMicrophone?: boolean;
}

/** Lightweight session identity shared across the autonomous capture surfaces. */
export interface CaptureSessionInfo {
  id: string;
  title?: string | null;
  objective?: string | null;
  status?: string | null;
  duration_minutes?: number | null;
  plan?: Record<string, unknown> | null;
  /** `plan_build` (topics built upfront) vs `free_conversation` (no plan). */
  plan_mode?: string | null;
  /** System this capture is scoped to (from `/systems/:id/capture`), if any. */
  system_id?: string | null;
}

/** Resolved deictic document context for a turn / voice frame (D3 / D6). */
export interface CaptureDocumentContext {
  /** Every pinned piece rides on the turn. */
  document_refs: Record<string, unknown>[];
  /** The focused ("EN SCÈNE") piece — the deictic visual context. */
  visual_context: Record<string, unknown> | null;
}

const FINALIZE_IDLE: CaptureFinalizeState = {
  stage: 'idle',
  processed: 0,
  total: 0,
  message: null,
};

@Injectable()
export class CaptureEngine {
  private readonly api = inject(ApiService);
  private readonly voiceSession = inject(VoiceSessionService);
  private readonly livekit = inject(LiveKitConversationService);
  private readonly destroyRef = inject(DestroyRef);

  private connection: VoiceSessionConnection | LiveKitConversationConnection | null = null;
  private eventsSub: Subscription | null = null;

  // ---- voice capture audio pump (D3) -------------------------------------
  private transport: 'backend_ws' | 'livekit' = 'backend_ws';
  private micStream: MediaStream | null = null;
  private recorder: MediaRecorder | null = null;
  /** Realtime-STT lane: the published track is transcribed by the sidecar, so
   * WebM frames are dropped and the client VAD never auto-endpoints. Set from
   * the `session.ready` payload (mirrors the v0 monolith). */
  private realtimeSttActive = false;
  private audioContext: AudioContext | null = null;
  private vadRaf: number | null = null;
  private vadSpeechDetected = false;
  private vadTurnStartedAt = 0;
  private vadLastVoiceAt = 0;
  private vadSilenceSince = 0;
  private vadNoiseFloor = 0;
  private readonly pendingFrameSends = new Set<Promise<void>>();
  /** Resolves the in-flight WS finalize once the proposal arrives (capture_finished). */
  private finalizeResolver: ((proposalId: string | null) => void) | null = null;
  private finalizeTimeout: ReturnType<typeof setTimeout> | null = null;

  private static readonly VAD_SILENCE_MS = 1800;
  private static readonly VAD_MIN_SPEECH_MS = 500;
  private static readonly VAD_MAX_TURN_MS = 45000;
  private static readonly VAD_RMS_THRESHOLD = 0.02;

  // ---- signal surface (the downstream-stable contract) -------------------

  private readonly _sessionId = signal<string | null>(null);
  private readonly _session = signal<CaptureSessionInfo | null>(null);
  private readonly _systemId = signal<string | null>(null);
  private readonly _documents = signal<CaptureSessionDocument[]>([]);
  private readonly _proposalId = signal<string | null>(null);
  private readonly _state = signal<CaptureConnectionState>('idle');
  private readonly _feed = signal<CaptureFeedItem[]>([]);
  private readonly _oracle = signal<CaptureOracleItem[]>([]);
  private readonly _viewReferences = signal<CaptureViewReference[]>([]);
  private readonly _pinnedViews = signal<CapturePinnedView[]>([]);
  private readonly _activeViewKey = signal<string | null>(null);
  private readonly _finalize = signal<CaptureFinalizeState>(FINALIZE_IDLE);
  private readonly _lastError = signal<string | null>(null);
  private readonly _micActive = signal(false);
  private readonly _micMuted = signal(false);

  /** Capture session this engine is bound to (null until `connect`). */
  readonly sessionId = this._sessionId.asReadonly();
  /** Richer session identity shared across the autonomous flow surfaces. */
  readonly session = this._session.asReadonly();
  /** System scope (from `/systems/:id/capture`); null at the capability level. */
  readonly systemId = this._systemId.asReadonly();
  /** Documents attached to the session (uploaded or referenced). */
  readonly documents = this._documents.asReadonly();
  /** Knowledge proposal id produced by {@link finalize}. */
  readonly proposalId = this._proposalId.asReadonly();
  /** Pinned pieces — "La Scène" (D3). */
  readonly scene = this._pinnedViews.asReadonly();
  /** Key of the focused ("EN SCÈNE") piece. */
  readonly activeViewKey = this._activeViewKey.asReadonly();
  /** Realtime connection lifecycle. */
  readonly connectionState = this._state.asReadonly();
  /** Append-only timeline of `speak | note | anchor` events. */
  readonly feed = this._feed.asReadonly();
  /** Calm Oracle suggestions. */
  readonly oracle = this._oracle.asReadonly();
  /** All journaled deictic view references (anchors), newest last. */
  readonly viewReferences = this._viewReferences.asReadonly();
  /** End-of-capture finalize / background-index progress. */
  readonly finalizeStage = this._finalize.asReadonly();
  /** Last transport / request error, surfaced for diagnostics. */
  readonly lastError = this._lastError.asReadonly();

  readonly connected = computed(() => this._state() === 'connected');
  /** Mic is capturing AND not muted-while-typing — drives the composer VU (D3). */
  readonly micActive = computed(() => this._micActive() && !this._micMuted());
  /** Anchors filtered to the timeline-relevant (non-discarded) set. */
  readonly anchors = computed(() =>
    this._viewReferences().filter((v) => v.status !== 'discarded'),
  );

  /** The single focused piece ("EN SCÈNE"); falls back to the first pin. */
  readonly activeView = computed<CapturePinnedView | null>(() => {
    const key = this._activeViewKey();
    const pins = this._pinnedViews();
    return pins.find((p) => p.key === key) ?? pins[0] ?? null;
  });

  /**
   * Deictic document context riding on each turn (D3 / D6): every pinned piece
   * becomes a `document_ref`; the focused piece is the `visual_context`.
   */
  readonly documentContext = computed<CaptureDocumentContext>(() => {
    const pins = this._pinnedViews();
    if (!pins.length) return { document_refs: [], visual_context: null };
    const focus = this.activeView();
    return {
      document_refs: pins.map((pin) => this.pinToRef(pin)),
      visual_context: focus ? this.pinToRef(focus) : null,
    };
  });

  constructor() {
    this.destroyRef.onDestroy(() => this.disconnect());
  }

  // ---- lifecycle ---------------------------------------------------------

  /**
   * Open the realtime connection for a capture session and start projecting
   * its events into the signals. Reuses the existing voice transports.
   */
  async connect(sessionId: string, options: CaptureConnectOptions = {}): Promise<void> {
    if (this.connection) this.disconnect();
    this._sessionId.set(sessionId);
    this._state.set('connecting');
    this._lastError.set(null);
    // Hydrate the existing Fil from the backend projection (D1 step C) BEFORE
    // going live, so re-entering a session shows the prior timeline and live WS
    // events upsert on top of it (WS stays the live source of truth).
    await this.hydrateFeed();
    this.transport = options.transport === 'livekit' ? 'livekit' : 'backend_ws';
    try {
      if (this.transport === 'livekit') {
        const connection = await this.livekit.open(sessionId, {
          surface: 'knowledge_capture',
          mode: 'conversation_only',
          publishMicrophone: options.publishMicrophone ?? false,
          ...(options.livekit ?? {}),
        });
        this.connection = connection;
        this.subscribe(connection.events$);
      } else {
        const connection = this.voiceSession.open(sessionId);
        this.connection = connection;
        this.subscribe(connection.events$);
        connection.start({ mode: 'conversation_only' });
      }
      this._state.set('connected');
      // Voice is captured continuously over the backend WS (D3). LiveKit instead
      // publishes a mic track when `publishMicrophone` is set, so no WebM pump.
      if (this.transport === 'backend_ws') void this.startMic();
    } catch (error) {
      this._state.set('error');
      this._lastError.set(this.errorMessage(error));
    }
  }

  /** Tear down the realtime connection. Safe to call repeatedly. */
  disconnect(): void {
    this.stopMic();
    this.realtimeSttActive = false;
    // A WS finalize in flight can never complete without the socket — resolve it
    // so the publish surface's await never hangs (it falls back to its error UI).
    if (this.finalizeResolver) this.settleFinalize(null);
    this.eventsSub?.unsubscribe();
    this.eventsSub = null;
    const connection = this.connection;
    this.connection = null;
    if (connection) {
      try {
        void (connection.close() as unknown);
      } catch {
        /* best-effort close */
      }
    }
    if (this._state() !== 'idle') this._state.set('closed');
  }

  // ---- voice capture audio pump (D3) -------------------------------------

  /**
   * Open the mic and pump WebM frames over the backend WS (D3 voice channel),
   * mirroring the v0 monolith's recorder: stream frames continuously tagged with
   * the deictic-aware {@link voiceFrameMeta} (so dictated "cette page…" resolves
   * against the pieces in scene), and let a client VAD endpoint the turn on
   * silence. In realtime-STT mode the published track is the source, so WebM
   * frames are dropped and the VAD never auto-endpoints. No-ops off the
   * backend_ws transport and degrades to text-only if the mic is unavailable.
   */
  async startMic(): Promise<void> {
    if (this.transport !== 'backend_ws') return;
    if (this.recorder || typeof MediaRecorder === 'undefined') return;
    const media = navigator.mediaDevices;
    if (!media?.getUserMedia) return;
    try {
      this.micStream = await media.getUserMedia({ audio: true });
    } catch (error) {
      this._lastError.set(this.errorMessage(error));
      return;
    }
    try {
      const recorder = new MediaRecorder(this.micStream);
      this.recorder = recorder;
      recorder.ondataavailable = (event) => this.onAudioChunk(event.data);
      recorder.start(1200);
      this._micActive.set(true);
      this.startVadMonitor();
    } catch (error) {
      this._lastError.set(this.errorMessage(error));
      this.stopMic();
    }
  }

  /** Stop the mic pump and release the device. Safe to call repeatedly. */
  stopMic(): void {
    this.stopVadMonitor();
    const recorder = this.recorder;
    this.recorder = null;
    if (recorder && recorder.state !== 'inactive') {
      try {
        recorder.stop();
      } catch {
        /* best-effort stop */
      }
    }
    const stream = this.micStream;
    this.micStream = null;
    stream?.getTracks().forEach((track) => track.stop());
    this._micActive.set(false);
  }

  /**
   * Mute-mic-while-typing gate (D3) — CONFIGURABLE, DEFAULT OFF. While muted,
   * captured frames are dropped (the typed text channel is never overwritten by
   * dictation) and the VAD suspends auto-endpointing.
   */
  setMicMuted(muted: boolean): void {
    this._micMuted.set(muted);
  }

  /**
   * Signal the current voice turn boundary to the backend (client endpointing,
   * D3). `auto` reasons (silence / max_turn) come from the client VAD; an
   * explicit 'manual' / 'stop' is a user action.
   */
  endpointTurn(reason: string): void {
    this.connection?.endpoint(this.voiceFrameMeta(reason));
  }

  private onAudioChunk(blob: Blob): void {
    if (!blob || blob.size <= 0) return;
    if (this.realtimeSttActive) return;
    if (this._micMuted()) return;
    const connection = this.connection;
    if (!connection) return;
    const send = connection
      .sendAudioFrame(blob, this.voiceFrameMeta())
      .catch((error: unknown) => this._lastError.set(this.errorMessage(error)));
    this.pendingFrameSends.add(send);
    void send.finally(() => this.pendingFrameSends.delete(send));
  }

  private startVadMonitor(): void {
    this.stopVadMonitor();
    const stream = this.micStream;
    if (!stream) return;
    const AudioContextCtor =
      window.AudioContext ||
      (window as Window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AudioContextCtor) return;
    let context: AudioContext;
    try {
      context = new AudioContextCtor();
    } catch {
      return;
    }
    this.audioContext = context;
    const analyser = context.createAnalyser();
    analyser.fftSize = 1024;
    analyser.smoothingTimeConstant = 0.18;
    context.createMediaStreamSource(stream).connect(analyser);
    const data = new Uint8Array(analyser.fftSize);
    this.vadSpeechDetected = false;
    this.vadTurnStartedAt = performance.now();
    this.vadLastVoiceAt = this.vadTurnStartedAt;
    this.vadSilenceSince = 0;
    this.vadNoiseFloor = 0;
    const tick = () => {
      if (!this.recorder || this.recorder.state !== 'recording') return;
      analyser.getByteTimeDomainData(data);
      let sum = 0;
      for (const sample of data) {
        const normalized = (sample - 128) / 128;
        sum += normalized * normalized;
      }
      const rms = Math.sqrt(sum / data.length);
      const now = performance.now();
      this.vadNoiseFloor =
        this.vadNoiseFloor <= 0 ? rms : this.vadNoiseFloor * 0.975 + rms * 0.025;
      const speechThreshold = Math.max(
        CaptureEngine.VAD_RMS_THRESHOLD,
        this.vadNoiseFloor * 2.6 + 0.004,
      );
      const silenceThreshold = Math.max(this.vadNoiseFloor * 1.7 + 0.002, speechThreshold * 0.62);
      if (rms >= speechThreshold) {
        this.vadSpeechDetected = true;
        this.vadLastVoiceAt = now;
        this.vadSilenceSince = 0;
      } else if (rms <= silenceThreshold) {
        if (this.vadSilenceSince <= 0) this.vadSilenceSince = now;
      } else {
        this.vadSilenceSince = 0;
      }
      // Realtime STT owns turn segmentation; muted-while-typing suspends it too.
      if (!this.realtimeSttActive && !this._micMuted()) {
        const elapsed = now - this.vadTurnStartedAt;
        const reachedSilence =
          this.vadSpeechDetected &&
          elapsed >= CaptureEngine.VAD_MIN_SPEECH_MS &&
          this.vadSilenceSince > 0 &&
          now - this.vadLastVoiceAt >= CaptureEngine.VAD_SILENCE_MS;
        const reachedMax = elapsed >= CaptureEngine.VAD_MAX_TURN_MS;
        if (reachedSilence || (reachedMax && this.vadSpeechDetected)) {
          this.flushRecorder();
          this.endpointTurn('silence');
          this.resetVadTurn(now);
        } else if (reachedMax) {
          this.resetVadTurn(now);
        }
      }
      this.vadRaf = requestAnimationFrame(tick);
    };
    this.vadRaf = requestAnimationFrame(tick);
  }

  private resetVadTurn(now: number): void {
    this.vadSpeechDetected = false;
    this.vadTurnStartedAt = now;
    this.vadLastVoiceAt = now;
    this.vadSilenceSince = 0;
  }

  private stopVadMonitor(): void {
    if (this.vadRaf !== null) {
      cancelAnimationFrame(this.vadRaf);
      this.vadRaf = null;
    }
    const context = this.audioContext;
    this.audioContext = null;
    if (context) void context.close().catch(() => undefined);
  }

  private flushRecorder(): void {
    const recorder = this.recorder as (MediaRecorder & { requestData?: () => void }) | null;
    if (!recorder || recorder.state !== 'recording' || typeof recorder.requestData !== 'function') {
      return;
    }
    try {
      recorder.requestData();
    } catch {
      /* best-effort flush before endpoint */
    }
  }

  // ---- turns -------------------------------------------------------------

  /**
   * Send a text turn through the composer (D3 text channel). Journals the turn
   * via HTTP, optimistically appends it to the feed, and merges any deictic
   * `view_references` the backend resolved for this turn into the anchors.
   */
  async sendTextTurn(
    text: string,
    options: Partial<Omit<CaptureTurnRequest, 'text'>> = {},
  ): Promise<void> {
    const sessionId = this._sessionId();
    const trimmed = text.trim();
    if (!sessionId || !trimmed) return;
    const turnId = options.client_turn_id ?? this.uid();
    this.appendFeed({
      id: turnId,
      kind: 'note',
      channel: 'text',
      speaker: options.speaker ?? 'expert',
      text: trimmed,
      partial: false,
      ts_ms: Date.now(),
      turn_id: turnId,
    });
    const context = this.documentContext();
    try {
      const response = await firstValueFrom(
        this.api.addCaptureTurn(sessionId, {
          speaker: options.speaker ?? 'expert',
          text: trimmed,
          input_modality: 'text',
          client_turn_id: turnId,
          ...(context.document_refs.length ? { document_refs: context.document_refs } : {}),
          ...(context.visual_context ? { visual_context: context.visual_context } : {}),
          ...options,
        }),
      );
      for (const ref of response?.view_references ?? []) {
        this.ingestViewReference(
          { ...ref, turn_id: ref.turn_id ?? turnId },
          { asFeed: true, channel: 'text' },
        );
      }
    } catch (error) {
      this._lastError.set(this.errorMessage(error));
    }
  }

  // ---- scene (La Scène / pins, D3) ---------------------------------------

  /** Pin a piece to the scene and focus it. Best-effort journals the view. */
  pinView(view: CapturePinnedView, options: { record?: boolean } = {}): void {
    this._pinnedViews.update((pins) =>
      pins.some((p) => p.key === view.key) ? pins : [...pins, view],
    );
    this._activeViewKey.set(view.key);
    if (options.record !== false) this.recordView(view);
  }

  /** Bring an already-pinned piece "EN SCÈNE". */
  focusView(key: string): void {
    if (this._pinnedViews().some((p) => p.key === key)) this._activeViewKey.set(key);
  }

  /** Remove a pinned piece; re-focuses the first remaining one. */
  unpinView(key: string): void {
    this._pinnedViews.update((pins) => pins.filter((p) => p.key !== key));
    if (this._activeViewKey() === key) {
      this._activeViewKey.set(this._pinnedViews()[0]?.key ?? null);
    }
  }

  /**
   * Document context for voice frames (D3 / D6). The realtime audio pump is
   * owned by the transport; attach this to each `VoiceFrameMeta` so dictated
   * deictic phrases resolve against the pieces currently in scene.
   */
  voiceFrameMeta(reason: string | null = null): VoiceFrameMeta {
    const context = this.documentContext();
    return {
      turn_id: null,
      question_id: null,
      retrieval_event_id: null,
      interruption_of_event_id: null,
      content_type: 'audio/webm',
      auto: reason != null && reason !== 'manual',
      reason,
      document_refs: context.document_refs,
      visual_context: context.visual_context,
    };
  }

  private recordView(view: CapturePinnedView): void {
    const sessionId = this._sessionId();
    if (!sessionId || !view.document_id) return;
    void firstValueFrom(
      this.api.recordCaptureDocumentView(sessionId, {
        document_id: view.document_id,
        collection: view.collection,
        collection_name: view.collection,
        filename: view.filename,
        title: view.title,
        page: view.page,
        slide: view.slide,
        image_index: view.image_index,
        association_mode: view.association_mode || 'active_view',
      }),
    ).catch(() => {
      /* view logging is audit metadata — never interrupt capture */
    });
  }

  private pinToRef(pin: CapturePinnedView): Record<string, unknown> {
    const ref: Record<string, unknown> = {
      document_id: pin.document_id,
      collection: pin.collection,
      collection_name: pin.collection,
      filename: pin.filename,
      title: pin.title,
      association_mode: pin.association_mode || 'active_view',
    };
    if (pin.page != null) ref['page'] = pin.page;
    if (pin.slide != null) ref['slide'] = pin.slide;
    if (pin.image_index != null) ref['image_index'] = pin.image_index;
    return ref;
  }

  // ---- session + documents store -----------------------------------------

  /**
   * Set the system scope for the autonomous flow (new sessions inherit it; the
   * dashboard filters by it). Read from the `/systems/:id/capture` route or the
   * `?systemId=` query param by the shell.
   */
  setSystemId(systemId: string | null): void {
    this._systemId.set(systemId || null);
  }

  /** Bind the engine to a session without opening the realtime leg. */
  setSession(info: CaptureSessionInfo | null): void {
    this._session.set(info);
    if (info?.id) this._sessionId.set(info.id);
    // Resuming a system-scoped session preserves the scope for downstream lists.
    if (info?.system_id) this._systemId.set(info.system_id);
  }

  /** Load (or refresh) the documents attached to the bound session. */
  async loadDocuments(): Promise<void> {
    const sessionId = this._sessionId();
    if (!sessionId) return;
    try {
      const payload = await firstValueFrom(this.api.listCaptureDocuments(sessionId));
      this.applyDocumentsPayload(payload);
    } catch (error) {
      this._lastError.set(this.errorMessage(error));
    }
  }

  /**
   * Hydrate the timeline from the backend feed projection (D1 step C) on session
   * load/resume, so re-entering a session shows the existing Fil. WS remains the
   * live source: live events upsert by turn/event id over the hydrated entries.
   */
  async hydrateFeed(): Promise<void> {
    const sessionId = this._sessionId();
    if (!sessionId) return;
    try {
      const payload = await firstValueFrom(this.api.getCaptureFeed(sessionId));
      const entries = payload?.feed ?? [];
      const items = entries.map<CaptureFeedItem>((entry) => ({
        id: entry.id,
        kind: entry.kind,
        channel: entry.channel === 'text' ? 'text' : 'voice',
        speaker: this.normalizeSpeakerOrNull(entry.speaker),
        text: entry.text ?? '',
        partial: false,
        ts_ms: entry.ts_ms ?? Date.now(),
        seq: entry.seq ?? null,
        turn_id: entry.turn_id ?? null,
        ...(entry.view ? { view: entry.view } : {}),
      }));
      this.mergeHydratedFeed(items);
      for (const entry of entries) {
        if (entry.kind === 'anchor' && entry.view) this.ingestViewReference(entry.view);
      }
    } catch (error) {
      this._lastError.set(this.errorMessage(error));
    }
  }

  private mergeHydratedFeed(items: CaptureFeedItem[]): void {
    if (!items.length) return;
    this._feed.update((existing) => {
      const byKey = new Map<string, CaptureFeedItem>(
        existing.map((item) => [`${item.kind}:${item.id}`, item]),
      );
      for (const item of items) {
        const key = `${item.kind}:${item.id}`;
        const prev = byKey.get(key);
        byKey.set(key, prev ? { ...prev, ...item } : item);
      }
      return Array.from(byKey.values()).sort(
        (a, b) => a.ts_ms - b.ts_ms || (a.seq ?? 0) - (b.seq ?? 0),
      );
    });
  }

  private applyDocumentsPayload(payload: unknown): void {
    const docs = (payload as { documents?: CaptureSessionDocument[] } | null)?.documents;
    if (Array.isArray(docs)) this._documents.set(docs.filter(Boolean));
  }

  /** Persist the end-of-capture share-level triage (D5 / T0.1). */
  async setShareLevels(items: CaptureShareLevelItem[]): Promise<void> {
    const sessionId = this._sessionId();
    if (!sessionId || !items.length) return;
    this._documents.update((docs) =>
      docs.map((doc) => {
        const match = items.find((i) => i.document_id === doc.document_id);
        return match ? { ...doc, share_level: match.share_level } : doc;
      }),
    );
    try {
      const payload = await firstValueFrom(this.api.setCaptureShareLevel(sessionId, items));
      this.applyDocumentsPayload(payload);
    } catch (error) {
      this._lastError.set(this.errorMessage(error));
    }
  }

  // ---- anchors -----------------------------------------------------------

  /**
   * Confirm / discard / rebind an anchor (D2 / T0.3). Optimistically patches
   * the local view reference, then persists via {@link ApiService.updateCaptureView}.
   */
  async updateView(eventId: string, body: CaptureViewUpdateRequest): Promise<void> {
    const sessionId = this._sessionId();
    if (!sessionId || !eventId) return;
    const optimisticStatus = this.statusForAction(body.action);
    const priorStatus = optimisticStatus
      ? this._viewReferences().find((r) => r.event_id === eventId)?.status ?? null
      : null;
    if (optimisticStatus) this.patchViewStatus(eventId, optimisticStatus);
    try {
      const updated = await firstValueFrom(this.api.updateCaptureView(sessionId, eventId, body));
      if (updated) this.ingestViewReference({ ...updated, event_id: updated.event_id ?? eventId });
    } catch (error) {
      // The POST failed: undo the optimistic patch so the chip reflects reality.
      if (optimisticStatus) this.patchViewStatus(eventId, priorStatus);
      this._lastError.set(this.errorMessage(error));
    }
  }

  /**
   * Client-only confirmation of a ghost anchor (D2): the backend already
   * journaled `confirmed` (1 view) — the 4200 ms countdown / "Confirmer" is a
   * pure UX layer with zero backend cost. Settles the local status only.
   */
  confirmAnchorLocal(eventId: string): void {
    if (!eventId) return;
    this._viewReferences.update((refs) =>
      refs.map((r) =>
        (r.event_id ?? r.turn_id) === eventId && (r.status == null || r.status === 'pending')
          ? { ...r, status: 'confirmed' }
          : r,
      ),
    );
  }

  // ---- finalize (stub — extended in Phase 4/6) ---------------------------

  /**
   * Kick off the end-of-capture finalize (D5): generate the knowledge proposal
   * (the report). Heavy indexing is a background concern that the report's
   * banner reflects via `capture.finalize.progress` WS events. Returns the
   * proposal id so the publish surface can route to the report.
   */
  async finalize(): Promise<string | null> {
    const sessionId = this._sessionId();
    if (!sessionId) return null;
    this._finalize.set({ ...FINALIZE_IDLE, stage: 'running', message: 'Génération de la synthèse…' });
    // Prefer the live WS path: the backend gateway streams honest
    // `capture.finalize.progress` stage events to the report banner and returns
    // the proposal via `conversation.step` (capture_finished). Fall back to the
    // HTTP proposal endpoint when offline.
    const connection = this.connection;
    if (connection && this._state() === 'connected' && this.transport === 'backend_ws') {
      return this.finalizeOverWs(connection);
    }
    return this.finalizeOverHttp(sessionId);
  }

  private async finalizeOverHttp(sessionId: string): Promise<string | null> {
    try {
      const payload = await firstValueFrom(this.api.createCaptureProposal(sessionId));
      const proposalId =
        (payload as { id?: string; proposal_id?: string } | null)?.id ??
        (payload as { proposal_id?: string } | null)?.proposal_id ??
        null;
      this._proposalId.set(proposalId);
      this._finalize.update((s) =>
        s.stage === 'failed'
          ? s
          : { ...s, stage: 'done', message: 'Rapport prêt — indexation en arrière-plan.' },
      );
      return proposalId;
    } catch (error) {
      this._lastError.set(this.errorMessage(error));
      this._finalize.set({ ...FINALIZE_IDLE, stage: 'failed', message: this.errorMessage(error) });
      return null;
    }
  }

  private finalizeOverWs(
    connection: VoiceSessionConnection | LiveKitConversationConnection,
  ): Promise<string | null> {
    return new Promise<string | null>((resolve) => {
      this.clearFinalizeWait();
      this.finalizeResolver = (proposalId) => resolve(proposalId);
      // Safety net: never hang the publish surface if the WS drops mid-finalize.
      this.finalizeTimeout = setTimeout(() => {
        this.finalizeResolver = null;
        this.finalizeTimeout = null;
        void this.finalizeOverHttp(this._sessionId() ?? '').then(resolve);
      }, 90000);
      connection.captureFinish();
    });
  }

  private settleFinalize(proposalId: string | null): void {
    const resolver = this.finalizeResolver;
    this.clearFinalizeWait();
    resolver?.(proposalId);
  }

  private clearFinalizeWait(): void {
    if (this.finalizeTimeout !== null) {
      clearTimeout(this.finalizeTimeout);
      this.finalizeTimeout = null;
    }
    this.finalizeResolver = null;
  }

  /** Keep / ignore an Oracle suggestion (calm, non-blocking — D3 / §5.1). */
  setOracleStatus(id: string, status: CaptureOracleItem['status']): void {
    this._oracle.update((items) => items.map((q) => (q.id === id ? { ...q, status } : q)));
  }

  /** Reset all session-scoped state (e.g. when leaving the capture). */
  reset(): void {
    this.disconnect();
    this._sessionId.set(null);
    this._session.set(null);
    this._documents.set([]);
    this._proposalId.set(null);
    this._feed.set([]);
    this._oracle.set([]);
    this._viewReferences.set([]);
    this._pinnedViews.set([]);
    this._activeViewKey.set(null);
    this._finalize.set(FINALIZE_IDLE);
    this._lastError.set(null);
    this._state.set('idle');
  }

  // ---- WS event dispatch -------------------------------------------------

  private subscribe(events$: Observable<VoiceSessionEvent>): void {
    this.eventsSub = events$.subscribe({
      next: (event: VoiceSessionEvent) => this.dispatch(event),
      error: (error: unknown) => {
        this._state.set('error');
        this._lastError.set(this.errorMessage(error));
      },
      complete: () => {
        if (this._state() === 'connected') this._state.set('closed');
      },
    });
  }

  /** Map a realtime event into the signal surface. */
  private dispatch(event: VoiceSessionEvent): void {
    const payload = event.payload ?? {};
    switch (event.type) {
      case 'session.ready':
        this.realtimeSttActive =
          payload['stt_mode'] === 'realtime' || payload['realtime_stt'] === true;
        break;
      case 'text.partial':
        this.upsertSpeak(event, payload, true);
        break;
      case 'text.final':
        this.upsertSpeak(event, payload, false);
        break;
      case 'capture.view.referenced':
        this.ingestViewReference(this.toViewReference(payload), { asFeed: true });
        break;
      case 'capture.finalize.progress':
        this.applyFinalizeProgress(payload);
        break;
      case 'conversation.step':
        this.applyConversationStep(payload);
        break;
      case 'oracle.delta':
      case 'oracle.commit':
        this.upsertOracle(payload);
        break;
      case 'session.error':
        this._lastError.set(String(payload['message'] ?? 'capture transport error'));
        break;
      case 'session.close':
        if (this._state() === 'connected') this._state.set('closed');
        break;
      default:
        break;
    }
  }

  private upsertSpeak(event: VoiceSessionEvent, payload: Record<string, unknown>, partial: boolean): void {
    const turnId = (payload['turn_id'] as string) || event.id;
    const text = String(payload['text'] ?? '');
    const speaker = this.normalizeSpeaker(payload['speaker']);
    this._feed.update((items) => {
      const idx = items.findIndex((item) => item.turn_id === turnId && item.kind === 'speak');
      const next: CaptureFeedItem = {
        id: turnId,
        kind: 'speak',
        channel: 'voice',
        speaker,
        text,
        partial,
        ts_ms: event.ts_ms || Date.now(),
        turn_id: turnId,
      };
      if (idx === -1) return [...items, next];
      const copy = items.slice();
      copy[idx] = { ...copy[idx], ...next };
      return copy;
    });
  }

  private applyConversationStep(payload: Record<string, unknown>): void {
    // End-of-capture: the gateway returns the built proposal here (after streaming
    // its capture.finalize.progress stages). Settle the in-flight WS finalize.
    if (payload['capture_finished']) {
      const proposal = payload['proposal'] as { id?: string } | null;
      const proposalId = proposal?.id ?? null;
      if (proposalId) this._proposalId.set(proposalId);
      this._finalize.update((s) =>
        s.stage === 'failed'
          ? s
          : { ...s, stage: 'done', message: 'Rapport prêt — indexation en arrière-plan.' },
      );
      this.settleFinalize(proposalId);
      return;
    }
    const text = String(payload['prompt'] ?? payload['text'] ?? '').trim();
    if (!text) return;
    this.appendFeed({
      id: (payload['event_id'] as string) || this.uid(),
      kind: 'speak',
      channel: 'voice',
      speaker: 'system',
      text,
      partial: false,
      ts_ms: Date.now(),
      turn_id: (payload['question_id'] as string) ?? null,
    });
  }

  private upsertOracle(payload: Record<string, unknown>): void {
    const id = String(payload['question_id'] ?? payload['id'] ?? this.uid());
    const text = String(payload['question_text'] ?? payload['text'] ?? '').trim();
    if (!text) return;
    const status = (payload['status'] as CaptureOracleItem['status']) || 'active';
    this._oracle.update((items) => {
      const idx = items.findIndex((item) => item.id === id);
      const next: CaptureOracleItem = { id, text, status, ts_ms: Date.now() };
      if (idx === -1) return [...items, next];
      const copy = items.slice();
      copy[idx] = next;
      return copy;
    });
  }

  private applyFinalizeProgress(payload: Record<string, unknown>): void {
    // The gateway streams free-form stage names (`start`, `report`, `done`,
    // `error`, …) with a human `label`. Map them onto the engine's lifecycle.
    const raw = String(payload['stage'] ?? 'running');
    const stage: CaptureFinalizeStage =
      raw === 'error'
        ? 'failed'
        : raw === 'done'
          ? 'done'
          : raw === 'indexing'
            ? 'indexing'
            : 'running';
    this._finalize.set({
      stage,
      processed: Number(payload['processed'] ?? 0) || 0,
      total: Number(payload['total'] ?? 0) || 0,
      message: (payload['label'] as string) ?? (payload['message'] as string) ?? null,
    });
  }

  /**
   * Merge a view reference into the anchors signal (keyed by event id, falling
   * back to turn id) and optionally append a matching `anchor` feed item.
   */
  private ingestViewReference(
    ref: CaptureViewReference,
    opts: { asFeed?: boolean; channel?: 'voice' | 'text' } = {},
  ): void {
    const key = ref.event_id ?? ref.turn_id ?? null;
    this._viewReferences.update((refs) => {
      const idx = key ? refs.findIndex((r) => (r.event_id ?? r.turn_id) === key) : -1;
      if (idx === -1) return [...refs, ref];
      const copy = refs.slice();
      copy[idx] = { ...copy[idx], ...ref };
      return copy;
    });
    if (opts.asFeed) {
      const feedId = ref.event_id ?? ref.turn_id ?? this.uid();
      this._feed.update((items) => {
        const idx = items.findIndex((i) => i.kind === 'anchor' && i.id === feedId);
        const next: CaptureFeedItem = {
          id: feedId,
          kind: 'anchor',
          channel: opts.channel ?? 'voice',
          speaker: null,
          text: ref.statement ?? ref.trigger_phrase ?? ref.title ?? ref.filename ?? 'view referenced',
          partial: false,
          ts_ms: items[idx]?.ts_ms ?? Date.now(),
          turn_id: ref.turn_id ?? null,
          view: ref,
        };
        if (idx === -1) return [...items, next];
        const copy = items.slice();
        copy[idx] = { ...copy[idx], ...next };
        return copy;
      });
    }
  }

  private patchViewStatus(eventId: string, status: CaptureAnchorStatus | null): void {
    this._viewReferences.update((refs) =>
      refs.map((r) => (r.event_id === eventId ? { ...r, status: status ?? undefined } : r)),
    );
  }

  private statusForAction(action: CaptureViewUpdateRequest['action']): CaptureAnchorStatus | null {
    switch (action) {
      case 'confirm':
      case 'rebind':
        return 'confirmed';
      case 'discard':
        return 'discarded';
      default:
        return null;
    }
  }

  private toViewReference(payload: Record<string, unknown>): CaptureViewReference {
    return {
      session_id: (payload['session_id'] as string) ?? this._sessionId(),
      document_id: (payload['document_id'] as string) ?? null,
      filename: (payload['filename'] as string) ?? null,
      title: (payload['title'] as string) ?? null,
      page: (payload['page'] as number) ?? null,
      slide: (payload['slide'] as number) ?? null,
      image_index: (payload['image_index'] as number) ?? null,
      turn_id: (payload['turn_id'] as string) ?? null,
      timecode_ms: (payload['timecode_ms'] as number) ?? null,
      statement: (payload['statement'] as string) ?? null,
      trigger_phrase: (payload['trigger_phrase'] as string) ?? null,
      event_id: (payload['event_id'] as string) ?? null,
      status: (payload['status'] as CaptureAnchorStatus) ?? undefined,
      confidence: (payload['confidence'] as number) ?? null,
    };
  }

  private appendFeed(item: CaptureFeedItem): void {
    this._feed.update((items) => [...items, item]);
  }

  private normalizeSpeaker(value: unknown): CaptureFeedItem['speaker'] {
    return value === 'system' || value === 'operator' || value === 'expert' ? value : 'expert';
  }

  private normalizeSpeakerOrNull(value: unknown): CaptureFeedItem['speaker'] {
    return value === 'system' || value === 'operator' || value === 'expert' ? value : null;
  }

  private uid(): string {
    return crypto.randomUUID?.() ?? `cap-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  }

  private errorMessage(error: unknown): string {
    if (error instanceof Error) return error.message;
    return typeof error === 'string' ? error : 'unexpected capture engine error';
  }
}

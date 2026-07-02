import { DestroyRef, Injectable, computed, inject, signal } from '@angular/core';
import { firstValueFrom, type Observable, type Subscription } from 'rxjs';
import {
  ApiService,
  type CaptureAnchorStatus,
  type CapturePinnedView,
  type CaptureProposal,
  type CapturePublicationResult,
  type CaptureSessionDocument,
  type CaptureShareLevelItem,
  type CaptureTurnRequest,
  type CaptureViewReference,
  type CaptureViewUpdateRequest,
  type ProposalReviewRequest,
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
import { WorkspaceService } from '@app/core/workspace.service';
import { CanonicalApiService } from '@app/core/canonical-api.service';

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
  /** Topic this open question is grounded in (when the gateway provides it). */
  topic_id?: string | null;
  /** Backend priority (higher = surface first); already sorted by the gateway. */
  priority?: number | null;
}

/**
 * A single relance ("hint") from the backend hint-queue (P0 #1). The gateway
 * stages grounded follow-up questions per sous-sujet; the session UI surfaces
 * the principal hint + the queue. Polled via {@link ApiService.getCaptureHintQueue}.
 */
export interface CaptureHint {
  id: string;
  subtopic_id?: string;
  hint: string;
  full_question?: string;
  priority?: number;
  source?: string;
  kb_excerpt?: string;
}

/** Auto-detected section suggestion (from `section.active` / `evaluation.delta`). */
export interface CaptureSectionSuggestion {
  topic_id: string | null;
  subtopic_id: string | null;
  confidence?: number | null;
  manual_locked?: boolean;
}

/** A sous-sujet leaf in the parsed plan tree (P0 #1 section rail). */
export interface CapturePlanSubtopic {
  id: string;
  title?: string;
  objective?: string;
  prompt?: string;
  status?: string;
}

/** A topic node in the parsed plan tree (P0 #1 section rail). */
export interface CapturePlanTopic {
  id: string;
  title?: string;
  objective?: string;
  prompt?: string;
  status?: string;
  subtopics?: CapturePlanSubtopic[];
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

/** End-of-session closure sheet (markdown recap + structured lists). */
export interface CaptureClosureSheet {
  markdown: string;
  topics?: string[];
  captured_facts?: unknown[];
  unresolved?: Array<{ bucket?: string; label?: string; status?: string }>;
}

/** Display prioritization of the live session (visual only, no mechanics). */
export type CaptureFilLayout = 'documents' | 'transcript';

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
  private readonly workspace = inject(WorkspaceService);
  private readonly canonicalApi = inject(CanonicalApiService);
  private readonly destroyRef = inject(DestroyRef);

  private connection: VoiceSessionConnection | LiveKitConversationConnection | null = null;
  private eventsSub: Subscription | null = null;
  /** Light polling of the hint-queue while connected (P0 #1, ~15s). */
  private hintPollTimer: ReturnType<typeof setInterval> | null = null;
  private static readonly HINT_POLL_MS = 15000;

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
  /** Session-level collection slug (fallback for per-doc preview URLs). */
  private readonly _documentsCollection = signal<string | null>(null);
  private readonly _proposalId = signal<string | null>(null);
  /** Full knowledge proposal (the report fiche), captured at finalize (P0 #2). */
  private readonly _proposal = signal<CaptureProposal | null>(null);
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

  // ---- fil layout (priorité pièces jointes vs transcript) -----------------
  private readonly _filLayout = signal<CaptureFilLayout>('documents');
  /** Once the operator toggles in-session, the system default must not stomp it. */
  private filLayoutTouched = false;

  // ---- session minuterie / closure (P1, v0) ------------------------------
  private readonly _paused = signal(false);
  /** Cumulative extra minutes granted via {@link extendSession}. */
  private readonly _extraMinutes = signal(0);
  /** 1s ticker driving the countdown computeds (started at connect). */
  private readonly _nowTick = signal(Date.now());
  private readonly _sessionStartedAt = signal<number | null>(null);
  /** Wall-clock when the current pause began (null while running). */
  private readonly _pausedAt = signal<number | null>(null);
  /** Total time spent paused so far (frozen out of the elapsed count). */
  private readonly _pausedAccumMs = signal(0);
  private readonly _closureSheet = signal<CaptureClosureSheet | null>(null);
  private tickTimer: ReturnType<typeof setInterval> | null = null;
  private static readonly TICK_MS = 1000;
  private static readonly DEFAULT_DURATION_MIN = 30;
  private static readonly NOTICE_WINDOW_MS = 5 * 60 * 1000;

  // ---- oracle enrichment / report export (P1) ----------------------------
  private readonly _oracleSuppressed = signal(false);
  private readonly _reportExport = signal<string | null>(null);

  /**
   * Feed item id to scroll to when re-entering the session surface
   * ("Revoir l'instant capté" from the review fiche). Consumed once.
   */
  readonly revisitTarget = signal<string | null>(null);

  // ---- section steering (P0 #1) ------------------------------------------
  private readonly _activeTopicId = signal<string | null>(null);
  private readonly _activeSubtopicId = signal<string | null>(null);
  private readonly _sectionSuggestion = signal<CaptureSectionSuggestion | null>(null);
  private readonly _hintQueue = signal<CaptureHint[]>([]);

  // ---- publication (P0 #3) -----------------------------------------------
  private readonly _collections = signal<string[]>([]);
  private readonly _publication = signal<CapturePublicationResult | null>(null);

  /** Capture session this engine is bound to (null until `connect`). */
  readonly sessionId = this._sessionId.asReadonly();
  /** Richer session identity shared across the autonomous flow surfaces. */
  readonly session = this._session.asReadonly();
  /** System scope (from `/systems/:id/capture`); null at the capability level. */
  readonly systemId = this._systemId.asReadonly();
  /** Documents attached to the session (uploaded or referenced). */
  readonly documents = this._documents.asReadonly();
  /** Session-level collection slug (preview URL fallback when a doc lacks one). */
  readonly documentsCollection = this._documentsCollection.asReadonly();
  /** Knowledge proposal id produced by {@link finalize}. */
  readonly proposalId = this._proposalId.asReadonly();
  /** Full knowledge proposal (the report fiche); null until finalize / loadProposal. */
  readonly proposal = this._proposal.asReadonly();
  /** Active topic in the section rail (manual selection or auto-detection). */
  readonly activeTopicId = this._activeTopicId.asReadonly();
  /** Active sous-sujet in the section rail. */
  readonly activeSubtopicId = this._activeSubtopicId.asReadonly();
  /** Latest auto-detected section suggestion (clickable in the rail). */
  readonly sectionSuggestion = this._sectionSuggestion.asReadonly();
  /** Backend relances ("pile de relances") for the active sous-sujet. */
  readonly hintQueue = this._hintQueue.asReadonly();
  /** Available KB destinations/collections for publication (P0 #3). */
  readonly collections = this._collections.asReadonly();
  /** Result of the last successful publication (export_urls, document_id, …). */
  readonly publication = this._publication.asReadonly();
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
  /** Session display mode: pièces jointes au centre ('documents') vs transcript. */
  readonly filLayout = this._filLayout.asReadonly();

  /**
   * The session plan parsed into a typed topics/sous-sujets tree (P0 #1). Reads
   * `session().plan.topics`; tolerates the loose `Record<string, unknown>` plan
   * shape and skips malformed nodes so the section rail always renders.
   */
  readonly planTopics = computed<CapturePlanTopic[]>(() => {
    const plan = this._session()?.plan;
    const rawTopics = plan && typeof plan === 'object' ? (plan as Record<string, unknown>)['topics'] : null;
    if (!Array.isArray(rawTopics)) return [];
    const topics: CapturePlanTopic[] = [];
    for (const raw of rawTopics) {
      if (!raw || typeof raw !== 'object') continue;
      const node = raw as Record<string, unknown>;
      const id = node['id'] != null ? String(node['id']) : '';
      if (!id) continue;
      const subtopics: CapturePlanSubtopic[] = [];
      const rawSubs = node['subtopics'];
      if (Array.isArray(rawSubs)) {
        for (const rawSub of rawSubs) {
          if (!rawSub || typeof rawSub !== 'object') continue;
          const sub = rawSub as Record<string, unknown>;
          const subId = sub['id'] != null ? String(sub['id']) : '';
          if (!subId) continue;
          subtopics.push({
            id: subId,
            title: sub['title'] != null ? String(sub['title']) : undefined,
            objective: sub['objective'] != null ? String(sub['objective']) : undefined,
            prompt: sub['prompt'] != null ? String(sub['prompt']) : undefined,
            status: sub['status'] != null ? String(sub['status']) : undefined,
          });
        }
      }
      topics.push({
        id,
        title: node['title'] != null ? String(node['title']) : undefined,
        objective: node['objective'] != null ? String(node['objective']) : undefined,
        prompt: node['prompt'] != null ? String(node['prompt']) : undefined,
        status: node['status'] != null ? String(node['status']) : undefined,
        subtopics,
      });
    }
    return topics;
  });

  readonly connected = computed(() => this._state() === 'connected');
  /** Mic is capturing AND not muted-while-typing — drives the composer VU (D3). */
  readonly micActive = computed(() => this._micActive() && !this._micMuted());

  // ---- session minuterie / closure (P1, v0) ------------------------------
  /** Whether the capture is currently paused (timer frozen, mic cut). */
  readonly paused = this._paused.asReadonly();
  /** End-of-session closure sheet (loaded on demand via {@link loadClosureSheet}). */
  readonly closureSheet = this._closureSheet.asReadonly();
  /** Whether the operator has globally hidden the oracle for this session. */
  readonly oracleSuppressed = this._oracleSuppressed.asReadonly();
  /** Last exported report markdown (for reuse/preview). */
  readonly reportExport = this._reportExport.asReadonly();

  /** Planned session length in minutes (incl. prolongations); fallback 30. */
  readonly durationMinutes = computed(() => {
    const base = Number(this._session()?.duration_minutes);
    const minutes = Number.isFinite(base) && base > 0 ? base : CaptureEngine.DEFAULT_DURATION_MIN;
    return minutes + this._extraMinutes();
  });
  /** Elapsed capture time (ms), with paused spans frozen out. */
  readonly elapsedMs = computed(() => {
    const start = this._sessionStartedAt();
    if (start == null) return 0;
    const now = this._nowTick();
    let elapsed = now - start - this._pausedAccumMs();
    const pausedAt = this._pausedAt();
    if (pausedAt != null) elapsed -= now - pausedAt;
    return Math.max(0, elapsed);
  });
  /** Remaining time before the échéance (ms); negative once in overtime. */
  readonly remainingMs = computed(() => this.durationMinutes() * 60000 - this.elapsedMs());
  /** True once the planned duration is exhausted. */
  readonly overtime = computed(() => this.remainingMs() <= 0);
  /** "5 dernières minutes" notice window (not yet in overtime). */
  readonly lastFiveMinutes = computed(() => {
    const remaining = this.remainingMs();
    return remaining > 0 && remaining <= CaptureEngine.NOTICE_WINDOW_MS;
  });
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
    // Transport selection mirrors the v0 monolith: when the workspace is wired
    // for the LiveKit voice gateway (the gpt-realtime-whisper sidecar transcribes
    // a PUBLISHED mic track), we MUST open LiveKit and publish the mic — a plain
    // backend_ws WebM pump delivers nothing to the realtime lane (the frames are
    // dropped client-side), which is why "la voix n'est pas captée".
    const transport: 'backend_ws' | 'livekit' =
      options.transport ?? (this.preferLiveKit() ? 'livekit' : 'backend_ws');
    this.transport = transport;
    try {
      if (transport === 'livekit') {
        const connection = await this.openLiveKit(sessionId, options);
        this.connection = connection;
        this.subscribe(connection.events$);
        this._state.set('connected');
        this.onConnected();
        // LiveKit publishes the mic track itself (publishMicrophone); no WebM pump.
        return;
      }
      const connection = this.voiceSession.open(sessionId);
      this.connection = connection;
      this.subscribe(connection.events$);
      connection.start({ mode: 'conversation_only' });
      this._state.set('connected');
      this.onConnected();
      // Voice is captured continuously over the backend WS (D3 cascade lane).
      void this.startMic();
    } catch (error) {
      // LiveKit unavailable → degrade to the backend WS so the session still opens.
      if (transport === 'livekit') {
        try {
          this.transport = 'backend_ws';
          const connection = this.voiceSession.open(sessionId);
          this.connection = connection;
          this.subscribe(connection.events$);
          connection.start({ mode: 'conversation_only' });
          this._state.set('connected');
          this.onConnected();
          this._lastError.set('Passerelle LiveKit indisponible — bascule WebSocket.');
          void this.startMic();
          return;
        } catch (fallbackError) {
          this._state.set('error');
          this._lastError.set(this.errorMessage(fallbackError));
          return;
        }
      }
      this._state.set('error');
      this._lastError.set(this.errorMessage(error));
    }
  }

  /**
   * Open the LiveKit voice leg with the agent-dispatch + mic-publish options the
   * realtime gateway needs (mirrors the v0 `ensureVoiceConnection` livekit path).
   */
  private openLiveKit(
    sessionId: string,
    options: CaptureConnectOptions,
  ): Promise<LiveKitConversationConnection> {
    return this.livekit.open(sessionId, {
      runtime: 'cascade_openai',
      provider: 'cascade_openai',
      transport: 'livekit',
      language: 'fr',
      output_language: 'fr',
      capability: 'voice2voice_interaction',
      mode: 'conversation_only',
      surface: 'knowledge_capture',
      system_id: this._systemId(),
      tandem_oracle: true,
      publishMicrophone: options.publishMicrophone ?? true,
      dispatchAgent: true,
      requireVoiceGateway: true,
      ...(options.livekit ?? {}),
    });
  }

  /**
   * True when the active workspace is configured to route voice through the
   * LiveKit gateway (transport === 'livekit', or livekit_enabled with no explicit
   * transport). Ported from the v0 `shouldPreferLiveKitTransport`.
   */
  private preferLiveKit(): boolean {
    const settings = this.asRecord(this.workspace.current()?.settings);
    const voiceRuntime = this.asRecord(settings['voice_runtime']);
    const livekit = this.asRecord(settings['livekit']);
    const livekitEnabled =
      voiceRuntime['livekit_enabled'] === true ||
      settings['livekit_enabled'] === true ||
      livekit['enabled'] === true;
    const transport = String(
      voiceRuntime['transport'] ||
        voiceRuntime['default_transport'] ||
        voiceRuntime['realtime_transport'] ||
        livekit['transport'] ||
        livekit['default_transport'] ||
        settings['voice_transport'] ||
        '',
    )
      .trim()
      .toLowerCase();
    return transport === 'livekit' || (livekitEnabled && !transport);
  }

  private asRecord(value: unknown): Record<string, unknown> {
    return value && typeof value === 'object' && !Array.isArray(value)
      ? (value as Record<string, unknown>)
      : {};
  }

  /**
   * Post-connect hook: pull the initial relances and start the light hint-queue
   * poll (the backend doesn't push relances live — "silent oracle" by design).
   */
  private onConnected(): void {
    this.startTicker();
    void this.refreshHintQueue();
    this.startHintPoll();
    // Seed the gateway with the current scene so realtime voice turns can resolve
    // deictic anchors from the first word (Section A).
    this.pushScene();
  }

  /**
   * Push the current scene state (every pinned piece + the focused
   * `visual_context`) to the gateway over the control channel (Section A). In
   * realtime STT (LiveKit) the continuous mic track never carries per-turn
   * `visual_context`, so the gateway uses this last-known scene as the fallback
   * when committing a voice turn — restoring voice-driven view anchors.
   */
  private pushScene(): void {
    const context = this.documentContext();
    this.connection?.captureScene({
      visual_context: context.visual_context,
      document_refs: context.document_refs,
    });
  }

  /** Start the 1s ticker that drives the countdown computeds. */
  private startTicker(): void {
    this.stopTicker();
    if (this._sessionStartedAt() == null) this._sessionStartedAt.set(Date.now());
    this._nowTick.set(Date.now());
    this.tickTimer = setInterval(() => this._nowTick.set(Date.now()), CaptureEngine.TICK_MS);
  }

  private stopTicker(): void {
    if (this.tickTimer !== null) {
      clearInterval(this.tickTimer);
      this.tickTimer = null;
    }
  }

  private startHintPoll(): void {
    this.stopHintPoll();
    this.hintPollTimer = setInterval(() => {
      if (!this.connected()) return;
      void this.refreshHintQueue();
    }, CaptureEngine.HINT_POLL_MS);
  }

  private stopHintPoll(): void {
    if (this.hintPollTimer !== null) {
      clearInterval(this.hintPollTimer);
      this.hintPollTimer = null;
    }
  }

  /** Tear down the realtime connection. Safe to call repeatedly. */
  disconnect(): void {
    this.stopHintPoll();
    this.stopTicker();
    this.stopMic();
    this.realtimeSttActive = false;
    // A WS finalize in flight can never complete without the socket — recover
    // it (the proposal is usually already persisted server-side) so the await
    // resolves with the real report instead of a guaranteed error UI.
    if (this.finalizeResolver) {
      const resolver = this.finalizeResolver;
      this.clearFinalizeWait();
      void this.recoverFinalize().then((id) => resolver(id));
    }
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
    this.pushScene();
  }

  /** Bring an already-pinned piece "EN SCÈNE". */
  focusView(key: string): void {
    if (this._pinnedViews().some((p) => p.key === key)) {
      this._activeViewKey.set(key);
      this.pushScene();
    }
  }

  /** Remove a pinned piece; re-focuses the first remaining one. */
  unpinView(key: string): void {
    this._pinnedViews.update((pins) => pins.filter((p) => p.key !== key));
    if (this._activeViewKey() === key) {
      this._activeViewKey.set(this._pinnedViews()[0]?.key ?? null);
    }
    this.pushScene();
  }

  /**
   * Track the page the expert is actually looking at on the focused piece. The
   * inline preview reports page navigation here; we stamp it on the active pin
   * (its `key` stays stable) so both the deictic `visual_context` and a manual
   * "Marquer dans le fil" reference the *shown* page, not the pin-time default.
   */
  setActiveViewPage(page: number | null): void {
    const key = this._activeViewKey();
    if (!key) return;
    const normalized = page != null && page > 0 ? page : null;
    let changed = false;
    this._pinnedViews.update((pins) =>
      pins.map((p) => {
        if (p.key !== key || (p.page ?? null) === normalized) return p;
        changed = true;
        return { ...p, page: normalized };
      }),
    );
    if (changed) this.pushScene();
  }

  /**
   * Manually anchor the focused piece into the Fil (Section B). Voice anchors
   * only fire on precise deictic phrases; this explicit affordance journals the
   * active view (`association_mode: 'manual'`) and appends a confirmed `anchor`
   * feed item, so marking is predictable. The record endpoint returns the
   * journaled event (`{ event: { id } }`) which keys the anchor; we synthesize a
   * stable id when the call fails so the Fil still shows the mark.
   */
  async markActiveView(): Promise<void> {
    const sessionId = this._sessionId();
    const view = this.activeView();
    if (!sessionId || !view) return;
    let eventId: string | null = null;
    try {
      const response = await firstValueFrom(
        this.api.recordCaptureDocumentView(sessionId, {
          document_id: view.document_id,
          collection: view.collection,
          collection_name: view.collection,
          filename: view.filename,
          title: view.title,
          page: view.page,
          slide: view.slide,
          image_index: view.image_index,
          association_mode: 'manual',
        }),
      );
      eventId = (response as { event?: { id?: string | null } } | null)?.event?.id ?? null;
    } catch (error) {
      this._lastError.set(this.errorMessage(error));
    }
    this.ingestViewReference(
      { ...view, status: 'confirmed', event_id: eventId ?? this.uid() },
      { asFeed: true },
    );
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
    if (systemId) this.resolveFilLayout(systemId);
  }

  /**
   * Session-time layout switch (ephemeral by design — never persisted). Takes
   * priority over the system default for the rest of the séance.
   */
  setFilLayout(mode: CaptureFilLayout): void {
    this.filLayoutTouched = true;
    this._filLayout.set(mode);
  }

  /**
   * Resolve the system-level default (`settings.capture.fil_layout`). Any
   * missing/invalid value → 'documents'. A prior in-session toggle wins.
   */
  private resolveFilLayout(systemId: string): void {
    this.canonicalApi.getSystem(systemId).subscribe((sys) => {
      if (this.filLayoutTouched) return;
      const capture = this.asRecord(this.asRecord(sys?.settings)['capture']);
      const raw = capture['fil_layout'];
      this._filLayout.set(raw === 'transcript' ? 'transcript' : 'documents');
    });
  }

  /** Bind the engine to a session without opening the realtime leg. */
  setSession(info: CaptureSessionInfo | null): void {
    this._session.set(info);
    if (info?.id) this._sessionId.set(info.id);
    // Resuming a system-scoped session preserves the scope for downstream lists.
    if (info?.system_id && info.system_id !== this._systemId()) {
      this.setSystemId(info.system_id);
    }
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
    const body = payload as
      | { documents?: CaptureSessionDocument[]; collection?: string | null; collection_name?: string | null }
      | null;
    if (Array.isArray(body?.documents)) this._documents.set(body!.documents.filter(Boolean));
    const collection = (body?.collection ?? body?.collection_name ?? '').toString().trim();
    if (collection) this._documentsCollection.set(collection);
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

  // ---- session minuterie / closure (P1, v0) ------------------------------

  /** Pause the capture: freeze the countdown, cut the mic, notify the backend. */
  async pause(): Promise<void> {
    if (this._paused()) return;
    this._paused.set(true);
    this._pausedAt.set(Date.now());
    this.stopMic();
    const sessionId = this._sessionId();
    if (!sessionId) return;
    try {
      await firstValueFrom(this.api.pauseCaptureSession(sessionId));
    } catch (error) {
      this._lastError.set(this.errorMessage(error));
    }
  }

  /** Resume the capture: bank the paused span, reopen the mic, notify the backend. */
  async resume(): Promise<void> {
    if (!this._paused()) return;
    const pausedAt = this._pausedAt();
    if (pausedAt != null) {
      this._pausedAccumMs.update((acc) => acc + Math.max(0, Date.now() - pausedAt));
    }
    this._pausedAt.set(null);
    this._paused.set(false);
    void this.startMic();
    const sessionId = this._sessionId();
    if (!sessionId) return;
    try {
      await firstValueFrom(this.api.resumeCaptureSession(sessionId));
    } catch (error) {
      this._lastError.set(this.errorMessage(error));
    }
  }

  /** Prolong the session by `minutes` (default +15) — pushes the échéance out. */
  async extendSession(minutes = 15): Promise<void> {
    this._extraMinutes.update((m) => m + minutes);
    const sessionId = this._sessionId();
    if (!sessionId) return;
    try {
      await firstValueFrom(this.api.extendCaptureSession(sessionId, minutes));
    } catch (error) {
      this._lastError.set(this.errorMessage(error));
    }
  }

  /** Load the end-of-session closure sheet (markdown recap + structured lists). */
  async loadClosureSheet(): Promise<void> {
    const sessionId = this._sessionId();
    if (!sessionId) return;
    try {
      const payload = await firstValueFrom(this.api.getCaptureClosureSheet(sessionId));
      this._closureSheet.set(payload ?? null);
    } catch (error) {
      this._lastError.set(this.errorMessage(error));
    }
  }

  /** Programme a follow-up session at closure (non-terminal — the séance lives on). */
  async scheduleFollowup(): Promise<void> {
    const sessionId = this._sessionId();
    if (!sessionId) return;
    try {
      await firstValueFrom(this.api.applyCaptureSessionClosure(sessionId, { action: 'schedule' }));
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

  // ---- section steering (P0 #1) ------------------------------------------

  /**
   * Manually steer the capture to a topic / sous-sujet (operator click on the
   * section rail). Tells the gateway (`section.select`), updates the local
   * active markers, then refreshes the relances scoped to the new sous-sujet.
   * `manual=true` locks out the auto-detection so a click sticks.
   */
  async selectSection(
    topicId: string | null,
    subtopicId: string | null,
    manual = true,
  ): Promise<void> {
    this.connection?.sectionSelect({ topic_id: topicId, subtopic_id: subtopicId, manual });
    this._activeTopicId.set(topicId);
    this._activeSubtopicId.set(subtopicId);
    await this.refreshHintQueue(subtopicId ?? undefined);
  }

  /** Mark the active section finished (operator action / progression). */
  finishSection(): void {
    this.connection?.sectionFinish({
      topic_id: this._activeTopicId(),
      subtopic_id: this._activeSubtopicId(),
    });
  }

  /**
   * Pull the backend hint-queue (relances) for the given sous-sujet (defaults to
   * the active one). The backend stages grounded follow-ups but never pushes
   * them live, so this is polled on connect / section change / interval.
   */
  async refreshHintQueue(subtopicId?: string): Promise<void> {
    const sessionId = this._sessionId();
    if (!sessionId) return;
    const target = subtopicId ?? this._activeSubtopicId() ?? undefined;
    try {
      const payload = await firstValueFrom(this.api.getCaptureHintQueue(sessionId, target));
      const hints = (payload as { hints?: CaptureHint[] } | null)?.hints;
      this._hintQueue.set(Array.isArray(hints) ? hints : []);
    } catch (error) {
      this._hintQueue.set([]);
      this._lastError.set(this.errorMessage(error));
    }
  }

  // ---- proposal / report (P0 #2) -----------------------------------------

  /**
   * Restore the proposal for the bound session (dashboard re-entry / resume):
   * list the session's proposals and adopt the one whose `session_id` matches
   * (falling back to the most recent), so the report fiche renders without a
   * fresh finalize.
   */
  async loadProposal(): Promise<CaptureProposal | null> {
    const sessionId = this._sessionId();
    if (!sessionId) return null;
    try {
      const payload = await firstValueFrom(
        this.api.listCaptureProposals(undefined, this._systemId(), sessionId),
      );
      const proposals = (payload as { proposals?: CaptureProposal[] } | null)?.proposals ?? [];
      const match =
        proposals.find((p) => p?.session_id === sessionId) ?? proposals[0] ?? null;
      if (match) this.setProposal(match);
      return match;
    } catch (error) {
      this._lastError.set(this.errorMessage(error));
      return null;
    }
  }

  /** Persist a manual markdown edit of the report; refresh from the response. */
  async saveReport(content: string): Promise<void> {
    const proposalId = this._proposalId();
    if (!proposalId) return;
    try {
      const payload = await firstValueFrom(
        this.api.updateCaptureProposalContent(proposalId, content),
      );
      this.applyProposalResponse(payload);
    } catch (error) {
      this._lastError.set(this.errorMessage(error));
    }
  }

  /** Apply a free-text AI instruction to the report; refresh from the response. */
  async applyInstruction(text: string): Promise<void> {
    const proposalId = this._proposalId();
    const instruction = text.trim();
    if (!proposalId || !instruction) return;
    try {
      const payload = await firstValueFrom(
        this.api.applyCaptureProposalInstruction(proposalId, {
          instruction,
          current_content: this._proposal()?.proposal?.report_markdown ?? null,
        }),
      );
      this.applyProposalResponse(payload);
    } catch (error) {
      this._lastError.set(this.errorMessage(error));
    }
  }

  /**
   * Advance the review workflow (accept / reject / changes requested). Returns
   * `true` when the decision was applied (status echoed back), `false` on
   * failure — the caller surfaces the outcome so a rejection never fails
   * silently.
   */
  async reviewProposal(
    status: ProposalReviewRequest['status'],
    notes?: string,
  ): Promise<boolean> {
    const proposalId = this._proposalId();
    if (!proposalId) {
      this._lastError.set('Aucune proposition à réviser.');
      return false;
    }
    try {
      const payload = await firstValueFrom(
        this.api.reviewCaptureProposal(proposalId, {
          status,
          reviewer: 'demo-operator',
          review_notes: notes ?? null,
        }),
      );
      this.applyProposalResponse(payload);
      const applied = (this._proposal()?.status ?? '').toLowerCase() === status;
      if (!applied) this._lastError.set('La décision de revue n’a pas été enregistrée.');
      return applied;
    } catch (error) {
      this._lastError.set(this.errorMessage(error));
      return false;
    }
  }

  /**
   * Export the current report as Markdown via the backend, then trigger a
   * client-side Blob download (`rapport-<titre>.md`). Memoises the markdown in
   * {@link reportExport} for reuse.
   */
  async exportReport(): Promise<void> {
    const sessionId = this._sessionId();
    if (!sessionId) return;
    const proposalId = this._proposalId();
    try {
      const payload = await firstValueFrom(
        this.api.exportCaptureProposal(sessionId, proposalId ? { proposal_id: proposalId } : {}),
      );
      const markdown = payload?.markdown ?? '';
      this._reportExport.set(markdown);
      this.downloadMarkdown(markdown);
    } catch (error) {
      this._lastError.set(this.errorMessage(error));
    }
  }

  private downloadMarkdown(markdown: string): void {
    if (typeof document === 'undefined' || typeof URL?.createObjectURL !== 'function') return;
    const slug =
      (this._session()?.title ?? 'rapport')
        .toString()
        .toLowerCase()
        .normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '')
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-+|-+$/g, '') || 'rapport';
    const blob = new Blob([markdown], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `rapport-${slug}.md`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  /** Answer a single open question; the backend re-synthesises and returns the proposal. */
  async answerOpenQuestion(questionId: string, text: string): Promise<void> {
    const proposalId = this._proposalId();
    if (!proposalId || !questionId) return;
    try {
      const payload = await firstValueFrom(
        this.api.answerCaptureProposalOpenQuestion(proposalId, questionId, { text }),
      );
      this.applyProposalResponse(payload);
    } catch (error) {
      this._lastError.set(this.errorMessage(error));
    }
  }

  /** Bulk-patch open-question statuses (answer / defer / invalidate). */
  async patchOpenQuestions(
    items: Array<{
      question_key?: string | null;
      question_id?: string | null;
      question_text?: string | null;
      status: 'open' | 'answered' | 'invalid' | 'deferred';
    }>,
  ): Promise<void> {
    const proposalId = this._proposalId();
    if (!proposalId || !items.length) return;
    try {
      const payload = await firstValueFrom(
        this.api.patchCaptureProposalOpenQuestions(proposalId, { items }),
      );
      this.applyProposalResponse(payload);
    } catch (error) {
      this._lastError.set(this.errorMessage(error));
    }
  }

  // ---- publication (P0 #3) -----------------------------------------------

  /** Load the available KB destinations/collections for the publish surface. */
  async loadCollections(): Promise<void> {
    try {
      const payload = await firstValueFrom(
        this.api.get<{ collections?: string[] }>('/documents/collections'),
      );
      this._collections.set(Array.isArray(payload?.collections) ? payload.collections : []);
    } catch (error) {
      this._lastError.set(this.errorMessage(error));
    }
  }

  /**
   * Publish the accepted report to the KB (P0 #3). Accepts the proposal first if
   * it isn't already, then pushes the fiche; stores the result and merges it
   * into the proposal's `publication` block. Errors surface via {@link lastError}.
   */
  async publish(body: {
    category?: string | null;
    destination?: string | null;
    destination_scope?: string | null;
    final_title?: string | null;
    include_unresolved_questions?: boolean;
  }): Promise<CapturePublicationResult | null> {
    const proposalId = this._proposalId();
    if (!proposalId) return null;
    try {
      const status = (this._proposal()?.status ?? '').toLowerCase();
      // A rejected fiche must NOT be silently re-accepted on publish: the
      // reviewer's decision stands until they explicitly accept it again.
      if (status === 'rejected') {
        this._lastError.set('Fiche rejetée — acceptez-la explicitement avant de publier.');
        return null;
      }
      if (status !== 'accepted' && status !== 'published') {
        const accepted = await this.reviewProposal('accepted');
        if (!accepted) return null;
      }
      const payload = await firstValueFrom(this.api.publishCaptureProposal(proposalId, body));
      const result = (payload as CapturePublicationResult | null) ?? null;
      this._publication.set(result);
      if (result) {
        this._proposal.update((p) => {
          if (!p) return p;
          const inner = p.proposal ?? {};
          const publication = {
            ...(inner.publication ?? {}),
            ...(result as Record<string, unknown>),
          } as NonNullable<CaptureProposal['proposal']>['publication'];
          return { ...p, proposal: { ...inner, publication } };
        });
      }
      return result;
    } catch (error) {
      this._lastError.set(this.errorMessage(error));
      return null;
    }
  }

  /**
   * Adopt a full proposal object as the current report (from finalize, WS
   * capture_finished, or {@link loadProposal}). Keeps `proposalId` in sync.
   */
  private setProposal(proposal: CaptureProposal | null): void {
    this._proposal.set(proposal);
    if (proposal?.id) this._proposalId.set(proposal.id);
  }

  /**
   * Adopt a proposal returned by an edit endpoint, when the response actually
   * carries one (some endpoints echo the updated proposal, others don't).
   */
  private applyProposalResponse(payload: unknown): void {
    if (!payload || typeof payload !== 'object') return;
    const candidate = payload as Partial<CaptureProposal>;
    if (typeof candidate.id === 'string' || candidate.proposal !== undefined) {
      this.setProposal(payload as CaptureProposal);
    }
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
    // Prefer the live WS path on BOTH realtime transports: the gateway streams
    // honest `capture.finalize.progress` stage events to the report banner and
    // returns the proposal via `conversation.step` (capture_finished). On
    // LiveKit (andritz) the HTTP fallback would route a planned session through
    // `create_update_proposal` (verbatim facts) instead of `finalize_capture`
    // (reformulated report) — so the WS `captureFinish()` is what produces the
    // reformulated per-section report. Fall back to HTTP when offline (90s guard).
    const connection = this.connection;
    if (
      connection &&
      this._state() === 'connected' &&
      (this.transport === 'backend_ws' || this.transport === 'livekit')
    ) {
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
      // Capture the FULL proposal object (the report fiche), not just its id, so
      // the review surface renders immediately (P0 #2).
      this.applyProposalResponse(payload);
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
        const resolver = this.finalizeResolver;
        this.clearFinalizeWait();
        void this.recoverFinalize().then((id) => resolver?.(id));
      }, 90000);
      connection.captureFinish();
    });
  }

  /**
   * Recover a finalize whose WS leg died or whose terminal `conversation.step`
   * was lost: the proposal usually ALREADY exists server-side (the gateway
   * builds it before emitting the step), so fetch it first and only re-trigger
   * the heavy HTTP finalize when nothing was persisted.
   */
  private async recoverFinalize(): Promise<string | null> {
    const existing = await this.loadProposal();
    if (existing?.id) {
      this._finalize.update((s) =>
        s.stage === 'failed'
          ? s
          : { ...s, stage: 'done', message: 'Rapport prêt — indexation en arrière-plan.' },
      );
      return existing.id;
    }
    const sessionId = this._sessionId();
    return sessionId ? this.finalizeOverHttp(sessionId) : null;
  }

  /**
   * The backend just reported a terminal finalize stage (done/error) or closed
   * the realtime leg while a WS finalize is still awaiting its
   * `conversation.step`. Shrink the 90s guard to a short grace so a lost step
   * event never blocks the transition to the review surface.
   */
  private expediteFinalizeRecovery(graceMs: number): void {
    if (!this.finalizeResolver) return;
    if (this.finalizeTimeout !== null) clearTimeout(this.finalizeTimeout);
    this.finalizeTimeout = setTimeout(() => {
      const resolver = this.finalizeResolver;
      this.clearFinalizeWait();
      void this.recoverFinalize().then((id) => resolver?.(id));
    }, graceMs);
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

  /**
   * Keep / ignore / defer an Oracle suggestion (calm, non-blocking — D3 / §5.1).
   * Optimistic local update + best-effort persistence to the backend so the
   * triage survives reload.
   */
  setOracleStatus(id: string, status: CaptureOracleItem['status']): void {
    this._oracle.update((items) => items.map((q) => (q.id === id ? { ...q, status } : q)));
    const sessionId = this._sessionId();
    if (!sessionId) return;
    void firstValueFrom(
      this.api.patchCaptureOracleQuestions(sessionId, { items: [{ question_id: id, status }] }),
    ).catch((error: unknown) => this._lastError.set(this.errorMessage(error)));
  }

  /** Différer une piste de l'oracle (raccourci sur {@link setOracleStatus}). */
  deferOracle(id: string): void {
    this.setOracleStatus(id, 'deferred');
  }

  /**
   * Masquer / réafficher globalement l'oracle pour la séance. Persists via the
   * session `suppress_oracle_questions` flag.
   */
  setOracleSuppressed(suppressed: boolean): void {
    this._oracleSuppressed.set(suppressed);
    const sessionId = this._sessionId();
    if (!sessionId) return;
    void firstValueFrom(
      this.api.patchCaptureSessionFlags(sessionId, { suppress_oracle_questions: suppressed }),
    ).catch((error: unknown) => this._lastError.set(this.errorMessage(error)));
  }

  /**
   * Human label for an oracle item's `topic_id`, mapped via the parsed plan
   * tree (topics then sous-sujets). Returns null when unmappable.
   */
  topicLabelFor(topicId: string | null | undefined): string | null {
    const id = (topicId ?? '').trim();
    if (!id) return null;
    const topics = this.planTopics();
    const topic = topics.find((t) => t.id === id);
    if (topic) return topic.title || topic.id;
    for (const t of topics) {
      const sub = (t.subtopics ?? []).find((s) => s.id === id);
      if (sub) return sub.title || sub.id;
    }
    return null;
  }

  /** Reset all session-scoped state (e.g. when leaving the capture). */
  reset(): void {
    this.disconnect();
    this._sessionId.set(null);
    this._session.set(null);
    this._documents.set([]);
    this._proposalId.set(null);
    this._proposal.set(null);
    this._feed.set([]);
    this._oracle.set([]);
    this._viewReferences.set([]);
    this._pinnedViews.set([]);
    this._activeViewKey.set(null);
    this._activeTopicId.set(null);
    this._activeSubtopicId.set(null);
    this._sectionSuggestion.set(null);
    this._hintQueue.set([]);
    this._publication.set(null);
    this._finalize.set(FINALIZE_IDLE);
    this._paused.set(false);
    this._extraMinutes.set(0);
    this._sessionStartedAt.set(null);
    this._pausedAt.set(null);
    this._pausedAccumMs.set(0);
    this._closureSheet.set(null);
    this._oracleSuppressed.set(false);
    this._reportExport.set(null);
    this._lastError.set(null);
    // Layout stays on the system default; the ephemeral toggle dies with the séance.
    this.filLayoutTouched = false;
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
      case 'section.active':
        this.applySectionActive(payload);
        break;
      case 'evaluation.delta':
        this.applyEvaluationDelta(payload);
        break;
      case 'oracle.questions':
        this.ingestOpenQuestions(payload);
        break;
      case 'oracle.delta':
      case 'oracle.commit':
        this.upsertOracle(payload);
        break;
      case 'session.error':
        this._lastError.set(String(payload['message'] ?? 'capture transport error'));
        // A transport error mid-finalize likely means the terminal step will
        // never arrive — recover promptly instead of hanging on the 90s guard.
        this.expediteFinalizeRecovery(4000);
        break;
      case 'session.close':
        if (this._state() === 'connected') this._state.set('closed');
        this.expediteFinalizeRecovery(2000);
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
      const proposal = payload['proposal'] as CaptureProposal | null;
      const proposalId = proposal?.id ?? null;
      // Capture the FULL proposal object (the report fiche) for the review surface (P0 #2).
      if (proposal) this.setProposal(proposal);
      else if (proposalId) this._proposalId.set(proposalId);
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

  /**
   * Auto section detection (`section.active`): record the suggestion and, unless
   * the operator has manually locked the section, follow it (P0 #1). On the
   * LiveKit transport this event may never arrive — manual selection + the
   * hint-queue poll remain the guaranteed path.
   */
  private applySectionActive(payload: Record<string, unknown>): void {
    const suggestion: CaptureSectionSuggestion = {
      topic_id: payload['topic_id'] != null ? String(payload['topic_id']) : null,
      subtopic_id: payload['subtopic_id'] != null ? String(payload['subtopic_id']) : null,
      confidence: payload['confidence'] != null ? Number(payload['confidence']) : null,
      manual_locked: payload['manual_locked'] === true,
    };
    this._sectionSuggestion.set(suggestion);
    if (!suggestion.manual_locked) {
      this._activeTopicId.set(suggestion.topic_id);
      this._activeSubtopicId.set(suggestion.subtopic_id);
    }
  }

  /**
   * `evaluation.delta`: carries a `section_suggestion` (auto steering) and the
   * oracle `open_questions` at the top level — feed both (P0 #1).
   */
  private applyEvaluationDelta(payload: Record<string, unknown>): void {
    const raw = payload['section_suggestion'];
    if (raw && typeof raw === 'object') {
      const node = raw as Record<string, unknown>;
      const suggestion: CaptureSectionSuggestion = {
        topic_id: node['topic_id'] != null ? String(node['topic_id']) : null,
        subtopic_id: node['subtopic_id'] != null ? String(node['subtopic_id']) : null,
        confidence: node['confidence'] != null ? Number(node['confidence']) : null,
        manual_locked: node['manual_locked'] === true,
      };
      this._sectionSuggestion.set(suggestion);
      if (!suggestion.manual_locked && suggestion.subtopic_id) {
        this._activeTopicId.set(suggestion.topic_id);
        this._activeSubtopicId.set(suggestion.subtopic_id);
      }
    }
    this.ingestOpenQuestions(payload);
  }

  /**
   * Upsert grounded oracle open questions (from `oracle.questions` /
   * `evaluation.delta`) into the oracle signal. Accepts the top-level
   * `open_questions` array (or a nested `oracle.open_questions`), keyed by id.
   */
  private ingestOpenQuestions(payload: Record<string, unknown>): void {
    const nested =
      payload['oracle'] && typeof payload['oracle'] === 'object'
        ? (payload['oracle'] as Record<string, unknown>)
        : {};
    const raw = Array.isArray(payload['open_questions'])
      ? (payload['open_questions'] as unknown[])
      : Array.isArray(nested['open_questions'])
        ? (nested['open_questions'] as unknown[])
        : null;
    if (!raw) return;
    const ts = Date.now();
    this._oracle.update((items) => {
      const byId = new Map(items.map((q) => [q.id, q]));
      for (const entry of raw) {
        if (!entry || typeof entry !== 'object') continue;
        const q = entry as Record<string, unknown>;
        const text = String(q['text'] ?? q['follow_up'] ?? '').trim();
        if (!text) continue;
        const id = String(q['id'] ?? q['question_id'] ?? this.uid());
        const prev = byId.get(id);
        byId.set(id, {
          id,
          text,
          status: this.normalizeOracleStatus(q['status'], prev?.status),
          ts_ms: prev?.ts_ms ?? ts,
          topic_id: q['topic_id'] != null ? String(q['topic_id']) : prev?.topic_id ?? null,
          priority: q['priority'] != null ? Number(q['priority']) : prev?.priority ?? null,
        });
      }
      return Array.from(byId.values());
    });
  }

  private normalizeOracleStatus(
    value: unknown,
    fallback: CaptureOracleItem['status'] = 'active',
  ): CaptureOracleItem['status'] {
    return value === 'active' ||
      value === 'open' ||
      value === 'answered' ||
      value === 'dismissed' ||
      value === 'deferred'
      ? value
      : fallback;
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
    // Terminal stage reached but the `conversation.step` carrying the proposal
    // can be lost (LiveKit data-channel drop, gateway hiccup). Give it a short
    // grace, then recover by fetching the persisted proposal — never let the
    // finalize surface sit on the 90s guard after the backend said "done".
    if (stage === 'done') this.expediteFinalizeRecovery(6000);
    else if (stage === 'failed') this.expediteFinalizeRecovery(1500);
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
    const feedId = ref.event_id ?? ref.turn_id ?? null;
    if (opts.asFeed) {
      const id = feedId ?? this.uid();
      this._feed.update((items) => {
        const idx = items.findIndex((i) => i.kind === 'anchor' && i.id === id);
        const next: CaptureFeedItem = {
          id,
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
    } else if (feedId) {
      // Anchor chips in the Fil are bound to `item.view` on the FEED item, not
      // to `_viewReferences` — a correction (confirm / discard / rebind) must
      // refresh the existing feed copy too, or the chip appears dead. Update
      // in place only; never append a new feed row on a pure correction.
      this._feed.update((items) => {
        const idx = items.findIndex((i) => i.kind === 'anchor' && i.id === feedId);
        if (idx === -1) return items;
        const copy = items.slice();
        copy[idx] = { ...copy[idx], view: { ...copy[idx].view, ...ref } };
        return copy;
      });
    }
  }

  private patchViewStatus(eventId: string, status: CaptureAnchorStatus | null): void {
    this._viewReferences.update((refs) =>
      refs.map((r) => (r.event_id === eventId ? { ...r, status: status ?? undefined } : r)),
    );
    // Mirror onto the feed-bound copy the chips actually render.
    this._feed.update((items) =>
      items.map((i) =>
        i.kind === 'anchor' && i.view?.event_id === eventId
          ? { ...i, view: { ...i.view, status: status ?? undefined } }
          : i,
      ),
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
      collection: (payload['collection'] as string) ?? (payload['collection_name'] as string) ?? null,
      collection_name:
        (payload['collection_name'] as string) ?? (payload['collection'] as string) ?? null,
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

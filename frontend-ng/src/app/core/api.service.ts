import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';

export interface CapturePlanRequest {
  objective: string;
  title?: string | null;
  expert_profile?: string | null;
  duration_minutes?: number | null;
  context_id?: string | null;
  system_id?: string | null;
  knowledge_refs?: string[];
  voice_runtime?: string;
  plan_mode?: 'ai_plan' | 'provided_plan' | 'free_conversation' | 'plan_build' | string;
  capture_domain?: string | null;
  provided_plan_text?: string | null;
  plan_source_kind?: 'manual' | 'pasted_text' | 'uploaded_file' | 'conversation' | null;
  plan_source_filename?: string | null;
  plan_source_replaces_existing_plan?: boolean;
}

export interface CapturePlanSourceExtractResponse {
  filename: string;
  text: string;
  chars: number;
  content_type?: string | null;
  document_type?: string | null;
  truncated?: boolean;
}

export interface CaptureQualityBacklog {
  imprecisions: Array<Record<string, unknown>>;
  contradictions: Array<Record<string, unknown>>;
  open_questions: Array<Record<string, unknown>>;
  defer_weak_contradictions?: boolean;
}

export interface PlanDialogueTurnRequest {
  text?: string;
  confirm_finalize?: boolean;
}

export interface CaptureTurnRequest {
  speaker: 'expert' | 'system' | 'operator';
  text: string;
  question_id?: string | null;
  audio_ref?: string | null;
  client_turn_id?: string | null;
  retrieval_event_id?: string | null;
  interruption_of_event_id?: string | null;
  turn_kind?: 'answer' | 'correction' | 'complement';
  input_modality?: 'voice' | 'text';
  /**
   * When ``false`` the turn is journaled without triggering the evaluation
   * loop — used by the unified composer for silent text expressions (the
   * written equivalent of a free-conversation voice turn).
   */
  compute_evaluation?: boolean;
  document_refs?: Record<string, unknown>[];
  visual_context?: Record<string, unknown> | null;
}

/**
 * A journaled deictic view reference. Shared shape between the realtime
 * `capture.view.referenced` WS event (voice turns) and the `view_references`
 * array returned synchronously in the turn HTTP response (text turns).
 */
export interface CaptureViewReference {
  session_id?: string | null;
  document_id?: string | null;
  filename?: string | null;
  title?: string | null;
  page?: number | null;
  slide?: number | null;
  image_index?: number | null;
  turn_id?: string | null;
  timecode_ms?: number | null;
  statement?: string | null;
  trigger_phrase?: string | null;
  /** Journaled capture event id — addresses this anchor for updateCaptureView. */
  event_id?: string | null;
  /**
   * Anchor lifecycle status (D2). `pending` is purely client-side (ghost
   * countdown); the backend journals `confirmed` (1 distinct view) or
   * `lowconf` (>=2 views, confidence < 0.7); `discarded` is a user correction.
   */
  status?: CaptureAnchorStatus;
  /** Deterministic confidence of the deictic resolution (1.0 = single view). */
  confidence?: number | null;
}

/** Anchor lifecycle status shared with the backend journaling contract (D2). */
export type CaptureAnchorStatus = 'pending' | 'confirmed' | 'lowconf' | 'discarded';

/**
 * One entry of the backend "Le Fil" feed projection (D1 step C). The event
 * ledger is projected server-side into ordered `speak | note | anchor` entries
 * so the Fil can hydrate on session load/resume before appending live WS
 * events. Mirrors the {@link CaptureFeedItem} the engine binds to.
 */
export interface CaptureFeedEntry {
  id: string;
  kind: 'speak' | 'note' | 'anchor';
  channel: 'voice' | 'text';
  speaker: string | null;
  text: string;
  partial: boolean;
  ts_ms: number | null;
  turn_id?: string | null;
  event_id?: string | null;
  view?: CaptureViewReference;
}

/** Document share scope for the end-of-capture triage (D5). Default `excerpt`. */
export type CaptureShareLevel = 'full' | 'excerpt' | 'none';

/**
 * Per-document indexing lifecycle shared with the backend. During the session
 * we only ever surface `not_indexed` / `referenced`; `queued` / `indexed` /
 * `failed` belong to the end-of-capture background batch.
 *
 * Lifted out of the v0 monolith so the new `capture-fil/` experience can bind
 * to a stable contract without importing from the frozen component.
 */
export type CaptureIndexStatus = 'not_indexed' | 'referenced' | 'queued' | 'indexed' | 'failed';

/** A document attached to a capture session (uploaded or referenced). */
export interface CaptureSessionDocument {
  document_id?: string | null;
  filename?: string | null;
  title?: string | null;
  collection?: string | null;
  collection_name?: string | null;
  status?: string | null;
  chunks_processed?: number | null;
  job_id?: string | null;
  /** Indexing lifecycle state (shared contract with the backend). */
  index_status?: CaptureIndexStatus | null;
  /** Number of journaled view references pointing at this document. */
  referenced_views_count?: number | null;
  /**
   * Share scope chosen at end-of-capture triage (D5). Replaces the v0
   * boolean `full_share` (kept for retro-read of legacy sessions).
   */
  share_level?: CaptureShareLevel;
  /** Legacy v0 flag — `true` maps to `share_level: 'full'`. */
  full_share?: boolean | null;
}

/** A document view pinned to the omni-composer / "en scène". */
export interface CapturePinnedView {
  key: string;
  document_id: string | null;
  collection: string | null;
  filename: string | null;
  title: string | null;
  page?: number | null;
  slide?: number | null;
  image_index?: number | null;
  association_mode?: string;
}

/** Body for `POST .../views/{event_id}` — anchor correction (D2 / T0.3). */
export interface CaptureViewUpdateRequest {
  action: 'confirm' | 'discard' | 'rebind';
  document_id?: string | null;
  page?: number | null;
  slide?: number | null;
  image_index?: number | null;
}

/** One item of the end-of-capture share-level triage payload (D5 / T0.1). */
export interface CaptureShareLevelItem {
  document_id: string;
  share_level: CaptureShareLevel;
}

/**
 * Response of `POST .../turns` (addCaptureTurn). `view_references` carries the
 * deictic references the backend journaled for THIS text turn (voice turns get
 * the same payload over the WS instead). Empty/absent when nothing was journaled.
 */
export interface CaptureTurnResponse {
  next_prompt?: string | null;
  next_question_id?: string | null;
  system_prompt_event_id?: string | null;
  evaluation?: { verdict: string; score: number; follow_up?: string } | null;
  view_references?: CaptureViewReference[];
}

export interface CaptureDocumentViewRequest {
  document_id?: string | null;
  collection?: string | null;
  collection_name?: string | null;
  filename?: string | null;
  title?: string | null;
  page?: number | null;
  page_number?: number | null;
  slide?: number | null;
  image_index?: number | null;
  preview?: string | null;
  association_mode?: string;
}

export interface RetrievalPrefetchRequest {
  client_turn_id?: string | null;
  question_id?: string | null;
  partial_text: string;
  mode?: string;
  top_k?: number;
}

export interface ConversationStepRequest {
  client_turn_id?: string | null;
  text: string;
  question_id?: string | null;
  retrieval_event_id?: string | null;
  interruption_of_event_id?: string | null;
  last_proposal_id?: string | null;
}

export interface PublishedCaptureFicheUser {
  id: string;
  label: string;
}

export interface PublishedCaptureFiche {
  id: string;
  proposal_id: string;
  title: string;
  category?: string | null;
  destination?: string | null;
  collection_slug?: string | null;
  published_at?: string | null;
  published_by?: PublishedCaptureFicheUser | null;
  author?: PublishedCaptureFicheUser | null;
  capture_session_id: string;
  session_title?: string | null;
  document_id?: string | null;
  word_count?: number;
  chunks_processed?: number;
  open_questions_count?: number;
  preview_url?: string | null;
  raw_url?: string | null;
  session_owned_by_current_user?: boolean;
}

export interface ProposalReviewRequest {
  status: 'accepted' | 'rejected' | 'changes_requested';
  reviewer?: string | null;
  review_notes?: string | null;
}

export interface CaptureEventAmendRequest {
  text_amended: string;
  actor?: string | null;
  reason?: string | null;
}

/**
 * Body for the inline chat-correction endpoint. An expert (REVIEW_ROLES)
 * corrects/completes an assistant answer; the backend turns it into a
 * ``pending_review`` knowledge proposal. ``input_modality`` distinguishes a
 * typed correction (``text``) from a dictated one (``voice``); when voice was
 * used, ``transcript_raw`` carries the raw STT output while ``correction``
 * holds the expert-edited text.
 */
export interface ChatCorrectionRequest {
  query: string;
  answer: string;
  correction: string;
  message_id: string;
  session_id?: string | null;
  sources?: unknown[];
  transcript_raw?: string | null;
  /** Pre-resolved object-store reference, when the caller already uploaded. */
  audio_ref?: string | null;
  /** Base64-encoded dictation audio (no data: prefix) for backend audit/replay. */
  audio_base64?: string | null;
  audio_content_type?: string | null;
  input_modality: 'text' | 'voice';
}

export interface ChatCorrectionResponse {
  proposal_id: string;
  review_queue_url?: string | null;
  /**
   * Lifecycle of the correction. ``published`` means the workspace has expert
   * review disabled and the fiche went live immediately; ``pending_review``
   * keeps the legacy review-queue flow.
   */
  status?: 'published' | 'pending_review' | string | null;
  /**
   * Ready-to-show natural-language acknowledgement sentence (e.g. "J'ai bien
   * pris en compte votre correction : …"). Empty/absent when the backend has
   * nothing conversational to surface.
   */
  acknowledgement?: string | null;
  /** Server-assigned id of the persisted acknowledgement assistant message. */
  ack_message_id?: string | null;
  /** Short thematic synthesis of the correction. */
  summary?: string | null;
}

export interface VoiceRuntimeProviderOption {
  slug: string;
  status: string;
  description?: string;
  transport?: string;
  models?: string[];
  capabilities?: Record<string, boolean>;
}

export interface VoiceRuntimeCatalog {
  default_provider: string;
  allowed_providers: string[];
  fallback_providers: string[];
  events: string[];
  providers: VoiceRuntimeProviderOption[];
  decision_rule?: string;
}

export type KnowledgeGuideTargetType = 'collection' | 'scope';
export type KnowledgeGuideStatus = 'draft' | 'published' | 'archived';

export interface KnowledgeGuide {
  id: string;
  guide_key: string;
  workspace_id: string;
  target_type: KnowledgeGuideTargetType;
  target_ref: string;
  title: string;
  status: KnowledgeGuideStatus;
  version: number;
  is_current: boolean;
  supersedes_id?: string | null;
  created_by_user_id?: string | null;
  created_at?: string | null;
  published_at?: string | null;
  snippet?: string | null;
  markdown?: string | null;
}

export interface KnowledgeGuideList {
  workspace_id: string;
  workspace_slug: string;
  items: KnowledgeGuide[];
}

export interface TableFactItem {
  content?: string | null;
  semantic_type?: string | null;
  document_id?: string | null;
  document_filename?: string | null;
  sheet_name?: string | null;
  cell_ref?: string | null;
  cell_range?: string | null;
  row_start?: number | null;
  row_end?: number | null;
  row_label?: string | null;
  column_header?: string | null;
  unit?: string | null;
  table_region_id?: string | null;
  interpretation_note?: string | null;
  chunk_index?: number | null;
  subject?: string | null;
  measure?: string | null;
  value_raw?: string | null;
  value_numeric?: number | null;
}

export interface TableFactList {
  collection_name: string;
  vector_db_type: string;
  items: TableFactItem[];
  total_returned: number;
  total?: number;
  has_more?: boolean;
  by_type?: Record<string, number>;
  total_is_exact?: boolean;
  limit: number;
  offset: number;
}

export interface TableQueryResponse {
  intent: string;
  plan: Record<string, unknown>;
  answer_payload: Record<string, unknown>;
  evidence_rows: Record<string, unknown>[];
  excluded_rows: Record<string, unknown>[];
  warnings: string[];
  effective_profile: Record<string, unknown>;
}

export interface DocumentFactItem {
  content?: string | null;
  semantic_type?: string | null;
  document_id?: string | null;
  document_filename?: string | null;
  document_type?: string | null;
  source_path?: string | null;
  subject?: string | null;
  predicate?: string | null;
  value_raw?: string | null;
  value_numeric?: number | null;
  unit?: string | null;
  page?: number | null;
  section_path?: string | null;
  paragraph_index?: number | null;
  table_index?: number | null;
  evidence_locator?: Record<string, unknown> | null;
  qualifiers?: Record<string, unknown> | null;
  semantic_tags?: string[] | null;
  confidence?: number | null;
}

export interface DocumentFactList {
  collection_name: string;
  items: DocumentFactItem[];
  total_returned: number;
  total?: number;
  has_more?: boolean;
  by_type?: Record<string, number>;
  limit: number;
  offset: number;
}

export interface DocumentQueryResponse {
  intent: string;
  plan: Record<string, unknown>;
  answer_payload: Record<string, unknown>;
  evidence_rows: Record<string, unknown>[];
  warnings: string[];
  effective_profile: Record<string, unknown>;
}

@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly http = inject(HttpClient);
  readonly base = '/api/v1';

  get<T>(path: string, params?: Record<string, string>): Observable<T> {
    let httpParams = new HttpParams();
    if (params) {
      Object.entries(params).forEach(([k, v]) => (httpParams = httpParams.set(k, v)));
    }
    return this.http.get<T>(`${this.base}${path}`, { params: httpParams });
  }

  post<T>(path: string, body: unknown = {}): Observable<T> {
    return this.http.post<T>(`${this.base}${path}`, body);
  }

  patch<T>(path: string, body: unknown = {}): Observable<T> {
    return this.http.patch<T>(`${this.base}${path}`, body);
  }

  put<T>(path: string, body: unknown = {}): Observable<T> {
    return this.http.put<T>(`${this.base}${path}`, body);
  }

  delete<T>(path: string): Observable<T> {
    return this.http.delete<T>(`${this.base}${path}`);
  }

  getBlob(path: string): Observable<Blob> {
    return this.http.get(`${this.base}${path}`, { responseType: 'blob' });
  }

  /** Upload an audio blob and receive a transcription. */
  transcribeAudio(
    blob: Blob,
    filename = 'recording.webm',
    provider?: string | null,
  ): Observable<{ text: string; provider?: string; model?: string; fallback?: boolean }> {
    const form = new FormData();
    form.append('file', blob, filename);
    let params = new HttpParams().set('language', 'fr');
    if (provider) params = params.set('provider', provider);
    const options = { params };
    return this.http.post<{ text: string; provider?: string; model?: string; fallback?: boolean }>(
      `${this.base}/voice/transcribe`,
      form,
      options,
    );
  }

  /** Synthesize speech (returns a playable audio Blob). */
  synthesizeSpeech(
    text: string,
    voice = 'nova',
    provider?: string | null,
    options?: { latency_profile?: string | null; surface?: string | null; format?: string | null },
  ): Observable<Blob> {
    return this.http.post(
      `${this.base}/voice/synthesize`,
      {
        text,
        voice,
        provider: provider || undefined,
        latency_profile: options?.latency_profile || undefined,
        surface: options?.surface || undefined,
        format: options?.format || undefined,
      },
      { responseType: 'blob' },
    );
  }

  listVoiceRuntimes(): Observable<VoiceRuntimeCatalog> {
    return this.get<VoiceRuntimeCatalog>('/voice/runtimes');
  }

  listKnowledgeGuides(params?: {
    target_type?: KnowledgeGuideTargetType;
    target_ref?: string;
    status?: KnowledgeGuideStatus;
    current_only?: boolean;
  }): Observable<KnowledgeGuideList> {
    const query: Record<string, string> = {};
    if (params?.target_type) query['target_type'] = params.target_type;
    if (params?.target_ref) query['target_ref'] = params.target_ref;
    if (params?.status) query['status'] = params.status;
    if (params?.current_only !== undefined) query['current_only'] = String(params.current_only);
    return this.get<KnowledgeGuideList>('/knowledge/guides', query);
  }

  createKnowledgeGuide(body: {
    target_type: KnowledgeGuideTargetType;
    target_ref: string;
    title: string;
    markdown: string;
    status?: KnowledgeGuideStatus;
  }): Observable<KnowledgeGuide> {
    return this.post<KnowledgeGuide>('/knowledge/guides', body);
  }

  updateKnowledgeGuide(
    guideKey: string,
    body: Partial<{
      target_type: KnowledgeGuideTargetType;
      target_ref: string;
      title: string;
      markdown: string;
      status: KnowledgeGuideStatus;
    }>,
  ): Observable<KnowledgeGuide> {
    return this.patch<KnowledgeGuide>(`/knowledge/guides/${guideKey}`, body);
  }

  listTableFacts(params: {
    collection_name: string;
    semantic_type?: string;
    sheet_name?: string;
    q?: string;
    limit?: number;
    offset?: number;
  }): Observable<TableFactList> {
    const query: Record<string, string> = {
      collection_name: params.collection_name,
      limit: String(params.limit ?? 100),
      offset: String(params.offset ?? 0),
    };
    if (params.semantic_type) query['semantic_type'] = params.semantic_type;
    if (params.sheet_name) query['sheet_name'] = params.sheet_name;
    if (params.q) query['q'] = params.q;
    return this.get<TableFactList>('/documents/table-facts', query);
  }

  queryKnowledgeTable(body: {
    collection_or_scope?: string | null;
    question: string;
    mode?: string;
    filters?: Record<string, unknown>;
    system_id?: string | null;
    table_profile_key?: string | null;
    include_evidence?: boolean;
  }): Observable<TableQueryResponse> {
    return this.post<TableQueryResponse>('/knowledge/table-query', body);
  }

  listDocumentFacts(params: {
    collection_name: string;
    semantic_type?: string;
    q?: string;
    limit?: number;
    offset?: number;
  }): Observable<DocumentFactList> {
    const query: Record<string, string> = {
      collection_name: params.collection_name,
      limit: String(params.limit ?? 100),
      offset: String(params.offset ?? 0),
    };
    if (params.semantic_type) query['semantic_type'] = params.semantic_type;
    if (params.q) query['q'] = params.q;
    return this.get<DocumentFactList>('/documents/document-facts', query);
  }

  queryKnowledgeDocument(body: {
    collection_or_scope?: string | null;
    question: string;
    mode?: string;
    filters?: Record<string, unknown>;
    system_id?: string | null;
    document_profile_key?: string | null;
    include_evidence?: boolean;
  }): Observable<DocumentQueryResponse> {
    return this.post<DocumentQueryResponse>('/knowledge/document-query', body);
  }

  createCapturePlan(body: CapturePlanRequest): Observable<unknown> {
    return this.post('/knowledge-capture/plans', body);
  }

  extractCapturePlanSource(file: File): Observable<CapturePlanSourceExtractResponse> {
    const form = new FormData();
    form.append('file', file, file.name);
    return this.http.post<CapturePlanSourceExtractResponse>(`${this.base}/knowledge-capture/plan-source/extract`, form);
  }

  listCaptureSessions(
    status?: string,
    domain?: string,
    systemId?: string | null,
    includeArchived = false,
  ): Observable<unknown> {
    const params: Record<string, string> = {};
    if (status) params['status'] = status;
    if (domain) params['domain'] = domain;
    if (systemId) params['system_id'] = systemId;
    if (includeArchived) params['include_archived'] = 'true';
    return this.get('/knowledge-capture/sessions', Object.keys(params).length ? params : undefined);
  }

  listPublishedCaptureFiches(params?: {
    category?: string;
    destination?: string;
    author_user_id?: string;
    published_after?: string;
    published_before?: string;
    q?: string;
    limit?: number;
    offset?: number;
  }): Observable<{ fiches: PublishedCaptureFiche[]; total: number; limit: number; offset: number; has_more: boolean }> {
    const query: Record<string, string> = {};
    if (params?.category) query['category'] = params.category;
    if (params?.destination) query['destination'] = params.destination;
    if (params?.author_user_id) query['author_user_id'] = params.author_user_id;
    if (params?.published_after) query['published_after'] = params.published_after;
    if (params?.published_before) query['published_before'] = params.published_before;
    if (params?.q) query['q'] = params.q;
    if (params?.limit != null) query['limit'] = String(params.limit);
    if (params?.offset != null) query['offset'] = String(params.offset);
    return this.get('/knowledge-capture/fiches', Object.keys(query).length ? query : undefined);
  }

  archiveCaptureSession(sessionId: string): Observable<unknown> {
    return this.post(`/knowledge-capture/sessions/${sessionId}/archive`);
  }

  unarchiveCaptureSession(sessionId: string): Observable<unknown> {
    return this.post(`/knowledge-capture/sessions/${sessionId}/unarchive`);
  }

  deleteCaptureSession(sessionId: string): Observable<unknown> {
    return this.delete(`/knowledge-capture/sessions/${sessionId}`);
  }

  getCaptureQualityBacklog(sessionId: string): Observable<CaptureQualityBacklog> {
    return this.get<CaptureQualityBacklog>(`/knowledge-capture/sessions/${sessionId}/quality-backlog`);
  }

  deferCaptureQualityItem(
    sessionId: string,
    body: { item_id: string; bucket: string; deferred_reason?: string },
  ): Observable<CaptureQualityBacklog> {
    return this.post<CaptureQualityBacklog>(`/knowledge-capture/sessions/${sessionId}/quality/defer`, body);
  }

  patchCaptureOracleQuestions(
    sessionId: string,
    body: {
      items: Array<{
        question_id?: string | null;
        question_text?: string | null;
        status: 'active' | 'open' | 'answered' | 'dismissed' | 'deferred';
      }>;
    },
  ): Observable<unknown> {
    return this.patch(`/knowledge-capture/sessions/${sessionId}/oracle-questions`, body);
  }

  patchCaptureSessionFlags(
    sessionId: string,
    body: {
      defer_weak_contradictions?: boolean;
      suppress_oracle_questions?: boolean;
      capture_domain?: string;
      focused_quality_question_id?: string | null;
      focused_quality_evaluation_id?: string | null;
    },
  ): Observable<unknown> {
    return this.patch(`/knowledge-capture/sessions/${sessionId}/flags`, body);
  }

  planDialogueTurn(sessionId: string, body: PlanDialogueTurnRequest): Observable<unknown> {
    return this.post(`/knowledge-capture/sessions/${sessionId}/plan/dialogue-turn`, body);
  }

  finalizeCapturePlan(sessionId: string): Observable<unknown> {
    return this.post(`/knowledge-capture/sessions/${sessionId}/plan/finalize`);
  }

  getCapturePlanTopics(sessionId: string): Observable<unknown> {
    return this.get(`/knowledge-capture/sessions/${sessionId}/plan/topics`);
  }

  updateCapturePlanTopics(sessionId: string, topics: Record<string, unknown>[]): Observable<unknown> {
    return this.patch(`/knowledge-capture/sessions/${sessionId}/plan/topics`, { topics });
  }

  validateCapturePlanTopics(sessionId: string): Observable<unknown> {
    return this.post(`/knowledge-capture/sessions/${sessionId}/plan/validate-topics`);
  }

  getCaptureHintQueue(sessionId: string, subtopicId?: string): Observable<unknown> {
    const params = subtopicId ? { subtopic_id: subtopicId } : undefined;
    return this.get(`/knowledge-capture/sessions/${sessionId}/hint-queue`, params);
  }

  pauseCaptureSession(sessionId: string): Observable<unknown> {
    return this.post(`/knowledge-capture/sessions/${sessionId}/pause`);
  }

  resumeCaptureSession(sessionId: string): Observable<unknown> {
    return this.post(`/knowledge-capture/sessions/${sessionId}/resume`);
  }

  getCaptureClosureSheet(sessionId: string): Observable<{
    markdown: string;
    topics?: string[];
    captured_facts?: unknown[];
    unresolved?: Array<{ bucket?: string; label?: string; status?: string }>;
  }> {
    return this.get(`/knowledge-capture/sessions/${sessionId}/closure-sheet`);
  }

  applyCaptureSessionClosure(
    sessionId: string,
    body: { action: 'finish' | 'extend' | 'schedule'; extension_minutes?: number },
  ): Observable<unknown> {
    return this.post(`/knowledge-capture/sessions/${sessionId}/closure`, body);
  }

  extendCaptureSession(sessionId: string, extensionMinutes = 15): Observable<unknown> {
    return this.post(`/knowledge-capture/sessions/${sessionId}/extend`, {
      action: 'extend',
      extension_minutes: extensionMinutes,
    });
  }

  exportCaptureProposal(
    sessionId: string,
    body: { executive_summary?: string; proposal_id?: string },
  ): Observable<{ markdown: string }> {
    return this.post<{ markdown: string }>(`/knowledge-capture/sessions/${sessionId}/proposal/export`, body);
  }

  publishCaptureProposal(
    proposalId: string,
    body?: {
      category?: string | null;
      destination?: string | null;
      destination_scope?: string | null;
      final_title?: string | null;
      include_unresolved_questions?: boolean;
    },
  ): Observable<unknown> {
    return this.post(`/knowledge-capture/proposals/${proposalId}/publish`, body || {});
  }

  updateCapturePlan(sessionId: string, plan: Record<string, unknown>): Observable<unknown> {
    return this.patch(`/knowledge-capture/sessions/${sessionId}/plan`, { plan });
  }

  approveCapturePlan(sessionId: string): Observable<unknown> {
    return this.post(`/knowledge-capture/sessions/${sessionId}/plan/approve`);
  }

  startCaptureSession(sessionId: string): Observable<unknown> {
    return this.post(`/knowledge-capture/sessions/${sessionId}/start`);
  }

  addCaptureTurn(sessionId: string, body: CaptureTurnRequest): Observable<CaptureTurnResponse> {
    return this.post<CaptureTurnResponse>(`/knowledge-capture/sessions/${sessionId}/turns`, body);
  }

  listCaptureDocuments(sessionId: string): Observable<unknown> {
    return this.get(`/knowledge-capture/sessions/${sessionId}/documents`);
  }

  uploadCaptureDocuments(sessionId: string, files: FileList | File[]): Observable<unknown> {
    const formData = new FormData();
    Array.from(files).forEach((file) => formData.append('files', file));
    return this.post(`/knowledge-capture/sessions/${sessionId}/documents`, formData);
  }

  recordCaptureDocumentView(sessionId: string, body: CaptureDocumentViewRequest): Observable<unknown> {
    return this.post(`/knowledge-capture/sessions/${sessionId}/documents/view`, body);
  }

  /**
   * End-of-capture selection: mark which uploaded documents should be ingested
   * in full by the background batch (in addition to the views journaled during
   * the session). Returns the updated documents collection (same shape as the
   * GET endpoint), so the caller can refresh chip statuses.
   */
  setCaptureDocumentsFullShare(sessionId: string, documentIds: string[]): Observable<unknown> {
    return this.post(`/knowledge-capture/sessions/${sessionId}/documents/full-share`, {
      document_ids: documentIds,
    });
  }

  /**
   * End-of-capture triage (D5 / T0.1): set the share scope per document.
   * Replaces the boolean `full-share` selection with `{full, excerpt, none}`.
   * Returns the updated documents collection (same shape as the GET endpoint).
   */
  setCaptureShareLevel(sessionId: string, items: CaptureShareLevelItem[]): Observable<unknown> {
    return this.post(`/knowledge-capture/sessions/${sessionId}/documents/share-level`, { items });
  }

  /**
   * Anchor correction (D2 / T0.3): confirm / discard / rebind a journaled
   * deictic view reference, addressed by its capture event id. Returns the
   * updated reference so the caller can refresh the anchor chip.
   */
  updateCaptureView(
    sessionId: string,
    eventId: string,
    body: CaptureViewUpdateRequest,
  ): Observable<CaptureViewReference> {
    return this.post<CaptureViewReference>(
      `/knowledge-capture/sessions/${sessionId}/views/${eventId}`,
      body,
    );
  }

  /**
   * Typed projection of the event ledger into the ordered "Le Fil" feed (D1
   * step C): `speak | note | anchor` entries with anchor status/confidence.
   * The Fil hydrates from this on session load/resume, then keeps appending
   * live WS events (WS stays the live source of truth).
   */
  getCaptureFeed(sessionId: string): Observable<{ feed: CaptureFeedEntry[] }> {
    return this.get<{ feed: CaptureFeedEntry[] }>(`/knowledge-capture/sessions/${sessionId}/feed`);
  }

  listCaptureEvents(sessionId: string, afterSequence?: number, businessOnly = false): Observable<unknown> {
    const params: Record<string, string> = {};
    if (afterSequence !== undefined) {
      params['after_sequence'] = String(afterSequence);
    }
    if (businessOnly) {
      params['business_only'] = 'true';
    }
    return this.get(`/knowledge-capture/sessions/${sessionId}/events`, params);
  }

  prefetchCaptureRetrieval(
    sessionId: string,
    body: RetrievalPrefetchRequest,
  ): Observable<unknown> {
    return this.post(`/knowledge-capture/sessions/${sessionId}/retrieval-prefetch`, body);
  }

  runConversationStep(
    sessionId: string,
    body: ConversationStepRequest,
  ): Observable<unknown> {
    return this.post(`/knowledge-capture/sessions/${sessionId}/conversation-step`, body);
  }

  amendCaptureEvent(
    sessionId: string,
    eventId: string,
    body: CaptureEventAmendRequest,
  ): Observable<unknown> {
    return this.patch(`/knowledge-capture/sessions/${sessionId}/events/${eventId}/amend`, body);
  }

  createCaptureProposal(sessionId: string): Observable<unknown> {
    return this.post(`/knowledge-capture/sessions/${sessionId}/proposal`);
  }

  listCaptureProposals(status?: string, systemId?: string | null, sessionId?: string | null): Observable<unknown> {
    const params: Record<string, string> = {};
    if (status) params['status'] = status;
    if (systemId) params['system_id'] = systemId;
    if (sessionId) params['session_id'] = sessionId;
    return this.get('/knowledge-capture/proposals', Object.keys(params).length ? params : undefined);
  }

  reviewCaptureProposal(proposalId: string, body: ProposalReviewRequest): Observable<unknown> {
    return this.patch(`/knowledge-capture/proposals/${proposalId}/review`, body);
  }

  updateCaptureProposalContent(proposalId: string, content: string): Observable<unknown> {
    return this.patch(`/knowledge-capture/proposals/${proposalId}/content`, { content });
  }

  patchCaptureProposalOpenQuestions(
    proposalId: string,
    body: {
      items: Array<{
        question_key?: string | null;
        question_id?: string | null;
        question_text?: string | null;
        status: 'open' | 'answered' | 'invalid' | 'deferred';
      }>;
    },
  ): Observable<unknown> {
    return this.patch(`/knowledge-capture/proposals/${proposalId}/open-questions`, body);
  }

  /** Answer a single open question (text OR voice-transcribed-to-text). Marks the
   * question `answered` and returns the proposal after targeted section re-synthesis. */
  answerCaptureProposalOpenQuestion(
    proposalId: string,
    questionId: string,
    body: { text: string },
  ): Observable<unknown> {
    return this.post(
      `/knowledge-capture/proposals/${proposalId}/open-questions/${questionId}/answer`,
      body,
    );
  }

  applyCaptureProposalInstruction(
    proposalId: string,
    body: { instruction: string; current_content?: string | null },
  ): Observable<unknown> {
    return this.post(`/knowledge-capture/proposals/${proposalId}/instruction`, body);
  }

  /**
   * Submit an expert correction/completion of a chat answer. Creates a
   * ``pending_review`` knowledge proposal in the existing KC review queue.
   * The backend returns 403 when the feature is disabled for the workspace
   * or the caller lacks the ``chat_correct`` permission, so callers must
   * degrade gracefully on that status.
   */
  submitChatCorrection(body: ChatCorrectionRequest): Observable<ChatCorrectionResponse> {
    return this.post<ChatCorrectionResponse>('/knowledge-capture/chat-correction', body);
  }

}

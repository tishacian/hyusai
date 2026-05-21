import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';

export interface CapturePlanRequest {
  objective: string;
  title?: string | null;
  expert_profile?: string | null;
  duration_minutes?: number;
  context_id?: string | null;
  system_id?: string | null;
  knowledge_refs?: string[];
  voice_runtime?: string;
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
}

export interface TableFactList {
  collection_name: string;
  vector_db_type: string;
  items: TableFactItem[];
  total_returned: number;
  limit: number;
  offset: number;
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
    const options = provider ? { params: new HttpParams().set('provider', provider) } : {};
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

  createCapturePlan(body: CapturePlanRequest): Observable<unknown> {
    return this.post('/knowledge-capture/plans', body);
  }

  listCaptureSessions(status?: string): Observable<unknown> {
    return this.get('/knowledge-capture/sessions', status ? { status } : undefined);
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

  addCaptureTurn(sessionId: string, body: CaptureTurnRequest): Observable<unknown> {
    return this.post(`/knowledge-capture/sessions/${sessionId}/turns`, body);
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

  listCaptureProposals(status?: string): Observable<unknown> {
    return this.get('/knowledge-capture/proposals', status ? { status } : undefined);
  }

  reviewCaptureProposal(proposalId: string, body: ProposalReviewRequest): Observable<unknown> {
    return this.patch(`/knowledge-capture/proposals/${proposalId}/review`, body);
  }
}

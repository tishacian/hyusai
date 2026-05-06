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

  /** Upload an audio blob and receive a transcription. */
  transcribeAudio(blob: Blob, filename = 'recording.webm'): Observable<{ text: string }> {
    const form = new FormData();
    form.append('file', blob, filename);
    return this.http.post<{ text: string }>(`${this.base}/voice/transcribe`, form);
  }

  /** Synthesize speech (returns a playable audio Blob). */
  synthesizeSpeech(text: string, voice = 'nova'): Observable<Blob> {
    return this.http.post(
      `${this.base}/voice/synthesize`,
      { text, voice },
      { responseType: 'blob' },
    );
  }

  listVoiceRuntimes(): Observable<unknown> {
    return this.get('/knowledge-capture/voice-runtimes');
  }

  createCapturePlan(body: CapturePlanRequest): Observable<unknown> {
    return this.post('/knowledge-capture/plans', body);
  }

  listCaptureSessions(status?: string): Observable<unknown> {
    return this.get('/knowledge-capture/sessions', status ? { status } : undefined);
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

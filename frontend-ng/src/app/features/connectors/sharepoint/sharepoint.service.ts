/**
 * Typed HTTP wrapper around the `/api/v1/sharepoint/*` routes shipped
 * in the 2026-04-20 Guest-Link foundation (commits `671a3a4`→`df4cf80`)
 * and extended in Vague E / E4.1 with RAG ingest + audit hooks.
 *
 * Two auth modes, one backend:
 *  - `'session'` — Guest Link / OTP (Playwright-captured storage_state,
 *    uploaded via PUT /sessions/{key}).
 *  - `'msal'`    — Standard OAuth (MSAL app with admin-consented
 *    delegated permissions).
 *
 * The UI picks the user-facing label; the backend mode string stays the
 * historical `session`/`msal` values so we don't churn the API surface.
 */
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from '@app/core/api.service';

export type SharePointAuthMode = 'session' | 'msal';

export interface SharePointSessionStatus {
  session_key: string;
  exists: boolean;
  tenant_host?: string | null;
  sharing_url?: string | null;
  captured_at?: string | null;
}

export interface SharePointSyncRequest {
  session_key: string;
  folder_server_relative_url: string;
  sharing_url?: string | null;
  auth_mode: SharePointAuthMode;
  prune_local_files?: boolean;
  client_id?: string | null;
  tenant_host?: string | null;
  user_hint?: string | null;
  output_dir?: string | null;
  collection_name?: string;
}

export type SharePointJobState = 'running' | 'completed' | 'failed';
export type SharePointJobStatus = 'completed' | 'login_required' | 'failed' | null;

export interface SharePointJobSummary {
  job_id: string;
  session_key: string;
  auth_mode: SharePointAuthMode;
  state: SharePointJobState;
  status: SharePointJobStatus;
  progress?: string | null;
  files_total: number;
  files_downloaded: number;
  bytes_total: number;
  ingested_count: number;
  ingest_failed_count: number;
  collection_name?: string | null;
  login_required_detail?: string | null;
  error?: string | null;
  output_dir?: string | null;
  folder_server_relative_url?: string | null;
  created_at: string;
  updated_at: string;
}

export interface SharePointSessionUpload {
  /** Raw JSON produced by
   * `python scripts/sharepoint_connector_demo.py --export-session`. */
  session_dict: Record<string, unknown>;
}

@Injectable({ providedIn: 'root' })
export class SharepointApiService {
  private readonly api = inject(ApiService);

  getSessionStatus(sessionKey: string): Observable<SharePointSessionStatus> {
    return this.api.get<SharePointSessionStatus>(
      `/sharepoint/sessions/${encodeURIComponent(sessionKey)}`,
    );
  }

  uploadSession(sessionKey: string, body: SharePointSessionUpload): Observable<void> {
    return this.api.put<void>(
      `/sharepoint/sessions/${encodeURIComponent(sessionKey)}`,
      body,
    );
  }

  deleteSession(sessionKey: string): Observable<void> {
    return this.api.delete<void>(
      `/sharepoint/sessions/${encodeURIComponent(sessionKey)}`,
    );
  }

  enqueueSync(request: SharePointSyncRequest): Observable<SharePointJobSummary> {
    return this.api.post<SharePointJobSummary>('/sharepoint/sync', request);
  }

  getJob(jobId: string): Observable<SharePointJobSummary> {
    return this.api.get<SharePointJobSummary>(
      `/sharepoint/sync/${encodeURIComponent(jobId)}`,
    );
  }

  listJobs(limit = 20): Observable<{ jobs: SharePointJobSummary[] }> {
    return this.api.get<{ jobs: SharePointJobSummary[] }>(
      `/sharepoint/sync`,
      { limit: String(limit) },
    );
  }
}

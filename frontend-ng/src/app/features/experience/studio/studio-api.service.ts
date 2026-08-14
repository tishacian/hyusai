import { Injectable, inject } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { Observable, of } from 'rxjs';
import { catchError, map } from 'rxjs/operators';
import { ApiService } from '@app/core/api.service';
import { CanonicalApiService, type System } from '@app/core/canonical-api.service';
import { hydrateDocument } from './studio-document';
import type { ReadyCheck } from './studio-publish';
import type { StudioExperience } from './studio-model';

export interface StudioBinding {
  binding_key: string;
  system_id: string;
  published_flow_version_id: string;
  flow_sha256?: string;
  ingress_id: string;
  input_schema_sha256?: string;
  output_schema_sha256?: string;
  confirmation_policy: string;
  on_unavailable: string;
}

export interface StudioIngress {
  ingress_id: string;
  kind?: string;
  input_schema?: unknown;
}

export interface StudioIngressList {
  system_id: string;
  published_flow_version_id: string;
  flow_sha256?: string;
  ingresses: StudioIngress[];
}

export interface StudioDetail extends Omit<StudioExperience, 'draft'> {
  draft: {
    pages: unknown;
    binding_keys: string[];
    revision: number;
    content_sha256?: string;
  } | null;
}

export interface StudioRelease {
  id: string;
  release_number: number;
  notes?: string;
}

export function apiMessage(err: unknown, fallback: string): string {
  if (err instanceof HttpErrorResponse) {
    const detail = err.error?.detail;
    if (typeof detail === 'string' && detail.trim()) return detail;
    if (detail && typeof detail === 'object' && typeof detail.message === 'string') {
      return detail.message;
    }
  }
  return fallback;
}

@Injectable({ providedIn: 'root' })
export class StudioApiService {
  private readonly api = inject(ApiService);
  private readonly canonical = inject(CanonicalApiService);

  listExperiences(): Observable<StudioExperience[]> {
    return this.api.get<{ experiences: StudioExperience[] }>('/experiences').pipe(
      map((body) => body.experiences ?? []),
      catchError(() => of([])),
    );
  }

  getExperience(id: string): Observable<StudioDetail> {
    return this.api.get<StudioDetail>(`/experiences/${encodeURIComponent(id)}`);
  }

  createExperience(body: {
    name: string;
    slug: string;
    pattern: string;
    languages: string[];
    theme: Record<string, unknown>;
  }): Observable<StudioDetail> {
    return this.api.post<StudioDetail>('/experiences', body);
  }

  patchExperience(
    id: string,
    body: Partial<{
      name: string;
      slug: string;
      pattern: string;
      languages: string[];
      theme: Record<string, unknown>;
    }>,
  ): Observable<StudioDetail> {
    return this.api.patch<StudioDetail>(`/experiences/${encodeURIComponent(id)}`, body);
  }

  saveDraft(id: string, pages: unknown, bindingKeys: readonly string[]): Observable<unknown> {
    return this.api.put(`/experiences/${encodeURIComponent(id)}/draft`, {
      pages,
      binding_keys: [...bindingKeys],
    });
  }

  readyCheck(id: string): Observable<ReadyCheck> {
    return this.api.get<ReadyCheck>(`/experiences/${encodeURIComponent(id)}/ready-check`);
  }

  createRelease(id: string, notes: string): Observable<StudioRelease> {
    return this.api.post<StudioRelease>(`/experiences/${encodeURIComponent(id)}/releases`, { notes });
  }

  listReleases(id: string): Observable<StudioRelease[]> {
    return this.api.get<{ releases: StudioRelease[] }>(`/experiences/${encodeURIComponent(id)}/releases`).pipe(
      map((body) => body.releases ?? []),
    );
  }

  deploy(
    id: string,
    body: { channel: 'pilot' | 'live'; release_id: string; audience?: Record<string, unknown> },
  ): Observable<unknown> {
    return this.api.post(`/experiences/${encodeURIComponent(id)}/deployments`, body);
  }

  listBindings(): Observable<StudioBinding[]> {
    return this.api.get<{ bindings: StudioBinding[] }>('/system-bindings').pipe(
      map((body) => body.bindings ?? []),
      catchError(() => of([])),
    );
  }

  createBinding(body: {
    binding_key: string;
    system_id: string;
    published_flow_version_id: string;
    ingress_id: string;
    confirmation_policy: string;
    on_unavailable: string;
  }): Observable<StudioBinding> {
    return this.api.post<StudioBinding>('/system-bindings', body);
  }

  patchBinding(
    key: string,
    body: Partial<{ confirmation_policy: string; on_unavailable: string }>,
  ): Observable<StudioBinding> {
    return this.api.patch<StudioBinding>(`/system-bindings/${encodeURIComponent(key)}`, body);
  }

  publishedSystems(): Observable<Array<System & { published_flow_version_id?: string | null }>> {
    return this.canonical.listSystems().pipe(
      map((rows) =>
        rows.filter((row) => {
          const id = (row as System & { published_flow_version_id?: string | null }).published_flow_version_id;
          return typeof id === 'string' && !!id;
        }),
      ),
    );
  }

  listIngresses(systemId: string): Observable<StudioIngressList | null> {
    return this.api.get<StudioIngressList>(`/systems/${encodeURIComponent(systemId)}/ingresses`).pipe(
      catchError(() => of(null)),
    );
  }

  draftDocument(detail: StudioDetail) {
    return hydrateDocument(detail.draft?.pages ?? { pages: [] });
  }
}

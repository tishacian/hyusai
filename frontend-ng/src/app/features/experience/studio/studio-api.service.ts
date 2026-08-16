import { Injectable, inject } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';
import { ApiService } from '@app/core/api.service';
import { CanonicalApiService, type System } from '@app/core/canonical-api.service';
import type { I18nService } from '@app/core/i18n.service';
import { hydrateDocument } from './studio-document';
import type { ReadyBindingEvidence, ReadyCheck } from './studio-publish';
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
  output_schema?: unknown | null;
  ingresses: StudioIngress[];
}

export interface StudioDraft {
  pages: unknown;
  binding_keys: string[];
  revision: number;
  content_sha256: string;
}

export interface StudioDraftRevision extends StudioDraft {
  id: string;
  experience_id: string;
  saved_by?: string | null;
  created_at?: string | null;
}

export interface StudioDeployment {
  id?: string;
  channel: 'pilot' | 'live' | string;
  release_id: string;
  previous_release_id?: string | null;
  audience?: Record<string, unknown> | null;
  updated_at?: string | null;
}

export interface StudioDetail extends Omit<StudioExperience, 'draft' | 'deployments'> {
  draft: StudioDraft | null;
  deployments?: StudioDeployment[];
}

export interface StudioRelease {
  id: string;
  release_number: number;
  content_sha256?: string;
  pages?: unknown;
  bindings_snapshot?: ReadyBindingEvidence[];
  access_snapshot?: Record<string, unknown>;
  identity_snapshot?: Record<string, unknown>;
  languages?: string[];
  theme?: Record<string, unknown>;
  renderer_version?: string | null;
  notes?: string;
  created_at?: string | null;
}

export interface StudioDrift {
  status: 'drift' | 'unavailable';
  binding: StudioBinding;
  reasons: string[];
}

export function apiCode(err: unknown): string | null {
  if (!(err instanceof HttpErrorResponse)) return null;
  const detail = err.error?.detail;
  return detail && typeof detail === 'object' && typeof detail.code === 'string'
    ? detail.code
    : null;
}

function apiMessage(err: unknown, fallback: string): string {
  if (err instanceof HttpErrorResponse) {
    const detail = err.error?.detail;
    if (typeof detail === 'string' && detail.trim()) return detail;
    if (detail && typeof detail === 'object' && typeof detail.message === 'string') {
      return detail.message;
    }
  }
  return fallback;
}

/**
 * A business rejection always carries a `{code, message}` detail; the API only
 * answers with a detail *array* when it refuses the payload's shape. So an array
 * means this bundle and the API no longer agree on the contract — a tab that
 * outlived a deployment — and no retry will help until the page is reloaded.
 */
export function isContractMismatch(err: unknown): boolean {
  return err instanceof HttpErrorResponse && err.status === 422 && Array.isArray(err.error?.detail);
}

/** Resolves an API failure into text the author can act on. */
export function studioError(i18n: I18nService, err: unknown, fallbackKey: string): string {
  if (isContractMismatch(err)) return i18n.t('experience.error.outdated_tab');
  return apiMessage(err, i18n.t(fallbackKey));
}

@Injectable({ providedIn: 'root' })
export class StudioApiService {
  private readonly api = inject(ApiService);
  private readonly canonical = inject(CanonicalApiService);

  listExperiences(): Observable<StudioExperience[]> {
    return this.api.get<{ experiences: StudioExperience[] }>('/experiences').pipe(
      map((body) => body.experiences ?? []),
    );
  }

  getExperience(id: string): Observable<StudioDetail> {
    return this.api.get<StudioDetail>(`/experiences/${encodeURIComponent(id)}`);
  }

  createExperience(body: {
    name: string;
    description?: string | null;
    emblem?: string | null;
    slug: string;
    pattern: string;
    languages: string[];
    theme: Record<string, unknown>;
    access_policy?: Record<string, unknown>;
  }): Observable<StudioDetail> {
    return this.api.post<StudioDetail>('/experiences', body);
  }

  patchExperience(
    id: string,
    body: Partial<{
      name: string;
      description: string | null;
      emblem: string | null;
      slug: string;
      pattern: string;
      languages: string[];
      theme: Record<string, unknown>;
      access_policy: Record<string, unknown>;
      expected_updated_at: string;
    }>,
  ): Observable<StudioDetail> {
    return this.api.patch<StudioDetail>(`/experiences/${encodeURIComponent(id)}`, body);
  }

  saveDraft(
    id: string,
    pages: unknown,
    bindingKeys: readonly string[],
    expectedRevision: number,
  ): Observable<StudioDraft> {
    return this.api.put<StudioDraft>(`/experiences/${encodeURIComponent(id)}/draft`, {
      pages,
      binding_keys: [...bindingKeys],
      expected_revision: expectedRevision,
    });
  }

  listDraftRevisions(id: string): Observable<StudioDraftRevision[]> {
    return this.api
      .get<{ revisions: StudioDraftRevision[] }>(
        `/experiences/${encodeURIComponent(id)}/draft/revisions`,
      )
      .pipe(map((body) => body.revisions ?? []));
  }

  restoreDraftRevision(
    id: string,
    revision: number,
    expectedRevision: number,
  ): Observable<StudioDraft> {
    return this.api.post<StudioDraft>(
      `/experiences/${encodeURIComponent(id)}/draft/revisions/${revision}/restore`,
      { expected_revision: expectedRevision },
    );
  }

  finalizeDraft(
    id: string,
    body: {
      pages: unknown;
      bindingKeys: readonly string[];
      expectedRevision: number;
      bindings: readonly StudioBinding[];
      languages: readonly string[];
      theme: Record<string, unknown>;
      accessPolicy: Record<string, unknown>;
      description?: string | null;
      emblem?: string | null;
      expectedExperienceUpdatedAt: string;
    },
  ): Observable<StudioDraft> {
    return this.api.put<StudioDraft>(`/experiences/${encodeURIComponent(id)}/draft/finalize`, {
      pages: body.pages,
      binding_keys: [...body.bindingKeys],
      expected_revision: body.expectedRevision,
      bindings: body.bindings.map((row) => ({
        binding_key: row.binding_key,
        system_id: row.system_id,
        published_flow_version_id: row.published_flow_version_id,
        ingress_id: row.ingress_id,
        confirmation_policy: row.confirmation_policy,
        on_unavailable: row.on_unavailable,
      })),
      languages: [...body.languages],
      theme: body.theme,
      access_policy: body.accessPolicy,
      description: body.description ?? null,
      emblem: body.emblem ?? null,
      expected_experience_updated_at: body.expectedExperienceUpdatedAt,
    });
  }

  readyCheck(id: string): Observable<ReadyCheck> {
    return this.api.get<ReadyCheck>(`/experiences/${encodeURIComponent(id)}/ready-check`);
  }

  createRelease(
    id: string,
    body: {
      notes: string;
      expectedDraftRevision: number;
      expectedContentSha256: string;
      expectedExperienceUpdatedAt: string;
      expectedBindingsSha256: string;
    },
  ): Observable<StudioRelease> {
    return this.api.post<StudioRelease>(`/experiences/${encodeURIComponent(id)}/releases`, {
      notes: body.notes,
      expected_draft_revision: body.expectedDraftRevision,
      expected_content_sha256: body.expectedContentSha256,
      expected_experience_updated_at: body.expectedExperienceUpdatedAt,
      expected_bindings_sha256: body.expectedBindingsSha256,
    });
  }

  listReleases(id: string): Observable<StudioRelease[]> {
    return this.api.get<{ releases: StudioRelease[] }>(`/experiences/${encodeURIComponent(id)}/releases`).pipe(
      map((body) => body.releases ?? []),
    );
  }

  deploy(
    id: string,
    body: {
      channel: 'pilot' | 'live';
      release_id: string;
      expected_current_release_id: string | null;
      expected_deployment_updated_at: string | null;
      audience?: Record<string, unknown>;
    },
  ): Observable<StudioDeployment> {
    return this.api.post<StudioDeployment>(`/experiences/${encodeURIComponent(id)}/deployments`, body);
  }

  rollback(
    id: string,
    channel: 'pilot' | 'live',
    body: {
      releaseId: string;
      expectedCurrentReleaseId: string;
      expectedDeploymentUpdatedAt: string;
    },
  ): Observable<StudioDeployment> {
    return this.api.post<StudioDeployment>(
      `/experiences/${encodeURIComponent(id)}/deployments/${channel}/rollback`,
      {
        release_id: body.releaseId,
        expected_current_release_id: body.expectedCurrentReleaseId,
        expected_deployment_updated_at: body.expectedDeploymentUpdatedAt,
      },
    );
  }

  listBindings(): Observable<StudioBinding[]> {
    return this.api.get<{ bindings: StudioBinding[] }>('/system-bindings').pipe(
      map((body) => body.bindings ?? []),
    );
  }

  listDriftedBindings(): Observable<StudioDrift[]> {
    return this.api.get<{ bindings: StudioDrift[] }>('/system-bindings/drift').pipe(
      map((body) => body.bindings ?? []),
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
    body: Partial<{
      confirmation_policy: string;
      on_unavailable: string;
      published_flow_version_id: string;
      ingress_id: string;
    }>,
  ): Observable<StudioBinding> {
    return this.api.patch<StudioBinding>(`/system-bindings/${encodeURIComponent(key)}`, body);
  }

  publishedSystems(): Observable<Array<System & { published_flow_version_id?: string | null }>> {
    return this.canonical.listSystems({ propagateErrors: true }).pipe(
      map((rows) =>
        rows.filter((row) => {
          const id = (row as System & { published_flow_version_id?: string | null }).published_flow_version_id;
          return row.status === 'active' && typeof id === 'string' && !!id;
        }),
      ),
    );
  }

  listIngresses(systemId: string): Observable<StudioIngressList> {
    return this.api.get<StudioIngressList>(`/systems/${encodeURIComponent(systemId)}/ingresses`);
  }

  draftDocument(detail: StudioDetail) {
    return hydrateDocument(detail.draft?.pages ?? { pages: [] });
  }
}

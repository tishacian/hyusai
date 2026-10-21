import { Injectable, inject } from '@angular/core';
import { Observable, map } from 'rxjs';
import { ApiService } from '@app/core/api.service';
import type { Skill } from '@app/core/canonical-api.service';

/** A built-in example, with the exact envelope an import would send. */
export interface SystemExample {
  id: string;
  version: string;
  name: string;
  objective: string;
  requires: string[];
  provenance: { publisher: string; source: string; example_id: string; version: string };
  envelope: Record<string, unknown>;
}

/** What `POST /systems/import` would create; nothing exists yet. */
export interface SystemImportPreview {
  name: string;
  objective: string;
  nodes: Array<{ id: string; label: string | null; kind: string | null; skill_slug: string | null }>;
  edge_count: number;
  resolved_skills: string[];
  unresolved_skills: string[];
  source: Record<string, unknown>;
  valid: boolean;
  issues: unknown[];
}

/**
 * Reads and writes of the "where to start" step of Créer. Every call keeps its
 * error channel and is pinned to the workspace it was made for; the caller
 * drops a response that lands after a workspace switch.
 */
@Injectable({ providedIn: 'root' })
export class StartApiService {
  private readonly api = inject(ApiService);

  examples(workspaceSlug: string | null): Observable<SystemExample[]> {
    return this.api
      .get<{ examples: SystemExample[] }>('/systems/examples', undefined, { workspaceSlug })
      .pipe(map((body) => body.examples ?? []));
  }

  preview(envelope: Record<string, unknown>, workspaceSlug: string | null): Observable<SystemImportPreview> {
    return this.api.post<SystemImportPreview>('/systems/import/preview', { envelope }, { workspaceSlug });
  }

  importEnvelope(envelope: Record<string, unknown>, workspaceSlug: string | null): Observable<{ id: string }> {
    return this.api.post<{ id: string }>('/systems/import', { envelope }, { workspaceSlug });
  }

  skills(workspaceSlug: string | null): Observable<Skill[]> {
    return this.api
      .get<Skill[] | { skills: Skill[] }>('/skills', undefined, { workspaceSlug })
      .pipe(map((body) => (Array.isArray(body) ? body : body.skills ?? [])));
  }

  collectionCount(workspaceSlug: string | null): Observable<number> {
    return this.api
      .get<{ items?: unknown[] }>('/documents/collections', undefined, { workspaceSlug })
      .pipe(map((body) => (Array.isArray(body.items) ? body.items.length : 0)));
  }

  publishedSystemCount(workspaceSlug: string | null): Observable<number> {
    return this.api
      .get<Array<Record<string, unknown>> | { systems: Array<Record<string, unknown>> }>('/systems', undefined, { workspaceSlug })
      .pipe(
        map((body) => (Array.isArray(body) ? body : body.systems ?? [])),
        map((rows) => rows.filter((row) => row['status'] === 'active'
          && typeof row['published_flow_version_id'] === 'string'
          && !!row['published_flow_version_id']).length),
      );
  }
}

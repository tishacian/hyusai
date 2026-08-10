import { Injectable, computed, effect, inject, signal } from '@angular/core';
import {
  EMPTY,
  Observable,
  catchError,
  filter,
  map,
  of,
  tap,
  throwError,
} from 'rxjs';
import { ApiService } from '@app/core/api.service';
import type { SystemStatus } from '@app/core/canonical-api.service';
import { WorkspaceService } from '@app/core/workspace.service';
import {
  readWorkspaceLocalJson,
  writeWorkspaceLocalJson,
} from '@app/core/workspace-local-storage';

export interface SystemAgent {
  id: string;
  name: string;
  description: string;
  objective?: string;
  capability_id?: string | null;
  status: SystemStatus;
  rag_mode?: string;
  model?: string;
  template?: string;
  prompt?: string;
  skills?: string[];
  collections?: string[];
  draft?: boolean;
  created_at?: string;
  // Persisted shape carried by `_serialize`; read to tell an executable Flow
  // apart from a RAG pipeline without a second round-trip.
  flow_definition?: Record<string, unknown> | null;
  settings?: Record<string, unknown> | null;
  // Canonical per-System defaults exposed by the backend (migration 005).
  default_prompt_type?: string | null;
  default_model?: string | null;
  retrieval_mode_default?: string | null;
}

const LS_KEY = 'agentium_system_drafts';

@Injectable({ providedIn: 'root' })
export class SystemsStore {
  private readonly api = inject(ApiService);
  private readonly workspace = inject(WorkspaceService);

  private readonly remote = signal<SystemAgent[]>([]);
  private readonly draftsWorkspaceSlug = signal<string | null>(this.workspace.currentSlug());
  private readonly drafts = signal<SystemAgent[]>(this.readDrafts());
  private readonly capabilityFilter = signal<string | null>(null);
  private loadGeneration = 0;
  readonly loading = signal<boolean>(true);

  readonly systems = computed<SystemAgent[]>(() => {
    const ids = new Set(this.remote().map((a) => a.id));
    const onlyLocal = this.drafts().filter((d) => !ids.has(d.id));
    const combined = [...this.remote(), ...onlyLocal];
    const capabilityId = this.capabilityFilter();
    return capabilityId
      ? combined.filter((system) => system.capability_id === capabilityId)
      : combined;
  });

  constructor() {
    this.workspace.registerContextReset((transition) => {
      this.loadGeneration += 1;
      this.remote.set([]);
      this.capabilityFilter.set(null);
      this.draftsWorkspaceSlug.set(transition.nextSlug);
      this.drafts.set(this.readDrafts(transition.nextSlug));
      this.loading.set(true);
    });
    effect(() => {
      writeWorkspaceLocalJson(
        localStorage,
        LS_KEY,
        this.draftsWorkspaceSlug(),
        this.drafts(),
      );
    });
  }

  private readDrafts(slug = this.workspace.currentSlug()): SystemAgent[] {
    return readWorkspaceLocalJson<SystemAgent[]>({
      storage: localStorage,
      baseKey: LS_KEY,
      workspaceSlug: slug,
      knownWorkspaceSlugs: this.workspace.workspaces().map((workspace) => workspace.slug),
      isValue: (value): value is SystemAgent[] => Array.isArray(value),
    }) ?? [];
  }

  load(options?: { capabilityId?: string | null }): Observable<SystemAgent[]> {
    const scope = this.workspace.captureRequestScope();
    const generation = ++this.loadGeneration;
    const capabilityId = options?.capabilityId || null;
    this.capabilityFilter.set(capabilityId);
    this.remote.set([]);
    this.loading.set(true);
    // Canonical `/systems` — the legacy `/agents` path has been retired.
    return this.api
      .get<{ systems: SystemAgent[] } | SystemAgent[]>(
        '/systems',
        capabilityId ? { capability_id: capabilityId } : undefined,
        {
        workspaceSlug: scope.workspaceSlug,
        },
      )
      .pipe(
        map((res) => (Array.isArray(res) ? res : res?.systems ?? [])),
        map((list) =>
          list.map((a) => ({
            ...a,
            description: a.description ?? a.objective ?? '',
          })),
        ),
        filter(() => (
          generation === this.loadGeneration
          && this.workspace.isRequestScopeCurrent(scope)
        )),
        tap((list) => {
          this.remote.set(list);
          this.loading.set(false);
        }),
        catchError((error: unknown) => {
          if (
            generation !== this.loadGeneration
            || !this.workspace.isRequestScopeCurrent(scope)
          ) {
            return EMPTY;
          }
          this.remote.set([]);
          this.loading.set(false);
          return throwError(() => error);
        }),
      );
  }

  findById(id: string): SystemAgent | null {
    return this.systems().find((s) => s.id === id) ?? null;
  }

  getById(id: string): Observable<SystemAgent | null> {
    const scope = this.workspace.captureRequestScope();
    const local = this.findById(id);
    if (local) {
      return of(local).pipe(
        filter(() => this.workspace.isRequestScopeCurrent(scope)),
      );
    }
    return this.api
      .get<SystemAgent>(`/systems/${id}`, undefined, {
        workspaceSlug: scope.workspaceSlug,
      })
      .pipe(
        map((a) => ({ ...a, description: a.description ?? '' })),
        filter(() => this.workspace.isRequestScopeCurrent(scope)),
        catchError((error: unknown) => (
          this.workspace.isRequestScopeCurrent(scope) ? throwError(() => error) : EMPTY
        )),
      );
  }

  createDraft(input: Partial<SystemAgent> & { name: string }): SystemAgent {
    const slug = input.name
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '')
      .slice(0, 32);
    const id = `draft-${slug || 'system'}-${Date.now().toString(36)}`;
    const draft: SystemAgent = {
      id,
      name: input.name,
      description: input.description ?? '',
      status: 'draft',
      rag_mode: input.rag_mode ?? 'OmniRAG',
      model: input.model ?? 'gpt-4o-mini',
      template: input.template,
      prompt: input.prompt,
      skills: input.skills ?? [],
      collections: input.collections ?? [],
      draft: true,
      created_at: new Date().toISOString(),
    };
    this.drafts.update((list) => [...list, draft]);
    return draft;
  }

  removeDraft(id: string): void {
    this.drafts.update((list) => list.filter((d) => d.id !== id));
  }
}

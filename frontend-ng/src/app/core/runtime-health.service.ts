import { Injectable, computed, inject, signal } from '@angular/core';
import { EMPTY, Observable, catchError, filter, of, shareReplay, tap } from 'rxjs';

import { ApiService } from './api.service';
import { WorkspaceService } from './workspace.service';

type Status = 'bound' | 'stub' | 'unbound' | 'catalog_only';

interface RuntimeHealthEntry {
  status: Status;
  declared_status?: string | null;
  module?: string | null;
}

interface RuntimeHealthResponse {
  skills: Record<string, RuntimeHealthEntry>;
  summary: Record<Status, number>;
}

/**
 * Preset → underlying skill slugs mapping used by retrieval modes in
 * the System Builder and Chat panel. When any of the required slugs is
 * not `bound`, the preset is surfaced with a warning badge or disabled.
 */
export const RETRIEVAL_PRESET_SKILLS: Record<string, string[]> = {
  OmniRAG: ['chain_mixed_hah_v1', 'semantic_search_v1'],
  HAH: ['chain_mixed_hah_v1', 'semantic_search_v1'],
  Hybrid: ['chain_hybrid_v1', 'semantic_search_v1'],
  Semantic: ['chain_naive_v1', 'semantic_search_v1'],
  None: ['llm_rag_answer_v1'],
};

@Injectable({ providedIn: 'root' })
export class RuntimeHealthService {
  private readonly api = inject(ApiService);
  private readonly workspace = inject(WorkspaceService);

  private readonly data = signal<RuntimeHealthResponse | null>(null);
  private cache$: Observable<RuntimeHealthResponse> | null = null;

  constructor() {
    this.workspace.registerContextReset(() => {
      this.data.set(null);
      this.cache$ = null;
    });
  }

  load(force = false): Observable<RuntimeHealthResponse> {
    if (!force && this.cache$) return this.cache$;
    const scope = this.workspace.captureRequestScope();
    this.cache$ = this.api
      .get<RuntimeHealthResponse>('/skills/runtime-health', undefined, {
        workspaceSlug: scope.workspaceSlug,
      })
      .pipe(
        filter(() => this.workspace.isRequestScopeCurrent(scope)),
        tap((r) => {
          this.data.set(r);
        }),
        catchError(() => {
          if (!this.workspace.isRequestScopeCurrent(scope)) return EMPTY;
          const empty = { skills: {}, summary: { bound: 0, stub: 0, unbound: 0, catalog_only: 0 } as Record<Status, number> };
          this.data.set(empty);
          return of(empty);
        }),
        shareReplay(1),
      );
    return this.cache$;
  }

  readonly snapshot = computed(() => this.data()?.skills ?? {});
  readonly summary = computed(() => this.data()?.summary ?? null);

  /** Return the worst status across the slugs of a retrieval preset. */
  presetStatus(preset: string): Status {
    const slugs = RETRIEVAL_PRESET_SKILLS[preset] ?? [];
    if (!slugs.length) return 'bound';
    const snap = this.snapshot();
    const order: Status[] = ['catalog_only', 'unbound', 'stub', 'bound'];
    let worstIdx = order.length - 1;
    for (const slug of slugs) {
      const entry = snap[slug];
      const st: Status = entry?.status ?? 'catalog_only';
      const idx = order.indexOf(st);
      if (idx !== -1 && idx < worstIdx) worstIdx = idx;
    }
    return order[worstIdx];
  }

  presetHealthy(preset: string): boolean {
    return this.presetStatus(preset) === 'bound';
  }
}

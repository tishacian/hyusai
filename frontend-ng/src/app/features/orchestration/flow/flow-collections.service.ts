/**
 * `FlowCollectionsService` — the collections catalogue for the Flow Builder's
 * asset-node picker.
 *
 * The Flow Builder had no shared collections source (the inspector shipped a
 * plain `collection_slug` text input as a Phase-1 stopgap). This service is
 * that source: a single, cached fetch of `GET /documents/collections` exposed
 * as signals with explicit load/empty/error state so the picker can degrade to
 * a manual text input when the catalogue can't be loaded.
 *
 * Root-provided so the (create/destroy) inspector reuses one fetch instead of
 * re-hitting the endpoint every time it opens.
 */
import { Injectable, inject, signal } from '@angular/core';
import { ApiService } from '@app/core/api.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { Subscription } from 'rxjs';

/** Shape returned by `GET /documents/collections` (subset we consume). */
interface CollectionsPayload {
  collections?: string[];
  items?: Array<{ slug?: string; name?: string }>;
  default?: string | null;
}

interface DocumentsPayload {
  documents?: Array<{
    document_id?: string | null;
    filename?: string | null;
    status?: string | null;
  }>;
  total?: number;
  has_more?: boolean;
}

export interface FlowDocumentOption {
  id: string;
  filename: string;
  status: string | null;
}

export type FlowCollectionsState = 'idle' | 'loading' | 'loaded' | 'error';

@Injectable({ providedIn: 'root' })
export class FlowCollectionsService {
  private readonly api = inject(ApiService);
  private readonly workspace = inject(WorkspaceService);

  /** De-duped, sorted collection slugs (empty until the first response). */
  readonly collections = signal<string[]>([]);
  readonly state = signal<FlowCollectionsState>('idle');
  /** Per-collection document catalogue used by Retrieval node scoping. */
  readonly documents = signal<Record<string, FlowDocumentOption[]>>({});
  readonly documentStates = signal<Record<string, FlowCollectionsState>>({});
  readonly documentTotals = signal<Record<string, number>>({});
  readonly documentHasMore = signal<Record<string, boolean>>({});
  private readonly documentNextOffsets = signal<Record<string, number>>({});

  private started = false;
  private request: Subscription | null = null;
  private readonly documentRequests = new Map<string, Subscription>();

  constructor() {
    this.workspace.registerContextReset((transition) => {
      const shouldReload = this.started;
      this.request?.unsubscribe();
      this.request = null;
      for (const request of this.documentRequests.values()) request.unsubscribe();
      this.documentRequests.clear();
      this.started = false;
      this.collections.set([]);
      this.state.set('idle');
      this.documents.set({});
      this.documentStates.set({});
      this.documentTotals.set({});
      this.documentHasMore.set({});
      this.documentNextOffsets.set({});
      if (shouldReload) {
        queueMicrotask(() => {
          if (this.workspace.contextEpoch() !== transition.nextEpoch) return;
          this.started = true;
          this.load();
        });
      }
    });
  }

  /** Fetch once (idempotent). Call when an asset node is first inspected. */
  ensureLoaded(): void {
    if (this.started) return;
    this.started = true;
    this.load();
  }

  /** Force a re-fetch — used by the picker's "retry" affordance after an error. */
  retry(): void {
    this.started = true;
    this.load();
  }

  /** Load a bounded, tenant-scoped document catalogue for one selected
   * collection. The endpoint caps a page at 1000; the total is kept so the UI
   * can state explicitly when the picker is showing a bounded prefix. */
  ensureDocumentsLoaded(collection: string, force = false, append = false): void {
    const slug = collection.trim();
    if (!slug) return;
    const current = this.documentStates()[slug];
    if (!force && (current === 'loading' || current === 'loaded')) return;
    if (append && this.documentHasMore()[slug] !== true) return;

    const scope = this.workspace.captureRequestScope();
    const existing = append ? this.documentsFor(slug) : [];
    const offset = append ? this.documentNextOffsets()[slug] ?? existing.length : 0;
    this.documentStates.update((states) => ({ ...states, [slug]: 'loading' }));
    this.documentRequests.get(slug)?.unsubscribe();
    const request = this.api
      .get<DocumentsPayload>(
        `/documents/list?collection_name=${encodeURIComponent(slug)}&limit=1000&offset=${offset}`,
      )
      .subscribe({
        next: (res) => {
          if (!this.workspace.isRequestScopeCurrent(scope)) return;
          const byId = new Map(existing.map((item) => [item.id, item] as const));
          for (const item of res?.documents ?? []) {
            const id = String(item?.document_id ?? '').trim();
            if (!id || byId.has(id)) continue;
            byId.set(id, {
              id,
              filename: String(item?.filename ?? id).trim() || id,
              status: item?.status ? String(item.status) : null,
            });
          }
          const options = [...byId.values()].sort((a, b) =>
            a.filename.localeCompare(b.filename),
          );
          const nextOffset = offset + (res?.documents?.length ?? 0);
          const total = Math.max(Number(res?.total ?? options.length) || 0, options.length);
          this.documents.update((all) => ({ ...all, [slug]: options }));
          this.documentTotals.update((totals) => ({
            ...totals,
            [slug]: total,
          }));
          this.documentNextOffsets.update((offsets) => ({
            ...offsets,
            [slug]: nextOffset,
          }));
          this.documentHasMore.update((states) => ({
            ...states,
            [slug]: typeof res?.has_more === 'boolean'
              ? res.has_more
              : nextOffset < total,
          }));
          this.documentStates.update((states) => ({ ...states, [slug]: 'loaded' }));
        },
        error: () => {
          if (!this.workspace.isRequestScopeCurrent(scope)) return;
          this.documents.update((all) => ({ ...all, [slug]: existing }));
          this.documentStates.update((states) => ({ ...states, [slug]: 'error' }));
        },
      });
    this.documentRequests.set(slug, request);
  }

  /** Append the next bounded page so documents beyond the first 1000 remain
   * selectable without loading an entire large collection automatically. */
  loadMoreDocuments(collection: string): void {
    this.ensureDocumentsLoaded(collection, true, true);
  }

  documentsFor(collection: string): FlowDocumentOption[] {
    return this.documents()[collection] ?? [];
  }

  private load(): void {
    const scope = this.workspace.captureRequestScope();
    this.state.set('loading');
    this.request?.unsubscribe();
    this.request = this.api.get<CollectionsPayload>('/documents/collections').subscribe({
      next: (res) => {
        if (!this.workspace.isRequestScopeCurrent(scope)) return;
        const fromNames = res?.collections ?? [];
        const fromItems = (res?.items ?? [])
          .map((item) => item.slug || item.name || '')
          .filter((slug) => !!slug);
        const slugs = Array.from(new Set([...fromNames, ...fromItems]))
          .filter((slug) => !!slug)
          .sort((a, b) => a.localeCompare(b));
        this.collections.set(slugs);
        this.state.set('loaded');
      },
      error: () => {
        if (!this.workspace.isRequestScopeCurrent(scope)) return;
        this.collections.set([]);
        this.state.set('error');
      },
    });
  }
}

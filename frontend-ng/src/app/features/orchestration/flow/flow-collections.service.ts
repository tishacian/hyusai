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

export type FlowCollectionsState = 'idle' | 'loading' | 'loaded' | 'error';

@Injectable({ providedIn: 'root' })
export class FlowCollectionsService {
  private readonly api = inject(ApiService);
  private readonly workspace = inject(WorkspaceService);

  /** De-duped, sorted collection slugs (empty until the first response). */
  readonly collections = signal<string[]>([]);
  readonly state = signal<FlowCollectionsState>('idle');

  private started = false;
  private request: Subscription | null = null;

  constructor() {
    this.workspace.registerContextReset((transition) => {
      const shouldReload = this.started;
      this.request?.unsubscribe();
      this.request = null;
      this.started = false;
      this.collections.set([]);
      this.state.set('idle');
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

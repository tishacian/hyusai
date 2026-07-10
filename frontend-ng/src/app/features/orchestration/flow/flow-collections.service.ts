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

  /** De-duped, sorted collection slugs (empty until the first response). */
  readonly collections = signal<string[]>([]);
  readonly state = signal<FlowCollectionsState>('idle');

  private started = false;

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
    this.state.set('loading');
    this.api.get<CollectionsPayload>('/documents/collections').subscribe({
      next: (res) => {
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
        this.collections.set([]);
        this.state.set('error');
      },
    });
  }
}

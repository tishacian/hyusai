import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { SlicePipe } from '@angular/common';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { forkJoin, Observable, of } from 'rxjs';
import { catchError, map } from 'rxjs/operators';
import {
  CkObjectHeaderComponent,
  type CkObjectKpi,
} from '@app/shared/cockpit/object-header.component';
import { CkTabsComponent, CkTabComponent } from '@app/shared/cockpit/tabs.component';
import { CkPanelComponent } from '@app/shared/cockpit/panel.component';
import { IconComponent } from '@app/shared/ui/icon.component';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import { LensService } from '@app/core/lens';
import { CanonicalApiService, type System } from '@app/core/canonical-api.service';
import { ApiService, DocumentFactItem, KnowledgeGuide, TableFactItem } from '@app/core/api.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { DocumentPreviewComponent } from '@app/shared/document-preview/document-preview.component';
import {
  EmbeddingMapComponent,
  type EmbeddingNodeSelection,
} from './embedding-map.component';

/**
 * `KnowledgeViewComponent` — detail page for a single Knowledge Base
 * (Qdrant collection). Uses the canonical `<ck-object-header>` +
 * `<ck-tabs>` pattern with **live** facets:
 *
 *   - **Overview**  — resolved counts, vector DB, last indexed
 *   - **Sources**   — table of ingested documents
 *   - **Chunks**    — distribution + sample (from stats endpoint)
 *   - **Bindings**  — Systems whose `flow_definition.collections`
 *                     references this KB (client-side filter, low
 *                     cardinality — acceptable tradeoff, see
 *                     vague-b-p1 plan §Commit 4)
 */
interface DocRow {
  document_id: string;
  filename: string;
  source_kind?: string;
  extension?: string;
  chunk_count?: number;
  chunks_count?: number;
  mime_type?: string;
  uploaded_at?: string;
  size?: number;
  status?: string;
  source_id?: string;
}

interface StatsPayload {
  collection_name?: string;
  vector_db_type?: string;
  total_chunks?: number;
  vector_dim?: number | null;
  cache_stats?: Record<string, unknown> | null;
}

interface ChunkRow {
  point_id?: string;
  chunk_id?: string;
  document_id?: string;
  document_filename?: string;
  chunk_index?: number | null;
  section_path?: string | null;
  page?: number | string | null;
  semantic_type?: string | null;
  content_length: number;
  content: string;
  truncated: boolean;
}

interface ChunksPayload {
  count: number;
  offset: number;
  has_more: boolean;
  total?: number;
  total_is_exact?: boolean;
  navigation_note?: string;
  chunks: ChunkRow[];
}

interface CollectionsPayload {
  collections?: string[];
  items?: Array<{
    slug?: string;
    name?: string;
    document_count?: number;
    source_count?: number;
    chunk_count?: number;
  }>;
  vector_db_type?: string;
  default?: string | null;
}

interface InventorySourcePayload {
  id?: string;
  filename: string;
  source_kind?: string;
  extension?: string;
  chunk_count?: number;
  mime_type?: string;
  size_bytes?: number;
  status?: string;
  indexed_at?: string | null;
  metadata?: Record<string, unknown>;
}

interface InventoryPayload {
  source_count?: number;
  sources_total?: number;
  document_count?: number;
  chunk_count?: number;
  sources?: InventorySourcePayload[];
  sources_offset?: number;
  sources_limit?: number | null;
  sources_returned?: number;
  sources_has_more?: boolean;
  by_kind?: Record<string, number>;
  by_extension?: Record<string, number>;
  by_status?: Record<string, number>;
  top_sources?: InventorySourcePayload[];
  chunk_buckets?: Record<string, { sources: number; chunks: number }>;
  chunk_percentiles?: Record<string, number>;
  zero_chunk_sources?: number;
  error_sources?: number;
  heavy_sources?: number;
}

interface CollectionDiagnosticsPayload {
  collection_id?: string;
  collection_slug?: string;
  vector_db_type?: string;
  vector_points?: number | null;
  vector_dim?: number | null;
  ledger_source_count?: number;
  ledger_document_count?: number;
  ledger_chunk_sum?: number;
  document_names_count?: number;
  drift?: number | null;
  drift_status?: 'ok' | 'warning' | 'drift' | 'unknown';
  dense?: boolean;
  chunk_buckets?: Record<string, { sources: number; chunks: number }>;
  chunk_percentiles?: Record<string, number>;
  top_sources?: InventorySourcePayload[];
  zero_chunk_sources?: number;
  error_sources?: number;
  heavy_sources?: number;
  by_kind?: Record<string, number>;
  by_extension?: Record<string, number>;
  by_status?: Record<string, number>;
  document_facts?: {
    total?: number;
    by_type?: Record<string, number>;
    docs_by_document_type?: Record<string, number>;
  };
  table_facts?: {
    total?: number;
    by_type?: Record<string, number>;
  };
  feature_status?: Record<string, { state?: string; reason?: string }>;
}

interface KnowledgeScopeApi {
  key: string;
  label?: string | null;
  collection_slugs?: string[];
  table_profile_key?: string | null;
  document_profile_key?: string | null;
}

interface KnowledgeGuideRow {
  guide: KnowledgeGuide;
  binding_label: string;
  binding_kind: 'collection' | 'scope';
}

interface GuideBlock {
  kind: 'h1' | 'h2' | 'h3' | 'li' | 'p';
  text: string;
}

type KbTabId =
  | 'overview'
  | 'sources'
  | 'chunks'
  | 'graph'
  | 'structure'
  | 'facts'
  | 'ocr'
  | 'table-facts'
  | 'guides'
  | 'diagnostics'
  | 'bindings';

@Component({
  selector: 'app-knowledge-view',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    SlicePipe,
    IconComponent,
    EmptyStateComponent,
    CkObjectHeaderComponent,
    CkTabsComponent,
    CkTabComponent,
    CkPanelComponent,
    DocumentPreviewComponent,
    EmbeddingMapComponent,
  ],
  template: `
    <ck-object-header
      eyebrow="Knowledge · Collection"
      [title]="title()"
      subtitle="A knowledge base is a pool of context that one or more Systems can cite at run time."
      [kpis]="kpis()"
    >
      <button
        actions
        type="button"
        (click)="onTabChange('guides')"
        class="inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium bg-brand-500/10 hover:bg-brand-500/15 ring-1 ring-brand-500/25 text-brand-200 transition"
      >
        <app-icon name="book-open" [size]="14" /> Guide
      </button>
      <button
        actions
        type="button"
        (click)="onTabChange('table-facts')"
        class="inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition"
      >
        <app-icon name="table" [size]="14" /> Table facts
      </button>
      <button
        actions
        type="button"
        (click)="bindingsPanelOpen.set(true)"
        class="inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition"
      >
        <app-icon name="link" [size]="14" /> Bindings
      </button>
      <a
        actions
        routerLink="/knowledge"
        class="inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition"
      >
        <app-icon name="arrow-left" [size]="14" /> Back
      </a>
    </ck-object-header>

    @if (!loading() && docCount() === 0 && chunkCount() === 0) {
      <div class="mb-4 rounded-md border border-amber-400/25 bg-amber-500/10 px-4 py-3 text-sm text-amber-100">
        Collection vide ou non indexée : elle ne peut pas encore alimenter le retrieval ni Knowledge Capture.
      </div>
    }
    @if (!loadingBindings() && bindings().length === 0) {
      <div class="mb-4 rounded-md border border-brand-400/20 bg-brand-500/10 px-4 py-3 text-sm text-brand-100">
        Aucun système n’utilise cette collection pour l’instant. Créez ou mettez à jour un Context pour la rendre disponible dans Capture.
      </div>
    }

    <ck-tabs
      [active]="activeTab()"
      [maxVisible]="8"
      (activeChange)="onTabChange($event)"
      ariaLabel="Knowledge facets"
    >
      <ck-tab id="overview" label="Overview">
        <section class="t-card t-elevated rounded-md p-5 space-y-4">
          <div class="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <div>
              <div class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">Documents</div>
              <div class="text-lg font-semibold text-white tabular-nums">{{ loading() ? '…' : docCount() }}</div>
            </div>
            <div>
              <div class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">Chunks</div>
              <div class="text-lg font-semibold text-white tabular-nums">{{ loading() ? '…' : chunkCount() }}</div>
            </div>
            <div>
              <div class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">Vector DB</div>
              <div class="text-lg font-semibold text-white">{{ vectorDbType() || '—' }}</div>
            </div>
            <div>
              <div class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">Embedding dim</div>
              <div class="text-lg font-semibold text-white tabular-nums">{{ vectorDim() ?? '—' }}</div>
            </div>
          </div>
          <div class="text-xs text-gray-400 leading-relaxed max-w-2xl border-t border-white/5 pt-4">
            The collection holds embedded chunks of source documents. Presets (RAG,
            CHAH, HAH) decide how it is consumed by a System at run time. Last
            ingestion time is tracked per document in the Sources tab.
          </div>
          <div class="flex items-center gap-2 flex-wrap text-xs pt-2">
            <p class="text-[11px] text-gray-500">
              Lens: <span class="font-mono text-brand-300">{{ lens() }}</span>
            </p>
          </div>
          @if (diagnostics()) {
            <div class="grid gap-3 border-t border-white/5 pt-4 md:grid-cols-4">
              <article class="rounded border border-white/10 bg-black/20 p-3">
                <div class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">Density</div>
                <div class="mt-1 text-sm font-semibold" [class.text-amber-200]="diagnostics()?.dense" [class.text-emerald-200]="!diagnostics()?.dense">
                  {{ diagnostics()?.dense ? 'Dense corpus' : 'Standard corpus' }}
                </div>
                <p class="mt-1 text-[11px] text-gray-500">Threshold: 100k chunks or 5k sources.</p>
              </article>
              <article class="rounded border border-white/10 bg-black/20 p-3">
                <div class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">Vector points</div>
                <div class="mt-1 text-sm font-semibold text-white tabular-nums">{{ diagnostics()?.vector_points ?? '—' }}</div>
                <p class="mt-1 text-[11px] text-gray-500">Qdrant points currently addressable.</p>
              </article>
              <article class="rounded border border-white/10 bg-black/20 p-3">
                <div class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">Ledger chunks</div>
                <div class="mt-1 text-sm font-semibold text-white tabular-nums">{{ diagnostics()?.ledger_chunk_sum ?? '—' }}</div>
                <p class="mt-1 text-[11px] text-gray-500">Chunk sum from active sources.</p>
              </article>
              <article class="rounded border p-3" [class.border-emerald-400/25]="diagnostics()?.drift_status === 'ok'" [class.border-amber-400/25]="diagnostics()?.drift_status !== 'ok'" [class.bg-emerald-500/10]="diagnostics()?.drift_status === 'ok'" [class.bg-amber-500/10]="diagnostics()?.drift_status !== 'ok'">
                <div class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">Drift</div>
                <div class="mt-1 text-sm font-semibold text-white tabular-nums">{{ diagnostics()?.drift ?? '—' }}</div>
                <p class="mt-1 text-[11px] text-gray-500">{{ diagnostics()?.drift_status || 'unknown' }}</p>
              </article>
            </div>
          }
        </section>
      </ck-tab>

      <ck-tab id="sources" label="Sources">
        <section class="t-card rounded-md p-4 mb-4">
          <div class="grid gap-3 md:grid-cols-[minmax(0,1fr)_160px_140px_140px_170px]">
            <label class="block">
              <span class="ck-mono mb-1 block text-[10px] uppercase tracking-wider text-gray-500">Search sources</span>
              <input
                type="search"
                class="w-full rounded bg-black/25 border border-white/10 px-3 py-2 text-sm text-white outline-none focus:border-brand-400"
                placeholder="Filename, type, extension…"
                [value]="sourceQuery()"
                (input)="sourceQuery.set($any($event.target).value)"
                (keydown.enter)="loadSources(0)"
              />
            </label>
            <label class="block">
              <span class="ck-mono mb-1 block text-[10px] uppercase tracking-wider text-gray-500">Kind</span>
              <select
                class="w-full rounded bg-black/25 border border-white/10 px-2 py-2 text-sm text-white outline-none focus:border-brand-400"
                [value]="sourceKindFilter()"
                (change)="sourceKindFilter.set($any($event.target).value); loadSources(0)"
              >
                <option value="">All kinds</option>
                @for (item of sourceKindOptions(); track item.key) {
                  <option [value]="item.key">{{ item.key }} ({{ item.count }})</option>
                }
              </select>
            </label>
            <label class="block">
              <span class="ck-mono mb-1 block text-[10px] uppercase tracking-wider text-gray-500">Extension</span>
              <select
                class="w-full rounded bg-black/25 border border-white/10 px-2 py-2 text-sm text-white outline-none focus:border-brand-400"
                [value]="sourceExtensionFilter()"
                (change)="sourceExtensionFilter.set($any($event.target).value); loadSources(0)"
              >
                <option value="">All ext.</option>
                @for (item of sourceExtensionOptions(); track item.key) {
                  <option [value]="item.key">{{ item.key }} ({{ item.count }})</option>
                }
              </select>
            </label>
            <label class="block">
              <span class="ck-mono mb-1 block text-[10px] uppercase tracking-wider text-gray-500">Status</span>
              <select
                class="w-full rounded bg-black/25 border border-white/10 px-2 py-2 text-sm text-white outline-none focus:border-brand-400"
                [value]="sourceStatusFilter()"
                (change)="sourceStatusFilter.set($any($event.target).value); loadSources(0)"
              >
                <option value="">All status</option>
                @for (item of sourceStatusOptions(); track item.key) {
                  <option [value]="item.key">{{ item.key }} ({{ item.count }})</option>
                }
              </select>
            </label>
            <div class="grid grid-cols-[1fr_auto] gap-2">
              <label class="block">
                <span class="ck-mono mb-1 block text-[10px] uppercase tracking-wider text-gray-500">Sort</span>
                <select
                  class="w-full rounded bg-black/25 border border-white/10 px-2 py-2 text-sm text-white outline-none focus:border-brand-400"
                  [value]="sourceSort()"
                  (change)="sourceSort.set($any($event.target).value); loadSources(0)"
                >
                  <option value="filename">Filename</option>
                  <option value="chunk_count">Chunks</option>
                  <option value="indexed_at">Indexed</option>
                  <option value="status">Status</option>
                  <option value="source_kind">Kind</option>
                </select>
              </label>
              <button
                type="button"
                title="Toggle sort direction"
                aria-label="Toggle sort direction"
                class="mt-5 inline-flex h-9 w-9 items-center justify-center rounded bg-white/5 text-gray-200 ring-1 ring-white/10 hover:bg-white/10"
                (click)="toggleSourceSortDir()"
              >
                <app-icon [name]="sourceSortDir() === 'asc' ? 'arrow-up' : 'arrow-down'" [size]="14" />
              </button>
            </div>
          </div>
          <div class="mt-3 flex items-center justify-between gap-3 text-xs text-gray-500">
            <span>{{ sourceTotal() }} filtered / {{ sourceGlobalTotal() }} total sources</span>
            <button
              type="button"
              class="inline-flex items-center gap-1.5 rounded bg-white/5 px-3 py-1.5 text-xs font-medium text-gray-200 ring-1 ring-white/10 hover:bg-white/10"
              (click)="loadSources(0)"
            >
              <app-icon name="search" [size]="13" /> Apply
            </button>
          </div>
        </section>
        @if (loadingSources()) {
          <div class="t-card rounded-md p-5 text-center text-gray-400 text-sm">
            <app-icon name="loader-2" [size]="14" class="animate-spin inline-block mr-2" />
            Loading sources…
          </div>
        } @else if (sources().length === 0) {
          <app-empty-state
            icon="file-text"
            title="No sources yet"
            description="Upload documents to this collection from the Knowledge index."
          />
        } @else {
          <div class="t-card rounded-md overflow-hidden">
            <table class="w-full text-sm">
              <thead class="text-[10px] uppercase tracking-wider text-gray-500 bg-black/20">
                <tr>
                  <th class="text-left px-4 py-2 font-semibold">Filename</th>
                  <th class="text-right px-4 py-2 font-semibold">Chunks</th>
                  <th class="text-left px-4 py-2 font-semibold">Type</th>
                  <th class="text-left px-4 py-2 font-semibold">Uploaded</th>
                  <th class="text-right px-4 py-2 font-semibold">Preview</th>
                </tr>
              </thead>
              <tbody>
                @for (s of sources(); track s.document_id) {
                  <tr class="border-t border-white/5 hover:bg-white/5 transition">
                    <td class="px-4 py-2.5 text-white truncate max-w-xs">{{ s.filename }}</td>
                    <td class="px-4 py-2.5 text-right tabular-nums text-gray-300">{{ s.chunk_count ?? '—' }}</td>
                    <td class="px-4 py-2.5 text-gray-400 text-xs">{{ s.mime_type || '—' }}</td>
                    <td class="px-4 py-2.5 text-gray-400 text-xs">{{ s.uploaded_at ? (s.uploaded_at | slice:0:10) : '—' }}</td>
                    <td class="px-4 py-2.5 text-right">
                      <button
                        type="button"
                        title="Preview source document"
                        class="inline-flex items-center justify-center rounded p-1.5 text-gray-400 ring-1 ring-white/10 hover:bg-white/10 hover:text-white"
                        (click)="previewDocument(s)"
                      >
                        <app-icon name="eye" [size]="14" />
                      </button>
                    </td>
                  </tr>
                }
              </tbody>
            </table>
            <div class="flex items-center justify-between gap-3 border-t border-white/5 px-4 py-3 text-xs text-gray-400">
              <span class="font-mono">
                {{ sourceOffset() + 1 }}–{{ sourceOffset() + sources().length }} / {{ sourceTotal() }}
              </span>
              <div class="flex items-center gap-1.5">
                <button
                  type="button"
                  title="Previous page"
                  aria-label="Previous page"
                  class="inline-flex h-7 w-7 items-center justify-center rounded bg-white/5 text-gray-200 ring-1 ring-white/10 hover:bg-white/10 disabled:opacity-40 disabled:hover:bg-white/5"
                  [disabled]="loadingSources() || sourceOffset() === 0"
                  (click)="loadSources(sourceOffset() > sourcePageSize ? sourceOffset() - sourcePageSize : 0)"
                >
                  <app-icon name="chevron-left" [size]="13" />
                </button>
                <button
                  type="button"
                  title="Next page"
                  aria-label="Next page"
                  class="inline-flex h-7 w-7 items-center justify-center rounded bg-white/5 text-gray-200 ring-1 ring-white/10 hover:bg-white/10 disabled:opacity-40 disabled:hover:bg-white/5"
                  [disabled]="loadingSources() || !sourcesHasMore()"
                  (click)="loadSources(sourceOffset() + sourcePageSize)"
                >
                  <app-icon name="chevron-right" [size]="13" />
                </button>
              </div>
            </div>
          </div>
        }
      </ck-tab>

      <ck-tab id="chunks" label="Chunks">
        <section class="t-card rounded-md p-5 space-y-4">
          <div class="grid grid-cols-2 md:grid-cols-3 gap-4 text-sm">
            <div>
              <div class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">Total chunks</div>
              <div class="text-xl font-semibold text-white tabular-nums">{{ loading() ? '…' : chunkCount() }}</div>
            </div>
            <div>
              <div class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">Avg chunks / doc</div>
              <div class="text-xl font-semibold text-white tabular-nums">{{ avgChunksPerDoc() }}</div>
            </div>
            <div>
              <div class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">Vector dim</div>
              <div class="text-xl font-semibold text-white tabular-nums">{{ vectorDim() ?? '—' }}</div>
            </div>
          </div>

          @if (topSources().length > 0) {
            <div class="border-t border-white/5 pt-3">
              <div class="ck-mono text-[10px] uppercase tracking-wider text-gray-500 mb-2">
                Top sources by chunks
              </div>
              <div class="space-y-1.5">
                @for (s of topSources(); track s.document_id) {
                  <div class="flex items-center gap-3 text-xs">
                    <div class="flex-1 min-w-0 truncate text-gray-200">{{ s.filename }}</div>
                    <div class="w-48 bg-white/5 h-1.5 rounded overflow-hidden">
                      <div
                        class="h-full bg-brand-500"
                        [style.width.%]="distributionPct(s.chunk_count)"
                      ></div>
                    </div>
                    <div class="w-10 text-right text-gray-400 tabular-nums">{{ s.chunk_count ?? 0 }}</div>
                  </div>
                }
              </div>
            </div>
          }
          @if (chunkBucketRows().length > 0) {
            <div class="grid gap-2 border-t border-white/5 pt-3 md:grid-cols-6">
              @for (bucket of chunkBucketRows(); track bucket.label) {
                <article class="rounded border border-white/10 bg-black/20 p-3">
                  <div class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">{{ bucket.label }}</div>
                  <div class="mt-1 text-sm font-semibold text-white tabular-nums">{{ bucket.sources }}</div>
                  <p class="mt-1 text-[11px] text-gray-500">{{ bucket.chunks }} chunks</p>
                </article>
              }
            </div>
          }
          @if (chunkPercentiles()['p50'] !== undefined) {
            <div class="flex flex-wrap gap-2 border-t border-white/5 pt-3 text-xs text-gray-400">
              <span class="rounded bg-white/5 px-2 py-1 ring-1 ring-white/10">p50 {{ chunkPercentiles()['p50'] }}</span>
              <span class="rounded bg-white/5 px-2 py-1 ring-1 ring-white/10">p90 {{ chunkPercentiles()['p90'] }}</span>
              <span class="rounded bg-white/5 px-2 py-1 ring-1 ring-white/10">p95 {{ chunkPercentiles()['p95'] }}</span>
              <span class="rounded bg-white/5 px-2 py-1 ring-1 ring-white/10">p99 {{ chunkPercentiles()['p99'] }}</span>
            </div>
          }
        </section>

        <section class="t-card rounded-md overflow-hidden mt-4">
          <div class="px-5 py-4 border-b border-white/5 flex flex-wrap items-center justify-between gap-3">
            <div>
              <div class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">Indexed chunks</div>
              <h3 class="mt-1 text-base font-semibold text-white">Browse embedded chunks</h3>
              <p class="mt-1 max-w-2xl text-xs leading-relaxed text-gray-400">
                The exact text segments stored in the vector index, with their retrieval locators
                (chunk index, section, page). This is what chat actually cites.
              </p>
            </div>
            <div class="flex items-center gap-2">
              <select
                [value]="chunkDocFilter()"
                (change)="onChunkDocFilterChange($event)"
                class="rounded bg-white/5 px-2 py-1.5 text-xs text-gray-200 ring-1 ring-white/10 max-w-[220px]"
              >
                <option value="">All documents</option>
                @for (s of sources(); track s.document_id) {
                  <option [value]="s.document_id">{{ s.filename }}</option>
                }
              </select>
              <button
                type="button"
                (click)="loadChunks(0)"
                class="inline-flex items-center gap-1.5 rounded bg-white/5 px-3 py-1.5 text-xs font-medium text-gray-200 ring-1 ring-white/10 hover:bg-white/10"
              >
                <app-icon name="refresh-cw" [size]="13" /> Load
              </button>
            </div>
          </div>

          @if (loadingChunks()) {
            <div class="p-5 text-center text-gray-400 text-sm">
              <app-icon name="loader-2" [size]="14" class="animate-spin inline-block mr-2" />
              Loading chunks…
            </div>
          } @else if (chunks().length === 0) {
            <div class="p-5 text-center text-gray-500 text-sm">
              No chunks loaded yet. Use “Load” to fetch chunk bodies.
            </div>
          } @else {
            @if (chunkNavigationNote()) {
              <div class="border-b border-amber-400/15 bg-amber-500/10 px-5 py-2 text-xs text-amber-100">
                {{ chunkNavigationNote() }}
              </div>
            }
            <ul class="divide-y divide-white/5">
              @for (c of chunks(); track c.point_id) {
                <li class="px-5 py-3.5 space-y-2">
                  <div class="flex flex-wrap items-center gap-2 text-[10px] text-gray-500">
                    <span class="rounded bg-white/5 px-1.5 py-0.5 font-mono text-gray-300 ring-1 ring-white/10">#{{ c.chunk_index ?? '—' }}</span>
                    <span class="truncate max-w-[260px] text-gray-300">{{ c.document_filename || '—' }}</span>
                    @if (c.section_path) {
                      <span class="text-brand-300">§ {{ c.section_path }}</span>
                    }
                    @if (c.page) {
                      <span>p.{{ c.page }}</span>
                    }
                    @if (c.semantic_type) {
                      <span class="rounded bg-brand-500/10 px-1.5 py-0.5 text-brand-200">{{ c.semantic_type }}</span>
                    }
                    <span class="ml-auto tabular-nums">{{ c.content_length }} chars</span>
                  </div>
                  <p class="text-xs leading-relaxed text-gray-200 whitespace-pre-wrap">{{ c.content }}{{ c.truncated ? '…' : '' }}</p>
                </li>
              }
            </ul>
            <div class="px-5 py-3 border-t border-white/5 flex items-center justify-between text-xs text-gray-400">
              <span>
                Showing {{ chunkOffset() + 1 }}–{{ chunkOffset() + chunks().length }} / {{ chunkTotal() || '—' }}
                @if (!chunkTotalExact()) {
                  <span class="text-amber-200">(estimated)</span>
                }
              </span>
              <div class="flex items-center gap-2">
                <button
                  type="button"
                  [disabled]="chunkOffset() === 0"
                  (click)="loadChunks(chunkOffset() - chunkPageSize)"
                  class="rounded px-2 py-1 ring-1 ring-white/10 hover:bg-white/5 disabled:opacity-40"
                >
                  <app-icon name="chevron-left" [size]="12" /> Prev
                </button>
                <button
                  type="button"
                  [disabled]="!chunksHasMore()"
                  (click)="loadChunks(chunkOffset() + chunkPageSize)"
                  class="rounded px-2 py-1 ring-1 ring-white/10 hover:bg-white/5 disabled:opacity-40"
                >
                  Next <app-icon name="chevron-right" [size]="12" />
                </button>
              </div>
            </div>
          }
        </section>
      </ck-tab>

      <ck-tab id="graph" label="Graph">
        <app-embedding-map
          [collection]="kbId"
          [active]="activeTab() === 'graph'"
          [documents]="sources()"
          (previewRequested)="previewFromNode($event)"
        />
      </ck-tab>

      <ck-tab id="structure" label="Structure">
        <section class="t-card rounded-md overflow-hidden">
          <div class="px-5 py-4 border-b border-white/5 flex items-start justify-between gap-3">
            <div>
              <div class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">
                Document intelligence
              </div>
              <h3 class="mt-1 text-base font-semibold text-white">Extracted document structure</h3>
              <p class="mt-1 max-w-2xl text-xs leading-relaxed text-gray-400">
                Headings, procedures, warnings and tables are extracted from PDF, DOCX,
                Markdown and HTML manuals so retrieval can cite pages and sections, not only chunks.
              </p>
              <p class="mt-2 text-[11px] text-gray-500">
                {{ documentFacts().length }} loaded / {{ documentFactTotal() }} total document facts
              </p>
            </div>
            <button
              type="button"
              (click)="loadDocumentFacts()"
              class="inline-flex items-center gap-1.5 rounded bg-white/5 px-3 py-2 text-xs font-medium text-gray-200 ring-1 ring-white/10 hover:bg-white/10"
            >
              <app-icon name="refresh-cw" [size]="13" /> Refresh
            </button>
          </div>

          @if (loadingDocumentFacts()) {
            <div class="p-5 text-sm text-gray-400">
              <app-icon name="loader-2" [size]="14" class="animate-spin inline-block mr-2" />
              Loading document structure…
            </div>
          } @else if (documentFacts().length === 0) {
            <app-empty-state
              icon="file-search"
              title="No document structure yet"
              description="Re-index PDF, DOCX, Markdown or HTML sources to populate structure and facts."
            />
          } @else {
            <div class="grid gap-4 p-5 lg:grid-cols-3">
              @for (group of documentStructureGroups(); track group.type) {
                <article class="rounded border border-white/10 bg-black/20 p-4">
                  <div class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">{{ group.type }}</div>
                  <div class="mt-1 text-2xl font-semibold text-white tabular-nums">{{ group.count }}</div>
                  <p class="mt-2 text-xs text-gray-500">{{ group.hint }}</p>
                </article>
              }
            </div>
            <div class="divide-y divide-white/5 border-t border-white/5">
              @for (fact of structurePreviewFacts(); track documentFactKey(fact, $index)) {
                <article class="px-5 py-4 hover:bg-white/[0.03] transition">
                  <div class="flex flex-wrap items-center gap-2 text-[11px] text-gray-500">
                    <span class="ck-mono rounded bg-brand-500/10 px-2 py-1 text-brand-300 ring-1 ring-brand-500/20">
                      {{ fact.semantic_type || 'document_fact' }}
                    </span>
                    @if (fact.page) {
                      <span>Page {{ fact.page }}</span>
                    }
                    @if (fact.section_path) {
                      <span class="truncate">Section: <span class="text-gray-300">{{ fact.section_path }}</span></span>
                    }
                  </div>
                  <h4 class="mt-2 text-sm font-medium text-white truncate">
                    {{ fact.document_filename || 'Document source' }}
                  </h4>
                  <p class="mt-2 text-xs leading-relaxed text-gray-300 whitespace-pre-wrap">{{ fact.content }}</p>
                </article>
              }
            </div>
          }
        </section>
      </ck-tab>

      <ck-tab id="facts" label="Facts">
        <section class="t-card rounded-md overflow-hidden">
          <div class="px-5 py-4 border-b border-white/5 flex flex-col gap-3 xl:flex-row xl:items-end xl:justify-between">
            <div>
              <div class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">
                Generic fact layer
              </div>
              <h3 class="mt-1 text-base font-semibold text-white">Document facts</h3>
              <p class="mt-1 max-w-2xl text-xs leading-relaxed text-gray-400">
                Browse extracted procedures, warnings, parameters, definitions and evidence locators.
                These facts complement table facts and vector chunks.
              </p>
              <p class="mt-2 text-[11px] text-gray-500">
                {{ documentFacts().length }} loaded / {{ documentFactTotal() }} total document facts
              </p>
            </div>
            <button
              type="button"
              (click)="loadDocumentFacts()"
              class="inline-flex items-center gap-1.5 rounded bg-white/5 px-3 py-2 text-xs font-medium text-gray-200 ring-1 ring-white/10 hover:bg-white/10"
            >
              <app-icon name="refresh-cw" [size]="13" /> Refresh facts
            </button>
          </div>
          <div class="grid gap-3 border-b border-white/5 px-5 py-4 md:grid-cols-[minmax(0,1fr)_240px]">
            <label class="block">
              <span class="ck-mono mb-1 block text-[10px] uppercase tracking-wider text-gray-500">Search</span>
              <input
                class="w-full rounded bg-black/25 border border-white/10 px-3 py-2 text-sm text-white outline-none focus:border-brand-400"
                type="search"
                placeholder="Procedure, warning, parameter, section…"
                [value]="documentFactQuery()"
                (input)="documentFactQuery.set($any($event.target).value)"
                (keydown.enter)="loadDocumentFacts()"
              />
            </label>
            <label class="block">
              <span class="ck-mono mb-1 block text-[10px] uppercase tracking-wider text-gray-500">Type</span>
              <select
                class="w-full rounded bg-black/25 border border-white/10 px-3 py-2 text-sm text-white outline-none focus:border-brand-400"
                [value]="documentFactType()"
                (change)="documentFactType.set($any($event.target).value); loadDocumentFacts(0)"
              >
                <option value="">All document facts</option>
                <option value="document_heading">Headings</option>
                <option value="document_procedure_step">Procedure steps</option>
                <option value="document_warning">Warnings</option>
                <option value="document_parameter">Parameters</option>
                <option value="document_definition">Definitions</option>
                <option value="document_table">Tables</option>
              </select>
            </label>
          </div>
          @if (loadingDocumentFacts()) {
            <div class="p-5 text-sm text-gray-400">
              <app-icon name="loader-2" [size]="14" class="animate-spin inline-block mr-2" />
              Loading document facts…
            </div>
          } @else if (documentFacts().length === 0) {
            <app-empty-state
              icon="file-search"
              title="No document facts found"
              description="Re-index manual/procedure sources with Document Intelligence enabled, then refresh this tab."
            />
          } @else {
            <div class="divide-y divide-white/5">
              @for (fact of documentFacts(); track documentFactKey(fact, $index)) {
                <article class="px-5 py-4 hover:bg-white/[0.03] transition">
                  <div class="flex flex-wrap items-center gap-2 text-[11px] text-gray-500">
                    <span class="ck-mono rounded bg-brand-500/10 px-2 py-1 text-brand-300 ring-1 ring-brand-500/20">
                      {{ fact.semantic_type || 'document_fact' }}
                    </span>
                    @if (fact.document_type) {
                      <span>{{ fact.document_type }}</span>
                    }
                    @if (fact.page) {
                      <span>Page {{ fact.page }}</span>
                    }
                    @if (fact.paragraph_index !== null && fact.paragraph_index !== undefined) {
                      <span>Paragraph {{ fact.paragraph_index }}</span>
                    }
                    @if (fact.table_index !== null && fact.table_index !== undefined) {
                      <span>Table {{ fact.table_index }}</span>
                    }
                  </div>
                  <h4 class="mt-2 text-sm font-medium text-white truncate">
                    {{ fact.document_filename || 'Document source' }}
                  </h4>
                  @if (fact.section_path) {
                    <p class="mt-1 text-[11px] text-gray-500 truncate">{{ fact.section_path }}</p>
                  }
                  <div class="mt-2 flex flex-wrap gap-2 text-[11px]">
                    @if (fact.subject) {
                      <span class="rounded bg-white/5 px-2 py-1 text-gray-300">subject: {{ fact.subject }}</span>
                    }
                    @if (fact.predicate) {
                      <span class="rounded bg-white/5 px-2 py-1 text-gray-300">predicate: {{ fact.predicate }}</span>
                    }
                    @if (fact.value_raw) {
                      <span class="rounded bg-white/5 px-2 py-1 text-gray-300">value: {{ fact.value_raw }}</span>
                    }
                    @if (fact.unit) {
                      <span class="rounded bg-white/5 px-2 py-1 text-gray-300">unit: {{ fact.unit }}</span>
                    }
                  </div>
                  <p class="mt-3 text-xs leading-relaxed text-gray-300 whitespace-pre-wrap">{{ fact.content }}</p>
                </article>
              }
            </div>
            <div class="flex items-center justify-between border-t border-white/5 px-5 py-3 text-xs text-gray-400">
              <span>{{ documentFactOffset() + 1 }}–{{ documentFactOffset() + documentFacts().length }} / {{ documentFactTotal() }}</span>
              <div class="flex items-center gap-1.5">
                <button
                  type="button"
                  title="Previous page"
                  aria-label="Previous page"
                  class="inline-flex h-7 w-7 items-center justify-center rounded bg-white/5 text-gray-200 ring-1 ring-white/10 hover:bg-white/10 disabled:opacity-40"
                  [disabled]="loadingDocumentFacts() || documentFactOffset() === 0"
                  (click)="loadDocumentFacts(documentFactOffset() > documentFactPageSize ? documentFactOffset() - documentFactPageSize : 0)"
                >
                  <app-icon name="chevron-left" [size]="13" />
                </button>
                <button
                  type="button"
                  title="Next page"
                  aria-label="Next page"
                  class="inline-flex h-7 w-7 items-center justify-center rounded bg-white/5 text-gray-200 ring-1 ring-white/10 hover:bg-white/10 disabled:opacity-40"
                  [disabled]="loadingDocumentFacts() || !documentFactsHasMore()"
                  (click)="loadDocumentFacts(documentFactOffset() + documentFactPageSize)"
                >
                  <app-icon name="chevron-right" [size]="13" />
                </button>
              </div>
            </div>
          }
        </section>
      </ck-tab>

      <ck-tab id="ocr" label="OCR">
        <section class="t-card rounded-md overflow-hidden">
          <div class="px-5 py-4 border-b border-white/5 flex flex-col gap-3 xl:flex-row xl:items-end xl:justify-between">
            <div>
              <div class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">
                Visual document intelligence
              </div>
              <h3 class="mt-1 text-base font-semibold text-white">OCR / visual evidence</h3>
              <p class="mt-1 max-w-2xl text-xs leading-relaxed text-gray-400">
                Inspect text extracted from scanned PDFs and images. V1 stores OCR blocks as
                document facts, V1.5 exposes them here, and V2 can route/enrich through
                service providers such as PP-OCR, Tesseract or vision fallback.
              </p>
              <p class="mt-2 text-[11px] text-gray-500">
                {{ ocrFacts().length }} loaded / {{ ocrFactTotal() }} total OCR or visual facts
              </p>
            </div>
            <button
              type="button"
              (click)="loadOcrFacts()"
              class="inline-flex items-center gap-1.5 rounded bg-white/5 px-3 py-2 text-xs font-medium text-gray-200 ring-1 ring-white/10 hover:bg-white/10"
            >
              <app-icon name="refresh-cw" [size]="13" /> Refresh OCR
            </button>
          </div>
          <div class="grid gap-3 border-b border-white/5 px-5 py-4 md:grid-cols-[minmax(0,1fr)_220px]">
            <label class="block">
              <span class="ck-mono mb-1 block text-[10px] uppercase tracking-wider text-gray-500">Search OCR text</span>
              <input
                class="w-full rounded bg-black/25 border border-white/10 px-3 py-2 text-sm text-white outline-none focus:border-brand-400"
                type="search"
                placeholder="Text, warning, label, OCR block…"
                [value]="ocrFactQuery()"
                (input)="ocrFactQuery.set($any($event.target).value)"
                (keydown.enter)="loadOcrFacts()"
              />
            </label>
            <label class="block">
              <span class="ck-mono mb-1 block text-[10px] uppercase tracking-wider text-gray-500">Visual type</span>
              <select
                class="w-full rounded bg-black/25 border border-white/10 px-3 py-2 text-sm text-white outline-none focus:border-brand-400"
                [value]="ocrFactType()"
                (change)="ocrFactType.set($any($event.target).value); loadOcrFacts()"
              >
                <option value="">All OCR evidence</option>
                <option value="document_ocr_text">OCR pages</option>
                <option value="visual_text_block">Text blocks</option>
                <option value="visual_parameter">Visual parameters</option>
                <option value="visual_warning">Visual warnings</option>
              </select>
            </label>
          </div>
          @if (loadingOcrFacts()) {
            <div class="p-5 text-sm text-gray-400">
              <app-icon name="loader-2" [size]="14" class="animate-spin inline-block mr-2" />
              Loading OCR evidence…
            </div>
          } @else if (ocrFacts().length === 0) {
            <app-empty-state
              icon="scan-text"
              title="No OCR evidence found"
              description="Ingest scanned PDFs or image files with OCR enabled, then refresh this tab. Native text PDFs do not need OCR unless force OCR is enabled."
            />
          } @else {
            <div class="grid gap-4 p-5 md:grid-cols-4">
              @for (row of ocrSummaryRows(); track row.label) {
                <article class="rounded border border-white/10 bg-black/20 p-3">
                  <div class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">{{ row.label }}</div>
                  <div class="mt-1 text-xl font-semibold text-white tabular-nums">{{ row.value }}</div>
                  <p class="mt-1 text-[11px] text-gray-500">{{ row.hint }}</p>
                </article>
              }
            </div>
            <div class="divide-y divide-white/5 border-t border-white/5">
              @for (fact of ocrFacts(); track ocrFactKey(fact, $index)) {
                <article class="px-5 py-4 hover:bg-white/[0.03] transition">
                  <div class="flex flex-wrap items-center gap-2 text-[11px] text-gray-500">
                    <span class="ck-mono rounded bg-brand-500/10 px-2 py-1 text-brand-300 ring-1 ring-brand-500/20">
                      {{ fact.semantic_type || 'ocr' }}
                    </span>
                    @if (fact.page) {
                      <span>Page {{ fact.page }}</span>
                    }
                    @if (ocrProviderLabel(fact)) {
                      <span>Provider: <span class="text-gray-300">{{ ocrProviderLabel(fact) }}</span></span>
                    }
                    @if (ocrConfidenceLabel(fact)) {
                      <span>Confidence: <span class="text-gray-300">{{ ocrConfidenceLabel(fact) }}</span></span>
                    }
                    @if (ocrBoxLabel(fact)) {
                      <span>Box: <span class="font-mono text-gray-300">{{ ocrBoxLabel(fact) }}</span></span>
                    }
                  </div>
                  <h4 class="mt-2 text-sm font-medium text-white truncate">
                    {{ fact.document_filename || 'Visual source' }}
                  </h4>
                  @if (fact.section_path) {
                    <p class="mt-1 text-[11px] text-gray-500 truncate">{{ fact.section_path }}</p>
                  }
                  <p class="mt-3 text-xs leading-relaxed text-gray-300 whitespace-pre-wrap">{{ fact.content || fact.value_raw }}</p>
                  @if (ocrWarningLabel(fact)) {
                    <p class="mt-2 rounded border border-amber-400/20 bg-amber-400/10 px-2 py-1 text-[11px] text-amber-100">
                      {{ ocrWarningLabel(fact) }}
                    </p>
                  }
                </article>
              }
            </div>
          }
        </section>
      </ck-tab>

      <ck-tab id="table-facts" label="Table facts">
        <section class="t-card rounded-md overflow-hidden">
          <div class="px-5 py-4 border-b border-white/5 flex flex-col gap-3 xl:flex-row xl:items-end xl:justify-between">
            <div>
              <div class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">
                Spreadsheet intelligence
              </div>
              <h3 class="mt-1 text-base font-semibold text-white">Structured table facts</h3>
              <p class="mt-1 text-xs text-gray-400 max-w-2xl">
                Browse the indexed workbook facts used by chat: schema, row chunks,
                cell facts, table facts and semantic sentences with sheet/cell metadata.
              </p>
              <p class="mt-2 text-[11px] text-gray-500">
                {{ tableFacts().length }} loaded / {{ tableFactTotal() }} total table facts
              </p>
            </div>
            <button
              type="button"
              (click)="loadTableFacts()"
              class="inline-flex items-center gap-1.5 rounded bg-white/5 px-3 py-2 text-xs font-medium text-gray-200 ring-1 ring-white/10 hover:bg-white/10"
            >
              <app-icon name="refresh-cw" [size]="13" /> Refresh facts
            </button>
          </div>
          <div class="px-5 py-4 border-b border-white/5 grid gap-3 md:grid-cols-[minmax(0,1fr)_220px_220px]">
            <label class="block">
              <span class="ck-mono block text-[10px] uppercase tracking-wider text-gray-500 mb-1">Search</span>
              <input
                class="w-full rounded bg-black/25 border border-white/10 px-3 py-2 text-sm text-white outline-none focus:border-brand-400"
                type="search"
                placeholder="Sheet, label, cell, value…"
                [value]="tableFactQuery()"
                (input)="onTableFactQueryInput($any($event.target).value)"
                (keydown.enter)="loadTableFacts()"
              />
            </label>
            <label class="block">
              <span class="ck-mono block text-[10px] uppercase tracking-wider text-gray-500 mb-1">Type</span>
              <select
                class="w-full rounded bg-black/25 border border-white/10 px-3 py-2 text-sm text-white outline-none focus:border-brand-400"
                [value]="tableFactType()"
                (change)="tableFactType.set($any($event.target).value); loadTableFacts(0)"
              >
                <option value="">All table views</option>
                <option value="spreadsheet_cell_fact">Cell facts</option>
                <option value="spreadsheet_table_fact">Table facts</option>
                <option value="spreadsheet_semantic_sentence">Semantic sentences</option>
                <option value="spreadsheet_schema">Schema</option>
                <option value="spreadsheet_row">Rows</option>
              </select>
            </label>
            <label class="block">
              <span class="ck-mono block text-[10px] uppercase tracking-wider text-gray-500 mb-1">Sheet</span>
              <input
                class="w-full rounded bg-black/25 border border-white/10 px-3 py-2 text-sm text-white outline-none focus:border-brand-400"
                type="search"
                placeholder="Def strips"
                [value]="tableFactSheet()"
                (input)="onTableFactSheetInput($any($event.target).value)"
                (keydown.enter)="loadTableFacts()"
              />
            </label>
          </div>
          @if (!loadingTableFacts() && tableFacts().length > 0) {
            <div class="px-5 py-2 border-b border-white/5 text-[11px] text-gray-500">
              {{ visibleTableFacts().length }} résultat(s) affiché(s) sur {{ tableFactTotal() }} total. Les faits suspects restent visibles pour audit.
            </div>
          }
          @if (loadingTableFacts()) {
            <div class="p-5 text-sm text-gray-400">
              <app-icon name="loader-2" [size]="14" class="animate-spin inline-block mr-2" />
              Loading table facts…
            </div>
          } @else if (visibleTableFacts().length === 0) {
            <app-empty-state
              icon="table"
              title="No table facts found"
              description="Aucun fait ne correspond aux filtres. Ré-indexez les fichiers Excel si la collection devrait en contenir."
            />
          } @else {
            <div class="divide-y divide-white/5">
              @for (fact of visibleTableFacts(); track factKey(fact, $index)) {
                <article class="px-5 py-4 hover:bg-white/[0.03] transition">
                  <div class="flex flex-wrap items-center gap-2 text-[11px] text-gray-500">
                    <span class="ck-mono rounded bg-brand-500/10 px-2 py-1 text-brand-300 ring-1 ring-brand-500/20">
                      {{ fact.semantic_type || 'spreadsheet' }}
                    </span>
                    @if (fact.sheet_name) {
                      <span>Sheet: <span class="text-gray-300">{{ fact.sheet_name }}</span></span>
                    }
                    @if (fact.cell_ref || fact.cell_range) {
                      <span>Cell: <span class="font-mono text-gray-300">{{ fact.cell_ref || fact.cell_range }}</span></span>
                    }
                    @if (fact.unit) {
                      <span>Unit: <span class="text-gray-300">{{ fact.unit }}</span></span>
                    }
                  </div>
                  <h4 class="mt-2 text-sm font-medium text-white truncate">
                    {{ fact.document_filename || 'Spreadsheet source' }}
                  </h4>
                  <div class="mt-2 flex flex-wrap gap-2 text-[11px]">
                    @for (warning of tableFactWarnings(fact); track warning) {
                      <span class="rounded border border-amber-400/25 bg-amber-500/10 px-2 py-1 text-amber-200">{{ warning }}</span>
                    }
                    @if (fact.row_label) {
                      <span class="rounded bg-white/5 px-2 py-1 text-gray-300">row: {{ fact.row_label }}</span>
                    }
                    @if (fact.column_header) {
                      <span class="rounded bg-white/5 px-2 py-1 text-gray-300">column: {{ fact.column_header }}</span>
                    }
                    @if (fact.table_region_id) {
                      <span class="rounded bg-white/5 px-2 py-1 text-gray-500">region: {{ fact.table_region_id }}</span>
                    }
                  </div>
                  <p class="mt-3 text-xs leading-relaxed text-gray-300 whitespace-pre-wrap">
                    {{ fact.content }}
                  </p>
                  @if (fact.interpretation_note) {
                    <p class="mt-2 text-[11px] text-amber-200/80">{{ fact.interpretation_note }}</p>
                  }
                </article>
              }
            </div>
            <div class="flex items-center justify-between border-t border-white/5 px-5 py-3 text-xs text-gray-400">
              <span>{{ tableFactOffset() + 1 }}–{{ tableFactOffset() + tableFacts().length }} / {{ tableFactTotal() }}</span>
              <div class="flex items-center gap-1.5">
                <button
                  type="button"
                  title="Previous page"
                  aria-label="Previous page"
                  class="inline-flex h-7 w-7 items-center justify-center rounded bg-white/5 text-gray-200 ring-1 ring-white/10 hover:bg-white/10 disabled:opacity-40"
                  [disabled]="loadingTableFacts() || tableFactOffset() === 0"
                  (click)="loadTableFacts(tableFactOffset() > tableFactPageSize ? tableFactOffset() - tableFactPageSize : 0)"
                >
                  <app-icon name="chevron-left" [size]="13" />
                </button>
                <button
                  type="button"
                  title="Next page"
                  aria-label="Next page"
                  class="inline-flex h-7 w-7 items-center justify-center rounded bg-white/5 text-gray-200 ring-1 ring-white/10 hover:bg-white/10 disabled:opacity-40"
                  [disabled]="loadingTableFacts() || !tableFactsHasMore()"
                  (click)="loadTableFacts(tableFactOffset() + tableFactPageSize)"
                >
                  <app-icon name="chevron-right" [size]="13" />
                </button>
              </div>
            </div>
          }
        </section>
      </ck-tab>

      <ck-tab id="guides" label="Guides">
        <section class="t-card rounded-md overflow-hidden mb-4">
          <div class="px-5 py-4 border-b border-white/5 flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
            <div>
              <div class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">
                Collection guide
              </div>
              <h3 class="mt-1 text-base font-semibold text-white">Markdown interpretation guide</h3>
              <p class="mt-1 text-xs text-gray-400 max-w-2xl">
                Explain how to read this collection. Guides help query expansion
                and prompting, but raw table/document facts remain the proof.
              </p>
            </div>
            <div class="flex flex-wrap gap-2">
              <button
                type="button"
                (click)="saveCollectionGuide('draft')"
                [disabled]="savingGuide()"
                class="inline-flex items-center gap-1.5 rounded bg-white/5 px-3 py-2 text-xs font-medium text-gray-200 ring-1 ring-white/10 hover:bg-white/10 disabled:opacity-50"
              >
                <app-icon name="save" [size]="13" /> Save draft
              </button>
              <button
                type="button"
                (click)="saveCollectionGuide('published')"
                [disabled]="savingGuide()"
                class="inline-flex items-center gap-1.5 rounded bg-brand-500 px-3 py-2 text-xs font-semibold text-black hover:bg-brand-400 disabled:opacity-50"
              >
                <app-icon name="check" [size]="13" /> Publish
              </button>
            </div>
          </div>
          <div class="grid gap-0 lg:grid-cols-2">
            <div class="p-5 border-b border-white/5 lg:border-b-0 lg:border-r">
              <label class="block">
                <span class="ck-mono block text-[10px] uppercase tracking-wider text-gray-500 mb-1">Title</span>
                <input
                  class="w-full rounded bg-black/25 border border-white/10 px-3 py-2 text-sm text-white outline-none focus:border-brand-400"
                  [value]="guideTitle()"
                  (input)="guideTitle.set($any($event.target).value)"
                />
              </label>
              <label class="block mt-3">
                <span class="ck-mono block text-[10px] uppercase tracking-wider text-gray-500 mb-1">Markdown</span>
                <textarea
                  class="min-h-[28rem] w-full rounded bg-black/25 border border-white/10 px-3 py-2 font-mono text-xs leading-relaxed text-gray-200 outline-none focus:border-brand-400"
                  [value]="guideMarkdown()"
                  (input)="guideMarkdown.set($any($event.target).value)"
                ></textarea>
              </label>
              @if (guideError()) {
                <p class="mt-2 text-xs text-red-300">{{ guideError() }}</p>
              }
            </div>
            <div class="p-5">
              <div class="ck-mono text-[10px] uppercase tracking-wider text-gray-500 mb-2">Preview</div>
              <div class="min-h-[28rem] max-h-[36rem] overflow-auto rounded bg-black/25 p-4 text-sm leading-relaxed text-gray-300">
                @for (block of guideMarkdownBlocks(guideMarkdown()); track $index) {
                  @if (block.kind === 'h1') {
                    <h1 class="mb-3 text-xl font-semibold text-white">{{ block.text }}</h1>
                  } @else if (block.kind === 'h2') {
                    <h2 class="mt-5 mb-2 text-base font-semibold text-white">{{ block.text }}</h2>
                  } @else if (block.kind === 'h3') {
                    <h3 class="mt-4 mb-1 text-sm font-semibold text-brand-100">{{ block.text }}</h3>
                  } @else if (block.kind === 'li') {
                    <p class="pl-4 text-xs text-gray-300 before:content-['•'] before:mr-2 before:text-brand-300">{{ block.text }}</p>
                  } @else {
                    <p class="mb-2 text-xs text-gray-300">{{ block.text }}</p>
                  }
                } @empty {
                  <p class="text-xs text-gray-500">No Markdown yet.</p>
                }
              </div>
              <div class="mt-4">
                <div class="ck-mono text-[10px] uppercase tracking-wider text-gray-500 mb-2">Versions</div>
                @if (collectionGuideVersions().length === 0) {
                  <p class="text-xs text-gray-500">No saved versions yet.</p>
                } @else {
                  <div class="space-y-2">
                    @for (guide of collectionGuideVersions(); track guide.id) {
                      <button
                        type="button"
                        (click)="loadGuideIntoEditor(guide)"
                        class="w-full rounded border border-white/10 bg-white/5 px-3 py-2 text-left hover:bg-white/10"
                      >
                        <div class="flex items-center justify-between gap-2">
                          <span class="text-xs font-medium text-white">v{{ guide.version }} · {{ guide.status }}</span>
                          <span class="text-[11px] text-gray-500">{{ guide.created_at ? (guide.created_at | slice:0:10) : '—' }}</span>
                        </div>
                        <p class="mt-1 truncate text-[11px] text-gray-500">{{ guide.title }}</p>
                      </button>
                    }
                  </div>
                }
              </div>
            </div>
          </div>
        </section>

        @if (guideRows().length === 0) {
          <app-empty-state
            icon="book-open"
            title="No Knowledge Guide"
            description="Attach a Markdown guide from Workspace > Chat & Knowledge when this collection needs vocabulary, interpretation rules or query hints."
          />
        } @else {
          <section class="space-y-3">
            @for (row of guideRows(); track row.guide.id) {
              <article class="t-card rounded-md overflow-hidden">
                <div class="px-5 py-4 border-b border-white/5 flex items-start justify-between gap-3">
                  <div class="min-w-0">
                    <div class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">
                      {{ row.binding_kind === 'scope' ? 'Scope guide' : 'Collection guide' }} · {{ row.binding_label }}
                    </div>
                    <h3 class="mt-1 text-base font-semibold text-white truncate">{{ row.guide.title }}</h3>
                    <p class="mt-1 text-xs text-gray-500">
                      v{{ row.guide.version }} · {{ row.guide.status }} @if (row.guide.published_at) { · published {{ row.guide.published_at | slice:0:10 }} }
                    </p>
                  </div>
                  <a
                    [routerLink]="['/workspace', workspaceSlug(), 'chat-knowledge']"
                    class="inline-flex shrink-0 items-center gap-1.5 rounded bg-white/5 px-3 py-2 text-xs font-medium text-gray-200 ring-1 ring-white/10 hover:bg-white/10"
                  >
                    <app-icon name="pencil" [size]="13" /> Edit in settings
                  </a>
                </div>
                <div class="max-h-[34rem] overflow-auto bg-black/20 p-5 text-sm leading-relaxed text-gray-300">
                  @for (block of guideMarkdownBlocks(row.guide.markdown || row.guide.snippet || ''); track $index) {
                    @if (block.kind === 'h1') {
                      <h1 class="mb-3 text-xl font-semibold text-white">{{ block.text }}</h1>
                    } @else if (block.kind === 'h2') {
                      <h2 class="mt-5 mb-2 text-base font-semibold text-white">{{ block.text }}</h2>
                    } @else if (block.kind === 'h3') {
                      <h3 class="mt-4 mb-1 text-sm font-semibold text-brand-100">{{ block.text }}</h3>
                    } @else if (block.kind === 'li') {
                      <p class="pl-4 text-xs text-gray-300 before:content-['•'] before:mr-2 before:text-brand-300">{{ block.text }}</p>
                    } @else {
                      <p class="mb-2 text-xs text-gray-300">{{ block.text }}</p>
                    }
                  } @empty {
                    <p class="text-xs text-gray-500">No Markdown content.</p>
                  }
                </div>
              </article>
            }
          </section>
        }
      </ck-tab>

      <ck-tab id="diagnostics" label="Diagnostics">
        <section class="grid gap-4 lg:grid-cols-2">
          <article class="t-card rounded-md p-5">
            <div class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">Index health</div>
            <h3 class="mt-1 text-base font-semibold text-white">Collection diagnostics</h3>
            @if (loadingDiagnostics()) {
              <p class="mt-3 text-sm text-gray-400">
                <app-icon name="loader-2" [size]="14" class="mr-2 inline-block animate-spin" />
                Loading corpus diagnostics…
              </p>
            }
            <dl class="mt-4 grid grid-cols-2 gap-3 text-sm">
              @for (row of diagnosticRows(); track row.label) {
                <div class="rounded border border-white/10 bg-black/20 p-3">
                  <dt class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">{{ row.label }}</dt>
                  <dd class="mt-1 text-lg font-semibold text-white tabular-nums">{{ row.value }}</dd>
                  <p class="mt-1 text-[11px] text-gray-500">{{ row.hint }}</p>
                </div>
              }
            </dl>
            @if (diagnostics()) {
              <div class="mt-4 grid gap-3 text-xs md:grid-cols-3">
                <div class="rounded border border-white/10 bg-black/20 p-3">
                  <div class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">Zero chunks</div>
                  <div class="mt-1 text-lg font-semibold text-white">{{ diagnostics()?.zero_chunk_sources ?? 0 }}</div>
                </div>
                <div class="rounded border border-white/10 bg-black/20 p-3">
                  <div class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">Errors</div>
                  <div class="mt-1 text-lg font-semibold text-white">{{ diagnostics()?.error_sources ?? 0 }}</div>
                </div>
                <div class="rounded border border-white/10 bg-black/20 p-3">
                  <div class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">Heavy sources</div>
                  <div class="mt-1 text-lg font-semibold text-white">{{ diagnostics()?.heavy_sources ?? 0 }}</div>
                </div>
              </div>
            }
          </article>
          <article class="t-card rounded-md p-5">
            <div class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">Retrieval layers</div>
            <h3 class="mt-1 text-base font-semibold text-white">How this collection is queried</h3>
            <div class="mt-4 space-y-3 text-xs leading-relaxed text-gray-400">
              @for (row of featureRows(); track row.label) {
                <article class="rounded border border-white/10 bg-black/20 p-3">
                  <div class="flex items-center justify-between gap-3">
                    <span class="font-medium text-gray-200">{{ row.label }}</span>
                    <span class="rounded px-2 py-0.5 font-mono text-[10px]" [class.bg-emerald-500/10]="row.state === 'available'" [class.text-emerald-200]="row.state === 'available'" [class.bg-white/5]="row.state !== 'available'" [class.text-gray-400]="row.state !== 'available'">
                      {{ row.state }}
                    </span>
                  </div>
                  @if (row.reason) {
                    <p class="mt-2 text-gray-500">{{ row.reason }}</p>
                  }
                </article>
              }
              <p class="rounded border border-white/10 bg-black/20 p-3 font-mono text-[11px] text-gray-300">
                collection={{ kbId }} · vector={{ vectorDbType() || 'unknown' }} · docs={{ docCount() }} · chunks={{ chunkCount() }} · drift={{ diagnostics()?.drift ?? '—' }}
              </p>
            </div>
          </article>
        </section>
      </ck-tab>

      <ck-tab id="bindings" label="Bindings">
        @if (loadingBindings()) {
          <div class="t-card rounded-md p-5 text-center text-gray-400 text-sm">
            <app-icon name="loader-2" [size]="14" class="animate-spin inline-block mr-2" />
            Scanning Systems…
          </div>
        } @else if (bindings().length === 0) {
          <app-empty-state
            icon="link"
            title="No Systems bound"
            description="No System references this collection in its flow yet."
          />
        } @else {
          <ul class="space-y-2">
            @for (sys of bindings(); track sys.id) {
              <li class="t-card rounded-md p-4 flex items-center gap-3">
                <div class="w-9 h-9 rounded bg-brand-500/15 text-brand-400 ring-1 ring-brand-500/30 flex items-center justify-center shrink-0">
                  <app-icon name="cube" [size]="16" />
                </div>
                <div class="flex-1 min-w-0">
                  <a
                    [routerLink]="['/systems', sys.id]"
                    class="text-sm font-medium text-white hover:text-brand-300 transition truncate block"
                  >
                    {{ sys.name }}
                  </a>
                  <div class="text-[11px] text-gray-500 truncate">{{ sys.objective || '—' }}</div>
                </div>
                <span
                  class="ck-mono text-[10px] uppercase tracking-wider px-2 py-1 rounded bg-white/5 text-gray-400"
                >
                  {{ sys.retrieval_mode_default || 'auto' }}
                </span>
              </li>
            }
          </ul>
        }
      </ck-tab>
    </ck-tabs>

    <ck-panel
      [open]="bindingsPanelOpen()"
      (openChange)="bindingsPanelOpen.set($event)"
      position="side"
      eyebrow="Knowledge · panel"
      title="Bindings overview"
      width="420px"
    >
      <p class="text-xs text-gray-400 mb-3">
        Systems whose <span class="font-mono text-brand-300">flow_definition.collections</span>
        references this collection.
      </p>
      @if (bindings().length === 0) {
        <div class="text-xs text-gray-500">No bindings yet.</div>
      } @else {
        <ul class="space-y-1.5">
          @for (sys of bindings(); track sys.id) {
            <li>
              <a
                [routerLink]="['/systems', sys.id]"
                class="text-xs text-brand-300 hover:text-brand-200 transition truncate block"
              >
                {{ sys.name }}
              </a>
            </li>
          }
        </ul>
      }
    </ck-panel>

    <app-document-preview
      [open]="previewOpen()"
      [previewUrl]="previewUrl()"
      [title]="previewTitle()"
      subtitle="Knowledge source"
      (closed)="closePreview()"
    />
  `,
})
export class KnowledgeViewComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly http = inject(HttpClient);
  private readonly canonical = inject(CanonicalApiService);
  private readonly api = inject(ApiService);
  private readonly workspace = inject(WorkspaceService);
  readonly lensService = inject(LensService);

  private readonly base = '/api/v1/documents';

  kbId = '';
  readonly title = signal('Knowledge base');
  readonly activeTab = signal<KbTabId>('overview');
  readonly bindingsPanelOpen = signal(false);

  // Source document preview (shared with Secure Deposit viewer).
  readonly previewOpen = signal(false);
  readonly previewUrl = signal<string | null>(null);
  readonly previewTitle = signal('');

  // Chunk browser (Chunks tab).
  readonly chunkPageSize = 50;
  readonly chunks = signal<ChunkRow[]>([]);
  readonly loadingChunks = signal(false);
  readonly chunkOffset = signal(0);
  readonly chunkTotal = signal(0);
  readonly chunkTotalExact = signal(false);
  readonly chunkNavigationNote = signal('');
  readonly chunksHasMore = signal(false);
  readonly chunkDocFilter = signal('');

  readonly loading = signal(true);
  readonly loadingSources = signal(true);
  readonly loadingBindings = signal(true);
  readonly loadingTableFacts = signal(false);
  readonly loadingDocumentFacts = signal(false);
  readonly loadingOcrFacts = signal(false);
  readonly loadingDiagnostics = signal(false);
  readonly savingGuide = signal(false);
  readonly guideError = signal<string | null>(null);

  readonly docCount = signal(0);
  readonly chunkCount = signal(0);
  readonly vectorDim = signal<number | null>(null);
  readonly vectorDbType = signal<string>('');

  readonly sources = signal<DocRow[]>([]);
  readonly sourceTotal = signal(0);
  readonly sourceGlobalTotal = signal(0);
  readonly sourceOffset = signal(0);
  readonly sourcesHasMore = signal(false);
  readonly sourcePageSize = 50;
  readonly sourceQuery = signal('');
  readonly sourceKindFilter = signal('');
  readonly sourceExtensionFilter = signal('');
  readonly sourceStatusFilter = signal('');
  readonly sourceSort = signal('filename');
  readonly sourceSortDir = signal<'asc' | 'desc'>('asc');
  readonly sourceKinds = signal<Record<string, number>>({});
  readonly sourceExtensions = signal<Record<string, number>>({});
  readonly sourceStatuses = signal<Record<string, number>>({});
  readonly globalTopSources = signal<DocRow[]>([]);
  readonly chunkBuckets = signal<Record<string, { sources: number; chunks: number }>>({});
  readonly chunkPercentiles = signal<Record<string, number>>({});
  readonly bindings = signal<System[]>([]);
  readonly knowledgeGuides = signal<KnowledgeGuide[]>([]);
  readonly knowledgeScopes = signal<KnowledgeScopeApi[]>([]);
  readonly tableFacts = signal<TableFactItem[]>([]);
  readonly tableFactTotal = signal(0);
  readonly tableFactOffset = signal(0);
  readonly tableFactsHasMore = signal(false);
  readonly tableFactByType = signal<Record<string, number>>({});
  readonly tableFactPageSize = 120;
  readonly visibleTableFacts = computed(() => {
    const query = this.tableFactQuery().trim().toLowerCase();
    const sheet = this.tableFactSheet().trim().toLowerCase();
    if (!query && !sheet) return this.tableFacts();
    return this.tableFacts().filter((fact) => {
      const haystack = this.tableFactHaystack(fact);
      return (!query || haystack.includes(query)) && (!sheet || String(fact.sheet_name || '').toLowerCase().includes(sheet));
    });
  });
  readonly documentFacts = signal<DocumentFactItem[]>([]);
  readonly documentFactTotal = signal(0);
  readonly documentFactOffset = signal(0);
  readonly documentFactsHasMore = signal(false);
  readonly documentFactByType = signal<Record<string, number>>({});
  readonly documentFactPageSize = 160;
  readonly ocrFacts = signal<DocumentFactItem[]>([]);
  readonly ocrFactTotal = signal(0);
  readonly ocrFactByType = signal<Record<string, number>>({});
  readonly diagnostics = signal<CollectionDiagnosticsPayload | null>(null);
  readonly tableFactQuery = signal('');
  readonly tableFactType = signal('');
  readonly tableFactSheet = signal('');
  readonly documentFactQuery = signal('');
  readonly documentFactType = signal('');
  readonly ocrFactQuery = signal('');
  readonly ocrFactType = signal('');
  readonly guideTitle = signal('');
  readonly guideMarkdown = signal('');
  readonly editingGuideKey = signal<string | null>(null);
  private tableFactReloadTimer: ReturnType<typeof setTimeout> | null = null;

  readonly lens = this.lensService.lens;

  readonly kpis = computed<CkObjectKpi[]>(() => [
    {
      label: 'Docs',
      value: this.loading() ? '…' : String(this.docCount()),
      tone: 'cool',
      hint: 'Source documents ingested into this collection.',
    },
    {
      label: 'Chunks',
      value: this.loading() ? '…' : String(this.chunkCount()),
      tone: 'neutral',
      hint: 'Vector chunks currently indexed.',
    },
    {
      label: 'Bindings',
      value: this.loadingBindings() ? '…' : String(this.bindings().length),
      tone: this.bindings().length > 0 ? 'violet' : 'neutral',
      hint: 'Systems consuming this knowledge base.',
    },
    {
      label: 'Vector DB',
      value: this.vectorDbType() || '—',
      tone: 'neutral',
      hint: 'Underlying vector database type.',
    },
  ]);

  readonly avgChunksPerDoc = computed(() => {
    const docs = this.docCount();
    const chunks = this.chunkCount();
    if (!docs) return '—';
    return (chunks / docs).toFixed(1);
  });

  readonly topSources = computed(() => {
    return this.globalTopSources().slice(0, 10);
  });

  readonly sourceKindOptions = computed(() => this.entriesByCount(this.sourceKinds()));
  readonly sourceExtensionOptions = computed(() => this.entriesByCount(this.sourceExtensions()));
  readonly sourceStatusOptions = computed(() => this.entriesByCount(this.sourceStatuses()));
  readonly chunkBucketRows = computed(() => {
    const order = ['0', '1-5', '6-50', '51-200', '201-1000', '>1000'];
    const buckets = this.chunkBuckets();
    return order.map((label) => ({
      label,
      sources: buckets[label]?.sources ?? 0,
      chunks: buckets[label]?.chunks ?? 0,
    }));
  });
  readonly featureRows = computed(() => {
    const status = this.diagnostics()?.feature_status ?? {};
    return [
      ['Graph', status['graph']],
      ['Document facts', status['document_facts']],
      ['OCR', status['ocr']],
      ['Table facts', status['table_facts']],
    ].map(([label, value]) => ({
      label: String(label),
      state: (value as { state?: string; reason?: string } | undefined)?.state || 'unknown',
      reason: (value as { state?: string; reason?: string } | undefined)?.reason || '',
    }));
  });

  readonly guideRows = computed<KnowledgeGuideRow[]>(() => {
    const scopeLabels = new Map(
      this.knowledgeScopes().map((scope) => [scope.key, scope.label || scope.key] as const),
    );
    const scopesForCollection = new Set(
      this.knowledgeScopes()
        .filter((scope) => (scope.collection_slugs || []).includes(this.kbId))
        .map((scope) => scope.key),
    );
    return this.knowledgeGuides()
      .filter((guide) => guide.is_current)
      .flatMap((guide): KnowledgeGuideRow[] => {
        if (guide.target_type === 'collection' && guide.target_ref === this.kbId) {
          return [{ guide, binding_kind: 'collection', binding_label: this.kbId }];
        }
        if (guide.target_type === 'scope' && scopesForCollection.has(guide.target_ref)) {
          return [{
            guide,
            binding_kind: 'scope',
            binding_label: scopeLabels.get(guide.target_ref) || guide.target_ref,
          }];
        }
        return [];
      })
      .sort((a, b) => a.binding_label.localeCompare(b.binding_label) || b.guide.version - a.guide.version);
  });

  readonly collectionGuideVersions = computed(() =>
    this.knowledgeGuides()
      .filter((guide) => guide.target_type === 'collection' && guide.target_ref === this.kbId)
      .sort((a, b) => b.version - a.version),
  );

  readonly documentStructureGroups = computed(() => {
    const byType = this.documentFactByType();
    const count = (type: string) => byType[type] ?? 0;
    return [
      {
        type: 'Headings',
        count: count('document_heading'),
        hint: 'Section anchors used for page and section citations.',
      },
      {
        type: 'Procedures',
        count: count('document_procedure_step'),
        hint: 'Steps and procedural clauses extracted from manuals.',
      },
      {
        type: 'Warnings',
        count: count('document_warning'),
        hint: 'Safety, caution and warning statements.',
      },
      {
        type: 'Parameters',
        count: count('document_parameter'),
        hint: 'Explicit name/value or parameter statements.',
      },
      {
        type: 'Definitions',
        count: count('document_definition'),
        hint: 'Terminology and “is/means/refers to” statements.',
      },
      {
        type: 'Tables',
        count: count('document_table'),
        hint: 'Document tables extracted from DOCX/Markdown/HTML when available.',
      },
    ];
  });

  readonly structurePreviewFacts = computed(() => {
    const priority = new Set([
      'document_heading',
      'document_procedure_step',
      'document_warning',
      'document_parameter',
      'document_table',
    ]);
    return this.documentFacts()
      .filter((fact) => priority.has(fact.semantic_type || ''))
      .slice(0, 20);
  });

  readonly diagnosticRows = computed(() => [
    {
      label: 'Documents',
      value: this.loading() ? '…' : String(this.docCount()),
      hint: 'Source files tracked in this collection.',
    },
    {
      label: 'Chunks',
      value: this.loading() ? '…' : String(this.chunkCount()),
      hint: 'Semantic chunks available to vector retrieval.',
    },
    {
      label: 'Table facts',
      value: this.loadingTableFacts() ? '…' : String(this.tableFactTotal()),
      hint: 'Structured spreadsheet facts in this collection.',
    },
    {
      label: 'Document facts',
      value: this.loadingDocumentFacts() ? '…' : String(this.documentFactTotal()),
      hint: 'Structured manual/procedure facts in this collection.',
    },
    {
      label: 'OCR evidence',
      value: this.loadingOcrFacts() ? '…' : String(this.ocrFactTotal()),
      hint: 'OCR/visual facts indexed for this collection.',
    },
    {
      label: 'Guides',
      value: String(this.guideRows().length),
      hint: 'Current collection or scope interpretation guides.',
    },
    {
      label: 'Bindings',
      value: this.loadingBindings() ? '…' : String(this.bindings().length),
      hint: 'Systems using this collection.',
    },
  ]);

  readonly ocrSummaryRows = computed(() => {
    const facts = this.ocrFacts();
    const confidenceValues = facts
      .map((fact) => this.ocrConfidenceValue(fact))
      .filter((value): value is number => value !== null);
    const avgConfidence = confidenceValues.length
      ? `${Math.round((confidenceValues.reduce((sum, value) => sum + value, 0) / confidenceValues.length) * 100)}%`
      : '—';
    const providers = new Set(facts.map((fact) => this.ocrProviderLabel(fact)).filter(Boolean));
    return [
      {
        label: 'Evidence',
        value: String(facts.length),
        hint: 'OCR pages, blocks and visual facts currently loaded.',
      },
      {
        label: 'Pages',
        value: String(new Set(facts.map((fact) => `${fact.document_id || ''}:${fact.page ?? ''}`).filter(Boolean)).size),
        hint: 'Distinct document pages/images represented in this sample.',
      },
      {
        label: 'Providers',
        value: providers.size ? String(providers.size) : '—',
        hint: providers.size ? Array.from(providers).slice(0, 3).join(', ') : 'No provider metadata loaded.',
      },
      {
        label: 'Avg confidence',
        value: avgConfidence,
        hint: 'Average OCR confidence when provided by the extractor.',
      },
    ];
  });

  readonly workspaceSlug = computed(() => this.workspace.currentSlug() || this.workspace.current()?.slug || 'current');

  ngOnInit(): void {
    this.kbId = this.route.snapshot.paramMap.get('kbId') ?? '';
    this.title.set(this.kbId || 'Knowledge base');
    this.loadAll();
  }

  onTabChange(id: string): void {
    this.activeTab.set(id as KbTabId);
    if (id === 'diagnostics' && !this.diagnostics()) {
      this.loadDiagnostics();
    }
    if (id === 'table-facts' && this.tableFacts().length === 0) {
      this.loadTableFacts(0);
    }
    if ((id === 'structure' || id === 'facts' || id === 'diagnostics') && this.documentFacts().length === 0) {
      this.loadDocumentFacts(0);
    }
    if (id === 'ocr' && this.ocrFacts().length === 0) {
      this.loadOcrFacts();
    }
    if (id === 'diagnostics' && this.tableFacts().length === 0) {
      this.loadTableFacts(0);
    }
    if (id === 'diagnostics' && this.ocrFacts().length === 0) {
      this.loadOcrFacts();
    }
  }

  distributionPct(n: number | undefined): number {
    const max = this.topSources()[0]?.chunk_count ?? 1;
    if (!n || max === 0) return 0;
    return Math.max(3, Math.min(100, (n / max) * 100));
  }

  toggleSourceSortDir(): void {
    this.sourceSortDir.set(this.sourceSortDir() === 'asc' ? 'desc' : 'asc');
    this.loadSources(0);
  }

  private sourceInventoryUrl(offset: number): string {
    const params = new URLSearchParams({
      source_limit: String(this.sourcePageSize),
      source_offset: String(Math.max(0, offset)),
      sort: this.sourceSort(),
      sort_dir: this.sourceSortDir(),
    });
    if (this.sourceQuery().trim()) params.set('q', this.sourceQuery().trim());
    if (this.sourceKindFilter()) params.set('source_kind', this.sourceKindFilter());
    if (this.sourceExtensionFilter()) params.set('extension', this.sourceExtensionFilter());
    if (this.sourceStatusFilter()) params.set('status', this.sourceStatusFilter());
    return `${this.base}/collections/${encodeURIComponent(this.kbId)}/inventory?${params.toString()}`;
  }

  private entriesByCount(record: Record<string, number>): Array<{ key: string; count: number }> {
    return Object.entries(record || {})
      .map(([key, count]) => ({ key, count }))
      .sort((a, b) => b.count - a.count || a.key.localeCompare(b.key));
  }

  private applyDiagnostics(payload: CollectionDiagnosticsPayload): void {
    this.diagnostics.set(payload);
    if (payload.vector_points !== null && payload.vector_points !== undefined) {
      this.chunkCount.set(payload.vector_points);
    }
    if (payload.vector_dim !== null && payload.vector_dim !== undefined) {
      this.vectorDim.set(payload.vector_dim);
    }
    if (payload.vector_db_type) {
      this.vectorDbType.set(payload.vector_db_type);
    }
    if (payload.ledger_source_count !== undefined) {
      this.sourceGlobalTotal.set(payload.ledger_source_count);
    }
    if (payload.top_sources) {
      this.globalTopSources.set(payload.top_sources.map((source) => {
        const metadata = source.metadata ?? {};
        const documentId = String(metadata['document_id'] || source.id || source.filename);
        return {
          document_id: documentId,
          source_id: source.id,
          filename: source.filename,
          source_kind: source.source_kind,
          extension: source.extension,
          chunk_count: source.chunk_count ?? 0,
          chunks_count: source.chunk_count ?? 0,
          mime_type: source.mime_type,
          uploaded_at: source.indexed_at || undefined,
          size: source.size_bytes,
          status: source.status,
        } satisfies DocRow;
      }));
    }
    if (payload.chunk_buckets) this.chunkBuckets.set(payload.chunk_buckets);
    if (payload.chunk_percentiles) this.chunkPercentiles.set(payload.chunk_percentiles);
    if (payload.by_kind) this.sourceKinds.set(payload.by_kind);
    if (payload.by_extension) this.sourceExtensions.set(payload.by_extension);
    if (payload.by_status) this.sourceStatuses.set(payload.by_status);
    if (payload.document_facts) {
      this.documentFactTotal.set(payload.document_facts.total ?? 0);
      this.documentFactByType.set(payload.document_facts.by_type ?? {});
    }
    if (payload.table_facts) {
      this.tableFactTotal.set(payload.table_facts.total ?? 0);
      this.tableFactByType.set(payload.table_facts.by_type ?? {});
    }
  }

  loadDiagnostics(): void {
    if (!this.kbId) return;
    this.loadingDiagnostics.set(true);
    this.http
      .get<CollectionDiagnosticsPayload>(`${this.base}/collections/${encodeURIComponent(this.kbId)}/diagnostics`)
      .pipe(catchError(() => of<CollectionDiagnosticsPayload | null>(null)))
      .subscribe((payload) => {
        if (payload) this.applyDiagnostics(payload);
        this.loadingDiagnostics.set(false);
      });
  }

  previewDocument(doc: DocRow): void {
    if (!this.kbId || !doc.document_id) return;
    let url =
      `${this.base}/${encodeURIComponent(doc.document_id)}/rich-preview` +
      `?collection_name=${encodeURIComponent(this.kbId)}`;
    if (doc.filename) url += `&filename=${encodeURIComponent(doc.filename)}`;
    this.previewTitle.set(doc.filename || 'Document preview');
    this.previewUrl.set(url);
    this.previewOpen.set(true);
  }

  previewFromNode(selection: EmbeddingNodeSelection): void {
    if (!this.kbId || !selection.document_id) return;
    let url =
      `${this.base}/${encodeURIComponent(selection.document_id)}/rich-preview` +
      `?collection_name=${encodeURIComponent(this.kbId)}`;
    if (selection.title) url += `&filename=${encodeURIComponent(selection.title)}`;
    this.previewTitle.set(selection.title || 'Document preview');
    this.previewUrl.set(url);
    this.previewOpen.set(true);
  }

  closePreview(): void {
    this.previewOpen.set(false);
    this.previewUrl.set(null);
  }

  onChunkDocFilterChange(event: Event): void {
    this.chunkDocFilter.set((event.target as HTMLSelectElement).value);
    this.loadChunks(0);
  }

  loadChunks(offset: number): void {
    if (!this.kbId) return;
    const safeOffset = Math.max(0, offset);
    this.loadingChunks.set(true);
    let url =
      `${this.base}/chunks?collection_name=${encodeURIComponent(this.kbId)}` +
      `&limit=${this.chunkPageSize}&offset=${safeOffset}`;
    const docId = this.chunkDocFilter();
    if (docId) url += `&document_id=${encodeURIComponent(docId)}`;
    this.http
      .get<ChunksPayload>(url)
      .pipe(catchError(() => of<ChunksPayload>({ count: 0, offset: safeOffset, has_more: false, chunks: [] })))
      .subscribe((payload) => {
        this.chunks.set(payload.chunks ?? []);
        this.chunkOffset.set(safeOffset);
        this.chunkTotal.set(payload.total ?? payload.count ?? 0);
        this.chunkTotalExact.set(!!payload.total_is_exact);
        this.chunkNavigationNote.set(payload.navigation_note || '');
        this.chunksHasMore.set(!!payload.has_more);
        this.loadingChunks.set(false);
      });
  }

  loadSources(offset: number): void {
    if (!this.kbId) return;
    const safeOffset = Math.max(0, offset);
    this.loadingSources.set(true);
    this.http
      .get<InventoryPayload>(
        this.sourceInventoryUrl(safeOffset),
      )
      .pipe(catchError(() => of<InventoryPayload>({ sources: [], source_count: 0 })))
      .subscribe((payload) => this.applyInventoryPage(payload, safeOffset));
  }

  private applyInventoryPage(payload: InventoryPayload, requestedOffset: number): void {
    const documents = (payload.sources ?? []).map((source) => {
      const metadata = source.metadata ?? {};
      const documentId = String(metadata['document_id'] || source.id || source.filename);
      return {
        document_id: documentId,
        source_id: source.id,
        filename: source.filename,
        source_kind: source.source_kind,
        extension: source.extension,
        chunk_count: source.chunk_count ?? 0,
        chunks_count: source.chunk_count ?? 0,
        mime_type: source.mime_type,
        uploaded_at: source.indexed_at || undefined,
        size: source.size_bytes,
        status: source.status,
      } satisfies DocRow;
    });
    this.sources.set(documents);
    this.sourceTotal.set(payload.sources_total ?? payload.source_count ?? payload.document_count ?? documents.length);
    this.sourceGlobalTotal.set(payload.source_count ?? payload.document_count ?? documents.length);
    this.sourceOffset.set(payload.sources_offset ?? requestedOffset);
    this.sourcesHasMore.set(!!payload.sources_has_more);
    this.sourceKinds.set(payload.by_kind ?? {});
    this.sourceExtensions.set(payload.by_extension ?? {});
    this.sourceStatuses.set(payload.by_status ?? {});
    this.globalTopSources.set((payload.top_sources ?? []).map((source) => {
      const metadata = source.metadata ?? {};
      const documentId = String(metadata['document_id'] || source.id || source.filename);
      return {
        document_id: documentId,
        source_id: source.id,
        filename: source.filename,
        source_kind: source.source_kind,
        extension: source.extension,
        chunk_count: source.chunk_count ?? 0,
        chunks_count: source.chunk_count ?? 0,
        mime_type: source.mime_type,
        uploaded_at: source.indexed_at || undefined,
        size: source.size_bytes,
        status: source.status,
      } satisfies DocRow;
    }));
    this.chunkBuckets.set(payload.chunk_buckets ?? {});
    this.chunkPercentiles.set(payload.chunk_percentiles ?? {});
    this.loadingSources.set(false);
  }

  private loadAll(): void {
    if (!this.kbId) {
      this.loading.set(false);
      this.loadingSources.set(false);
      this.loadingBindings.set(false);
      return;
    }
    const q = encodeURIComponent(this.kbId);

    forkJoin({
      stats: this.http
        .get<StatsPayload>(`${this.base}/stats?collection_name=${q}`)
        .pipe(catchError(() => of<StatsPayload>({}))),
      inventory: this.http
        .get<InventoryPayload>(
          this.sourceInventoryUrl(0),
        )
        .pipe(catchError(() => of<InventoryPayload>({ sources: [], source_count: 0 }))),
      diagnostics: this.http
        .get<CollectionDiagnosticsPayload>(`${this.base}/collections/${q}/diagnostics`)
        .pipe(catchError(() => of<CollectionDiagnosticsPayload | null>(null))),
      meta: this.http
        .get<CollectionsPayload>(`${this.base}/collections`)
        .pipe(catchError(() => of<CollectionsPayload>({}))),
      guides: this.api
        .listKnowledgeGuides({ current_only: false })
        .pipe(catchError(() => of({ items: [] }))),
      scopes: this.api
        .get<{ scopes: KnowledgeScopeApi[] }>('/knowledge/scopes')
        .pipe(catchError(() => of({ scopes: [] }))),
    }).subscribe(({ stats, inventory, diagnostics, meta, guides, scopes }) => {
      this.chunkCount.set(stats.total_chunks ?? inventory.chunk_count ?? 0);
      this.vectorDim.set(stats.vector_dim ?? null);
      this.vectorDbType.set(stats.vector_db_type ?? meta.vector_db_type ?? '');
      this.applyInventoryPage(inventory, 0);
      if (diagnostics) {
        this.applyDiagnostics(diagnostics);
      }
      this.docCount.set(inventory.document_count ?? inventory.source_count ?? this.sources().length);
      this.loading.set(false);
      this.knowledgeGuides.set(guides.items || []);
      this.knowledgeScopes.set(scopes.scopes || []);
      this.hydrateGuideEditor();
    });

    this.canonical.listSystems().subscribe({
      next: (systems) => {
        const bound = (systems ?? []).filter((s) => {
          const flow = (s.flow_definition ?? {}) as Record<string, unknown>;
          const cols = flow['collections'];
          if (Array.isArray(cols)) return cols.includes(this.kbId);
          return false;
        });
        this.bindings.set(bound);
        this.loadingBindings.set(false);
      },
      error: () => {
        this.bindings.set([]);
        this.loadingBindings.set(false);
      },
    });
  }

  loadTableFacts(offset = 0): void {
    if (!this.kbId) return;
    const safeOffset = Math.max(0, offset);
    this.loadingTableFacts.set(true);
    this.api
      .listTableFacts({
        collection_name: this.kbId,
        semantic_type: this.tableFactType() || undefined,
        sheet_name: this.tableFactSheet() || undefined,
        q: this.tableFactQuery() || undefined,
        limit: this.tableFactPageSize,
        offset: safeOffset,
      })
      .pipe(catchError(() => of({ items: [] } as any)))
      .subscribe((payload) => {
        this.tableFacts.set(payload.items || []);
        this.tableFactTotal.set(payload.total ?? payload.total_returned ?? payload.items?.length ?? 0);
        this.tableFactOffset.set(payload.offset ?? safeOffset);
        this.tableFactsHasMore.set(!!payload.has_more);
        this.tableFactByType.set(payload.by_type || {});
        this.loadingTableFacts.set(false);
      });
  }

  onTableFactQueryInput(value: string): void {
    this.tableFactQuery.set(value);
    this.scheduleTableFactReload();
  }

  onTableFactSheetInput(value: string): void {
    this.tableFactSheet.set(value);
    this.scheduleTableFactReload();
  }

  tableFactWarnings(fact: TableFactItem): string[] {
    const warnings: string[] = [];
    const content = String(fact.content || fact.value_raw || '');
    if (content.includes('#DIV/0!') || content.includes('#VALUE!') || content.includes('#REF!')) {
      warnings.push('Erreur formule');
    }
    const row = String(fact.row_label || '').trim().toLowerCase();
    const column = String(fact.column_header || '').trim().toLowerCase();
    const value = String(fact.value_raw || fact.value_numeric || '').trim().toLowerCase();
    if (row && value && row === value) warnings.push('Valeur auto-référente');
    if (column && value && column === value) warnings.push('En-tête auto-référent');
    if (fact.interpretation_note) warnings.push('À relire');
    return warnings;
  }

  guideMarkdownBlocks(markdown: string): GuideBlock[] {
    return this.cleanGuideMarkdownForDisplay(markdown)
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line): GuideBlock => {
        if (line.startsWith('### ')) return { kind: 'h3', text: line.slice(4).trim() };
        if (line.startsWith('## ')) return { kind: 'h2', text: line.slice(3).trim() };
        if (line.startsWith('# ')) return { kind: 'h1', text: line.slice(2).trim() };
        if (/^[-*]\s+/.test(line)) return { kind: 'li', text: line.replace(/^[-*]\s+/, '').trim() };
        return { kind: 'p', text: line };
      });
  }

  private scheduleTableFactReload(): void {
    if (this.tableFactReloadTimer) {
      clearTimeout(this.tableFactReloadTimer);
    }
    this.tableFactReloadTimer = setTimeout(() => {
      this.tableFactReloadTimer = null;
      this.loadTableFacts(0);
    }, 350);
  }

  private tableFactHaystack(fact: TableFactItem): string {
    return [
      fact.content,
      fact.document_filename,
      fact.sheet_name,
      fact.cell_ref,
      fact.cell_range,
      fact.row_label,
      fact.column_header,
      fact.semantic_type,
      fact.subject,
      fact.measure,
      fact.value_raw,
      fact.value_numeric,
    ]
      .filter(Boolean)
      .join(' ')
      .toLowerCase();
  }

  private cleanGuideMarkdownForDisplay(markdown: string): string {
    return String(markdown || '')
      .split(/\r?\n/)
      .filter((line) => !/^statut\s*:\s*brouillon/i.test(line.trim()))
      .join('\n')
      .trim();
  }

  loadDocumentFacts(offset = 0): void {
    if (!this.kbId) return;
    const safeOffset = Math.max(0, offset);
    this.loadingDocumentFacts.set(true);
    this.api
      .listDocumentFacts({
        collection_name: this.kbId,
        semantic_type: this.documentFactType() || undefined,
        q: this.documentFactQuery() || undefined,
        limit: this.documentFactPageSize,
        offset: safeOffset,
      })
      .pipe(catchError(() => of({ items: [] } as any)))
      .subscribe((payload) => {
        this.documentFacts.set(payload.items || []);
        this.documentFactTotal.set(payload.total ?? payload.total_returned ?? payload.items?.length ?? 0);
        this.documentFactOffset.set(payload.offset ?? safeOffset);
        this.documentFactsHasMore.set(!!payload.has_more);
        this.documentFactByType.set(payload.by_type || {});
        this.loadingDocumentFacts.set(false);
      });
  }

  loadOcrFacts(): void {
    if (!this.kbId) return;
    this.loadingOcrFacts.set(true);
    const type = this.ocrFactType();
    const query = this.ocrFactQuery() || undefined;
    const request: Observable<{ items?: DocumentFactItem[]; total?: number; total_returned?: number; by_type?: Record<string, number> }> = type
      ? this.api.listDocumentFacts({
          collection_name: this.kbId,
          semantic_type: type,
          q: query,
          limit: 200,
        })
      : forkJoin([
          this.api.listDocumentFacts({
            collection_name: this.kbId,
            semantic_type: 'document_ocr_text',
            q: query,
            limit: 120,
          }),
          this.api.listDocumentFacts({
            collection_name: this.kbId,
            semantic_type: 'visual_text_block',
            q: query,
            limit: 120,
          }),
          this.api.listDocumentFacts({
            collection_name: this.kbId,
            semantic_type: 'visual_parameter',
            q: query,
            limit: 80,
          }),
          this.api.listDocumentFacts({
            collection_name: this.kbId,
            semantic_type: 'visual_warning',
            q: query,
            limit: 80,
          }),
        ]).pipe(
          map((payloads) => ({
            items: payloads.flatMap((payload) => payload.items || []),
            total: payloads.reduce((sum, payload) => sum + (payload.total ?? payload.total_returned ?? 0), 0),
            by_type: payloads.reduce((acc, payload) => ({ ...acc, ...(payload.by_type || {}) }), {} as Record<string, number>),
          })),
        );

    request
      .pipe(catchError(() => of({ items: [] } as any)))
      .subscribe((payload) => {
        this.ocrFacts.set(this.dedupeOcrFacts(payload.items || []));
        this.ocrFactTotal.set(payload.total ?? payload.total_returned ?? payload.items?.length ?? 0);
        this.ocrFactByType.set(payload.by_type || {});
        this.loadingOcrFacts.set(false);
      });
  }

  factKey(fact: TableFactItem, index: number): string {
    return `${fact.document_id || 'doc'}:${fact.chunk_index ?? index}:${fact.cell_ref || fact.cell_range || index}`;
  }

  documentFactKey(fact: DocumentFactItem, index: number): string {
    return [
      fact.document_id || 'doc',
      fact.semantic_type || 'fact',
      fact.page ?? '',
      fact.paragraph_index ?? '',
      fact.table_index ?? '',
      fact.subject || '',
      index,
    ].join(':');
  }

  ocrFactKey(fact: DocumentFactItem, index: number): string {
    return [
      fact.document_id || 'doc',
      fact.semantic_type || 'ocr',
      fact.page ?? '',
      this.ocrBoxLabel(fact),
      fact.content || fact.value_raw || '',
      index,
    ].join(':');
  }

  ocrProviderLabel(fact: DocumentFactItem): string {
    const qualifiers = this.asRecord(fact.qualifiers);
    const locator = this.asRecord(fact.evidence_locator);
    return this.toDisplayString(qualifiers['provider'] || qualifiers['model'] || locator['provider'] || locator['model']);
  }

  ocrConfidenceLabel(fact: DocumentFactItem): string {
    const value = this.ocrConfidenceValue(fact);
    return value === null ? '' : `${Math.round(value * 100)}%`;
  }

  ocrBoxLabel(fact: DocumentFactItem): string {
    const qualifiers = this.asRecord(fact.qualifiers);
    const locator = this.asRecord(fact.evidence_locator);
    const bbox = qualifiers['bbox'] || qualifiers['box'] || locator['bbox'] || locator['box'];
    if (Array.isArray(bbox)) {
      return bbox.map((value) => String(value)).join(', ');
    }
    return this.toDisplayString(bbox);
  }

  ocrWarningLabel(fact: DocumentFactItem): string {
    const qualifiers = this.asRecord(fact.qualifiers);
    const warning = qualifiers['warning'] || qualifiers['warnings'] || qualifiers['ocr_warning'];
    if (Array.isArray(warning)) return warning.map((item) => String(item)).join(' · ');
    return this.toDisplayString(warning);
  }

  private ocrConfidenceValue(fact: DocumentFactItem): number | null {
    const qualifiers = this.asRecord(fact.qualifiers);
    const locator = this.asRecord(fact.evidence_locator);
    const raw = fact.confidence ?? qualifiers['confidence'] ?? qualifiers['ocr_confidence'] ?? locator['confidence'];
    const value = Number(raw);
    if (!Number.isFinite(value)) return null;
    return value > 1 ? Math.max(0, Math.min(1, value / 100)) : Math.max(0, Math.min(1, value));
  }

  private dedupeOcrFacts(items: DocumentFactItem[]): DocumentFactItem[] {
    const seen = new Set<string>();
    const out: DocumentFactItem[] = [];
    for (const fact of items) {
      const key = [
        fact.document_id || '',
        fact.semantic_type || '',
        fact.page ?? '',
        this.ocrBoxLabel(fact),
        (fact.content || fact.value_raw || '').slice(0, 120),
      ].join(':');
      if (seen.has(key)) continue;
      seen.add(key);
      out.push(fact);
    }
    return out;
  }

  private asRecord(value: unknown): Record<string, unknown> {
    return value && typeof value === 'object' && !Array.isArray(value)
      ? value as Record<string, unknown>
      : {};
  }

  private toDisplayString(value: unknown): string {
    if (value === null || value === undefined) return '';
    if (typeof value === 'string') return value.trim();
    if (typeof value === 'number' || typeof value === 'boolean') return String(value);
    return '';
  }

  loadGuideIntoEditor(guide: KnowledgeGuide): void {
    this.editingGuideKey.set(guide.guide_key);
    this.guideTitle.set(guide.title || this.defaultGuideTitle());
    this.guideMarkdown.set(guide.markdown || guide.snippet || '');
    this.guideError.set(null);
  }

  saveCollectionGuide(status: 'draft' | 'published'): void {
    if (!this.kbId) return;
    const title = this.guideTitle().trim() || this.defaultGuideTitle();
    const markdown = this.guideMarkdown().trim();
    if (!markdown) {
      this.guideError.set('Markdown content is required before saving a guide.');
      return;
    }
    this.savingGuide.set(true);
    this.guideError.set(null);
    const existingKey = this.editingGuideKey() || this.collectionGuideVersions()[0]?.guide_key || null;
    const request = existingKey
      ? this.api.updateKnowledgeGuide(existingKey, {
          target_type: 'collection',
          target_ref: this.kbId,
          title,
          markdown,
          status,
        })
      : this.api.createKnowledgeGuide({
          target_type: 'collection',
          target_ref: this.kbId,
          title,
          markdown,
          status,
        });

    request.subscribe({
      next: (guide) => {
        this.savingGuide.set(false);
        this.editingGuideKey.set(guide.guide_key);
        this.api
          .listKnowledgeGuides({ current_only: false })
          .pipe(catchError(() => of({ items: this.knowledgeGuides() })))
          .subscribe((payload) => {
            this.knowledgeGuides.set(payload.items || []);
          });
      },
      error: () => {
        this.savingGuide.set(false);
        this.guideError.set('Unable to save this Knowledge Guide.');
      },
    });
  }

  private hydrateGuideEditor(): void {
    const current = this.collectionGuideVersions().find((guide) => guide.is_current);
    if (current) {
      this.loadGuideIntoEditor(current);
      return;
    }
    this.editingGuideKey.set(null);
    this.guideTitle.set(this.defaultGuideTitle());
    this.guideMarkdown.set('');
  }

  private defaultGuideTitle(): string {
    return `${this.kbId || 'Collection'} Knowledge Guide`;
  }
}

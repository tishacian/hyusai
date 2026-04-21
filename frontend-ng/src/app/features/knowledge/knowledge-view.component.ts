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
import { forkJoin, of } from 'rxjs';
import { catchError } from 'rxjs/operators';
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
  chunk_count?: number;
  mime_type?: string;
  uploaded_at?: string;
  size?: number;
}

interface StatsPayload {
  collection_name?: string;
  total_chunks?: number;
  vector_dim?: number | null;
  cache_stats?: Record<string, unknown> | null;
}

interface CollectionsPayload {
  collections?: string[];
  vector_db_type?: string;
  default?: string | null;
}

type KbTabId = 'overview' | 'sources' | 'chunks' | 'bindings';

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

    <ck-tabs
      [active]="activeTab()"
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
        </section>
      </ck-tab>

      <ck-tab id="sources" label="Sources">
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
                </tr>
              </thead>
              <tbody>
                @for (s of sources(); track s.document_id) {
                  <tr class="border-t border-white/5 hover:bg-white/5 transition">
                    <td class="px-4 py-2.5 text-white truncate max-w-xs">{{ s.filename }}</td>
                    <td class="px-4 py-2.5 text-right tabular-nums text-gray-300">{{ s.chunk_count ?? '—' }}</td>
                    <td class="px-4 py-2.5 text-gray-400 text-xs">{{ s.mime_type || '—' }}</td>
                    <td class="px-4 py-2.5 text-gray-400 text-xs">{{ s.uploaded_at ? (s.uploaded_at | slice:0:10) : '—' }}</td>
                  </tr>
                }
              </tbody>
            </table>
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

          @if (sources().length > 0) {
            <div class="border-t border-white/5 pt-3">
              <div class="ck-mono text-[10px] uppercase tracking-wider text-gray-500 mb-2">
                Distribution by document
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
  `,
})
export class KnowledgeViewComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly http = inject(HttpClient);
  private readonly canonical = inject(CanonicalApiService);
  readonly lensService = inject(LensService);

  private readonly base = '/api/v1/documents';

  kbId = '';
  readonly title = signal('Knowledge base');
  readonly activeTab = signal<KbTabId>('overview');
  readonly bindingsPanelOpen = signal(false);

  readonly loading = signal(true);
  readonly loadingSources = signal(true);
  readonly loadingBindings = signal(true);

  readonly docCount = signal(0);
  readonly chunkCount = signal(0);
  readonly vectorDim = signal<number | null>(null);
  readonly vectorDbType = signal<string>('');

  readonly sources = signal<DocRow[]>([]);
  readonly bindings = signal<System[]>([]);

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
    const sorted = [...this.sources()].sort(
      (a, b) => (b.chunk_count ?? 0) - (a.chunk_count ?? 0),
    );
    return sorted.slice(0, 10);
  });

  ngOnInit(): void {
    this.kbId = this.route.snapshot.paramMap.get('kbId') ?? '';
    this.title.set(this.kbId || 'Knowledge base');
    this.loadAll();
  }

  onTabChange(id: string): void {
    this.activeTab.set(id as KbTabId);
  }

  distributionPct(n: number | undefined): number {
    const max = this.topSources()[0]?.chunk_count ?? 1;
    if (!n || max === 0) return 0;
    return Math.max(3, Math.min(100, (n / max) * 100));
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
      list: this.http
        .get<{ documents?: DocRow[]; total?: number }>(
          `${this.base}/list?collection_name=${q}`,
        )
        .pipe(catchError(() => of({ documents: [], total: 0 }))),
      meta: this.http
        .get<CollectionsPayload>(`${this.base}/collections`)
        .pipe(catchError(() => of<CollectionsPayload>({}))),
    }).subscribe(({ stats, list, meta }) => {
      this.chunkCount.set(stats.total_chunks ?? 0);
      this.vectorDim.set(stats.vector_dim ?? null);
      this.vectorDbType.set(meta.vector_db_type ?? '');
      this.sources.set(list.documents ?? []);
      this.docCount.set(list.total ?? (list.documents?.length ?? 0));
      this.loading.set(false);
      this.loadingSources.set(false);
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
}

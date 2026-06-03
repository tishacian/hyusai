import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { catchError, of } from 'rxjs';

import { IconComponent } from '@app/shared/ui/icon.component';

export interface EmbeddingNodeSelection {
  document_id?: string;
  title?: string;
  collection?: string;
  chunk_count?: number;
}

export interface EmbeddingSourceOption {
  document_id: string;
  filename: string;
}

interface EmbeddingNode {
  id: number;
  point_id?: string;
  document_id?: string;
  document_filename?: string;
  chunk_index?: number | null;
  section_path?: string | null;
  page?: number | string | null;
  snippet?: string;
  source_kind?: string | null;
  project_code?: string | null;
  archive_name?: string | null;
  x: number;
  y: number;
}

interface EmbeddingEdge {
  source: number;
  target: number;
  weight: number;
}

interface EmbeddingGraphPayload {
  collection_name: string;
  document_id?: string | null;
  sample: number;
  total_chunks?: number;
  neighbors: number;
  min_score: number;
  vector_dim?: number | null;
  projection: string;
  nodes: EmbeddingNode[];
  edges: EmbeddingEdge[];
  supported: boolean;
  cached?: boolean;
  warnings?: string[];
}

interface PlottedEdge {
  key: string;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  weight: number;
}

@Component({
  selector: 'app-embedding-map',
  standalone: true,
  imports: [IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="rounded-md border border-white/10 bg-white/[0.03]">
      <div class="flex flex-col gap-3 border-b border-white/5 p-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p class="text-[10px] uppercase tracking-[0.18em] text-cyan-300">Embedding map</p>
          <h3 class="mt-1 text-sm font-semibold text-white">{{ collection() || 'Collection' }}</h3>
          <p class="mt-1 text-xs text-gray-500">
            {{ graphSummary() }}
          </p>
        </div>
        <div class="flex flex-wrap items-end gap-2">
          <label class="block">
            <span class="mb-1 block text-[10px] uppercase tracking-wider text-gray-500">Sample</span>
            <select
              class="rounded bg-black/30 px-2 py-1.5 text-xs text-gray-200 ring-1 ring-white/10"
              [value]="sample()"
              (change)="sample.set(+($any($event.target).value || 300))"
            >
              <option value="150">150</option>
              <option value="300">300</option>
              <option value="500">500</option>
            </select>
          </label>
          <label class="block">
            <span class="mb-1 block text-[10px] uppercase tracking-wider text-gray-500">Source</span>
            <select
              class="max-w-[260px] rounded bg-black/30 px-2 py-1.5 text-xs text-gray-200 ring-1 ring-white/10"
              [value]="documentId()"
              (change)="documentId.set($any($event.target).value)"
            >
              <option value="">Sample corpus</option>
              @for (doc of documents(); track doc.document_id) {
                <option [value]="doc.document_id">{{ doc.filename }}</option>
              }
            </select>
          </label>
          <button
            type="button"
            title="Refresh map"
            aria-label="Refresh map"
            class="inline-flex h-8 w-8 items-center justify-center rounded bg-white/5 text-gray-200 ring-1 ring-white/10 hover:bg-white/10"
            (click)="loadGraph()"
          >
            <app-icon name="refresh-cw" [size]="14" />
          </button>
        </div>
      </div>

      @if (loading()) {
        <div class="p-8 text-center text-sm text-gray-400">
          <app-icon name="loader-2" [size]="14" class="mr-2 inline-block animate-spin" />
          Loading sampled graph…
        </div>
      } @else if (error()) {
        <div class="p-6 text-sm text-amber-100">
          {{ error() }}
        </div>
      } @else if (!graph()?.supported) {
        <div class="p-6 text-sm text-gray-400">
          Embedding graph is not available for this vector store.
        </div>
      } @else if (!graph()?.nodes?.length) {
        <div class="p-6 text-sm text-gray-500">
          No sampled vectors returned for this collection.
        </div>
      } @else {
        <div class="grid gap-0 lg:grid-cols-[minmax(0,1fr)_320px]">
          <div class="min-h-[460px] border-b border-white/5 bg-black/20 lg:border-b-0 lg:border-r">
            <div class="flex items-center justify-between gap-2 border-b border-white/5 px-4 py-2">
              <div class="flex items-center gap-1.5">
                <button
                  type="button"
                  title="Zoom out"
                  aria-label="Zoom out"
                  class="inline-flex h-7 w-7 items-center justify-center rounded bg-white/5 text-gray-300 ring-1 ring-white/10 hover:bg-white/10"
                  (click)="zoom.set(clamp(zoom() - 0.2, 0.8, 2.4))"
                >
                  <app-icon name="minus" [size]="13" />
                </button>
                <input
                  type="range"
                  min="0.8"
                  max="2.4"
                  step="0.1"
                  class="w-24 accent-cyan-300"
                  [value]="zoom()"
                  (input)="zoom.set(+$any($event.target).value)"
                />
                <button
                  type="button"
                  title="Zoom in"
                  aria-label="Zoom in"
                  class="inline-flex h-7 w-7 items-center justify-center rounded bg-white/5 text-gray-300 ring-1 ring-white/10 hover:bg-white/10"
                  (click)="zoom.set(clamp(zoom() + 0.2, 0.8, 2.4))"
                >
                  <app-icon name="plus" [size]="13" />
                </button>
              </div>
              <div class="flex items-center gap-1.5">
                <button type="button" title="Pan left" aria-label="Pan left" class="map-btn" (click)="panX.set(panX() - 5)">
                  <app-icon name="chevron-left" [size]="13" />
                </button>
                <button type="button" title="Pan up" aria-label="Pan up" class="map-btn" (click)="panY.set(panY() - 5)">
                  <app-icon name="chevron-up" [size]="13" />
                </button>
                <button type="button" title="Pan down" aria-label="Pan down" class="map-btn" (click)="panY.set(panY() + 5)">
                  <app-icon name="chevron-down" [size]="13" />
                </button>
                <button type="button" title="Pan right" aria-label="Pan right" class="map-btn" (click)="panX.set(panX() + 5)">
                  <app-icon name="chevron-right" [size]="13" />
                </button>
                <button type="button" title="Reset view" aria-label="Reset view" class="map-btn" (click)="resetView()">
                  <app-icon name="crosshair" [size]="13" />
                </button>
              </div>
            </div>
            <svg class="h-[420px] w-full" viewBox="0 0 100 100" role="img" aria-label="Sampled embedding graph">
              <g [attr.transform]="viewTransform()">
                @for (edge of plottedEdges(); track edge.key) {
                  <line
                    [attr.x1]="edge.x1"
                    [attr.y1]="edge.y1"
                    [attr.x2]="edge.x2"
                    [attr.y2]="edge.y2"
                    [attr.stroke-opacity]="edgeOpacity(edge.weight)"
                    stroke="rgb(34 211 238)"
                    stroke-width="0.12"
                  />
                }
                @for (node of graph()?.nodes || []; track node.id) {
                  <circle
                    class="cursor-pointer transition hover:stroke-white"
                    [attr.cx]="pointX(node)"
                    [attr.cy]="pointY(node)"
                    r="0.9"
                    [attr.fill]="nodeColor(node)"
                    stroke="rgba(255,255,255,0.35)"
                    stroke-width="0.15"
                    (click)="selectNode(node)"
                  >
                    <title>{{ nodeTitle(node) }}</title>
                  </circle>
                }
              </g>
            </svg>
          </div>
          <aside class="space-y-3 p-4">
            <div class="grid grid-cols-2 gap-2 text-xs">
              <div class="rounded border border-white/10 bg-black/20 p-3">
                <div class="text-[10px] uppercase tracking-wider text-gray-500">Sample</div>
                <div class="mt-1 font-semibold text-white tabular-nums">{{ graph()?.sample || 0 }} / {{ graph()?.total_chunks || '—' }}</div>
              </div>
              <div class="rounded border border-white/10 bg-black/20 p-3">
                <div class="text-[10px] uppercase tracking-wider text-gray-500">Projection</div>
                <div class="mt-1 font-semibold text-white">{{ graph()?.projection || '—' }}</div>
              </div>
              <div class="rounded border border-white/10 bg-black/20 p-3">
                <div class="text-[10px] uppercase tracking-wider text-gray-500">Vector dim</div>
                <div class="mt-1 font-semibold text-white tabular-nums">{{ graph()?.vector_dim || '—' }}</div>
              </div>
              <div class="rounded border border-white/10 bg-black/20 p-3">
                <div class="text-[10px] uppercase tracking-wider text-gray-500">Edges</div>
                <div class="mt-1 font-semibold text-white tabular-nums">{{ graph()?.edges?.length || 0 }}</div>
              </div>
            </div>
            @for (warning of graph()?.warnings || []; track warning) {
              <p class="rounded border border-amber-400/20 bg-amber-500/10 px-3 py-2 text-xs text-amber-100">
                {{ warning }}
              </p>
            }
            @if (selectedNode()) {
              <article class="rounded border border-cyan-300/20 bg-cyan-300/10 p-3 text-xs">
                <div class="font-medium text-white truncate">{{ selectedNode()?.document_filename || 'Sampled chunk' }}</div>
                <div class="mt-1 flex flex-wrap gap-1.5 text-[10px] text-cyan-100/80">
                  @if (selectedNode()?.chunk_index !== null && selectedNode()?.chunk_index !== undefined) {
                    <span>#{{ selectedNode()?.chunk_index }}</span>
                  }
                  @if (selectedNode()?.page) {
                    <span>p.{{ selectedNode()?.page }}</span>
                  }
                  @if (selectedNode()?.project_code) {
                    <span>{{ selectedNode()?.project_code }}</span>
                  }
                </div>
                @if (selectedNode()?.section_path) {
                  <p class="mt-2 truncate text-cyan-100/80">{{ selectedNode()?.section_path }}</p>
                }
                <p class="mt-2 leading-relaxed text-gray-200">{{ selectedNode()?.snippet || 'No snippet.' }}</p>
                <button
                  type="button"
                  class="mt-3 inline-flex items-center gap-1.5 rounded bg-cyan-300/15 px-2.5 py-1.5 text-xs font-medium text-cyan-100 ring-1 ring-cyan-300/25 hover:bg-cyan-300/20"
                  (click)="selectNode(selectedNode()!)"
                >
                  <app-icon name="eye" [size]="13" /> Preview source
                </button>
              </article>
            }
          </aside>
        </div>
      }
    </section>
  `,
  styles: [
    `
      .map-btn {
        align-items: center;
        background: rgb(255 255 255 / 0.05);
        border-radius: 0.25rem;
        color: rgb(209 213 219);
        display: inline-flex;
        height: 1.75rem;
        justify-content: center;
        width: 1.75rem;
        box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.1);
      }
      .map-btn:hover {
        background: rgb(255 255 255 / 0.1);
      }
    `,
  ],
})
export class EmbeddingMapComponent {
  private readonly http = inject(HttpClient);

  readonly collection = input<string>('');
  readonly active = input(false);
  readonly documents = input<EmbeddingSourceOption[]>([]);
  readonly previewRequested = output<EmbeddingNodeSelection>();

  readonly sample = signal(300);
  readonly documentId = signal('');
  readonly graph = signal<EmbeddingGraphPayload | null>(null);
  readonly loading = signal(false);
  readonly error = signal('');
  readonly selectedNode = signal<EmbeddingNode | null>(null);
  readonly zoom = signal(1);
  readonly panX = signal(0);
  readonly panY = signal(0);

  private lastLoadKey = '';

  readonly plottedEdges = computed<PlottedEdge[]>(() => {
    const graph = this.graph();
    if (!graph) return [];
    const byId = new Map(graph.nodes.map((node) => [node.id, node]));
    return (graph.edges || [])
      .map((edge) => {
        const source = byId.get(edge.source);
        const target = byId.get(edge.target);
        if (!source || !target) return null;
        return {
          key: `${edge.source}:${edge.target}`,
          x1: this.pointX(source),
          y1: this.pointY(source),
          x2: this.pointX(target),
          y2: this.pointY(target),
          weight: edge.weight,
        };
      })
      .filter((edge): edge is PlottedEdge => !!edge);
  });

  readonly graphSummary = computed(() => {
    const graph = this.graph();
    if (!graph) return 'Sampled embedding clusters load on demand.';
    return `${graph.sample} sampled chunk(s), ${graph.edges?.length || 0} similarity edge(s), ${graph.projection} projection.`;
  });

  constructor() {
    effect(() => {
      const active = this.active();
      const collection = this.collection();
      const sample = this.sample();
      const doc = this.documentId();
      const key = `${collection}:${sample}:${doc}`;
      if (!active || !collection || key === this.lastLoadKey) return;
      this.lastLoadKey = key;
      this.loadGraph();
    });
  }

  loadGraph(): void {
    const collection = this.collection();
    if (!collection) return;
    this.loading.set(true);
    this.error.set('');
    this.selectedNode.set(null);
    const params = new URLSearchParams({
      collection_name: collection,
      sample: String(Math.min(500, Math.max(10, this.sample()))),
      neighbors: '4',
      min_score: '0.55',
    });
    const doc = this.documentId();
    if (doc) params.set('document_id', doc);
    this.http
      .get<EmbeddingGraphPayload>(`/api/v1/documents/graph?${params.toString()}`)
      .pipe(catchError(() => of<EmbeddingGraphPayload | null>(null)))
      .subscribe((payload) => {
        this.loading.set(false);
        if (!payload) {
          this.graph.set(null);
          this.error.set('Unable to load sampled embedding graph.');
          return;
        }
        this.graph.set(payload);
        this.resetView();
      });
  }

  selectNode(node: EmbeddingNode): void {
    this.selectedNode.set(node);
    if (!node.document_id) return;
    this.previewRequested.emit({
      document_id: node.document_id,
      title: node.document_filename || node.point_id || 'Sampled chunk',
      collection: this.collection(),
    });
  }

  resetView(): void {
    this.zoom.set(1);
    this.panX.set(0);
    this.panY.set(0);
  }

  clamp(value: number, min: number, max: number): number {
    return Math.max(min, Math.min(max, value));
  }

  viewTransform(): string {
    const zoom = this.zoom();
    const origin = 50 - (50 * zoom);
    return `translate(${origin + this.panX()} ${origin + this.panY()}) scale(${zoom})`;
  }

  pointX(node: EmbeddingNode): number {
    return this.clamp((node.x ?? 0.5) * 92 + 4, 2, 98);
  }

  pointY(node: EmbeddingNode): number {
    return this.clamp((node.y ?? 0.5) * 92 + 4, 2, 98);
  }

  edgeOpacity(weight: number): number {
    return this.clamp(0.15 + weight * 0.65, 0.15, 0.75);
  }

  nodeColor(node: EmbeddingNode): string {
    const kind = String(node.source_kind || '').toLowerCase();
    if (kind.includes('pdf')) return '#22d3ee';
    if (kind.includes('image')) return '#a78bfa';
    if (kind.includes('markup') || kind.includes('html')) return '#34d399';
    if (kind.includes('text')) return '#fbbf24';
    return '#f472b6';
  }

  nodeTitle(node: EmbeddingNode): string {
    return [
      node.document_filename || node.point_id || 'Sampled chunk',
      node.chunk_index !== null && node.chunk_index !== undefined ? `#${node.chunk_index}` : '',
      node.page ? `p.${node.page}` : '',
      node.section_path || '',
    ].filter(Boolean).join(' · ');
  }
}

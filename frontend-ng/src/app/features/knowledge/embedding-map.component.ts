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
  sample_requested?: number;
  sample_cap?: number;
  sample_capped?: boolean;
  total_chunks?: number;
  total_is_dense?: boolean;
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
    <section class="ck-surface">
      <div class="flex flex-col gap-3 p-4 lg:flex-row lg:items-end lg:justify-between" style="border-bottom:1px solid var(--ck-stroke-2);">
        <div>
          <p class="ck-label" style="color:var(--ck-signal-cool); letter-spacing:0.18em;">Embedding map</p>
          <h3 class="mt-1 text-sm font-semibold" style="color:var(--ck-fg-1);">{{ collection() || 'Collection' }}</h3>
          <p class="mt-1 text-xs" style="color:var(--ck-fg-4);">
            {{ graphSummary() }}
          </p>
        </div>
        <div class="flex flex-wrap items-end gap-2">
          <label class="block">
            <span class="ck-label mb-1 block">Sample</span>
            <select
              class="ck-field-select px-2 py-1.5 text-xs"
              [value]="sample()"
              (change)="sample.set(+($any($event.target).value || 300))"
            >
              <option value="150">150</option>
              <option value="300">300</option>
              <option value="500">500</option>
            </select>
          </label>
          <label class="block">
            <span class="ck-label mb-1 block">Source</span>
            <select
              class="ck-field-select max-w-[260px] px-2 py-1.5 text-xs"
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
            class="ck-iconbtn h-8 w-8"
            (click)="loadGraph()"
          >
            <app-icon name="refresh-cw" [size]="14" />
          </button>
        </div>
      </div>

      @if (loading()) {
        <div class="p-8 text-center text-sm" style="color:var(--ck-fg-3);">
          <app-icon name="loader-2" [size]="14" class="mr-2 inline-block animate-spin" />
          Loading sampled graph…
        </div>
      } @else if (error()) {
        <div class="p-6 text-sm" style="color:var(--ck-signal-warn);">
          {{ error() }}
        </div>
      } @else if (!graph()?.supported) {
        <div class="p-6 text-sm" style="color:var(--ck-fg-3);">
          Embedding graph is not available for this vector store.
        </div>
      } @else if (!graph()?.nodes?.length) {
        <div class="p-6 text-sm" style="color:var(--ck-fg-4);">
          No sampled vectors returned for this collection.
        </div>
      } @else {
        <div class="grid gap-0 lg:grid-cols-[minmax(0,1fr)_320px]">
          <div class="ck-graph-pane min-h-[460px]" style="background:var(--ck-bg-inset);">
            <div class="flex items-center justify-between gap-2 px-4 py-2" style="border-bottom:1px solid var(--ck-stroke-2);">
              <div class="flex items-center gap-1.5">
                <button
                  type="button"
                  title="Zoom out"
                  aria-label="Zoom out"
                  class="ck-iconbtn h-7 w-7"
                  (click)="zoom.set(clamp(zoom() - 0.2, 0.8, 2.4))"
                >
                  <app-icon name="minus" [size]="13" />
                </button>
                <input
                  type="range"
                  min="0.8"
                  max="2.4"
                  step="0.1"
                  class="w-24"
                  style="accent-color:var(--ck-signal-cool);"
                  [value]="zoom()"
                  (input)="zoom.set(+$any($event.target).value)"
                />
                <button
                  type="button"
                  title="Zoom in"
                  aria-label="Zoom in"
                  class="ck-iconbtn h-7 w-7"
                  (click)="zoom.set(clamp(zoom() + 0.2, 0.8, 2.4))"
                >
                  <app-icon name="plus" [size]="13" />
                </button>
              </div>
              <div class="flex items-center gap-1.5">
                <button type="button" title="Pan left" aria-label="Pan left" class="ck-iconbtn h-7 w-7" (click)="panX.set(panX() - 5)">
                  <app-icon name="chevron-left" [size]="13" />
                </button>
                <button type="button" title="Pan up" aria-label="Pan up" class="ck-iconbtn h-7 w-7" (click)="panY.set(panY() - 5)">
                  <app-icon name="chevron-up" [size]="13" />
                </button>
                <button type="button" title="Pan down" aria-label="Pan down" class="ck-iconbtn h-7 w-7" (click)="panY.set(panY() + 5)">
                  <app-icon name="chevron-down" [size]="13" />
                </button>
                <button type="button" title="Pan right" aria-label="Pan right" class="ck-iconbtn h-7 w-7" (click)="panX.set(panX() + 5)">
                  <app-icon name="chevron-right" [size]="13" />
                </button>
                <button type="button" title="Reset view" aria-label="Reset view" class="ck-iconbtn h-7 w-7" (click)="resetView()">
                  <app-icon name="crosshair" [size]="13" />
                </button>
              </div>
            </div>
            <svg class="h-[420px] w-full" viewBox="0 0 100 100" role="img" aria-label="Sampled embedding graph">
              <g [attr.transform]="viewTransform()">
                @for (edge of plottedEdges(); track edge.key) {
                  <line
                    class="ck-edge"
                    [attr.x1]="edge.x1"
                    [attr.y1]="edge.y1"
                    [attr.x2]="edge.x2"
                    [attr.y2]="edge.y2"
                    [attr.stroke-opacity]="edgeOpacity(edge.weight)"
                    stroke-width="0.12"
                  />
                }
                @for (node of graph()?.nodes || []; track node.id) {
                  <circle
                    class="ck-node cursor-pointer transition"
                    [attr.cx]="pointX(node)"
                    [attr.cy]="pointY(node)"
                    r="0.9"
                    [attr.fill]="nodeColor(node)"
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
              <div class="ck-inset rounded p-3">
                <div class="ck-label">Sample</div>
                <div class="mt-1 font-semibold tabular-nums" style="color:var(--ck-fg-1);">{{ graph()?.sample || 0 }} / {{ graph()?.total_chunks || '—' }}</div>
                @if (graph()?.sample_capped) {
                  <div class="mt-1 text-[10px]" style="color:var(--ck-signal-warn);">cap {{ graph()?.sample_cap }}</div>
                }
              </div>
              <div class="ck-inset rounded p-3">
                <div class="ck-label">Projection</div>
                <div class="mt-1 font-semibold" style="color:var(--ck-fg-1);">{{ graph()?.projection || '—' }}</div>
              </div>
              <div class="ck-inset rounded p-3">
                <div class="ck-label">Vector dim</div>
                <div class="mt-1 font-semibold tabular-nums" style="color:var(--ck-fg-1);">{{ graph()?.vector_dim || '—' }}</div>
              </div>
              <div class="ck-inset rounded p-3">
                <div class="ck-label">Edges</div>
                <div class="mt-1 font-semibold tabular-nums" style="color:var(--ck-fg-1);">{{ graph()?.edges?.length || 0 }}</div>
              </div>
            </div>
            @for (warning of graph()?.warnings || []; track warning) {
              <p class="rounded px-3 py-2 text-xs" style="border:1px solid rgba(245,184,74,0.25); background:rgba(245,184,74,0.10); color:var(--ck-signal-warn);">
                {{ warning }}
              </p>
            }
            @if (selectedNode()) {
              <article class="rounded p-3 text-xs" style="border:1px solid rgba(125,211,252,0.25); background:rgba(125,211,252,0.08);">
                <div class="font-medium truncate" style="color:var(--ck-fg-1);">{{ selectedNode()?.document_filename || 'Sampled chunk' }}</div>
                <div class="mt-1 flex flex-wrap gap-1.5 text-[10px]" style="color:var(--ck-signal-cool);">
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
                  <p class="mt-2 truncate" style="color:var(--ck-fg-2);">{{ selectedNode()?.section_path }}</p>
                }
                <p class="mt-2 leading-relaxed" style="color:var(--ck-fg-2);">{{ selectedNode()?.snippet || 'No snippet.' }}</p>
                <button
                  type="button"
                  class="ck-btn-soft mt-3 px-2.5 py-1.5 text-xs font-medium"
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
      /* Cockpit DS-C — component-scoped helpers (token-driven; mirrors auth/exemplar pattern). */
      .ck-field-input,
      .ck-field-select,
      .ck-field-textarea {
        background: var(--ck-bg-inset);
        border: 1px solid var(--ck-stroke-2);
        border-radius: var(--ck-radius-sm);
        color: var(--ck-fg-1);
        font-family: var(--ck-font-sans);
        outline: none;
        transition:
          border-color var(--ck-dur-fast) var(--ck-ease-out),
          box-shadow var(--ck-dur-fast) var(--ck-ease-out),
          background var(--ck-dur-fast) var(--ck-ease-out);
      }
      .ck-field-input::placeholder,
      .ck-field-textarea::placeholder { color: var(--ck-fg-4); }
      .ck-field-input:focus,
      .ck-field-select:focus,
      .ck-field-textarea:focus {
        border-color: var(--ck-stroke-hot);
        background: var(--ck-bg-panel-hi);
        box-shadow: 0 0 0 1px var(--ck-signal-cool);
      }
      .ck-field-textarea { font-family: var(--ck-font-mono); }
      .ck-field-select {
        appearance: none;
        -webkit-appearance: none;
        background-image:
          linear-gradient(45deg, transparent 50%, var(--ck-fg-4) 50%),
          linear-gradient(135deg, var(--ck-fg-4) 50%, transparent 50%);
        background-position: calc(100% - 14px) 50%, calc(100% - 9px) 50%;
        background-size: 5px 5px, 5px 5px;
        background-repeat: no-repeat;
        padding-right: 1.75rem;
      }

      .ck-btn-soft,
      .ck-btn-primary {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 0.375rem;
        border-radius: var(--ck-radius-sm);
        cursor: pointer;
        transition:
          background var(--ck-dur-fast) var(--ck-ease-out),
          color var(--ck-dur-fast) var(--ck-ease-out),
          border-color var(--ck-dur-fast) var(--ck-ease-out);
      }
      .ck-btn-soft {
        background: var(--ck-bg-panel-hi);
        border: 1px solid var(--ck-stroke-2);
        color: var(--ck-fg-2);
      }
      .ck-btn-soft:hover:not(:disabled) {
        background: var(--ck-bg-inset);
        color: var(--ck-fg-1);
        border-color: var(--ck-stroke-3);
      }
      .ck-btn-soft:disabled { opacity: 0.4; cursor: not-allowed; }
      .ck-btn-primary {
        background: linear-gradient(180deg, rgba(125, 211, 252, 0.22), rgba(125, 211, 252, 0.12));
        border: 1px solid var(--ck-stroke-hot);
        color: var(--ck-fg-1);
        font-weight: 600;
      }
      .ck-btn-primary:hover:not(:disabled) {
        background: linear-gradient(180deg, rgba(125, 211, 252, 0.30), rgba(125, 211, 252, 0.18));
        border-color: rgba(125, 211, 252, 0.55);
      }
      .ck-btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }

      .ck-iconbtn {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        border-radius: var(--ck-radius-sm);
        background: var(--ck-bg-panel-hi);
        border: 1px solid var(--ck-stroke-2);
        color: var(--ck-fg-3);
        cursor: pointer;
        transition:
          background var(--ck-dur-fast) var(--ck-ease-out),
          color var(--ck-dur-fast) var(--ck-ease-out);
      }
      .ck-iconbtn:hover:not(:disabled) { background: var(--ck-bg-inset); color: var(--ck-fg-1); }
      .ck-iconbtn:disabled { opacity: 0.4; cursor: not-allowed; }
      .ck-iconbtn-danger:hover:not(:disabled) { color: var(--ck-signal-neg); }

      .ck-btn-ghost {
        background: transparent;
        border: 0;
        color: var(--ck-fg-3);
        border-radius: var(--ck-radius-sm);
        cursor: pointer;
        transition: color var(--ck-dur-fast), background var(--ck-dur-fast);
      }
      .ck-btn-ghost:hover:not(:disabled) { color: var(--ck-fg-1); background: var(--ck-bg-panel-hi); }

      .ck-ghost-icon {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        color: var(--ck-fg-3);
        border-radius: var(--ck-radius-sm);
        cursor: pointer;
        transition: color var(--ck-dur-fast), background var(--ck-dur-fast);
      }
      .ck-ghost-icon:hover { color: var(--ck-fg-1); background: var(--ck-bg-panel-hi); }
      .ck-ghost-icon-danger:hover { color: var(--ck-signal-neg); }

      .ck-divide > * + * { border-top: 1px solid var(--ck-stroke-2); }
      .ck-rowi { transition: background var(--ck-dur-fast) var(--ck-ease-out); }
      .ck-rowi:hover { background: var(--ck-bg-panel-hi); }

      /* Embedding scatter — cockpit signal palette. */
      .ck-graph-pane { border-bottom: 1px solid var(--ck-stroke-2); }
      @media (min-width: 1024px) {
        .ck-graph-pane { border-bottom: 0; border-right: 1px solid var(--ck-stroke-2); }
      }
      .ck-edge { stroke: var(--ck-signal-cool); }
      .ck-node { stroke: var(--ck-stroke-3); }
      .ck-node:hover { stroke: var(--ck-fg-1); }
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
    const cap = graph.sample_capped ? `, capped from ${graph.sample_requested}` : '';
    return `${graph.sample} sampled chunk(s)${cap}, ${graph.edges?.length || 0} similarity edge(s), ${graph.projection} projection.`;
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

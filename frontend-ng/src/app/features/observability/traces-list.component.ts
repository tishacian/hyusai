import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiService } from '@app/core/api.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import { StatTileComponent } from '@app/shared/ui/stat-tile.component';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import { DrawerComponent } from '@app/shared/ui/drawer.component';
import { GlyphComponent, PageFrameComponent } from '@app/shared/cockpit';

interface TraceStep {
  id?: string;
  name?: string;
  step_type?: string;
  start_time?: string;
  end_time?: string | null;
  duration_ms?: number | null;
  metadata?: Record<string, unknown>;
  error?: string | null;
  status?: string;
}

interface Trace {
  id: string;
  operation_type: string;
  start_time: string;
  end_time?: string | null;
  duration_ms?: number | null;
  steps?: TraceStep[];
  metadata?: Record<string, unknown>;
}

@Component({
  selector: 'app-traces-list',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    IconComponent,
    StatTileComponent,
    EmptyStateComponent,
    DrawerComponent,
    PageFrameComponent,
    GlyphComponent,
  ],
  template: `
    <ck-page-frame
      eyebrow="Measure · Observability"
      title="Traces"
      description="Execution traces for every Run — retrieval, synthesis, evaluation."
    >
      <div actions [style.display]="'inline-flex'" [style.alignItems]="'center'" [style.gap.px]="6">
        <select
          [(ngModel)]="filterType"
          (ngModelChange)="refresh()"
          class="ck-mono"
          [style.height.px]="28"
          [style.padding]="'0 10px'"
          [style.background]="'var(--ck-bg-inset)'"
          [style.color]="'var(--ck-fg-1)'"
          [style.border]="'1px solid var(--ck-stroke-2)'"
          [style.borderRadius.px]="4"
          [style.fontSize.px]="11"
          [style.letterSpacing]="'0.04em'"
        >
          <option value="">All operations</option>
          <option value="ingest">Ingest</option>
          <option value="search">Search</option>
          <option value="query">Query</option>
        </select>
        <button
          type="button"
          (click)="refresh()"
          [disabled]="loading()"
          class="ck-mono"
          [style.display]="'inline-flex'"
          [style.alignItems]="'center'"
          [style.gap.px]="6"
          [style.height.px]="28"
          [style.padding]="'0 12px'"
          [style.background]="'transparent'"
          [style.color]="'var(--ck-fg-2)'"
          [style.border]="'1px solid var(--ck-stroke-2)'"
          [style.borderRadius.px]="4"
          [style.fontSize.px]="11"
          [style.letterSpacing]="'0.08em'"
          [style.textTransform]="'uppercase'"
          [style.cursor]="'pointer'"
        >
          <ck-glyph name="orbit" [size]="12" />
          Refresh
        </button>
      </div>

    <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
      <app-stat-tile
        label="Traces"
        [value]="traces().length"
        icon="git-commit"
        [sparkline]="countSeries()"
        sparklineTone="neutral"
      />
      <app-stat-tile
        label="Avg duration"
        [value]="avgDuration()"
        unit="ms"
        icon="clock"
        [sparkline]="durationSeries()"
        sparklineTone="negative"
      />
      <app-stat-tile
        label="Slowest"
        [value]="maxDuration()"
        unit="ms"
        icon="gauge"
        [sparkline]="durationSeries()"
        sparklineTone="negative"
      />
      <app-stat-tile
        label="With errors"
        [value]="errorCount()"
        icon="alert-triangle"
        [trend]="errorCount() > 0 ? 'up' : null"
        trendSentiment="negative"
      />
    </div>

    <section class="t-card t-elevated rounded-md overflow-hidden">
      <div class="px-5 py-4 border-b border-white/5 flex items-center justify-between">
        <h3 class="text-sm font-semibold text-white flex items-center gap-1.5">
          <app-icon name="list-checks" [size]="16" class="text-brand-400" />
          Recent executions
        </h3>
      </div>

      @if (loading() && traces().length === 0) {
        <div class="divide-y divide-white/5">
          @for (_ of [0, 1, 2, 3, 4]; track $index) {
            <div class="px-5 py-3 animate-pulse">
              <div class="h-3 w-60 bg-white/5 rounded"></div>
            </div>
          }
        </div>
      } @else if (traces().length === 0) {
        <app-empty-state
          icon="git-commit"
          title="No traces yet"
          description="Run a RAG query to collect execution traces."
        />
      } @else {
        <ul class="divide-y divide-white/5">
          @for (t of traces(); track t.id) {
            <li
              class="px-5 py-3 cursor-pointer hover:bg-white/5 transition grid grid-cols-12 gap-3 items-center"
              (click)="openTrace(t)"
            >
              <div class="col-span-6 min-w-0 flex items-center gap-2">
                <div
                  class="w-7 h-7 rounded-md flex items-center justify-center text-xs font-semibold shrink-0"
                  [class.bg-brand-500\\/15]="t.operation_type === 'query'"
                  [class.text-brand-300]="t.operation_type === 'query'"
                  [class.bg-violet-500\\/15]="t.operation_type === 'search'"
                  [class.text-violet-300]="t.operation_type === 'search'"
                  [class.bg-emerald-500\\/15]="t.operation_type === 'ingest'"
                  [class.text-emerald-300]="t.operation_type === 'ingest'"
                  [class.bg-white\\/5]="
                    t.operation_type !== 'query' &&
                    t.operation_type !== 'search' &&
                    t.operation_type !== 'ingest'
                  "
                >
                  {{ t.operation_type.charAt(0).toUpperCase() }}
                </div>
                <div class="min-w-0">
                  <div class="text-sm text-white capitalize truncate">
                    {{ t.operation_type }}
                  </div>
                  <div class="text-[11px] text-gray-500 font-mono truncate">
                    {{ t.id.slice(0, 8) }}… · {{ formatDate(t.start_time) }}
                  </div>
                </div>
              </div>
              <div class="col-span-2 text-xs text-gray-400">
                {{ t.steps?.length ?? 0 }} steps
              </div>
              <div class="col-span-3 text-xs text-gray-300 font-mono tabular-nums">
                {{ t.duration_ms != null ? t.duration_ms.toFixed(0) + ' ms' : '—' }}
              </div>
              <div class="col-span-1 text-right">
                <app-icon name="chevron-right" [size]="14" class="text-gray-500" />
              </div>
            </li>
          }
        </ul>
      }
    </section>
    </ck-page-frame>

    <app-drawer
      [open]="selectedTrace() !== null"
      [title]="selectedOperationLabel()"
      [subtitle]="selectedSubtitle()"
      icon="git-commit"
      (close)="selectedTrace.set(null)"
    >
      @if (selectedTrace(); as trace) {
        <div class="space-y-4">
          <div class="grid grid-cols-3 gap-3">
            <div class="rounded bg-black/20 ring-1 ring-white/5 p-3">
              <div class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold mb-1">
                Duration
              </div>
              <div class="text-sm text-white font-mono">
                {{ trace.duration_ms != null ? trace.duration_ms.toFixed(1) + ' ms' : '—' }}
              </div>
            </div>
            <div class="rounded bg-black/20 ring-1 ring-white/5 p-3">
              <div class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold mb-1">
                Steps
              </div>
              <div class="text-sm text-white font-mono">{{ trace.steps?.length ?? 0 }}</div>
            </div>
            <div class="rounded bg-black/20 ring-1 ring-white/5 p-3">
              <div class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold mb-1">
                Started
              </div>
              <div class="text-sm text-white font-mono">
                {{ formatDate(trace.start_time) }}
              </div>
            </div>
          </div>

          @if (trace.metadata && hasKeys(trace.metadata)) {
            <div>
              <div class="text-xs uppercase tracking-wider text-gray-500 font-semibold mb-2">
                Metadata
              </div>
              <pre
                class="text-[11px] text-gray-200 bg-black/30 rounded p-3 font-mono whitespace-pre-wrap"
              >{{ jsonPretty(trace.metadata) }}</pre>
            </div>
          }

          <div>
            <div class="text-xs uppercase tracking-wider text-gray-500 font-semibold mb-2">
              Timeline
            </div>
            @if ((trace.steps?.length ?? 0) === 0) {
              <div class="text-xs text-gray-500">No recorded steps.</div>
            } @else {
              <ol class="space-y-2">
                @for (s of trace.steps ?? []; track $index; let i = $index) {
                  <li
                    class="rounded ring-1 ring-white/5 p-3"
                    [class.bg-red-500\\/5]="!!s.error"
                    [class.bg-black\\/20]="!s.error"
                  >
                    <div class="flex items-center justify-between mb-1">
                      <div class="flex items-center gap-2 min-w-0">
                        <span
                          class="w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-mono shrink-0"
                          [class.bg-brand-500\\/20]="!s.error"
                          [class.text-brand-300]="!s.error"
                          [class.bg-red-500\\/20]="!!s.error"
                          [class.text-red-300]="!!s.error"
                        >
                          {{ i + 1 }}
                        </span>
                        <span class="text-sm text-white truncate">{{ stepLabel(s) }}</span>
                      </div>
                      <span class="text-[11px] text-gray-400 font-mono shrink-0 ml-2">
                        {{ s.duration_ms != null ? s.duration_ms.toFixed(1) + ' ms' : '—' }}
                      </span>
                    </div>
                    @if (s.error) {
                      <div class="text-[11px] text-red-300 mt-1 font-mono">{{ s.error }}</div>
                    }
                    @if (s.metadata && hasKeys(s.metadata)) {
                      <details class="mt-2">
                        <summary class="text-[11px] text-gray-500 cursor-pointer hover:text-gray-300">
                          metadata
                        </summary>
                        <pre
                          class="mt-1 text-[11px] text-gray-200 bg-black/30 rounded p-2 font-mono whitespace-pre-wrap"
                        >{{ jsonPretty(s.metadata) }}</pre>
                      </details>
                    }
                  </li>
                }
              </ol>
            }
          </div>
        </div>
      }
    </app-drawer>
  `,
})
export class TracesListComponent implements OnInit {
  private readonly api = inject(ApiService);

  traces = signal<Trace[]>([]);
  loading = signal(false);
  filterType = '';
  selectedTrace = signal<Trace | null>(null);

  readonly avgDuration = computed(() => {
    const list = this.traces().filter((t) => t.duration_ms != null);
    if (list.length === 0) return '0';
    const sum = list.reduce((acc, t) => acc + (t.duration_ms ?? 0), 0);
    return (sum / list.length).toFixed(0);
  });

  readonly maxDuration = computed(() => {
    const list = this.traces().filter((t) => t.duration_ms != null);
    if (list.length === 0) return '0';
    return Math.max(...list.map((t) => t.duration_ms ?? 0)).toFixed(0);
  });

  readonly errorCount = computed(
    () =>
      this.traces().filter((t) => (t.steps ?? []).some((s) => !!s.error)).length,
  );

  /** Latest N trace durations, oldest first — for the sparkline. */
  readonly durationSeries = computed<number[]>(() => {
    const list = this.traces()
      .filter((t) => t.duration_ms != null && t.duration_ms > 0)
      .slice(0, 20);
    return list.map((t) => t.duration_ms ?? 0).reverse();
  });

  /** Cumulative trace counts over the last 20 entries — oldest first. */
  readonly countSeries = computed<number[]>(() => {
    const n = Math.min(this.traces().length, 20);
    if (n < 2) return [];
    return Array.from({ length: n }, (_, i) => i + 1);
  });

  readonly selectedOperationLabel = computed(() => {
    const t = this.selectedTrace();
    if (!t) return '';
    return (t.operation_type?.charAt(0).toUpperCase() ?? '') + (t.operation_type?.slice(1) ?? '');
  });

  readonly selectedSubtitle = computed(() => {
    const t = this.selectedTrace();
    if (!t) return '';
    return `Trace ${t.id.slice(0, 8)}…`;
  });

  ngOnInit(): void {
    this.refresh();
  }

  refresh(): void {
    this.loading.set(true);
    const url = this.filterType
      ? `/traces/traces?operation_type=${encodeURIComponent(this.filterType)}`
      : '/traces/traces';
    this.api.get<{ traces: Trace[] }>(url).subscribe({
      next: (res) => {
        // Sort most recent first.
        const list = (res?.traces ?? []).slice().sort((a, b) => {
          return (b.start_time ?? '').localeCompare(a.start_time ?? '');
        });
        this.traces.set(list);
        this.loading.set(false);
      },
      error: () => {
        this.traces.set([]);
        this.loading.set(false);
      },
    });
  }

  openTrace(t: Trace): void {
    // Fetch full trace (may include more step detail than the list view).
    this.api.get<Trace>(`/traces/traces/${t.id}`).subscribe({
      next: (full) => this.selectedTrace.set(full ?? t),
      error: () => this.selectedTrace.set(t),
    });
  }

  formatDate(iso?: string): string {
    if (!iso) return '';
    try {
      return new Date(iso).toLocaleString([], { dateStyle: 'short', timeStyle: 'medium' });
    } catch {
      return iso;
    }
  }

  stepLabel(s: TraceStep): string {
    return s.name || s.step_type || 'step';
  }

  hasKeys(obj: unknown): boolean {
    return !!obj && typeof obj === 'object' && Object.keys(obj as object).length > 0;
  }

  jsonPretty(obj: unknown): string {
    try {
      return JSON.stringify(obj, null, 2);
    } catch {
      return String(obj);
    }
  }
}

import {
  ChangeDetectionStrategy,
  Component,
  OnDestroy,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { ApiService } from '@app/core/api.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import { GlyphComponent, PageFrameComponent, StatReadoutComponent } from '@app/shared/cockpit';

interface MetricSummary {
  total_requests: number;
  total_errors: number;
  error_rate_percent: number;
  metrics_count: number;
}

interface CacheStats {
  size: number;
  max_size: number;
  usage_percent: number;
}

interface MetricDetail {
  count: number;
  avg_ms?: number;
  min_ms?: number;
  max_ms?: number;
  last_updated?: number;
}

interface MetricsResponse {
  metrics: Record<string, MetricDetail>;
  summary: MetricSummary;
}

@Component({
  selector: 'app-performance-dashboard',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconComponent, StatReadoutComponent, EmptyStateComponent, PageFrameComponent, GlyphComponent],
  template: `
    <ck-page-frame
      eyebrow="Measure · Observability"
      title="Performance"
      description="Request latency, error rate and cache efficiency across your systems."
    >
      <div actions [style.display]="'inline-flex'" [style.alignItems]="'center'" [style.gap.px]="10">
        <label class="ck-mono" [style.display]="'inline-flex'" [style.alignItems]="'center'" [style.gap.px]="6" [style.fontSize.px]="10" [style.color]="'var(--ck-fg-3)'" [style.letterSpacing]="'0.10em'" [style.textTransform]="'uppercase'" [style.cursor]="'pointer'">
          <input type="checkbox" [checked]="autoRefresh()" (change)="toggleAuto()" class="accent-cyan-500" />
          Auto-refresh
        </label>
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
      <ck-stat-readout variant="tile"
        label="Total requests"
        [value]="summary()?.total_requests ?? 0"
        icon="activity"
        [sparkline]="requestsSeries()"
        sparklineTone="neutral"
        [trend]="seriesTrend(requestsSeries())"
        trendSentiment="positive"
        [delta]="seriesDelta(requestsSeries())"
      />
      <ck-stat-readout variant="tile"
        label="Total errors"
        [value]="summary()?.total_errors ?? 0"
        icon="alert-triangle"
        [sparkline]="errorsSeries()"
        sparklineTone="negative"
        [trend]="seriesTrend(errorsSeries())"
        trendSentiment="negative"
        [delta]="seriesDelta(errorsSeries())"
      />
      <ck-stat-readout variant="tile"
        label="Error rate"
        [value]="errorRateDisplay()"
        unit="%"
        icon="alert-circle"
        [sparkline]="errorRateSeries()"
        sparklineTone="negative"
        [trend]="seriesTrend(errorRateSeries())"
        trendSentiment="negative"
      />
      <ck-stat-readout variant="tile"
        label="Cache usage"
        [value]="cacheUsageDisplay()"
        unit="%"
        icon="database"
        [sparkline]="cacheSeries()"
        sparklineTone="neutral"
        [hint]="(cache()?.size ?? 0) + ' / ' + (cache()?.max_size ?? 0)"
      />
    </div>

    <section class="ck-surface t-elevated rounded-md overflow-hidden mb-6">
      <div class="px-5 py-4 border-b border-white/5 flex items-center justify-between">
        <h3 class="text-sm font-semibold text-white flex items-center gap-1.5">
          <app-icon name="line-chart" [size]="16" class="text-cyan-400" />
          Latency & counters
        </h3>
        <span class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">
          {{ metricsList().length }} metrics
        </span>
      </div>

      @if (loading() && metricsList().length === 0) {
        <div class="divide-y divide-white/5">
          @for (_ of [0, 1, 2, 3, 4]; track $index) {
            <div class="px-5 py-3 flex items-center gap-3 animate-pulse">
              <div class="h-3 w-40 bg-white/5 rounded"></div>
              <div class="h-3 w-16 bg-white/5 rounded ml-auto"></div>
            </div>
          }
        </div>
      } @else if (metricsList().length === 0) {
        <app-empty-state
          icon="gauge"
          title="No metrics yet"
          description="Hit some endpoints to start collecting performance data."
        />
      } @else {
        <div class="divide-y divide-white/5">
          <div
            class="px-5 py-2 text-[10px] uppercase tracking-wider text-gray-500 font-semibold grid grid-cols-12 gap-3"
          >
            <div class="col-span-5">Metric</div>
            <div class="col-span-2 text-right">Count</div>
            <div class="col-span-2 text-right">Avg (ms)</div>
            <div class="col-span-2 text-right">Max (ms)</div>
            <div class="col-span-1 text-right">Kind</div>
          </div>
          @for (m of metricsList(); track m.key) {
            <div
              class="px-5 py-2.5 grid grid-cols-12 gap-3 items-center text-sm hover:bg-white/5 transition"
            >
              <div class="col-span-5 truncate font-mono text-xs text-gray-200">
                {{ m.key }}
              </div>
              <div class="col-span-2 text-right text-gray-300 tabular-nums">{{ m.count }}</div>
              <div class="col-span-2 text-right text-gray-300 tabular-nums">
                {{ m.avg_ms != null ? m.avg_ms.toFixed(1) : '—' }}
              </div>
              <div class="col-span-2 text-right text-gray-300 tabular-nums">
                {{ m.max_ms != null ? m.max_ms.toFixed(0) : '—' }}
              </div>
              <div class="col-span-1 text-right">
                <span
                  class="text-[9px] uppercase tracking-wider font-semibold px-1.5 py-0.5 rounded"
                  [class.bg-cyan-500\\/10]="m.kind === 'latency'"
                  [class.text-cyan-300]="m.kind === 'latency'"
                  [class.bg-red-500\\/10]="m.kind === 'error'"
                  [class.text-red-300]="m.kind === 'error'"
                  [class.bg-white\\/5]="m.kind === 'count'"
                  [class.text-gray-300]="m.kind === 'count'"
                >
                  {{ m.kind }}
                </span>
              </div>
            </div>
          }
        </div>
      }
    </section>

    <section class="ck-surface t-elevated rounded-md p-5">
      <h3 class="text-sm font-semibold text-white flex items-center gap-1.5 mb-3">
        <app-icon name="database" [size]="16" class="text-cyan-400" />
        Cache
      </h3>
      <div class="space-y-3">
        <div>
          <div class="flex items-center justify-between text-xs text-gray-400 mb-1">
            <span>Used</span>
            <span class="font-mono">{{ cache()?.size ?? 0 }} / {{ cache()?.max_size ?? 0 }}</span>
          </div>
          <div class="h-2 rounded-full bg-white/5 overflow-hidden">
            <div
              class="h-full bg-cyan-400 transition-all duration-300"
              [style.width.%]="cache()?.usage_percent ?? 0"
            ></div>
          </div>
        </div>
      </div>
    </section>
    </ck-page-frame>
  `,
})
export class PerformanceDashboardComponent implements OnInit, OnDestroy {
  private readonly api = inject(ApiService);

  summary = signal<MetricSummary | null>(null);
  cache = signal<CacheStats | null>(null);
  metrics = signal<Record<string, MetricDetail>>({});
  loading = signal(false);
  autoRefresh = signal(false);
  private timer: number | null = null;
  private readonly MAX_SERIES = 30;

  private readonly _requestsSeries = signal<number[]>([]);
  private readonly _errorsSeries = signal<number[]>([]);
  private readonly _errorRateSeries = signal<number[]>([]);
  private readonly _cacheSeries = signal<number[]>([]);

  readonly requestsSeries = this._requestsSeries.asReadonly();
  readonly errorsSeries = this._errorsSeries.asReadonly();
  readonly errorRateSeries = this._errorRateSeries.asReadonly();
  readonly cacheSeries = this._cacheSeries.asReadonly();

  seriesTrend(series: readonly number[]): 'up' | 'down' | 'flat' | null {
    if (series.length < 2) return null;
    const last = series[series.length - 1];
    const prev = series[series.length - 2];
    if (last > prev) return 'up';
    if (last < prev) return 'down';
    return 'flat';
  }

  seriesDelta(series: readonly number[]): string {
    if (series.length < 2) return '';
    const last = series[series.length - 1];
    const prev = series[series.length - 2];
    const diff = last - prev;
    if (diff === 0) return '';
    const sign = diff > 0 ? '+' : '';
    return sign + diff.toFixed(diff % 1 === 0 ? 0 : 1);
  }

  readonly metricsList = computed(() =>
    Object.entries(this.metrics()).map(([key, value]) => ({
      key,
      count: value.count ?? 0,
      avg_ms: value.avg_ms,
      min_ms: value.min_ms,
      max_ms: value.max_ms,
      kind: this.kindFor(key),
    })),
  );

  readonly errorRateDisplay = computed(() => {
    const s = this.summary();
    if (!s) return '0';
    return (s.error_rate_percent ?? 0).toFixed(1);
  });

  readonly errorRateTrend = computed<'up' | 'down' | null>(() => {
    const s = this.summary();
    if (!s || !s.error_rate_percent) return null;
    if (s.error_rate_percent > 5) return 'up';
    return null;
  });

  readonly cacheUsageDisplay = computed(() => {
    const c = this.cache();
    if (!c) return '0';
    return (c.usage_percent ?? 0).toFixed(0);
  });

  ngOnInit(): void {
    this.refresh();
  }

  ngOnDestroy(): void {
    this.stopAuto();
  }

  refresh(): void {
    this.loading.set(true);
    this.api.get<MetricsResponse>('/metrics').subscribe({
      next: (res) => {
        this.metrics.set(res?.metrics ?? {});
        const summary = res?.summary ?? null;
        this.summary.set(summary);
        if (summary) {
          this.pushSeries(this._requestsSeries, summary.total_requests ?? 0);
          this.pushSeries(this._errorsSeries, summary.total_errors ?? 0);
          this.pushSeries(this._errorRateSeries, summary.error_rate_percent ?? 0);
        }
        this.loading.set(false);
      },
      error: () => this.loading.set(false),
    });
    this.api.get<CacheStats>('/metrics/cache').subscribe({
      next: (res) => {
        this.cache.set(res);
        if (res) this.pushSeries(this._cacheSeries, res.usage_percent ?? 0);
      },
      error: () => this.cache.set(null),
    });
  }

  private pushSeries(sig: { update: (fn: (v: number[]) => number[]) => void }, value: number): void {
    sig.update((arr) => {
      const next = [...arr, value];
      return next.length > this.MAX_SERIES ? next.slice(next.length - this.MAX_SERIES) : next;
    });
  }

  toggleAuto(): void {
    this.autoRefresh.update((v) => !v);
    if (this.autoRefresh()) {
      this.timer = window.setInterval(() => this.refresh(), 5000);
    } else {
      this.stopAuto();
    }
  }

  private stopAuto(): void {
    if (this.timer != null) {
      window.clearInterval(this.timer);
      this.timer = null;
    }
  }

  private kindFor(key: string): 'latency' | 'error' | 'count' {
    if (key.includes('latency') || key.endsWith('_ms')) return 'latency';
    if (key.startsWith('errors:') || key.includes('error')) return 'error';
    return 'count';
  }
}

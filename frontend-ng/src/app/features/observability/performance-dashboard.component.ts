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
import { SectionHeaderComponent } from '@app/shared/ui/section-header.component';
import { StatTileComponent } from '@app/shared/ui/stat-tile.component';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';

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
  imports: [IconComponent, SectionHeaderComponent, StatTileComponent, EmptyStateComponent],
  template: `
    <app-section-header
      breadcrumb="Measure"
      title="Performance"
      icon="gauge"
      subtitle="Request latency, error rate and cache efficiency."
    >
      <label class="flex items-center gap-2 text-xs text-gray-400 cursor-pointer">
        <input type="checkbox" [checked]="autoRefresh()" (change)="toggleAuto()" class="accent-brand-500" />
        Auto-refresh
      </label>
      <button
        type="button"
        class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-white/5 text-gray-200 hover:bg-white/10 ring-1 ring-white/10 transition"
        (click)="refresh()"
        [disabled]="loading()"
      >
        <app-icon name="refresh-cw" [size]="14" [class.animate-spin]="loading()" />
        Refresh
      </button>
    </app-section-header>

    <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
      <app-stat-tile
        label="Total requests"
        [value]="summary()?.total_requests ?? 0"
        icon="activity"
      />
      <app-stat-tile
        label="Total errors"
        [value]="summary()?.total_errors ?? 0"
        icon="alert-triangle"
        [trend]="(summary()?.total_errors ?? 0) > 0 ? 'up' : null"
      />
      <app-stat-tile
        label="Error rate"
        [value]="errorRateDisplay()"
        unit="%"
        icon="alert-circle"
        [trend]="errorRateTrend()"
      />
      <app-stat-tile
        label="Cache usage"
        [value]="cacheUsageDisplay()"
        unit="%"
        icon="database"
        [hint]="(cache()?.size ?? 0) + ' / ' + (cache()?.max_size ?? 0)"
      />
    </div>

    <section class="t-card t-elevated rounded-md overflow-hidden mb-6">
      <div class="px-5 py-4 border-b border-white/5 flex items-center justify-between">
        <h3 class="text-sm font-semibold text-white flex items-center gap-1.5">
          <app-icon name="line-chart" [size]="16" class="text-brand-400" />
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
                  [class.bg-brand-500\\/10]="m.kind === 'latency'"
                  [class.text-brand-300]="m.kind === 'latency'"
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

    <section class="t-card t-elevated rounded-md p-5">
      <h3 class="text-sm font-semibold text-white flex items-center gap-1.5 mb-3">
        <app-icon name="database" [size]="16" class="text-brand-400" />
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
              class="h-full bg-gradient-to-r from-brand-400 to-violet-500 transition-all duration-300"
              [style.width.%]="cache()?.usage_percent ?? 0"
            ></div>
          </div>
        </div>
      </div>
    </section>
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
        this.summary.set(res?.summary ?? null);
        this.loading.set(false);
      },
      error: () => this.loading.set(false),
    });
    this.api.get<CacheStats>('/metrics/cache').subscribe({
      next: (res) => this.cache.set(res),
      error: () => this.cache.set(null),
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

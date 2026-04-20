import {
  ChangeDetectionStrategy,
  Component,
  NgZone,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { BaseChartDirective } from 'ng2-charts';
import type { ChartConfiguration, ChartData } from 'chart.js';
import { ToastrService } from 'ngx-toastr';
import { ApiService } from '@app/core/api.service';
import { SseChunk, SseService } from '@app/core/sse.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import { SectionHeaderComponent } from '@app/shared/ui/section-header.component';
import { StatTileComponent } from '@app/shared/ui/stat-tile.component';
import { DrawerComponent } from '@app/shared/ui/drawer.component';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import { ConfirmDialogComponent } from '@app/shared/ui/confirm-dialog.component';

interface Feed {
  id: string;
  name: string;
  url: string;
  category?: string;
  active?: boolean;
  article_count?: number;
  last_fetched?: string | null;
}

interface Target {
  id: string;
  name: string;
  description?: string;
  keywords?: string[];
  relevance_threshold?: number;
}

interface SafetyFilterItem {
  id: string;
  name: string;
  prompt_template: string;
  severity: string;
}

interface Article {
  id?: string;
  title: string;
  url?: string;
  summary?: string;
  published_at?: string;
  relevance_score?: number;
  sentiment?: 'positive' | 'negative' | 'neutral' | 'mixed';
  risk_level?: 'low' | 'medium' | 'high' | 'critical';
  safety_flag?: string | null;
  entities?: string[];
}

interface Dashboard {
  kpis: { total_articles: number; analyzed: number; active_feeds: number; high_risk: number };
  sentiment: { positive: number; negative: number; neutral: number; mixed: number };
  risk: { low: number; medium: number; high: number; critical: number };
  top_entities: { name: string; count: number }[];
  articles: Article[];
}

interface BatchProgress {
  type: string;
  batch_id?: string;
  progress?: number;
  message?: string;
  source?: string;
  stored?: number;
  analyzed?: number;
}

@Component({
  selector: 'app-news-lab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    BaseChartDirective,
    IconComponent,
    SectionHeaderComponent,
    StatTileComponent,
    DrawerComponent,
    EmptyStateComponent,
    ConfirmDialogComponent,
  ],
  template: `
    <app-section-header
      breadcrumb="Measure"
      title="News Lab"
      icon="newspaper"
      subtitle="Continuous market intelligence tuned to your semantic targets."
      pill="Live"
    >
      <span
        class="text-[10px] uppercase tracking-wider font-semibold px-2 py-1 rounded-full ring-1"
        [class.bg-emerald-500\\/10]="scheduler()?.running"
        [class.text-emerald-300]="scheduler()?.running"
        [class.ring-emerald-500\\/30]="scheduler()?.running"
        [class.bg-gray-500\\/10]="!scheduler()?.running"
        [class.text-gray-400]="!scheduler()?.running"
        [class.ring-white\\/10]="!scheduler()?.running"
      >
        Scheduler
        {{ scheduler()?.running ? 'ON · ' + schedulerInterval() : 'OFF' }}
      </span>
      <button
        type="button"
        class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-white/5 text-gray-200 hover:bg-white/10 ring-1 ring-white/10 transition"
        (click)="refreshAll()"
        [disabled]="loadingDashboard()"
      >
        <app-icon name="refresh-cw" [size]="14" [class.animate-spin]="loadingDashboard()" />
        Refresh
      </button>
      <button
        type="button"
        class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-brand-500 hover:bg-brand-600 text-white transition disabled:opacity-50"
        (click)="runBatch()"
        [disabled]="running()"
      >
        <app-icon [name]="running() ? 'loader-2' : 'play'" [size]="14" [class.animate-spin]="running()" />
        {{ running() ? 'Running…' : 'Run analysis' }}
      </button>
      <button
        type="button"
        (click)="drawerOpen.set(true)"
        class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-white/5 text-gray-200 hover:bg-white/10 ring-1 ring-white/10 transition"
      >
        <app-icon name="settings-2" [size]="14" /> Configure
      </button>
    </app-section-header>

    <!-- Batch progress bar -->
    @if (running() || batchMessage()) {
      <div class="t-card t-elevated rounded-md p-3 mb-4 flex items-center gap-3">
        <app-icon
          [name]="running() ? 'loader-2' : 'check-circle-2'"
          [size]="16"
          [class.animate-spin]="running()"
          [class.text-brand-400]="running()"
          [class.text-emerald-400]="!running()"
        />
        <div class="flex-1 min-w-0">
          <div class="text-xs text-white truncate">{{ batchMessage() || 'Starting…' }}</div>
          <div class="h-1.5 rounded-full bg-white/5 overflow-hidden mt-1.5">
            <div
              class="h-full bg-gradient-to-r from-brand-400 to-violet-500 transition-all duration-300"
              [style.width.%]="batchProgress()"
            ></div>
          </div>
        </div>
        <span class="text-[11px] font-mono text-gray-400">{{ batchProgress() }}%</span>
      </div>
    }

    <!-- KPIs -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
      <app-stat-tile
        label="Active feeds"
        [value]="dashboard()?.kpis?.active_feeds ?? 0"
        icon="rss"
      />
      <app-stat-tile
        label="Articles ingested"
        [value]="dashboard()?.kpis?.total_articles ?? 0"
        icon="newspaper"
      />
      <app-stat-tile
        label="Analyzed"
        [value]="dashboard()?.kpis?.analyzed ?? 0"
        icon="brain"
        [hint]="analyzedRatio() + '%'"
      />
      <app-stat-tile
        label="High-risk"
        [value]="dashboard()?.kpis?.high_risk ?? 0"
        icon="alert-triangle"
        [trend]="highRiskTrend()"
      />
    </div>

    <!-- Charts -->
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
      <section class="t-card t-elevated rounded-md p-5">
        <div class="flex items-center justify-between mb-3">
          <h3 class="text-sm font-semibold text-white flex items-center gap-1.5">
            <app-icon name="pie-chart" [size]="16" class="text-brand-400" /> Sentiment mix
          </h3>
          <span class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">
            Last 30 articles
          </span>
        </div>
        <div class="h-72">
          @if (chartsReady() && hasSentimentData()) {
            <canvas
              baseChart
              [data]="sentimentData()"
              [options]="doughnutOptions"
              type="doughnut"
            ></canvas>
          } @else if (chartsReady()) {
            <div class="h-full w-full flex flex-col items-center justify-center text-center">
              <app-icon name="pie-chart" [size]="28" class="text-gray-700 mb-2" />
              <div class="text-sm text-gray-400">No sentiment data yet.</div>
              <p class="text-xs text-gray-500 mt-1 max-w-xs">
                Trigger a run or wait for the scheduler.
              </p>
            </div>
          } @else {
            <div class="h-full w-full rounded bg-white/5 animate-pulse"></div>
          }
        </div>
      </section>

      <section class="t-card t-elevated rounded-md p-5">
        <div class="flex items-center justify-between mb-3">
          <h3 class="text-sm font-semibold text-white flex items-center gap-1.5">
            <app-icon name="bar-chart-3" [size]="16" class="text-brand-400" /> Top entities
          </h3>
          <span class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">
            {{ dashboard()?.top_entities?.length ?? 0 }} mentions
          </span>
        </div>
        <div class="h-72">
          @if (chartsReady() && (dashboard()?.top_entities?.length ?? 0) > 0) {
            <canvas
              baseChart
              [data]="entitiesData()"
              [options]="barOptions"
              type="bar"
            ></canvas>
          } @else if (chartsReady()) {
            <div class="h-full w-full flex flex-col items-center justify-center text-center">
              <app-icon name="tags" [size]="28" class="text-gray-700 mb-2" />
              <div class="text-sm text-gray-400">No entities detected yet.</div>
            </div>
          } @else {
            <div class="h-full w-full rounded bg-white/5 animate-pulse"></div>
          }
        </div>
      </section>
    </div>

    <!-- Article feed -->
    <section class="t-card t-elevated rounded-md overflow-hidden">
      <div class="px-5 py-4 border-b border-white/5 flex items-center justify-between">
        <h3 class="text-sm font-semibold text-white flex items-center gap-1.5">
          <app-icon name="newspaper" [size]="16" class="text-brand-400" /> Live feed
        </h3>
        <span class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">
          {{ articles().length }} articles
        </span>
      </div>
      @if (articles().length === 0) {
        <div class="px-5 py-10">
          <app-empty-state
            icon="newspaper"
            title="No articles yet"
            description="Add a feed in the configuration drawer then run an analysis."
          />
        </div>
      } @else {
        <ul class="divide-y divide-white/5">
          @for (a of articles(); track a.id ?? a.title) {
            <li class="px-5 py-3 flex items-start gap-3 text-sm group hover:bg-white/5 transition">
              <div
                class="w-2 h-2 rounded-full mt-1.5 shrink-0"
                [class.bg-emerald-400]="a.sentiment === 'positive'"
                [class.bg-gray-400]="!a.sentiment || a.sentiment === 'neutral'"
                [class.bg-amber-400]="a.sentiment === 'mixed'"
                [class.bg-red-400]="a.sentiment === 'negative'"
                [title]="a.sentiment || 'neutral'"
              ></div>
              <div class="flex-1 min-w-0">
                <div class="text-white line-clamp-2">{{ a.title }}</div>
                @if (a.summary) {
                  <div class="text-[11px] text-gray-400 line-clamp-2 mt-0.5">{{ a.summary }}</div>
                }
                <div class="text-[11px] text-gray-500 mt-1 flex items-center gap-2 flex-wrap">
                  @if (a.published_at) {
                    <span>{{ formatDate(a.published_at) }}</span>
                    <span class="text-gray-700">·</span>
                  }
                  @if (isNum(a.relevance_score)) {
                    <span class="font-mono"
                      >rel {{ (a.relevance_score! * 100).toFixed(0) }}%</span
                    >
                  }
                  @if (a.risk_level && a.risk_level !== 'low') {
                    <span
                      class="px-1.5 py-0.5 rounded uppercase tracking-wider text-[9px] font-semibold"
                      [class.bg-amber-500\\/10]="a.risk_level === 'medium'"
                      [class.text-amber-300]="a.risk_level === 'medium'"
                      [class.bg-red-500\\/10]="a.risk_level === 'high' || a.risk_level === 'critical'"
                      [class.text-red-300]="a.risk_level === 'high' || a.risk_level === 'critical'"
                    >
                      {{ a.risk_level }} risk
                    </span>
                  }
                  @for (t of (a.entities ?? []).slice(0, 4); track t) {
                    <span class="px-1.5 py-0.5 rounded bg-white/5 text-gray-300">{{ t }}</span>
                  }
                </div>
              </div>
              @if (a.url) {
                <a
                  [href]="a.url"
                  target="_blank"
                  rel="noreferrer"
                  class="shrink-0 p-1.5 rounded hover:bg-white/5 text-gray-500 hover:text-brand-400 transition mt-0.5"
                  title="Open source"
                >
                  <app-icon name="external-link" [size]="14" />
                </a>
              }
            </li>
          }
        </ul>
      }
    </section>

    <!-- Config drawer -->
    <app-drawer
      [open]="drawerOpen()"
      title="News Lab config"
      subtitle="Feeds, targets, filters & scheduler"
      icon="settings-2"
      (close)="drawerOpen.set(false)"
    >
      <div class="space-y-6">
        <!-- Scheduler -->
        <section>
          <h4 class="text-xs uppercase tracking-wider font-semibold text-gray-400 mb-2">
            Scheduler
          </h4>
          <div class="flex items-center justify-between px-3 py-2.5 rounded bg-black/20 ring-1 ring-white/5 text-sm">
            <div class="flex items-center gap-2">
              <span
                class="w-2 h-2 rounded-full"
                [class.bg-emerald-400]="scheduler()?.running"
                [class.bg-gray-500]="!scheduler()?.running"
              ></span>
              <span class="text-gray-200">{{
                scheduler()?.running ? 'Running · auto batch' : 'Paused'
              }}</span>
            </div>
            <span class="text-xs text-gray-500 font-mono">
              every {{ schedulerInterval() }}
            </span>
          </div>
        </section>

        <!-- Feeds -->
        <section>
          <div class="flex items-center justify-between mb-2">
            <h4 class="text-xs uppercase tracking-wider font-semibold text-gray-400">
              Feed sources ({{ feeds().length }})
            </h4>
          </div>

          <form
            class="grid grid-cols-6 gap-1.5 mb-2"
            (ngSubmit)="addFeed()"
          >
            <input
              [(ngModel)]="feedDraft.name"
              name="fname"
              placeholder="Name"
              class="col-span-2 bg-white/5 ring-1 ring-white/10 rounded px-2 py-1.5 text-sm text-white placeholder-gray-500 focus:outline-none focus:ring-brand-400"
              required
            />
            <input
              [(ngModel)]="feedDraft.url"
              name="furl"
              type="url"
              placeholder="https://example.com/feed.xml"
              class="col-span-3 bg-white/5 ring-1 ring-white/10 rounded px-2 py-1.5 text-sm text-white placeholder-gray-500 focus:outline-none focus:ring-brand-400"
              required
            />
            <button
              type="submit"
              class="bg-brand-500 hover:bg-brand-600 rounded text-white text-sm font-medium flex items-center justify-center gap-1 disabled:opacity-50"
              [disabled]="!feedDraft.name.trim() || !feedDraft.url.trim() || addingFeed()"
            >
              <app-icon
                [name]="addingFeed() ? 'loader-2' : 'plus'"
                [size]="13"
                [class.animate-spin]="addingFeed()"
              />
              Add
            </button>
          </form>

          @if (feeds().length === 0) {
            <app-empty-state icon="rss" title="No feeds" description="Add an RSS URL above." />
          } @else {
            <ul class="space-y-1.5">
              @for (f of feeds(); track f.id) {
                <li
                  class="flex items-center justify-between gap-2 text-sm text-gray-200 px-3 py-2 rounded bg-black/20 border border-white/5"
                >
                  <div class="flex-1 min-w-0">
                    <div class="truncate font-medium">{{ f.name }}</div>
                    <div class="text-[11px] text-gray-500 truncate font-mono">{{ f.url }}</div>
                  </div>
                  <span class="text-xs text-gray-500 shrink-0"
                    >{{ f.article_count ?? 0 }}</span
                  >
                  <button
                    type="button"
                    class="p-1 rounded hover:bg-red-500/10 text-gray-400 hover:text-red-400 transition shrink-0"
                    title="Delete"
                    (click)="requestDeleteFeed(f)"
                  >
                    <app-icon name="trash-2" [size]="13" />
                  </button>
                </li>
              }
            </ul>
          }
        </section>

        <!-- Targets -->
        <section>
          <div class="flex items-center justify-between mb-2">
            <h4 class="text-xs uppercase tracking-wider font-semibold text-gray-400">
              Semantic targets ({{ targets().length }})
            </h4>
          </div>

          <form class="space-y-1.5 mb-2" (ngSubmit)="addTarget()">
            <div class="grid grid-cols-6 gap-1.5">
              <input
                [(ngModel)]="targetDraft.name"
                name="tname"
                placeholder="Target name"
                class="col-span-2 bg-white/5 ring-1 ring-white/10 rounded px-2 py-1.5 text-sm text-white placeholder-gray-500 focus:outline-none focus:ring-brand-400"
                required
              />
              <input
                [(ngModel)]="targetDraft.description"
                name="tdesc"
                placeholder="Description / semantic anchor"
                class="col-span-4 bg-white/5 ring-1 ring-white/10 rounded px-2 py-1.5 text-sm text-white placeholder-gray-500 focus:outline-none focus:ring-brand-400"
                required
              />
            </div>
            <div class="grid grid-cols-6 gap-1.5">
              <input
                [(ngModel)]="targetDraft.keywords"
                name="tkw"
                placeholder="comma,separated,keywords"
                class="col-span-4 bg-white/5 ring-1 ring-white/10 rounded px-2 py-1.5 text-sm text-white placeholder-gray-500 focus:outline-none focus:ring-brand-400"
              />
              <input
                [(ngModel)]="targetDraft.threshold"
                name="tth"
                type="number"
                min="0"
                max="1"
                step="0.05"
                placeholder="0.30"
                class="bg-white/5 ring-1 ring-white/10 rounded px-2 py-1.5 text-sm text-white placeholder-gray-500 focus:outline-none focus:ring-brand-400"
              />
              <button
                type="submit"
                class="bg-brand-500 hover:bg-brand-600 rounded text-white text-sm font-medium flex items-center justify-center gap-1 disabled:opacity-50"
                [disabled]="!targetDraft.name.trim() || !targetDraft.description.trim() || addingTarget()"
              >
                <app-icon
                  [name]="addingTarget() ? 'loader-2' : 'plus'"
                  [size]="13"
                  [class.animate-spin]="addingTarget()"
                />
                Add
              </button>
            </div>
          </form>

          @if (targets().length === 0) {
            <app-empty-state icon="target" title="No targets" description="Describe topics you care about." />
          } @else {
            <ul class="space-y-1.5">
              @for (t of targets(); track t.id) {
                <li
                  class="flex items-start justify-between gap-2 text-sm text-gray-200 px-3 py-2 rounded bg-black/20 border border-white/5"
                >
                  <div class="flex-1 min-w-0">
                    <div class="truncate font-medium">{{ t.name }}</div>
                    @if (t.description) {
                      <div class="text-[11px] text-gray-400 line-clamp-1">{{ t.description }}</div>
                    }
                    <div class="text-[10px] text-gray-500 font-mono mt-0.5">
                      τ {{ t.relevance_threshold ?? 0.3 }} ·
                      {{ (t.keywords ?? []).length }} keywords
                    </div>
                  </div>
                </li>
              }
            </ul>
          }
        </section>

        <!-- Filters -->
        <section>
          <h4 class="text-xs uppercase tracking-wider font-semibold text-gray-400 mb-2">
            Safety filters ({{ filters().length }})
          </h4>
          @if (filters().length === 0) {
            <div class="text-xs text-gray-500 px-3 py-2 rounded bg-black/20 ring-1 ring-white/5">
              Backend defaults will apply. Add custom safety prompts via <code>/intelligence/filters</code>.
            </div>
          } @else {
            <ul class="space-y-1.5">
              @for (f of filters(); track f.id) {
                <li class="text-sm text-gray-200 px-3 py-2 rounded bg-black/20 border border-white/5">
                  <div class="flex items-center justify-between">
                    <span class="font-medium">{{ f.name }}</span>
                    <span
                      class="text-[10px] uppercase tracking-wider font-semibold px-1.5 py-0.5 rounded"
                      [class.bg-red-500\\/10]="f.severity === 'block'"
                      [class.text-red-300]="f.severity === 'block'"
                      [class.bg-amber-500\\/10]="f.severity === 'warn'"
                      [class.text-amber-300]="f.severity === 'warn'"
                    >
                      {{ f.severity }}
                    </span>
                  </div>
                </li>
              }
            </ul>
          }
        </section>
      </div>
    </app-drawer>

    <app-confirm-dialog
      [open]="deleteTarget() !== null"
      [title]="deleteTarget()?.name ?? ''"
      description="This feed and its articles will be removed from this workspace."
      confirmLabel="Delete"
      tone="danger"
      (confirm)="confirmDeleteFeed()"
      (cancel)="deleteTarget.set(null)"
    />
  `,
})
export class NewsLabComponent implements OnInit {
  private readonly api = inject(ApiService);
  private readonly sse = inject(SseService);
  private readonly zone = inject(NgZone);
  private readonly toast = inject(ToastrService);

  feeds = signal<Feed[]>([]);
  targets = signal<Target[]>([]);
  filters = signal<SafetyFilterItem[]>([]);
  dashboard = signal<Dashboard | null>(null);
  articles = signal<Article[]>([]);
  scheduler = signal<{ running: boolean; interval_seconds: number } | null>(null);

  drawerOpen = signal(false);
  chartsReady = signal(false);
  loadingDashboard = signal(false);
  running = signal(false);
  addingFeed = signal(false);
  addingTarget = signal(false);
  batchProgress = signal(0);
  batchMessage = signal<string>('');

  feedDraft = { name: '', url: '', category: 'general' };
  targetDraft = { name: '', description: '', keywords: '', threshold: 0.3 };

  deleteTarget = signal<Feed | null>(null);

  readonly schedulerInterval = computed(() => {
    const s = this.scheduler()?.interval_seconds ?? 0;
    if (!s) return '—';
    if (s % 3600 === 0) return `${s / 3600}h`;
    if (s % 60 === 0) return `${s / 60}m`;
    return `${s}s`;
  });

  readonly analyzedRatio = computed(() => {
    const k = this.dashboard()?.kpis;
    if (!k || !k.total_articles) return 0;
    return Math.round((k.analyzed / k.total_articles) * 100);
  });

  readonly highRiskTrend = computed<'up' | 'down' | null>(() => {
    const hr = this.dashboard()?.kpis?.high_risk ?? 0;
    return hr > 0 ? 'up' : null;
  });

  readonly hasSentimentData = computed(() => {
    const s = this.dashboard()?.sentiment;
    if (!s) return false;
    return s.positive + s.negative + s.neutral + s.mixed > 0;
  });

  readonly sentimentData = computed<ChartData<'doughnut'>>(() => {
    const s = this.dashboard()?.sentiment ?? { positive: 0, negative: 0, neutral: 0, mixed: 0 };
    return {
      labels: ['Positive', 'Neutral', 'Mixed', 'Negative'],
      datasets: [
        {
          data: [s.positive, s.neutral, s.mixed, s.negative],
          backgroundColor: ['#10b981', '#64748b', '#f59e0b', '#ef4444'],
          borderColor: 'rgba(15,23,42,0.6)',
          borderWidth: 2,
        },
      ],
    };
  });

  readonly entitiesData = computed<ChartData<'bar'>>(() => {
    const e = this.dashboard()?.top_entities ?? [];
    const top = e.slice(0, 8);
    return {
      labels: top.map((x) => x.name),
      datasets: [
        {
          label: 'Mentions',
          data: top.map((x) => x.count),
          backgroundColor: '#00bcd4',
          borderRadius: 6,
        },
      ],
    };
  });

  readonly doughnutOptions: ChartConfiguration<'doughnut'>['options'] = {
    responsive: true,
    maintainAspectRatio: false,
    cutout: '62%',
    plugins: { legend: { position: 'bottom', labels: { color: '#cbd5e1' } } },
  };

  readonly barOptions: ChartConfiguration<'bar'>['options'] = {
    responsive: true,
    maintainAspectRatio: false,
    indexAxis: 'y',
    plugins: { legend: { display: false } },
    scales: {
      x: { grid: { color: 'rgba(255,255,255,0.06)' }, ticks: { color: '#94a3b8' } },
      y: { grid: { display: false }, ticks: { color: '#94a3b8' } },
    },
  };

  ngOnInit(): void {
    this.refreshAll();
    this.zone.runOutsideAngular(() => {
      const schedule = (window as any).requestIdleCallback ?? window.setTimeout;
      schedule(() => {
        this.zone.run(() => this.chartsReady.set(true));
      }, { timeout: 1500 } as any);
    });
  }

  refreshAll(): void {
    this.loadingDashboard.set(true);
    this.api.get<Dashboard>('/intelligence/dashboard').subscribe({
      next: (d) => {
        this.dashboard.set(d);
        this.articles.set(d?.articles ?? []);
        this.loadingDashboard.set(false);
      },
      error: () => {
        this.dashboard.set(null);
        this.loadingDashboard.set(false);
      },
    });
    this.api.get<{ feeds: Feed[] }>('/intelligence/feeds').subscribe({
      next: (r) => this.feeds.set(r?.feeds ?? []),
      error: () => {},
    });
    this.api.get<{ targets: Target[] }>('/intelligence/targets').subscribe({
      next: (r) => this.targets.set(r?.targets ?? []),
      error: () => {},
    });
    this.api.get<{ filters: SafetyFilterItem[] }>('/intelligence/filters').subscribe({
      next: (r) => this.filters.set(r?.filters ?? []),
      error: () => {},
    });
    this.api.get<{ running: boolean; interval_seconds: number }>('/intelligence/scheduler').subscribe({
      next: (r) => this.scheduler.set(r),
      error: () => this.scheduler.set(null),
    });
  }

  addFeed(): void {
    const { name, url } = this.feedDraft;
    if (!name.trim() || !url.trim()) return;
    this.addingFeed.set(true);
    this.api
      .post<{ id: string }>('/intelligence/feeds', {
        name: name.trim(),
        url: url.trim(),
        category: this.feedDraft.category || 'general',
      })
      .subscribe({
        next: () => {
          this.feedDraft = { name: '', url: '', category: 'general' };
          this.toast.success('Feed added', 'News Lab');
          this.addingFeed.set(false);
          this.api.get<{ feeds: Feed[] }>('/intelligence/feeds').subscribe({
            next: (r) => this.feeds.set(r?.feeds ?? []),
          });
        },
        error: (err) => {
          this.toast.error(err?.error?.detail ?? 'Failed to add feed', 'News Lab');
          this.addingFeed.set(false);
        },
      });
  }

  addTarget(): void {
    const { name, description, keywords, threshold } = this.targetDraft;
    if (!name.trim() || !description.trim()) return;
    this.addingTarget.set(true);
    const kwList = (keywords || '')
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);
    this.api
      .post<{ id: string }>('/intelligence/targets', {
        name: name.trim(),
        description: description.trim(),
        keywords: kwList,
        relevance_threshold: Number(threshold) || 0.3,
      })
      .subscribe({
        next: () => {
          this.targetDraft = { name: '', description: '', keywords: '', threshold: 0.3 };
          this.toast.success('Target added', 'News Lab');
          this.addingTarget.set(false);
          this.api.get<{ targets: Target[] }>('/intelligence/targets').subscribe({
            next: (r) => this.targets.set(r?.targets ?? []),
          });
        },
        error: (err) => {
          this.toast.error(err?.error?.detail ?? 'Failed to add target', 'News Lab');
          this.addingTarget.set(false);
        },
      });
  }

  requestDeleteFeed(f: Feed): void {
    this.deleteTarget.set(f);
  }

  confirmDeleteFeed(): void {
    const f = this.deleteTarget();
    if (!f) return;
    this.api.delete(`/intelligence/feeds/${f.id}`).subscribe({
      next: () => {
        this.toast.success('Feed removed', 'News Lab');
        this.feeds.update((list) => list.filter((x) => x.id !== f.id));
        this.deleteTarget.set(null);
      },
      error: (err) => {
        this.toast.error(err?.error?.detail ?? 'Failed to delete feed', 'News Lab');
        this.deleteTarget.set(null);
      },
    });
  }

  runBatch(): void {
    if (this.running()) return;
    this.running.set(true);
    this.batchProgress.set(0);
    this.batchMessage.set('Starting batch…');
    this.sse.stream('/api/v1/intelligence/analyze', {}).subscribe({
      next: (chunk: SseChunk) => {
        // The backend emits plain JSON events (not chunk_type-shaped), so they
        // come through either as `content` (bare string) or as `data` when
        // the SSE service successfully parses them. Reparse if needed.
        const evt = this.extractEvent(chunk);
        if (!evt) {
          if (chunk.type === 'done') this.finishBatch();
          return;
        }
        if (typeof evt.progress === 'number') this.batchProgress.set(Math.min(100, evt.progress));
        const label = this.labelFor(evt);
        if (label) this.batchMessage.set(label);
        if (evt.type === 'batch_done' || evt.type === 'batch_error') {
          this.batchProgress.set(100);
          if (evt.type === 'batch_error') {
            this.toast.error(evt.message ?? 'Batch failed', 'News Lab');
          } else {
            this.toast.success(
              `${evt.stored ?? 0} new · ${evt.analyzed ?? 0} analyzed`,
              'Batch complete',
            );
          }
          this.finishBatch();
        }
      },
      error: () => {
        this.toast.error('Stream error', 'News Lab');
        this.finishBatch();
      },
    });
  }

  formatDate(iso: string): string {
    try {
      return new Date(iso).toLocaleString([], { dateStyle: 'short', timeStyle: 'short' });
    } catch {
      return iso;
    }
  }

  isNum(v: unknown): boolean {
    return typeof v === 'number' && !Number.isNaN(v);
  }

  private extractEvent(chunk: SseChunk): BatchProgress | null {
    if (chunk.type === 'done') return null;
    // The generic SSE service wraps JSON into the chunk itself, so after
    // parsing our backend's `{type: "batch_*", ...}`, those fields land
    // directly on `chunk` (unknown to the SseChunk interface).
    const raw = chunk as unknown as Record<string, unknown>;
    if (typeof raw['type'] === 'string') return raw as unknown as BatchProgress;
    // Fallback: text content that we can still parse as JSON.
    if (chunk.chunk_type === 'text' && typeof chunk.content === 'string') {
      try {
        return JSON.parse(chunk.content) as BatchProgress;
      } catch {
        return null;
      }
    }
    return null;
  }

  private labelFor(evt: BatchProgress): string {
    if (evt.type === 'batch_start') return `Batch ${evt.batch_id} · started`;
    if (evt.type === 'batch_fetch') return `Fetching feed · ${evt.source ?? ''}`;
    if (evt.type === 'batch_analyze') return `Analyzing articles…`;
    if (evt.type === 'batch_store') return `Storing results…`;
    if (evt.type === 'batch_done')
      return `Done · ${evt.stored ?? 0} stored · ${evt.analyzed ?? 0} analyzed`;
    if (evt.type === 'batch_error') return `Error: ${evt.message ?? 'unknown'}`;
    return evt.message ?? evt.type ?? '';
  }

  private finishBatch(): void {
    this.running.set(false);
    // Refresh dashboard + feeds article counts after a short delay so the
    // backend has time to commit the final analyze/store transaction.
    setTimeout(() => {
      this.refreshAll();
      setTimeout(() => this.batchMessage.set(''), 4000);
    }, 500);
  }
}

import { ChangeDetectionStrategy, Component, NgZone, OnInit, inject, signal } from '@angular/core';
import { BaseChartDirective } from 'ng2-charts';
import type { ChartConfiguration, ChartData } from 'chart.js';
import { ApiService } from '@app/core/api.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import { SectionHeaderComponent } from '@app/shared/ui/section-header.component';
import { StatTileComponent } from '@app/shared/ui/stat-tile.component';
import { DrawerComponent } from '@app/shared/ui/drawer.component';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';

interface Feed {
  id: string;
  name: string;
  article_count?: number;
  url?: string;
}

interface Target {
  id: string;
  name: string;
  relevance_threshold?: number;
}

interface Article {
  title: string;
  source: string;
  sentiment: 'positive' | 'neutral' | 'negative';
  tags: string[];
  url?: string;
  published_at?: string;
}

@Component({
  selector: 'app-news-lab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    BaseChartDirective,
    IconComponent,
    SectionHeaderComponent,
    StatTileComponent,
    DrawerComponent,
    EmptyStateComponent,
  ],
  template: `
    <app-section-header
      breadcrumb="Measure"
      title="News Lab"
      icon="newspaper"
      subtitle="Continuous market intelligence tuned to your semantic targets."
      pill="POC"
    >
      <button
        type="button"
        (click)="drawerOpen.set(true)"
        class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-brand-500 hover:bg-brand-600 text-white shadow-glow-sm transition"
      >
        <app-icon name="settings-2" [size]="14" /> Configure
      </button>
    </app-section-header>

    <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
      <app-stat-tile label="Sources" [value]="feeds().length" icon="rss" trend="up" delta="+2" />
      <app-stat-tile label="Articles today" value="186" icon="newspaper" trend="up" delta="+22%" />
      <app-stat-tile label="Positive sentiment" value="64" unit="%" icon="trending-up" trend="up" delta="+4pt" />
      <app-stat-tile label="Alerts" value="3" icon="bell" trend="flat" />
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
      <section class="t-card t-elevated rounded-md p-5">
        <div class="flex items-center justify-between mb-3">
          <h3 class="text-sm font-semibold text-white flex items-center gap-1.5">
            <app-icon name="line-chart" [size]="16" class="text-brand-400" /> Sentiment over time
          </h3>
          <span class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">Last 14 days</span>
        </div>
        <div class="h-72">
          @if (chartsReady()) {
            <canvas baseChart [data]="sentimentData" [options]="sentimentOptions" type="line"></canvas>
          } @else {
            <div class="h-full w-full rounded bg-white/5 animate-pulse"></div>
          }
        </div>
      </section>

      <section class="t-card t-elevated rounded-md p-5">
        <div class="flex items-center justify-between mb-3">
          <h3 class="text-sm font-semibold text-white flex items-center gap-1.5">
            <app-icon name="bar-chart-3" [size]="16" class="text-brand-400" /> Entities extracted
          </h3>
          <span class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">Top 8</span>
        </div>
        <div class="h-72">
          @if (chartsReady()) {
            <canvas baseChart [data]="entitiesData" [options]="barOptions" type="bar"></canvas>
          } @else {
            <div class="h-full w-full rounded bg-white/5 animate-pulse"></div>
          }
        </div>
      </section>
    </div>

    <section class="t-card t-elevated rounded-md overflow-hidden">
      <div class="px-5 py-4 border-b border-white/5 flex items-center justify-between">
        <h3 class="text-sm font-semibold text-white flex items-center gap-1.5">
          <app-icon name="newspaper" [size]="16" class="text-brand-400" /> Feed
        </h3>
        <span class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">
          {{ articles.length }} articles
        </span>
      </div>
      <ul class="divide-y divide-white/5">
        @for (a of articles; track a.title) {
          <li class="px-5 py-3 flex items-start gap-3 text-sm group hover:bg-white/5 transition">
            <div
              class="w-2 h-2 rounded-full mt-1.5 shrink-0"
              [class.bg-emerald-400]="a.sentiment === 'positive'"
              [class.bg-gray-400]="a.sentiment === 'neutral'"
              [class.bg-red-400]="a.sentiment === 'negative'"
            ></div>
            <div class="flex-1 min-w-0">
              <div class="text-white truncate">{{ a.title }}</div>
              <div class="text-[11px] text-gray-500 mt-0.5 flex items-center gap-2 flex-wrap">
                <span>{{ a.source }}</span>
                @for (t of a.tags; track t) {
                  <span class="px-1.5 py-0.5 rounded bg-white/5 text-gray-300 font-medium">{{ t }}</span>
                }
              </div>
            </div>
            <app-icon
              name="external-link"
              [size]="14"
              class="text-gray-500 group-hover:text-brand-400 transition mt-1"
            />
          </li>
        }
      </ul>
    </section>

    <app-drawer
      [open]="drawerOpen()"
      title="News Lab config"
      subtitle="Feeds, targets and safety"
      icon="settings-2"
      (close)="drawerOpen.set(false)"
    >
      <div class="space-y-6">
        <section>
          <div class="flex items-center justify-between mb-2">
            <h4 class="text-xs uppercase tracking-wider font-semibold text-gray-400">Feed sources</h4>
            <button class="text-xs text-brand-400 hover:text-brand-300 inline-flex items-center gap-1">
              <app-icon name="plus" [size]="12" /> Add
            </button>
          </div>
          @if (feeds().length === 0) {
            <app-empty-state icon="rss" title="No feeds" description="Configure an RSS or API source." />
          } @else {
            <ul class="space-y-2">
              @for (f of feeds(); track f.id) {
                <li class="flex items-center justify-between text-sm text-gray-200 px-3 py-2 rounded bg-black/20 border border-white/5">
                  <span class="truncate">{{ f.name }}</span>
                  <span class="text-xs text-gray-500">{{ f.article_count ?? 0 }} articles</span>
                </li>
              }
            </ul>
          }
        </section>

        <section>
          <div class="flex items-center justify-between mb-2">
            <h4 class="text-xs uppercase tracking-wider font-semibold text-gray-400">Semantic targets</h4>
            <button class="text-xs text-brand-400 hover:text-brand-300 inline-flex items-center gap-1">
              <app-icon name="plus" [size]="12" /> Add
            </button>
          </div>
          @if (targets().length === 0) {
            <app-empty-state icon="target" title="No targets" description="Describe the topics you care about." />
          } @else {
            <ul class="space-y-2">
              @for (t of targets(); track t.id) {
                <li class="flex items-center justify-between text-sm text-gray-200 px-3 py-2 rounded bg-black/20 border border-white/5">
                  <span class="truncate">{{ t.name }}</span>
                  <span class="text-xs text-gray-500">τ {{ t.relevance_threshold ?? 0.75 }}</span>
                </li>
              }
            </ul>
          }
        </section>

        <section>
          <h4 class="text-xs uppercase tracking-wider font-semibold text-gray-400 mb-2">Safety filters</h4>
          <div class="space-y-2 text-sm text-gray-200">
            <label class="flex items-center gap-2 cursor-pointer">
              <input type="checkbox" checked class="accent-brand-500" /> Filter NSFW content
            </label>
            <label class="flex items-center gap-2 cursor-pointer">
              <input type="checkbox" checked class="accent-brand-500" /> Block known disinformation sources
            </label>
            <label class="flex items-center gap-2 cursor-pointer">
              <input type="checkbox" class="accent-brand-500" /> Deduplicate aggressively
            </label>
          </div>
        </section>
      </div>
    </app-drawer>
  `,
})
export class NewsLabComponent implements OnInit {
  private readonly api = inject(ApiService);
  private readonly zone = inject(NgZone);

  feeds = signal<Feed[]>([]);
  targets = signal<Target[]>([]);
  drawerOpen = signal(false);
  chartsReady = signal<boolean>(false);

  readonly articles: Article[] = [
    {
      title: 'EU AI Act moves into enforcement — compliance deadlines take effect',
      source: 'Reuters',
      sentiment: 'neutral',
      tags: ['regulation', 'ai-act'],
    },
    {
      title: 'Enterprise RAG spend doubled in Q1 driven by finance and legal',
      source: 'The Information',
      sentiment: 'positive',
      tags: ['rag', 'finance'],
    },
    {
      title: 'Major LLM provider reports 14h outage, customers demand SLA credits',
      source: 'TechCrunch',
      sentiment: 'negative',
      tags: ['outage', 'llm'],
    },
    {
      title: 'Open-weights models close the gap with frontier systems on reasoning',
      source: 'arXiv',
      sentiment: 'positive',
      tags: ['research', 'open-source'],
    },
    {
      title: 'Gartner flags rising hallucination risk in customer-facing assistants',
      source: 'Gartner',
      sentiment: 'negative',
      tags: ['risk', 'hallucination'],
    },
  ];

  readonly sentimentData: ChartData<'line'> = {
    labels: ['Apr 2', 'Apr 4', 'Apr 6', 'Apr 8', 'Apr 10', 'Apr 12', 'Apr 14'],
    datasets: [
      {
        label: 'Positive',
        data: [58, 61, 63, 60, 64, 66, 64],
        borderColor: '#10b981',
        backgroundColor: 'rgba(16,185,129,0.15)',
        fill: true,
        tension: 0.35,
        pointRadius: 2,
        borderWidth: 2,
      },
      {
        label: 'Negative',
        data: [18, 20, 17, 19, 16, 14, 15],
        borderColor: '#ef4444',
        backgroundColor: 'rgba(239,68,68,0.1)',
        fill: true,
        tension: 0.35,
        pointRadius: 2,
        borderWidth: 2,
      },
    ],
  };

  readonly sentimentOptions: ChartConfiguration<'line'>['options'] = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: { legend: { labels: { color: '#cbd5e1' } } },
    scales: {
      x: { grid: { color: 'rgba(255,255,255,0.06)' }, ticks: { color: '#94a3b8' } },
      y: { grid: { color: 'rgba(255,255,255,0.06)' }, ticks: { color: '#94a3b8' } },
    },
  };

  readonly entitiesData: ChartData<'bar'> = {
    labels: ['OpenAI', 'Anthropic', 'Google', 'Meta', 'Mistral', 'Nvidia', 'EU AI Act', 'Cohere'],
    datasets: [
      {
        label: 'Mentions',
        data: [142, 108, 96, 82, 58, 118, 74, 42],
        backgroundColor: [
          '#00bcd4',
          '#8b5cf6',
          '#6366f1',
          '#0ea5e9',
          '#f59e0b',
          '#10b981',
          '#ef4444',
          '#ec4899',
        ],
        borderRadius: 6,
      },
    ],
  };

  readonly barOptions: ChartConfiguration<'bar'>['options'] = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: { legend: { display: false } },
    scales: {
      x: { grid: { display: false }, ticks: { color: '#94a3b8' } },
      y: { grid: { color: 'rgba(255,255,255,0.06)' }, ticks: { color: '#94a3b8' } },
    },
  };

  ngOnInit(): void {
    this.api.get<Feed[]>('/intelligence/feeds').subscribe({
      next: (data) => this.feeds.set(data ?? []),
      error: () => {},
    });
    this.api.get<Target[]>('/intelligence/targets').subscribe({
      next: (data) => this.targets.set(data ?? []),
      error: () => {},
    });
    this.zone.runOutsideAngular(() => {
      const schedule = (window as any).requestIdleCallback ?? window.setTimeout;
      schedule(() => {
        this.zone.run(() => this.chartsReady.set(true));
      }, { timeout: 1500 } as any);
    });
  }
}

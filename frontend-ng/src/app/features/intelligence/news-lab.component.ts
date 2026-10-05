import {
  ChangeDetectionStrategy,
  Component,
  Input,
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
import { I18nService } from '@app/core/i18n.service';
import { SseChunk, SseService } from '@app/core/sse.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import { SectionHeaderComponent } from '@app/shared/ui/section-header.component';
import { StatReadoutComponent } from '@app/shared/cockpit';
import { DrawerComponent } from '@app/shared/ui/drawer.component';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import { ConfirmDialogComponent } from '@app/shared/ui/confirm-dialog.component';
import {
  batchErrorMessage,
  knowledgeCollection,
  needsSetup,
  progressLabel,
  schedulerInterval,
  setupSteps,
  type BatchEvent,
  type KnowledgeCollectionRef,
} from './intelligence.vm';

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
  knowledge_collection?: Partial<KnowledgeCollectionRef> | null;
  synthesis?: {
    title: string;
    summary: string;
    key_findings: string[];
    recommended_actions: string[];
    entities: string[];
    source_articles: Array<{
      id?: string;
      title?: string;
      url?: string;
      risk_level?: string;
      relevance_score?: number;
    }>;
    knowledge_reference?: {
      recommended_collection?: string;
      status?: string;
      promotion_policy?: string;
    };
  };
}

/**
 * News Lab: the workspace's watch. It reads only this workspace's feeds,
 * targets and filters, and writes into the workspace's own knowledge
 * collection. Nothing is pre-filled: until a feed and a target exist, the
 * page guides the user to add them.
 */
@Component({
  selector: 'app-news-lab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    BaseChartDirective,
    IconComponent,
    SectionHeaderComponent,
    StatReadoutComponent,
    DrawerComponent,
    EmptyStateComponent,
    ConfirmDialogComponent,
  ],
  template: `
    <app-section-header
      [breadcrumb]="i18n.t('intelligence.newsLab.breadcrumb')"
      [title]="i18n.t('intelligence.newsLab.title')"
      icon="newspaper"
      [subtitle]="i18n.t('intelligence.newsLab.subtitle')"
      [pill]="i18n.t('intelligence.newsLab.pill')"
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
        {{
          scheduler()?.running
            ? i18n.t('intelligence.newsLab.scheduler.on', { interval: schedulerInterval() })
            : i18n.t('intelligence.newsLab.scheduler.off')
        }}
      </span>
      <button
        type="button"
        class="ck-btn ck-btn-quiet"
        (click)="refreshAll()"
        [disabled]="loadingDashboard()"
      >
        <app-icon name="refresh-cw" [size]="14" [class.animate-spin]="loadingDashboard()" />
        {{ i18n.t('common.refresh') }}
      </button>
      <button
        type="button"
        class="ck-btn ck-cta"
        (click)="runBatch()"
        [disabled]="running()"
      >
        <app-icon [name]="running() ? 'loader-2' : 'play'" [size]="14" [class.animate-spin]="running()" />
        {{ i18n.t(running() ? 'intelligence.newsLab.run.running' : 'intelligence.newsLab.run.action') }}
      </button>
      <button
        type="button"
        (click)="drawerOpen.set(true)"
        class="ck-btn ck-btn-quiet"
      >
        <app-icon name="settings-2" [size]="14" /> {{ i18n.t('intelligence.newsLab.configure') }}
      </button>
    </app-section-header>

    <!-- First run: nothing is pre-filled, so say what the watch still needs. -->
    @if (showSetup()) {
      <section class="ck-surface t-elevated rounded-md p-5 mb-6" data-testid="news-lab-setup">
        <h3 class="text-base font-semibold text-white">{{ i18n.t('intelligence.newsLab.setup.title') }}</h3>
        <p class="text-sm text-gray-300 mt-1 leading-relaxed">{{ i18n.t('intelligence.newsLab.setup.body') }}</p>
        <ol class="mt-4 space-y-2">
          @for (step of setup(); track step.key) {
            <li class="flex items-center gap-3 text-sm">
              <app-icon
                [name]="step.done ? 'check-circle-2' : 'circle'"
                [size]="16"
                [class.text-emerald-400]="step.done"
                [class.text-gray-500]="!step.done"
              />
              <span class="flex-1 text-gray-200">{{ i18n.t('intelligence.newsLab.setup.' + step.key) }}</span>
              <span class="text-[11px] text-gray-500">
                {{ i18n.t(step.done ? 'intelligence.newsLab.setup.done' : 'intelligence.newsLab.setup.todo') }}
              </span>
            </li>
          }
        </ol>
        <button type="button" class="ck-btn ck-cta mt-4" (click)="drawerOpen.set(true)">
          <app-icon name="settings-2" [size]="14" /> {{ i18n.t('intelligence.newsLab.configure') }}
        </button>
      </section>
    }

    <!-- Batch progress bar -->
    @if (running() || batchMessage()) {
      <div class="ck-surface t-elevated rounded-md p-3 mb-4 flex items-center gap-3">
        <app-icon
          [name]="running() ? 'loader-2' : 'check-circle-2'"
          [size]="16"
          [class.animate-spin]="running()"
          [class.text-cyan-400]="running()"
          [class.text-emerald-400]="!running()"
        />
        <div class="flex-1 min-w-0">
          <div class="text-xs text-white truncate">{{ batchMessage() || i18n.t('intelligence.newsLab.progress.starting') }}</div>
          <div class="h-1.5 rounded-full bg-white/5 overflow-hidden mt-1.5">
            <div
              class="h-full bg-cyan-400 transition-all duration-300"
              [style.width.%]="batchProgress()"
            ></div>
          </div>
        </div>
        <span class="text-[11px] font-mono text-gray-400">{{ batchProgress() }}%</span>
      </div>
    }

    <!-- KPIs -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
      <ck-stat-readout variant="tile"
        [label]="i18n.t('intelligence.newsLab.kpi.feeds')"
        [value]="dashboard()?.kpis?.active_feeds ?? 0"
        icon="rss"
      />
      <ck-stat-readout variant="tile"
        [label]="i18n.t('intelligence.newsLab.kpi.articles')"
        [value]="dashboard()?.kpis?.total_articles ?? 0"
        icon="newspaper"
      />
      <ck-stat-readout variant="tile"
        [label]="i18n.t('intelligence.newsLab.kpi.analyzed')"
        [value]="dashboard()?.kpis?.analyzed ?? 0"
        icon="brain"
        [hint]="analyzedRatio() + '%'"
      />
      <ck-stat-readout variant="tile"
        [label]="i18n.t('intelligence.newsLab.kpi.high_risk')"
        [value]="dashboard()?.kpis?.high_risk ?? 0"
        icon="alert-triangle"
        [trend]="highRiskTrend()"
      />
    </div>

    @if (dashboard()?.synthesis; as synthesis) {
      <section class="ck-surface t-elevated rounded-md p-5 mb-6">
        <div class="flex items-start justify-between gap-4 mb-4">
          <div>
            <div class="text-[10px] uppercase tracking-wider font-semibold text-cyan-300 mb-1">
              {{ i18n.t('intelligence.newsLab.brief.eyebrow') }}
            </div>
            <h3 class="text-base font-semibold text-white">{{ synthesis.title }}</h3>
            <p class="text-sm text-gray-300 mt-1 leading-relaxed">{{ synthesis.summary }}</p>
          </div>
          @if (latestRunId()) {
            <a
              [href]="'/runs/' + latestRunId()"
              class="ck-btn ck-btn--sm ck-btn-quiet shrink-0"
            >
              <app-icon name="git-commit" [size]="12" />
              {{ i18n.t('intelligence.newsLab.run.open', { id: latestRunId()!.slice(0, 8) }) }}
            </a>
          }
        </div>
        <div class="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div class="lg:col-span-2">
            <div class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold mb-2">
              {{ i18n.t('intelligence.newsLab.brief.findings') }}
            </div>
            <ul class="space-y-2">
              @for (finding of synthesis.key_findings || []; track finding) {
                <li class="text-sm text-gray-300 leading-relaxed flex gap-2">
                  <span class="mt-2 w-1.5 h-1.5 rounded-full bg-cyan-400 shrink-0"></span>
                  <span>{{ finding }}</span>
                </li>
              }
            </ul>
          </div>
          <div>
            <div class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold mb-2">
              {{ i18n.t('intelligence.newsLab.brief.collection') }}
            </div>
            @if (collection(); as ref) {
              <div class="text-sm text-white">{{ ref.name }}</div>
              <div class="text-[11px] text-gray-500 font-mono break-all mt-0.5">{{ ref.slug }}</div>
            } @else {
              <div class="text-sm text-gray-500">{{ i18n.t('intelligence.newsLab.brief.no_collection') }}</div>
            }
            <div class="flex flex-wrap gap-1.5 mt-3">
              @for (entity of synthesis.entities || []; track entity) {
                <span class="px-2 py-1 rounded bg-white/5 text-[11px] text-gray-300">{{ entity }}</span>
              }
            </div>
          </div>
        </div>
      </section>
    }

    <!-- Charts -->
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
      <section class="ck-surface t-elevated rounded-md p-5">
        <div class="flex items-center justify-between mb-3">
          <h3 class="text-sm font-semibold text-white flex items-center gap-1.5">
            <app-icon name="pie-chart" [size]="16" class="text-cyan-400" /> {{ i18n.t('intelligence.newsLab.sentiment.title') }}
          </h3>
          <span class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">
            {{ i18n.t('intelligence.newsLab.sentiment.scope') }}
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
            <div class="h-full flex items-center justify-center">
              <app-empty-state
                size="sm"
                icon="pie-chart"
                [title]="i18n.t('intelligence.newsLab.sentiment.empty.title')"
                [description]="i18n.t('intelligence.newsLab.sentiment.empty.body')"
              />
            </div>
          } @else {
            <div class="h-full w-full rounded bg-white/5 animate-pulse"></div>
          }
        </div>
      </section>

      <section class="ck-surface t-elevated rounded-md p-5">
        <div class="flex items-center justify-between mb-3">
          <h3 class="text-sm font-semibold text-white flex items-center gap-1.5">
            <app-icon name="bar-chart-3" [size]="16" class="text-cyan-400" /> {{ i18n.t('intelligence.newsLab.entities.title') }}
          </h3>
          <span class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">
            {{ i18n.t('intelligence.newsLab.entities.count', { count: dashboard()?.top_entities?.length ?? 0 }) }}
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
            <div class="h-full flex items-center justify-center">
              <app-empty-state
                size="sm"
                icon="tags"
                [title]="i18n.t('intelligence.newsLab.entities.empty.title')"
                [description]="i18n.t('intelligence.newsLab.entities.empty.body')"
              />
            </div>
          } @else {
            <div class="h-full w-full rounded bg-white/5 animate-pulse"></div>
          }
        </div>
      </section>
    </div>

    <!-- Article feed -->
    <section class="ck-surface t-elevated rounded-md overflow-hidden">
      <div class="px-5 py-4 border-b border-white/5 flex items-center justify-between">
        <h3 class="text-sm font-semibold text-white flex items-center gap-1.5">
          <app-icon name="newspaper" [size]="16" class="text-cyan-400" /> {{ i18n.t('intelligence.newsLab.feed.title') }}
        </h3>
        <span class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">
          {{ i18n.t('intelligence.newsLab.feed.count', { count: articles().length }) }}
        </span>
      </div>
      @if (articles().length === 0) {
        <div class="px-5 py-10">
          <app-empty-state
            icon="newspaper"
            [title]="i18n.t('intelligence.newsLab.feed.empty.title')"
            [description]="i18n.t('intelligence.newsLab.feed.empty.body')"
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
                [title]="i18n.t('intelligence.newsLab.sentiment.' + (a.sentiment || 'neutral'))"
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
                    <span class="font-mono">{{
                      i18n.t('intelligence.newsLab.article.relevance', { value: (a.relevance_score! * 100).toFixed(0) })
                    }}</span>
                  }
                  @if (a.risk_level && a.risk_level !== 'low') {
                    <span
                      class="px-1.5 py-0.5 rounded uppercase tracking-wider text-[9px] font-semibold"
                      [class.bg-amber-500\\/10]="a.risk_level === 'medium'"
                      [class.text-amber-300]="a.risk_level === 'medium'"
                      [class.bg-red-500\\/10]="a.risk_level === 'high' || a.risk_level === 'critical'"
                      [class.text-red-300]="a.risk_level === 'high' || a.risk_level === 'critical'"
                    >
                      {{ riskLabel(a.risk_level) }}
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
                  class="shrink-0 p-1.5 rounded hover:bg-white/5 text-gray-500 hover:text-cyan-400 transition mt-0.5"
                  [title]="i18n.t('intelligence.newsLab.article.open')"
                  [attr.aria-label]="i18n.t('intelligence.newsLab.article.open')"
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
      [title]="i18n.t('intelligence.newsLab.drawer.title')"
      [subtitle]="i18n.t('intelligence.newsLab.drawer.subtitle')"
      icon="settings-2"
      (close)="drawerOpen.set(false)"
    >
      <div class="space-y-6">
        <!-- Scheduler -->
        <section>
          <h4 class="text-xs uppercase tracking-wider font-semibold text-gray-400 mb-2">
            {{ i18n.t('intelligence.newsLab.scheduler.label') }}
          </h4>
          <div class="flex items-center justify-between px-3 py-2.5 rounded bg-black/20 ring-1 ring-white/5 text-sm">
            <div class="flex items-center gap-2">
              <span
                class="w-2 h-2 rounded-full"
                [class.bg-emerald-400]="scheduler()?.running"
                [class.bg-gray-500]="!scheduler()?.running"
              ></span>
              <span class="text-gray-200">{{
                i18n.t(scheduler()?.running ? 'intelligence.newsLab.scheduler.running' : 'intelligence.newsLab.scheduler.paused')
              }}</span>
            </div>
            <span class="text-xs text-gray-500 font-mono">
              {{ i18n.t('intelligence.newsLab.scheduler.every', { interval: schedulerInterval() }) }}
            </span>
          </div>
        </section>

        <!-- Feeds -->
        <section>
          <div class="flex items-center justify-between mb-2">
            <h4 class="text-xs uppercase tracking-wider font-semibold text-gray-400">
              {{ i18n.t('intelligence.newsLab.feeds.title', { count: feeds().length }) }}
            </h4>
          </div>

          <form
            class="grid grid-cols-6 gap-1.5 mb-2"
            (ngSubmit)="addFeed()"
          >
            <input
              [(ngModel)]="feedDraft.name"
              name="fname"
              [placeholder]="i18n.t('intelligence.newsLab.feeds.name')"
              class="col-span-2 bg-white/5 ring-1 ring-white/10 rounded px-2 py-1.5 text-sm text-white placeholder-gray-500 focus:outline-none focus:ring-cyan-400"
              required
            />
            <input
              [(ngModel)]="feedDraft.url"
              name="furl"
              type="url"
              placeholder="https://example.com/feed.xml"
              class="col-span-3 bg-white/5 ring-1 ring-white/10 rounded px-2 py-1.5 text-sm text-white placeholder-gray-500 focus:outline-none focus:ring-cyan-400"
              required
            />
            <button
              type="submit"
              class="ck-btn ck-btn--sm ck-cta"
              [disabled]="!feedDraft.name.trim() || !feedDraft.url.trim() || addingFeed()"
            >
              <app-icon
                [name]="addingFeed() ? 'loader-2' : 'plus'"
                [size]="13"
                [class.animate-spin]="addingFeed()"
              />
              {{ i18n.t('intelligence.newsLab.add') }}
            </button>
          </form>

          @if (feeds().length === 0) {
            <app-empty-state
              icon="rss"
              [title]="i18n.t('intelligence.newsLab.feeds.empty.title')"
              [description]="i18n.t('intelligence.newsLab.feeds.empty.body')"
            />
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
                    [title]="i18n.t('intelligence.newsLab.feeds.delete')"
                    [attr.aria-label]="i18n.t('intelligence.newsLab.feeds.delete')"
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
              {{ i18n.t('intelligence.newsLab.targets.title', { count: targets().length }) }}
            </h4>
          </div>

          <form class="space-y-1.5 mb-2" (ngSubmit)="addTarget()">
            <div class="grid grid-cols-6 gap-1.5">
              <input
                [(ngModel)]="targetDraft.name"
                name="tname"
                [placeholder]="i18n.t('intelligence.newsLab.targets.name')"
                class="col-span-2 bg-white/5 ring-1 ring-white/10 rounded px-2 py-1.5 text-sm text-white placeholder-gray-500 focus:outline-none focus:ring-cyan-400"
                required
              />
              <input
                [(ngModel)]="targetDraft.description"
                name="tdesc"
                [placeholder]="i18n.t('intelligence.newsLab.targets.description')"
                class="col-span-4 bg-white/5 ring-1 ring-white/10 rounded px-2 py-1.5 text-sm text-white placeholder-gray-500 focus:outline-none focus:ring-cyan-400"
                required
              />
            </div>
            <div class="grid grid-cols-6 gap-1.5">
              <input
                [(ngModel)]="targetDraft.keywords"
                name="tkw"
                [placeholder]="i18n.t('intelligence.newsLab.targets.keywords')"
                class="col-span-4 bg-white/5 ring-1 ring-white/10 rounded px-2 py-1.5 text-sm text-white placeholder-gray-500 focus:outline-none focus:ring-cyan-400"
              />
              <input
                [(ngModel)]="targetDraft.threshold"
                name="tth"
                type="number"
                min="0"
                max="1"
                step="0.05"
                placeholder="0.30"
                class="bg-white/5 ring-1 ring-white/10 rounded px-2 py-1.5 text-sm text-white placeholder-gray-500 focus:outline-none focus:ring-cyan-400"
              />
              <button
                type="submit"
                class="ck-btn ck-btn--sm ck-cta"
                [disabled]="!targetDraft.name.trim() || !targetDraft.description.trim() || addingTarget()"
              >
                <app-icon
                  [name]="addingTarget() ? 'loader-2' : 'plus'"
                  [size]="13"
                  [class.animate-spin]="addingTarget()"
                />
                {{ i18n.t('intelligence.newsLab.add') }}
              </button>
            </div>
          </form>

          @if (targets().length === 0) {
            <app-empty-state
              icon="target"
              [title]="i18n.t('intelligence.newsLab.targets.empty.title')"
              [description]="i18n.t('intelligence.newsLab.targets.empty.body')"
            />
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
                      {{
                        i18n.t('intelligence.newsLab.targets.meta', {
                          threshold: t.relevance_threshold ?? 0.3,
                          count: (t.keywords ?? []).length
                        })
                      }}
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
            {{ i18n.t('intelligence.newsLab.filters.title', { count: filters().length }) }}
          </h4>
          @if (filters().length === 0) {
            <div class="text-xs text-gray-500 px-3 py-2 rounded bg-black/20 ring-1 ring-white/5">
              {{ i18n.t('intelligence.newsLab.filters.empty') }}
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
      [description]="i18n.t('intelligence.newsLab.delete.body')"
      [confirmLabel]="i18n.t('common.delete')"
      tone="danger"
      (confirm)="confirmDeleteFeed()"
      (cancel)="deleteTarget.set(null)"
    />
  `,
})
export class NewsLabComponent implements OnInit {
  @Input() systemId: string | null = null;

  private readonly api = inject(ApiService);
  private readonly sse = inject(SseService);
  private readonly zone = inject(NgZone);
  private readonly toast = inject(ToastrService);
  readonly i18n = inject(I18nService);

  feeds = signal<Feed[]>([]);
  targets = signal<Target[]>([]);
  filters = signal<SafetyFilterItem[]>([]);
  dashboard = signal<Dashboard | null>(null);
  articles = signal<Article[]>([]);
  scheduler = signal<{ running: boolean; interval_seconds: number } | null>(null);

  drawerOpen = signal(false);
  chartsReady = signal(false);
  loadingDashboard = signal(false);
  feedsLoaded = signal(false);
  targetsLoaded = signal(false);
  running = signal(false);
  addingFeed = signal(false);
  addingTarget = signal(false);
  batchProgress = signal(0);
  batchMessage = signal<string>('');
  latestRunId = signal<string | null>(null);

  feedDraft = { name: '', url: '', category: 'general' };
  targetDraft = { name: '', description: '', keywords: '', threshold: 0.3 };

  deleteTarget = signal<Feed | null>(null);

  readonly schedulerInterval = computed(() => schedulerInterval(this.scheduler()?.interval_seconds));

  readonly setup = computed(() => setupSteps(this.feeds().length, this.targets().length));
  readonly showSetup = computed(
    () =>
      this.feedsLoaded() &&
      this.targetsLoaded() &&
      needsSetup(this.feeds().length, this.targets().length),
  );
  readonly collection = computed(() => knowledgeCollection(this.dashboard()));

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
      labels: ['positive', 'neutral', 'mixed', 'negative'].map((key) =>
        this.i18n.t(`intelligence.newsLab.sentiment.${key}`),
      ),
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
          label: this.i18n.t('intelligence.newsLab.entities.series'),
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
    this.loadFeeds();
    this.loadTargets();
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
          this.toast.success(this.i18n.t('intelligence.newsLab.toast.feed_added'), this.toastTitle());
          this.addingFeed.set(false);
          this.loadFeeds();
        },
        error: (err) => {
          this.toast.error(err?.error?.detail ?? this.i18n.t('intelligence.newsLab.toast.feed_failed'), this.toastTitle());
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
          this.toast.success(this.i18n.t('intelligence.newsLab.toast.target_added'), this.toastTitle());
          this.addingTarget.set(false);
          this.loadTargets();
        },
        error: (err) => {
          this.toast.error(err?.error?.detail ?? this.i18n.t('intelligence.newsLab.toast.target_failed'), this.toastTitle());
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
        this.toast.success(this.i18n.t('intelligence.newsLab.toast.feed_removed'), this.toastTitle());
        this.feeds.update((list) => list.filter((x) => x.id !== f.id));
        this.deleteTarget.set(null);
      },
      error: (err) => {
        this.toast.error(err?.error?.detail ?? this.i18n.t('intelligence.newsLab.toast.feed_remove_failed'), this.toastTitle());
        this.deleteTarget.set(null);
      },
    });
  }

  runBatch(): void {
    if (this.running()) return;
    this.running.set(true);
    this.batchProgress.set(0);
    this.batchMessage.set(this.i18n.t('intelligence.newsLab.progress.starting'));
    this.sse.stream('/api/v1/intelligence/analyze', { system_id: this.systemId || undefined }).subscribe({
      next: (chunk: SseChunk) => {
        // The backend emits plain JSON events (not chunk_type-shaped), so they
        // come through either as `content` (bare string) or as `data` when
        // the SSE service successfully parses them. Reparse if needed.
        const evt = this.extractEvent(chunk);
        if (!evt) {
          if (chunk.type === 'done') this.finishBatch();
          return;
        }
        if (evt.run_id) this.latestRunId.set(evt.run_id);
        if (typeof evt.progress === 'number') this.batchProgress.set(Math.min(100, evt.progress));
        const label = progressLabel(evt, this.i18n.t);
        if (label) this.batchMessage.set(label);
        if (evt.type === 'batch_complete' || evt.type === 'batch_done' || evt.type === 'batch_error' || evt.type === 'run_completed') {
          this.batchProgress.set(100);
          if (evt.type === 'batch_error') {
            this.toast.error(batchErrorMessage(evt, this.i18n.t), this.i18n.t('intelligence.newsLab.toast.batch_failed'));
          } else if (evt.type === 'batch_complete' || evt.type === 'batch_done') {
            this.toast.success(
              this.i18n.t('intelligence.newsLab.toast.batch_counts', {
                new: evt.total_articles ?? evt.stored ?? 0,
                analyzed: evt.analyzed ?? 0,
              }),
              this.i18n.t('intelligence.newsLab.toast.batch_done'),
            );
          }
          if (evt.type !== 'batch_complete') this.finishBatch();
        }
      },
      error: () => {
        this.toast.error(this.i18n.t('intelligence.newsLab.toast.stream_error'), this.toastTitle());
        this.finishBatch();
      },
    });
  }

  riskLabel(level: string): string {
    const key = `intelligence.newsLab.risk.${level}`;
    const label = this.i18n.t(key);
    return label === key ? level : label;
  }

  formatDate(iso: string): string {
    try {
      return new Date(iso).toLocaleString(this.i18n.locale(), { dateStyle: 'short', timeStyle: 'short' });
    } catch {
      return iso;
    }
  }

  isNum(v: unknown): boolean {
    return typeof v === 'number' && !Number.isNaN(v);
  }

  private toastTitle(): string {
    return this.i18n.t('intelligence.newsLab.toast.title');
  }

  private loadFeeds(): void {
    this.api.get<{ feeds: Feed[] }>('/intelligence/feeds').subscribe({
      next: (r) => {
        this.feeds.set(r?.feeds ?? []);
        this.feedsLoaded.set(true);
      },
      error: () => {},
    });
  }

  private loadTargets(): void {
    this.api.get<{ targets: Target[] }>('/intelligence/targets').subscribe({
      next: (r) => {
        this.targets.set(r?.targets ?? []);
        this.targetsLoaded.set(true);
      },
      error: () => {},
    });
  }

  private extractEvent(chunk: SseChunk): BatchEvent | null {
    if (chunk.type === 'done') return null;
    // The generic SSE service wraps JSON into the chunk itself, so after
    // parsing our backend's `{type: "batch_*", ...}`, those fields land
    // directly on `chunk` (unknown to the SseChunk interface).
    const raw = chunk as unknown as Record<string, unknown>;
    if (typeof raw['type'] === 'string') return raw as unknown as BatchEvent;
    // Fallback: text content that we can still parse as JSON.
    if (chunk.chunk_type === 'text' && typeof chunk.content === 'string') {
      try {
        return JSON.parse(chunk.content) as BatchEvent;
      } catch {
        return null;
      }
    }
    return null;
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

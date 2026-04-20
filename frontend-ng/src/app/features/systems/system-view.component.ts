import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { NgClass } from '@angular/common';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { forkJoin, of } from 'rxjs';
import { catchError } from 'rxjs/operators';
import { ChatPanelComponent } from '@app/features/chat/chat-panel.component';
import { IconComponent } from '@app/shared/ui/icon.component';
import { SectionHeaderComponent } from '@app/shared/ui/section-header.component';
import { StatTileComponent } from '@app/shared/ui/stat-tile.component';
import { StatusPulseComponent } from '@app/shared/ui/status-pulse.component';
import { ApiService } from '@app/core/api.service';
import { SettingsService } from '@app/core/settings.service';
import { SystemsStore } from './systems.store';

interface MetricsSummary {
  total_requests?: number;
  total_errors?: number;
  error_rate_percent?: number;
  metrics_count?: number;
}

interface LatestEvaluation {
  composite_score?: number;
  hallucination_rate?: number;
  claim_audit?: unknown;
  created_at?: string | null;
}

interface TraceRow {
  trace_id?: string;
  duration_ms?: number;
  agent_id?: string;
  operation_type?: string;
}

interface TabDef {
  id: 'overview' | 'design' | 'runs' | 'settings';
  label: string;
  icon: string;
}

interface WizardStep {
  key: 'identity' | 'knowledge' | 'model' | 'guardrails' | 'launch';
  title: string;
  description: string;
  icon: string;
  cta: string;
  route: string | unknown[];
  done: boolean;
}

interface PipelineStage {
  key: 'query' | 'retrieve' | 'rerank' | 'generate';
  name: string;
  icon: string;
  description: string;
  configureLabel: string;
  route: string | unknown[];
  tone: 'brand' | 'violet' | 'emerald';
}

@Component({
  selector: 'app-system-view',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    NgClass,
    RouterLink,
    ChatPanelComponent,
    IconComponent,
    SectionHeaderComponent,
    StatTileComponent,
    StatusPulseComponent,
  ],
  template: `
    <app-section-header
      breadcrumb="Systems"
      [title]="agentName()"
      icon="bot"
      [subtitle]="agentDescription() || 'Configure, run and refine this AI system.'"
      [pill]="isDraft() ? 'Draft' : ''"
    >
      <app-status-pulse [tone]="isDraft() ? 'warning' : 'success'" [label]="isDraft() ? 'Draft' : 'Ready'" />
      <button
        type="button"
        (click)="activeTab.set('runs')"
        class="inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition"
      >
        <app-icon name="message-square" [size]="14" /> Open playground
      </button>
    </app-section-header>

    <div class="flex items-center gap-1 border-b border-white/5 mb-6">
      @for (tab of tabs; track tab.id) {
        <button
          type="button"
          (click)="activeTab.set(tab.id)"
          [ngClass]="{
            'text-white border-brand-500': activeTab() === tab.id,
            'text-gray-400 border-transparent hover:text-gray-200': activeTab() !== tab.id
          }"
          class="relative inline-flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 transition"
        >
          <app-icon [name]="tab.icon" [size]="14" />
          {{ tab.label }}
        </button>
      }
    </div>

    <!-- Overview -->
    @if (activeTab() === 'overview') {
      <div class="space-y-6">
        <!-- OmniRAG banner: each stage links to the matching configuration -->
        <div
          class="relative overflow-hidden t-card rounded-md p-5"
          style="background: linear-gradient(135deg, rgba(0,188,212,0.08) 0%, rgba(139,92,246,0.08) 100%); border: 1px solid rgba(0,188,212,0.25);"
        >
          <div class="absolute -right-16 -top-16 w-56 h-56 rounded-full bg-brand-500/15 blur-3xl pointer-events-none"></div>
          <div class="relative flex items-center gap-3 flex-wrap">
            <app-icon name="atom" [size]="18" class="text-brand-400" />
            <span class="text-xs uppercase tracking-wider font-semibold text-brand-300">OmniRAG pipeline</span>
            <div class="flex items-center gap-2 ml-auto text-[11px]">
              @for (stage of pipelineStages; track stage.key; let last = $last) {
                <a
                  [routerLink]="stage.route"
                  class="inline-flex items-center gap-1.5 px-2 py-1 rounded bg-white/5 ring-1 ring-white/10 text-gray-200 hover:bg-white/10 hover:ring-brand-500/40 transition"
                  [title]="'Open ' + stage.configureLabel"
                >
                  <app-icon [name]="stage.icon" [size]="11" class="text-brand-400" />
                  {{ stage.name }}
                </a>
                @if (!last) {
                  <app-icon name="chevron-right" [size]="12" class="text-gray-600" />
                }
              }
            </div>
          </div>
        </div>

        <!-- KPI row — each tile is actionable and routes to observability -->
        <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
          <app-stat-tile
            label="Requests"
            [value]="kpiRequests()"
            hint="since restart"
            icon="play-circle"
            [interactive]="true"
            (click)="goto('/observability/performance')"
          />
          <app-stat-tile
            label="Errors"
            [value]="kpiErrors()"
            [trend]="errorsTrend()"
            icon="alert-triangle"
            [interactive]="true"
            (click)="goto('/observability/performance')"
          />
          <app-stat-tile
            label="Avg latency"
            [value]="kpiLatency()"
            unit="ms"
            icon="gauge"
            [interactive]="true"
            (click)="goto('/observability/traces')"
          />
          <app-stat-tile
            label="Quality"
            [value]="kpiQuality()"
            unit="/100"
            icon="target"
            [interactive]="true"
            (click)="goto('/observability')"
          />
          <app-stat-tile
            label="Error rate"
            [value]="kpiErrorRate()"
            unit="%"
            [trend]="errorRateTrend()"
            icon="alert-circle"
            [interactive]="true"
            (click)="goto('/observability/performance')"
          />
          <app-stat-tile
            label="Traces"
            [value]="kpiTraces()"
            icon="git-commit"
            [interactive]="true"
            (click)="goto('/observability/traces')"
          />
        </div>
        @if (kpisLoading()) {
          <p class="text-[11px] text-gray-500 -mt-2">Loading metrics…</p>
        }

        <!-- Setup wizard — each step has an actionable CTA -->
        <section class="t-card t-elevated rounded-md p-6">
          <div class="flex items-center gap-2 mb-4">
            <app-icon name="list-checks" [size]="16" class="text-brand-400" />
            <h3 class="text-base font-semibold text-white">Setup checklist</h3>
            <span class="ml-auto text-xs text-gray-400">{{ completedSteps() }} / {{ wizard().length }} done</span>
          </div>

          <div class="w-full h-1.5 rounded-full bg-white/5 overflow-hidden mb-4">
            <div
              class="h-full rounded-full bg-gradient-to-r from-brand-500 to-violet-500 transition-all"
              [style.width.%]="(completedSteps() / wizard().length) * 100"
            ></div>
          </div>

          <ul class="grid grid-cols-1 md:grid-cols-2 gap-3">
            @for (step of wizard(); track step.key; let i = $index) {
              <li
                class="flex items-start gap-3 px-4 py-3 rounded-md border"
                [ngClass]="step.done
                  ? 'border-emerald-500/20 bg-emerald-500/[0.04]'
                  : 'border-white/5 bg-black/20'"
              >
                <div
                  class="w-9 h-9 rounded-md flex items-center justify-center shrink-0"
                  [ngClass]="step.done
                    ? 'bg-emerald-500/15 text-emerald-400 ring-1 ring-emerald-500/30'
                    : 'bg-brand-500/10 text-brand-400 ring-1 ring-brand-500/20'"
                >
                  <app-icon [name]="step.done ? 'check-circle-2' : step.icon" [size]="16" />
                </div>
                <div class="flex-1 min-w-0">
                  <div class="flex items-center gap-2">
                    <span class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">Step {{ i + 1 }}</span>
                    <span class="text-sm font-medium text-white">{{ step.title }}</span>
                  </div>
                  <p class="text-[11px] text-gray-400 mt-0.5 leading-relaxed">{{ step.description }}</p>
                </div>
                <a
                  [routerLink]="step.route"
                  class="shrink-0 inline-flex items-center gap-1 px-2.5 py-1.5 rounded text-xs font-medium transition"
                  [ngClass]="step.done
                    ? 'bg-white/5 text-gray-300 hover:bg-white/10 ring-1 ring-white/10'
                    : 'bg-brand-500 text-white hover:bg-brand-600 shadow-glow-sm'"
                >
                  <app-icon [name]="step.done ? 'external-link' : 'arrow-right'" [size]="12" />
                  {{ step.cta }}
                </a>
              </li>
            }
          </ul>
        </section>
      </div>
    }

    <!-- Design canvas -->
    @if (activeTab() === 'design') {
      <div class="space-y-4">
        <!-- Orientation banner -->
        <div
          class="t-card rounded-md p-4 flex items-start gap-3"
          style="background: linear-gradient(135deg, rgba(139,92,246,0.08) 0%, rgba(0,188,212,0.08) 100%); border: 1px solid rgba(139,92,246,0.25);"
        >
          <div class="w-10 h-10 rounded-md flex items-center justify-center bg-violet-500/15 text-violet-300 ring-1 ring-violet-500/30 shrink-0">
            <app-icon name="workflow" [size]="18" />
          </div>
          <div class="flex-1 min-w-0">
            <div class="text-sm font-semibold text-white">Pipeline blueprint</div>
            <p class="text-xs text-gray-400 mt-0.5 leading-relaxed max-w-2xl">
              Each stage of this system is configurable independently. For a free-form, multi-branch
              composition (tool calls, guardrails, conditional routing), open this system in the Flow
              builder.
            </p>
          </div>
          <a
            routerLink="/orchestration"
            class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-brand-500 hover:bg-brand-600 text-white shadow-glow-sm transition shrink-0"
          >
            <app-icon name="workflow" [size]="14" /> Open in flow builder
          </a>
        </div>

        <!-- Pipeline stages — each with inline "Configure" action -->
        <section class="t-card t-elevated rounded-md overflow-hidden">
          <div class="px-5 py-4 border-b border-white/5 flex items-center justify-between">
            <h3 class="text-sm font-semibold text-white flex items-center gap-1.5">
              <app-icon name="layers" [size]="16" class="text-brand-400" />
              Stages
            </h3>
            <span class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">
              {{ pipelineStages.length }} active
            </span>
          </div>
          <ul>
            @for (stage of pipelineStages; track stage.key; let i = $index; let last = $last) {
              <li
                class="px-5 py-4 flex items-center gap-4"
                [class.border-b]="!last"
                [class.border-white\\/5]="!last"
              >
                <div
                  class="w-11 h-11 rounded-md flex items-center justify-center shrink-0 ring-1"
                  [ngClass]="{
                    'bg-brand-500/15 text-brand-400 ring-brand-500/30': stage.tone === 'brand',
                    'bg-violet-500/15 text-violet-400 ring-violet-500/30': stage.tone === 'violet',
                    'bg-emerald-500/15 text-emerald-400 ring-emerald-500/30': stage.tone === 'emerald'
                  }"
                >
                  <app-icon [name]="stage.icon" [size]="18" />
                </div>
                <div class="flex-1 min-w-0">
                  <div class="flex items-center gap-2">
                    <span class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">L{{ i + 1 }}</span>
                    <span class="text-sm font-medium text-white">{{ stage.name }}</span>
                  </div>
                  <p class="text-[12px] text-gray-400 mt-0.5 leading-relaxed">{{ stage.description }}</p>
                </div>
                <a
                  [routerLink]="stage.route"
                  class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition shrink-0"
                >
                  <app-icon name="settings-2" [size]="12" /> {{ stage.configureLabel }}
                </a>
              </li>
            }
          </ul>
        </section>
      </div>
    }

    <!-- Runs -->
    @if (activeTab() === 'runs') {
      <div class="t-card t-elevated rounded-md p-0 overflow-hidden min-h-[520px]">
        <app-chat-panel [systemId]="systemId" />
      </div>
    }

    <!-- Settings -->
    @if (activeTab() === 'settings') {
      <div class="space-y-4">
        <div class="flex items-center justify-between">
          <p class="text-xs text-gray-400">
            These values come from your workspace-wide settings. Changes apply to every system unless
            overridden on a per-system basis.
          </p>
          <a
            routerLink="/settings"
            class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium bg-brand-500 hover:bg-brand-600 text-white transition"
          >
            <app-icon name="sliders-horizontal" [size]="12" /> Edit in Settings
          </a>
        </div>

        <div class="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <section class="t-card t-elevated rounded-md p-5">
            <h3 class="text-sm font-semibold text-white mb-3 flex items-center gap-1.5">
              <app-icon name="tag" [size]="14" class="text-brand-400" /> Identity
            </h3>
            <div class="space-y-3 text-sm">
              <div>
                <div class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">Name</div>
                <div class="text-white">{{ agentName() }}</div>
              </div>
              <div>
                <div class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">System ID</div>
                <div class="text-gray-300 font-mono text-xs break-all">{{ systemId }}</div>
              </div>
              <div>
                <div class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">Status</div>
                <div class="text-white capitalize">{{ isDraft() ? 'Draft' : 'Ready' }}</div>
              </div>
            </div>
          </section>
          <section class="t-card t-elevated rounded-md p-5">
            <h3 class="text-sm font-semibold text-white mb-3 flex items-center gap-1.5">
              <app-icon name="cpu" [size]="14" class="text-brand-400" /> Model
            </h3>
            <div class="space-y-3 text-sm text-gray-300">
              <div>Provider: <span class="text-white font-mono">{{ settings.settings().defaultProvider || '—' }}</span></div>
              <div>Model: <span class="text-white font-mono">{{ settings.settings().defaultModel || '—' }}</span></div>
              <div>Temperature: <span class="text-white font-mono">{{ settings.settings().temperature?.toFixed(2) ?? '—' }}</span></div>
              <div>Max tokens: <span class="text-white font-mono">{{ settings.settings().maxTokens ?? '—' }}</span></div>
            </div>
          </section>
          <section class="t-card t-elevated rounded-md p-5">
            <h3 class="text-sm font-semibold text-white mb-3 flex items-center gap-1.5">
              <app-icon name="database" [size]="14" class="text-brand-400" /> Retrieval
            </h3>
            <div class="space-y-3 text-sm text-gray-300">
              <div>Pipeline: <span class="text-white font-mono">{{ settings.ragPipelineMode() || '—' }}</span></div>
              <div>Top-K: <span class="text-white font-mono">{{ settings.settings().ragTopK ?? '—' }}</span></div>
              <div>Similarity: <span class="text-white font-mono">{{ settings.settings().ragSimilarityThreshold?.toFixed(2) ?? '—' }}</span></div>
              <div class="pt-1">
                <a
                  routerLink="/knowledge"
                  class="inline-flex items-center gap-1 text-xs text-brand-400 hover:text-brand-300"
                >
                  <app-icon name="external-link" [size]="11" /> Manage collections
                </a>
              </div>
            </div>
          </section>
        </div>
      </div>
    }
  `,
})
export class SystemViewComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly store = inject(SystemsStore);
  private readonly api = inject(ApiService);
  readonly settings = inject(SettingsService);

  systemId = '';
  agentName = signal('System');
  agentDescription = signal('');
  isDraft = signal(false);
  activeTab = signal<TabDef['id']>('overview');

  private readonly metrics = signal<MetricsSummary | null>(null);
  private readonly latestEval = signal<LatestEvaluation | null>(null);
  private readonly traces = signal<TraceRow[]>([]);
  private readonly hasCollections = signal(false);
  readonly kpisLoading = signal(false);

  readonly kpiRequests = computed(() => this.metrics()?.total_requests ?? '—');
  readonly kpiErrors = computed(() => this.metrics()?.total_errors ?? '—');
  readonly kpiErrorRate = computed(() => {
    const rate = this.metrics()?.error_rate_percent;
    return rate == null ? '—' : rate.toFixed(1);
  });
  readonly kpiQuality = computed(() => {
    const s = this.latestEval()?.composite_score;
    return s == null ? '—' : s.toFixed(1);
  });
  readonly kpiTraces = computed(() => this.traces().length || '—');
  readonly errorRateTrend = computed<'up' | null>(() => {
    const rate = this.metrics()?.error_rate_percent;
    return rate != null && rate > 0 ? 'up' : null;
  });
  readonly errorsTrend = computed<'up' | null>(() => {
    const e = this.metrics()?.total_errors ?? 0;
    return e > 0 ? 'up' : null;
  });
  readonly kpiLatency = computed(() => {
    const rows = this.traces();
    if (!rows.length) return '—';
    const vals = rows.map((r) => r.duration_ms ?? 0).filter((v) => v > 0);
    if (!vals.length) return '—';
    const avg = vals.reduce((a, b) => a + b, 0) / vals.length;
    return Math.round(avg).toString();
  });

  readonly tabs: TabDef[] = [
    { id: 'overview', label: 'Overview', icon: 'layout-dashboard' },
    { id: 'design', label: 'Design', icon: 'workflow' },
    { id: 'runs', label: 'Runs', icon: 'message-square' },
    { id: 'settings', label: 'Settings', icon: 'settings' },
  ];

  readonly wizard = computed<WizardStep[]>(() => {
    const s = this.settings.settings();
    const hasModel = !!s.defaultModel;
    const hasPipeline = !!this.settings.ragPipelineMode();
    const draft = this.isDraft();
    return [
      {
        key: 'identity',
        title: 'Identity',
        description: 'Name, description and prompt.',
        icon: 'tag',
        cta: 'Review',
        route: ['/systems', this.systemId],
        done: !!this.agentName() && this.agentName() !== 'System',
      },
      {
        key: 'knowledge',
        title: 'Knowledge',
        description: 'Collections the system can retrieve from.',
        icon: 'database',
        cta: 'Open Knowledge',
        route: '/knowledge',
        done: this.hasCollections(),
      },
      {
        key: 'model',
        title: 'Model',
        description: 'Default LLM, temperature, max tokens.',
        icon: 'cpu',
        cta: 'Configure',
        route: '/settings',
        done: hasModel,
      },
      {
        key: 'guardrails',
        title: 'Guardrails',
        description: 'RAG pipeline mode, similarity threshold, safety filters.',
        icon: 'shield-check',
        cta: 'Configure',
        route: '/settings',
        done: hasPipeline,
      },
      {
        key: 'launch',
        title: 'Launch',
        description: 'Promote this draft and start serving traffic.',
        icon: 'rocket',
        cta: 'Open playground',
        route: ['/systems', this.systemId],
        done: !draft,
      },
    ];
  });

  readonly pipelineStages: PipelineStage[] = [
    {
      key: 'query',
      name: 'Query',
      icon: 'message-square',
      description: 'User intent parsing, query rewriting and routing.',
      configureLabel: 'System prompt',
      route: '/settings',
      tone: 'brand',
    },
    {
      key: 'retrieve',
      name: 'Retrieve',
      icon: 'database',
      description: 'Hybrid search over your collections (dense + BM25).',
      configureLabel: 'Collections',
      route: '/knowledge',
      tone: 'violet',
    },
    {
      key: 'rerank',
      name: 'Rerank',
      icon: 'filter',
      description: 'Cross-encoder reranking + context filtering.',
      configureLabel: 'Top-K & threshold',
      route: '/settings',
      tone: 'brand',
    },
    {
      key: 'generate',
      name: 'Generate',
      icon: 'sparkles',
      description: 'LLM synthesis with citations and guardrails.',
      configureLabel: 'Model',
      route: '/settings',
      tone: 'emerald',
    },
  ];

  readonly completedSteps = computed(() => this.wizard().filter((s) => s.done).length);

  goto(path: string): void {
    this.router.navigateByUrl(path);
  }

  ngOnInit(): void {
    this.systemId = this.route.snapshot.paramMap.get('systemId') ?? '';
    this.settings.refresh();
    const local = this.store.findById(this.systemId);
    if (local) {
      this.agentName.set(local.name);
      this.agentDescription.set(local.description || '');
      this.isDraft.set(!!local.draft);
    } else {
      this.store.getById(this.systemId).subscribe({
        next: (agent) => {
          if (!agent) return;
          this.agentName.set(agent.name);
          this.agentDescription.set(agent.description || '');
          this.isDraft.set(!!agent.draft);
        },
        error: () => {},
      });
    }
    this.loadKpis();
  }

  private loadKpis(): void {
    this.kpisLoading.set(true);
    forkJoin({
      metrics: this.api
        .get<MetricsSummary>('/metrics/summary')
        .pipe(catchError(() => of({} as MetricsSummary))),
      evaluation: this.api
        .get<{ evaluation: LatestEvaluation | null }>('/evaluation/latest', {
          agent_id: this.systemId,
        })
        .pipe(catchError(() => of({ evaluation: null }))),
      traces: this.api
        .get<{ traces: TraceRow[] }>('/traces/traces')
        .pipe(catchError(() => of({ traces: [] as TraceRow[] }))),
      collections: this.api
        .get<{ collections: string[] }>('/documents/collections')
        .pipe(catchError(() => of({ collections: [] as string[] }))),
    }).subscribe(({ metrics, evaluation, traces, collections }) => {
      this.metrics.set(metrics ?? null);
      this.latestEval.set(evaluation?.evaluation ?? null);
      const all = traces?.traces ?? [];
      this.traces.set(all.filter((t) => !this.systemId || t.agent_id === this.systemId));
      this.hasCollections.set((collections?.collections?.length ?? 0) > 0);
      this.kpisLoading.set(false);
    });
  }
}

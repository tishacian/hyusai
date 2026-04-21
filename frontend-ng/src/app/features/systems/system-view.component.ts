import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { NgClass } from '@angular/common';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { forkJoin, of } from 'rxjs';
import { catchError, map } from 'rxjs/operators';
import { ChatPanelComponent } from '@app/features/chat/chat-panel.component';
import { IconComponent } from '@app/shared/ui/icon.component';
import { StatusPulseComponent } from '@app/shared/ui/status-pulse.component';
import { RunOutcomeCardComponent, ImpactPreviewComponent, StatReadoutComponent } from '@app/shared/cockpit';
import {
  CkObjectHeaderComponent,
  type CkObjectKpi,
} from '@app/shared/cockpit/object-header.component';
import { CkTabsComponent, CkTabComponent } from '@app/shared/cockpit/tabs.component';
import { CkPanelComponent } from '@app/shared/cockpit/panel.component';
import { ApiService } from '@app/core/api.service';
import { CanonicalApiService, type Run, type System } from '@app/core/canonical-api.service';
import { NewsLabComponent } from '@app/features/intelligence/news-lab.component';
import { ZoomContextService } from '@app/core/zoom-context.service';
import { LensService } from '@app/core/lens';
import { SettingsService } from '@app/core/settings.service';
import { ToastrService } from 'ngx-toastr';
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
  id?: string;
  trace_id?: string;
  duration_ms?: number;
  agent_id?: string;
  system_id?: string;
  operation_type?: string;
}

type SystemTabId =
  | 'intelligence'
  | 'overview'
  | 'runs'
  | 'design'
  | 'context'
  | 'chat';

/**
 * Variant is a marker persisted on `flow_definition.variant` that lets
 * SystemViewComponent adapt its facets without introducing a separate
 * route. For Vague A we only recognize `intelligence` — other specialist
 * Systems will plug here the same way.
 */
type SystemVariant = 'intelligence' | 'standard';

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
    StatReadoutComponent,
    StatusPulseComponent,
    RunOutcomeCardComponent,
    ImpactPreviewComponent,
    CkObjectHeaderComponent,
    CkTabsComponent,
    CkTabComponent,
    CkPanelComponent,
    NewsLabComponent,
  ],
  template: `
    <ck-object-header
      [eyebrow]="headerEyebrow()"
      [title]="agentName()"
      [subtitle]="agentDescription() || headerFallbackSubtitle()"
      [kpis]="objectKpis()"
    >
      <app-status-pulse
        status
        [tone]="isDraft() ? 'warning' : 'success'"
        [label]="isDraft() ? 'Draft' : 'Ready'"
      />
      <button
        actions
        type="button"
        (click)="triggerRun()"
        [disabled]="triggering() || isDraft()"
        class="inline-flex items-center gap-1.5 px-3 py-2 rounded text-xs font-medium ck-mono transition"
        style="letter-spacing:0.14em; text-transform:uppercase; background:var(--ck-signal-pos); color:#020617;"
        [style.opacity]="triggering() || isDraft() ? '0.4' : '1'"
      >
        <app-icon name="play" [size]="12" />
        {{ triggering() ? 'Queueing…' : 'Run now' }}
      </button>
      <button
        actions
        type="button"
        (click)="chatPanelOpen.set(true)"
        class="inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition"
        title="Open chat panel"
      >
        <app-icon name="message-square" [size]="14" /> Chat
      </button>
      <button
        actions
        type="button"
        (click)="settingsPanelOpen.set(true)"
        class="inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition"
        title="Open settings panel"
      >
        <app-icon name="settings" [size]="14" /> Settings
      </button>
    </ck-object-header>

    <ck-tabs
      [active]="activeTab()"
      (activeChange)="onTabChange($event)"
      ariaLabel="System facets"
    >
      @if (isIntelligence()) {
        <ck-tab id="intelligence" label="News Lab">
          <app-news-lab />
        </ck-tab>
      }

      <ck-tab id="overview" label="Overview">
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
          <ck-stat-readout variant="tile"
            label="Requests"
            [value]="kpiRequests()"
            hint="since restart"
            icon="play-circle"
            [interactive]="true"
            (click)="goto('/observability/performance')"
          />
          <ck-stat-readout variant="tile"
            label="Errors"
            [value]="kpiErrors()"
            [trend]="errorsTrend()"
            icon="alert-triangle"
            [interactive]="true"
            (click)="goto('/observability/performance')"
          />
          <ck-stat-readout variant="tile"
            label="Avg latency"
            [value]="kpiLatency()"
            unit="ms"
            icon="gauge"
            [interactive]="true"
            (click)="goto('/runs')"
          />
          <ck-stat-readout variant="tile"
            label="Quality"
            [value]="kpiQuality()"
            unit="/100"
            icon="target"
            [interactive]="true"
            (click)="goto('/observability')"
          />
          <ck-stat-readout variant="tile"
            label="Error rate"
            [value]="kpiErrorRate()"
            unit="%"
            [trend]="errorRateTrend()"
            icon="alert-circle"
            [interactive]="true"
            (click)="goto('/observability/performance')"
          />
          <ck-stat-readout variant="tile"
            label="Runs"
            [value]="kpiTraces()"
            icon="git-commit"
            [interactive]="true"
            (click)="goto('/runs')"
          />
        </div>
        @if (kpisLoading()) {
          <p class="text-[11px] text-gray-500 -mt-2">Loading metrics…</p>
        }

        <!-- Universal Impact Preview — projects what would happen if the
             system's control-plane levers were shifted. -->
        <ck-impact-preview
          scope="system"
          [targetId]="systemId"
          label="System what-if · preview before you apply"
        />

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
      </ck-tab>

      <ck-tab id="runs" label="Runs">
        <div class="space-y-4">
          <div class="flex items-center justify-between">
            <div>
              <h3 class="text-sm font-semibold text-white">Run outcomes</h3>
              <p class="ck-mono" style="font-size:10px; color:var(--ck-fg-4); letter-spacing:0.08em; margin-top:2px;">
                Decision · Confidence · Value · Cost · Efficiency — canonical Outcome block per run.
              </p>
            </div>
            <button
              type="button"
              (click)="loadRuns()"
              class="ck-mono inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-xs transition"
              style="background:var(--ck-bg-inset); border:1px solid var(--ck-stroke-soft); color:var(--ck-fg-3); letter-spacing:0.12em; text-transform:uppercase;"
            >
              <app-icon name="refresh-cw" [size]="12" />
              Refresh
            </button>
          </div>

          @if (runsLoading()) {
            <div class="ck-mono" style="font-size:11px; color:var(--ck-fg-4);">Loading runs…</div>
          } @else if (runs().length === 0) {
            <div class="ck-surface rounded-md" style="padding:32px; text-align:center;">
              <div class="ck-mono" style="font-size:10px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4); margin-bottom:8px;">
                NO RUNS YET
              </div>
              <p class="text-sm text-white mb-1">This system has not produced any outcome.</p>
              <p class="ck-mono" style="font-size:11px; color:var(--ck-fg-4);">
                Click <span class="text-white">Run now</span> above to trigger a canonical run.
              </p>
            </div>
          } @else {
            <div class="space-y-3">
              @for (run of runs(); track run.id) {
                <ck-run-outcome-card [run]="run" />
              }
            </div>
          }
        </div>
      </ck-tab>

      <ck-tab id="design" label="Design">
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
            [queryParams]="{ systemId: systemId }"
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
      </ck-tab>

      <ck-tab id="context" label="Context">
        <div class="space-y-4">
        @if (contextLoading()) {
          <div class="t-card t-elevated rounded-md p-5 animate-pulse">
            <div class="h-3 w-40 bg-white/5 rounded mb-2"></div>
            <div class="h-3 w-64 bg-white/5 rounded"></div>
          </div>
        } @else if (!currentContext()) {
          <div class="t-card t-elevated rounded-md p-8 text-center text-gray-400 text-sm">
            No dedicated Context attached. This System runs on the workspace default.
            <div class="mt-3">
              <a
                routerLink="/steering/contexts"
                class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium bg-brand-500 hover:bg-brand-600 text-white transition"
              >
                <app-icon name="external-link" [size]="12" /> Manage contexts
              </a>
            </div>
          </div>
        } @else {
          <section class="t-card t-elevated rounded-md p-5">
            <div class="flex items-center gap-2 mb-4">
              <app-icon name="database" [size]="14" class="text-brand-400" />
              <h3 class="text-sm font-semibold text-white">{{ currentContext()!.name }}</h3>
              <span class="ml-auto text-[10px] font-mono px-2 py-0.5 rounded bg-white/5 text-gray-400 ring-1 ring-white/10">
                v{{ currentContext()!.version ?? 1 }}
              </span>
            </div>
            <div class="grid grid-cols-1 md:grid-cols-3 gap-4 text-sm">
              <div>
                <div class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold mb-1">Data refs</div>
                @if ((currentContext()!.data_refs ?? []).length === 0) {
                  <div class="text-gray-500">—</div>
                } @else {
                  <ul class="space-y-1">
                    @for (ref of currentContext()!.data_refs ?? []; track $index) {
                      <li class="font-mono text-xs text-gray-300 truncate">{{ ref }}</li>
                    }
                  </ul>
                }
              </div>
              <div>
                <div class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold mb-1">Memory refs</div>
                @if ((currentContext()!.memory_refs ?? []).length === 0) {
                  <div class="text-gray-500">—</div>
                } @else {
                  <ul class="space-y-1">
                    @for (ref of currentContext()!.memory_refs ?? []; track $index) {
                      <li class="font-mono text-xs text-gray-300 truncate">{{ ref }}</li>
                    }
                  </ul>
                }
              </div>
              <div>
                <div class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold mb-1">Permissions</div>
                <pre class="font-mono text-[11px] text-gray-300 whitespace-pre-wrap break-all">{{ permissionsPreview() }}</pre>
              </div>
            </div>
          </section>
        }
        </div>
      </ck-tab>
    </ck-tabs>

    <!-- Settings side panel — opened via header button; never a tab. -->
    <ck-panel
      [open]="settingsPanelOpen()"
      (openChange)="settingsPanelOpen.set($event)"
      position="side"
      eyebrow="System · panel"
      title="Settings"
      width="480px"
    >
      <div class="space-y-4">
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
            <div>
              <div class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">Execution mode</div>
              <div class="text-white">
                {{ executionModeLabel() }}
                <span class="ml-1 text-[10px] uppercase tracking-wider text-gray-500 font-mono">{{ executionModeRaw() }}</span>
              </div>
            </div>
          </div>
        </section>
        <section class="t-card t-elevated rounded-md p-5">
          <h3 class="text-sm font-semibold text-white mb-3 flex items-center gap-1.5">
            <app-icon name="cpu" [size]="14" class="text-brand-400" /> Model
          </h3>
          <div class="space-y-3 text-sm text-gray-300">
            <div>
              Default model:
              <span class="text-white font-mono">{{ effectiveModel() }}</span>
              @if (systemDefaults()?.default_model) {
                <span class="ml-1 text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-violet-500/10 text-violet-300 border border-violet-500/20">
                  override
                </span>
              }
            </div>
            <div>
              Reasoning template:
              <span class="text-white font-mono">{{ systemDefaults()?.default_prompt_type || 'auto' }}</span>
            </div>
            <div>Temperature: <span class="text-white font-mono">{{ settings.settings().temperature?.toFixed(2) ?? '—' }}</span></div>
            <div>Max tokens: <span class="text-white font-mono">{{ settings.settings().maxTokens ?? '—' }}</span></div>
          </div>
        </section>
        <section class="t-card t-elevated rounded-md p-5">
          <h3 class="text-sm font-semibold text-white mb-3 flex items-center gap-1.5">
            <app-icon name="database" [size]="14" class="text-brand-400" /> Retrieval
          </h3>
          <div class="space-y-3 text-sm text-gray-300">
            <div>
              Pipeline:
              <span class="text-white font-mono">{{ systemDefaults()?.retrieval_mode_default || settings.ragPipelineMode() || '—' }}</span>
              @if (systemDefaults()?.retrieval_mode_default && systemDefaults()?.retrieval_mode_default !== 'auto') {
                <span class="ml-1 text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-brand-500/10 text-brand-400 border border-brand-500/20">
                  pinned
                </span>
              }
            </div>
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
    </ck-panel>

    <!-- Chat side panel — opens on demand, preserves the canvas context. -->
    <ck-panel
      [open]="chatPanelOpen()"
      (openChange)="chatPanelOpen.set($event)"
      position="side"
      eyebrow="System · panel"
      title="Chat"
      width="520px"
    >
      <div class="t-card t-elevated rounded-md p-0 overflow-hidden min-h-[520px]">
        <app-chat-panel [systemId]="systemId" />
      </div>
    </ck-panel>
  `,
})
export class SystemViewComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly store = inject(SystemsStore);
  private readonly api = inject(ApiService);
  private readonly canonical = inject(CanonicalApiService);
  private readonly zoom = inject(ZoomContextService);
  private readonly toast = inject(ToastrService);
  readonly settings = inject(SettingsService);
  readonly lensService = inject(LensService);

  readonly runs = signal<Run[]>([]);
  readonly runsLoading = signal(false);
  readonly triggering = signal(false);

  systemId = '';
  agentName = signal('System');
  agentDescription = signal('');
  isDraft = signal(false);
  activeTab = signal<SystemTabId>('overview');

  /**
   * Variant derived from `flow_definition.variant`. When set to
   * `intelligence`, the view prepends a dedicated facet for the News Lab
   * so `/intelligence` is a thin redirect rather than a standalone page.
   */
  readonly variant = signal<SystemVariant>('standard');
  readonly isIntelligence = computed(() => this.variant() === 'intelligence');
  readonly headerEyebrow = computed(() =>
    this.isIntelligence() ? 'Systems · Intelligence' : 'Systems · System',
  );
  readonly headerFallbackSubtitle = computed(() =>
    this.isIntelligence()
      ? 'Market-signal briefs and continuous monitoring.'
      : 'Configure, run and refine this AI system.',
  );
  /** Side panels — Settings and Chat live here, never as tabs. */
  readonly settingsPanelOpen = signal(false);
  readonly chatPanelOpen = signal(false);

  readonly systemDefaults = signal<{
    default_prompt_type?: string | null;
    default_model?: string | null;
    retrieval_mode_default?: string | null;
    execution_mode?: string | null;
  } | null>(null);

  readonly executionModeRaw = computed(
    () => this.systemDefaults()?.execution_mode || 'real_time_decision',
  );

  readonly executionModeLabel = computed(() => {
    switch (this.executionModeRaw()) {
      case 'real_time_decision':
        return 'Real-time decision';
      case 'batch_processing':
        return 'Batch processing';
      case 'event_driven_automation':
        return 'Event-driven automation';
      case 'continuous_monitoring':
        return 'Continuous monitoring';
      case 'human_augmented':
        return 'Human-augmented';
      default:
        return this.executionModeRaw();
    }
  });

  readonly effectiveModel = computed(() => {
    const d = this.systemDefaults();
    return d?.default_model || this.settings.settings().defaultModel || '—';
  });

  readonly currentContext = signal<import('@app/core/canonical-api.service').Context | null>(null);
  readonly contextLoading = signal(false);

  readonly permissionsPreview = computed(() => {
    const p = this.currentContext()?.permissions ?? {};
    const keys = Object.keys(p);
    if (!keys.length) return '—';
    return JSON.stringify(p, null, 2);
  });

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

  /**
   * Object-level KPIs rendered in the persistent `<ck-object-header>`.
   * Values not yet tracked (ROI, unit cost) render as `—` — better to show
   * the slot and admit ignorance than fake a number. See mental-model §6.
   *
   * The current lens is threaded in as a hint so future iterations can
   * adapt the *set* of KPIs per lens (e.g. Govern highlights audit
   * deltas); for now all lenses share the same 4 KPIs.
   */
  readonly objectKpis = computed<CkObjectKpi[]>(() => {
    const quality = this.latestEval()?.composite_score;
    const errRate = this.metrics()?.error_rate_percent;
    const yieldValue =
      quality != null ? quality.toFixed(0) : errRate != null ? (100 - errRate).toFixed(0) : '—';
    return [
      { label: 'ROI', value: '—', hint: 'Return on decision — coming when Outcome.value is priced.' },
      { label: 'Cost', value: '—', hint: 'Unit cost per run — coming with cost accounting.' },
      {
        label: 'Yield',
        value: yieldValue === '—' ? '—' : `${yieldValue}%`,
        tone: yieldValue === '—' ? 'neutral' : 'cool',
        hint: 'Composite quality score (latest evaluation).',
      },
      {
        label: 'Runs',
        value: String(this.traces().length || this.runs().length || 0),
        tone: 'neutral',
      },
    ];
  });

  onTabChange(id: string): void {
    this.activeTab.set(id as SystemTabId);
  }

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
        cta: 'Open chat',
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
    this.zoom.setCurrentSystem(this.systemId || null);
    this.settings.refresh();
    this.loadVariantAndApplyFacet();
    const local = this.store.findById(this.systemId);
    if (local) {
      this.agentName.set(local.name);
      this.agentDescription.set(local.description || '');
      this.isDraft.set(!!local.draft);
      this.systemDefaults.set({
        default_prompt_type: local.default_prompt_type ?? null,
        default_model: local.default_model ?? null,
        retrieval_mode_default: local.retrieval_mode_default ?? null,
        execution_mode: (local as unknown as { execution_mode?: string | null }).execution_mode ?? null,
      });
    } else {
      this.store.getById(this.systemId).subscribe({
        next: (agent) => {
          if (!agent) return;
          this.agentName.set(agent.name);
          this.agentDescription.set(agent.description || '');
          this.isDraft.set(!!agent.draft);
          this.systemDefaults.set({
            default_prompt_type: agent.default_prompt_type ?? null,
            default_model: agent.default_model ?? null,
            retrieval_mode_default: agent.retrieval_mode_default ?? null,
            execution_mode: (agent as unknown as { execution_mode?: string | null }).execution_mode ?? null,
          });
        },
        error: () => {},
      });
    }
    this.loadKpis();
    this.loadRuns();
    this.loadContext();
  }

  /**
   * Fetch the canonical System row and derive the variant marker from
   * `flow_definition.variant`. When the URL carries `?facet=<id>`, the
   * matching tab is auto-activated — this is how `/intelligence` opens
   * directly on the News Lab facet without a second click.
   */
  private loadVariantAndApplyFacet(): void {
    if (!this.systemId) return;
    this.canonical.getSystem(this.systemId).subscribe({
      next: (sys: System | null) => {
        const flow = (sys?.flow_definition ?? {}) as Record<string, unknown>;
        const variant = String(flow['variant'] ?? '').toLowerCase();
        if (variant === 'intelligence') {
          this.variant.set('intelligence');
        } else {
          this.variant.set('standard');
        }
        this.applyRequestedFacet();
      },
      error: () => this.applyRequestedFacet(),
    });
  }

  private applyRequestedFacet(): void {
    const facet = this.route.snapshot.queryParamMap.get('facet');
    const allowed: SystemTabId[] = this.isIntelligence()
      ? ['intelligence', 'overview', 'runs', 'design', 'context']
      : ['overview', 'runs', 'design', 'context'];
    if (facet && (allowed as string[]).includes(facet)) {
      this.activeTab.set(facet as SystemTabId);
      return;
    }
    if (this.isIntelligence()) {
      this.activeTab.set('intelligence');
    }
  }

  private loadContext(): void {
    if (!this.systemId) return;
    this.contextLoading.set(true);
    this.canonical.listContexts({ system_id: this.systemId }).subscribe({
      next: (ctxList) => {
        this.currentContext.set((ctxList ?? [])[0] ?? null);
        this.contextLoading.set(false);
      },
      error: () => {
        this.currentContext.set(null);
        this.contextLoading.set(false);
      },
    });
  }

  loadRuns(): void {
    if (!this.systemId) return;
    this.runsLoading.set(true);
    this.canonical.listRuns({ system_id: this.systemId }).subscribe((list) => {
      this.runs.set(list);
      this.runsLoading.set(false);
    });
  }

  triggerRun(): void {
    if (this.triggering() || !this.systemId || this.isDraft()) return;
    this.triggering.set(true);
    this.canonical.triggerRun(this.systemId, { trigger: 'manual', input_ref: {} }).subscribe((run) => {
      this.triggering.set(false);
      if (!run) {
        this.toast.warning('Could not reach the run engine', 'Run not triggered');
        return;
      }
      this.toast.success(`Run ${run.id.slice(0, 8)} scheduled`, 'Run triggered');
      this.loadRuns();
      // Refresh once the engine has had time to execute the sequence.
      setTimeout(() => this.loadRuns(), 3500);
    });
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
      // Canonical `/runs` — legacy `/traces/traces` is deprecated.
      traces: this.api
        .get<{ runs: TraceRow[] } | TraceRow[]>('/runs', this.systemId ? { system_id: this.systemId } : {})
        .pipe(
          map((r) => (Array.isArray(r) ? r : r?.runs ?? [])),
          catchError(() => of([] as TraceRow[])),
        ),
      collections: this.api
        .get<{ collections: string[] }>('/documents/collections')
        .pipe(catchError(() => of({ collections: [] as string[] }))),
    }).subscribe(({ metrics, evaluation, traces, collections }) => {
      this.metrics.set(metrics ?? null);
      this.latestEval.set(evaluation?.evaluation ?? null);
      this.traces.set(
        (traces ?? []).filter((t) =>
          !this.systemId || t.system_id === this.systemId || t.agent_id === this.systemId,
        ),
      );
      this.hasCollections.set((collections?.collections?.length ?? 0) > 0);
      this.kpisLoading.set(false);
    });
  }
}

import { ChangeDetectionStrategy, Component, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { NgClass } from '@angular/common';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { Subscription, forkJoin, of } from 'rxjs';
import { catchError, distinctUntilChanged, map } from 'rxjs/operators';
import { ChatPanelComponent } from '@app/features/chat/chat-panel.component';
import { IconComponent } from '@app/shared/ui/icon.component';
import { StatusPulseComponent } from '@app/shared/ui/status-pulse.component';
import { NavLinkDirective, RunOutcomeCardComponent } from '@app/shared/cockpit';
import {
  CkObjectHeaderComponent,
  type CkObjectKpi,
} from '@app/shared/cockpit/object-header.component';
import { CkTabsComponent, CkTabComponent } from '@app/shared/cockpit/tabs.component';
import { CkPanelComponent } from '@app/shared/cockpit/panel.component';
import { ApiService } from '@app/core/api.service';
import { apiErrorMessage } from '@app/core/api-error-message';
import {
  CanonicalApiService,
  type Run,
  type System,
  type SystemOverview,
} from '@app/core/canonical-api.service';
import { NewsLabComponent } from '@app/features/intelligence/news-lab.component';
import { I18nService } from '@app/core/i18n.service';
import { LensService } from '@app/core/lens';
import { SettingsService } from '@app/core/settings.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { isObjectLens, type ObjectLens } from '@app/core/navigation.catalog';
import { ZoomContextService } from '@app/core/zoom-context.service';
import { WorkApiService } from '@app/features/experience/work/work-api.service';
import {
  WorkspaceViewContext,
  type WorkspaceViewRequest,
} from '@app/core/workspace-view-context';
import { ToastrService } from 'ngx-toastr';
import { FlowManifestService } from '@app/features/orchestration/flow/flow-manifest.service';
import { SystemsStore } from './systems.store';
import { SystemPerspectiveComponent } from './system-perspective.component';
import { SystemOverviewComponent } from './system-overview.component';
import { isFlowBackedSystem, systemFlowProfile } from './system-flow-profile';
import {
  SYSTEM_OBJECT_LENSES,
  type PerspectiveFact,
  type SystemPerspectiveResponse,
} from './system-perspective.models';

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
 * route. Specialist Systems can expose variant-specific labels and stages.
 */
type SystemVariant = 'intelligence' | 'expert_knowledge_capture' | 'translation_suite' | 'standard';

interface PipelineStage {
  key: string;
  name: string;
  icon: string;
  description: string;
  configureLabel: string;
  route: string;
  tone: 'brand' | 'violet' | 'emerald';
}

interface EffectiveRetrievalContext {
  knowledgeScope?: string;
  assistantProfile?: string;
  surface?: string;
  systemType?: string;
  collections: string[];
  retrievalDefaults?: Record<string, unknown>;
  grounding?: Record<string, unknown>;
  sourcePolicy?: Record<string, unknown>;
}

interface ContextConfigRow {
  key: string;
  value: string;
}

@Component({
  selector: 'app-system-view',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    NgClass,
    RouterLink,
    NavLinkDirective,
    ChatPanelComponent,
    IconComponent,
    StatusPulseComponent,
    RunOutcomeCardComponent,
    CkObjectHeaderComponent,
    CkTabsComponent,
    CkTabComponent,
    CkPanelComponent,
    NewsLabComponent,
    SystemPerspectiveComponent,
    SystemOverviewComponent,
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
        [tone]="headerStatusTone()"
        [label]="headerStatusLabel()"
      />
      @if (systemOverview()?.readiness?.can_run) {
        <a
          actions
          [navLink]="{ leaf: 'system-run', ref: systemId }"
          class="ck-btn-accent inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium transition"
          title="Open the published Flow in the Operator Runner"
          data-testid="system-operator-runner-link"
        >
          <app-icon name="play-circle" [size]="14" /> Operator Runner
        </a>
      }
      @if (!isExpertKnowledgeCapture() && !flowPublicationEnabled()) {
        <button
          actions
          type="button"
          (click)="triggerRun()"
          [disabled]="triggering() || isDraft()"
          class="inline-flex items-center gap-1.5 px-3 py-2 rounded text-xs font-medium ck-mono transition"
          style="letter-spacing:0.14em; text-transform:uppercase; background:var(--ck-signal-pos); color:var(--ck-on-signal);"
          [style.opacity]="triggering() || isDraft() ? '0.4' : '1'"
        >
          <app-icon name="play" [size]="12" />
          {{ triggering() ? 'Queueing…' : 'Run now' }}
        </button>
      }
      @if (isExpertKnowledgeCapture()) {
        <a
          actions
          [navLink]="{ leaf: 'system-capture-page', ref: systemId }"
          class="ck-cta inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium"
          [title]="i18n.t('systems.view.capture.cta.hint')"
        >
          <app-icon name="mic" [size]="14" /> {{ i18n.t('systems.view.capture.cta') }}
        </a>
      }
      @if (workOpenHref(); as workHref) {
        <a
          actions
          [navLink]="{ surface: 'work' }"
          class="ck-btn-quiet inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium"
        >{{ i18n.t('nav.open_in_work') }}</a>
      }
      <button
        actions
        type="button"
        (click)="chatPanelOpen.set(true)"
        class="ck-btn-quiet inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium"
        title="Open chat panel"
      >
        <app-icon name="message-square" [size]="14" /> Chat
      </button>
      @if (showSystemSettingsAction()) {
        <button
          actions
          type="button"
          (click)="settingsPanelOpen.set(true)"
          class="ck-btn-quiet inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium"
          title="Open settings panel"
        >
          <app-icon name="settings" [size]="14" /> Settings
        </button>
      }
    </ck-object-header>

    <ck-tabs
      [active]="activeTab()"
      (activeChange)="onTabChange($event)"
      ariaLabel="System facets"
    >
      @if (isIntelligence()) {
        <ck-tab id="intelligence" label="News Lab">
          <app-news-lab [systemId]="systemId" />
        </ck-tab>
      }

      <ck-tab id="overview" [label]="i18n.t('systems.view.tab.overview')">
        <app-system-overview
          [overview]="systemOverview()"
          [loading]="systemOverviewLoading()"
          [error]="systemOverviewError()"
          (retry)="loadSystemOverview()"
          (navigate)="goto($event)"
        />
      </ck-tab>

      <ck-tab id="runs" label="Runs">
        @if (system360Enabled()) {
          <app-system-perspective
            [lens]="activeObjectLens()"
            facet="runs"
            [perspective]="activePerspective()"
            [loading]="perspectivesLoading()"
            [error]="perspectivesError()"
          />
        } @else {
        <div class="space-y-4">
          <div class="flex items-center justify-between">
            <div>
              <h3 class="text-sm font-semibold text-white">Run outcomes</h3>
              @if (navigation.navV5Enabled()) {
                <a [navLink]="{ surface: 'runs' }" class="ck-mono text-xs" style="color:var(--ck-signal-cool);">
                  {{ i18n.t('nav.facet.see_in_runs') }}
                </a>
              }
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
                @if (flowPublicationEnabled()) {
                  Open <span class="text-white">Operator Runner</span> above, complete the required input, then execute the published Flow.
                } @else {
                  Click <span class="text-white">Run now</span> above to trigger a canonical run.
                }
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
        }
      </ck-tab>

      <ck-tab id="design" label="Design">
        @if (system360Enabled()) {
          <app-system-perspective
            [lens]="activeObjectLens()"
            facet="design"
            [perspective]="activePerspective()"
            [loading]="perspectivesLoading()"
            [error]="perspectivesError()"
          />
        } @else if (flowProfile(); as flow) {
          <div class="space-y-4" data-testid="system-flow-design">
            <div
              class="ck-surface rounded-md p-4 flex items-start gap-3"
              style="background: linear-gradient(135deg, rgba(139,92,246,0.08) 0%, rgba(0,188,212,0.08) 100%); border: 1px solid rgba(139,92,246,0.25);"
            >
              <div class="ck-tone-info w-10 h-10 rounded-md flex items-center justify-center shrink-0">
                <app-icon name="workflow" set="phosphor" [size]="18" />
              </div>
              <div class="flex-1 min-w-0">
                <div class="text-sm font-semibold text-white">Executable graph</div>
                <p class="text-xs text-gray-400 mt-0.5 leading-relaxed max-w-2xl">
                  {{ flowSummaryLine() }} {{ flowPublicationDetail() }}
                </p>
              </div>
              <a
                [navLink]="{ leaf: 'system-flow', ref: systemId }"
                class="ck-cta inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium shrink-0"
              >
                <app-icon name="workflow" [size]="14" /> Open in flow builder
              </a>
            </div>

            @if (flow.triggers.length > 0) {
              <section class="ck-surface t-elevated rounded-md p-5">
                <div class="flex items-center gap-2 mb-3">
                  <app-icon name="play-circle" [size]="16" class="ck-accent" />
                  <h3 class="text-sm font-semibold text-white">Triggers</h3>
                </div>
                <div class="flex flex-wrap gap-2">
                  @for (trigger of flow.triggers; track trigger.nodeId) {
                    <span class="ck-tone-neutral inline-flex items-center gap-2 rounded px-2.5 py-1.5">
                      <span class="ck-accent text-[10px] uppercase tracking-wider">{{ trigger.kind }}</span>
                      <span class="text-xs text-gray-200">{{ trigger.label }}</span>
                    </span>
                  }
                </div>
              </section>
            }

            <section class="ck-surface t-elevated rounded-md overflow-hidden">
              <div class="px-5 py-4 border-b border-white/5 flex items-center justify-between">
                <h3 class="text-sm font-semibold text-white flex items-center gap-1.5">
                  <app-icon name="layers" set="phosphor" [size]="16" class="ck-accent" />
                  Steps
                </h3>
                <span class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">
                  {{ flow.nodeCount }} nodes · {{ flow.edgeCount }} connections
                </span>
              </div>
              <ul>
                @for (step of flow.steps; track step.nodeId; let i = $index; let last = $last) {
                  <li
                    class="px-5 py-3 flex items-center gap-4"
                    [class.border-b]="!last"
                    [class.border-white\\/5]="!last"
                  >
                    <span class="ck-mono text-[10px] text-gray-500 w-6 shrink-0">{{ i + 1 }}</span>
                    <div class="flex-1 min-w-0">
                      <div class="flex items-center gap-2 flex-wrap">
                        <span class="text-sm font-medium text-white truncate">{{ step.label }}</span>
                        <span class="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-white/5 text-gray-400 ring-1 ring-white/10">
                          {{ step.kind }}
                        </span>
                        @if (step.runtimeStatus) {
                          <span
                            class="ck-pill"
                            [ngClass]="step.operational ? 'ck-tone-ok' : 'ck-tone-warn'"
                          >
                            {{ step.runtimeStatus }}
                          </span>
                        }
                      </div>
                      <p class="font-mono text-[11px] text-gray-500 mt-0.5 truncate">
                        {{ step.skillSlug || step.nodeId }}
                      </p>
                    </div>
                  </li>
                }
              </ul>
            </section>

            @if (flow.skillSlugs.length > 0) {
              <section class="ck-surface t-elevated rounded-md p-5">
                <div class="flex items-center gap-2 mb-3">
                  <app-icon name="zap" [size]="16" class="ck-accent" />
                  <h3 class="text-sm font-semibold text-white">Bound skills</h3>
                </div>
                <div class="flex flex-wrap gap-2">
                  @for (slug of flow.skillSlugs; track slug) {
                    <a
                      [navLink]="{ type: 'skill', ref: slug }"
                      class="ck-tone-info font-mono text-[11px] px-2 py-1 rounded"
                    >
                      {{ slug }}
                    </a>
                  }
                </div>
              </section>
            }
          </div>
        } @else {
        <div class="space-y-4">
        <!-- Orientation banner -->
        <div
          class="ck-surface rounded-md p-4 flex items-start gap-3"
          style="background: linear-gradient(135deg, rgba(139,92,246,0.08) 0%, rgba(0,188,212,0.08) 100%); border: 1px solid rgba(139,92,246,0.25);"
        >
          <div class="ck-tone-info w-10 h-10 rounded-md flex items-center justify-center shrink-0">
            <app-icon name="workflow" set="phosphor" [size]="18" />
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
            [navLink]="{ leaf: 'system-flow', ref: systemId }"
            class="ck-cta inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium shrink-0"
          >
            <app-icon name="workflow" [size]="14" /> Open in flow builder
          </a>
        </div>

        <!-- Pipeline stages — each with inline "Configure" action -->
        <section class="ck-surface t-elevated rounded-md overflow-hidden">
          <div class="px-5 py-4 border-b border-white/5 flex items-center justify-between">
            <h3 class="text-sm font-semibold text-white flex items-center gap-1.5">
              <app-icon name="layers" set="phosphor" [size]="16" class="ck-accent" />
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
                  class="w-11 h-11 rounded-md flex items-center justify-center shrink-0"
                  [ngClass]="stage.tone === 'emerald' ? 'ck-tone-ok' : 'ck-tone-info'"
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
      </ck-tab>

      <ck-tab id="context" label="Context">
        @if (system360Enabled()) {
          <app-system-perspective
            [lens]="activeObjectLens()"
            facet="context"
            [perspective]="activePerspective()"
            [loading]="perspectivesLoading()"
            [error]="perspectivesError()"
          />
        } @else {
        <div class="space-y-4">
        @if (contextLoading()) {
          <div class="ck-surface t-elevated rounded-md p-5 animate-pulse">
            <div class="h-3 w-40 bg-white/5 rounded mb-2"></div>
            <div class="h-3 w-64 bg-white/5 rounded"></div>
          </div>
        } @else if (!currentContext() && effectiveRetrievalContext(); as retrievalContext) {
          <section class="ck-surface t-elevated rounded-md p-5">
            <div class="flex items-start gap-3 mb-5">
              <div class="ck-tone-info w-9 h-9 rounded inline-flex items-center justify-center">
                <app-icon name="database" set="phosphor" [size]="16" />
              </div>
              <div class="min-w-0 flex-1">
                <div class="flex items-center gap-2 flex-wrap">
                  <h3 class="text-sm font-semibold text-white">Effective retrieval context</h3>
                  <span class="ck-pill ck-tone-ok">Runtime scoped</span>
                </div>
                <p class="text-xs text-gray-400 mt-1 leading-relaxed">
                  No dedicated Context row is attached. This System is scoped by its workspace chat retrieval profile.
                </p>
              </div>
              <div class="flex items-center gap-2 shrink-0">
                <a
                  [navLink]="{ surface: 'knowledge' }"
                  class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition"
                >
                  <app-icon name="database" [size]="12" /> Open Knowledge
                </a>
                <a
                  [navLink]="{ leaf: 'system-flow', ref: systemId }"
                  class="ck-cta inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium"
                >
                  <app-icon name="workflow" [size]="12" /> Open flow
                </a>
              </div>
            </div>

            <div class="grid grid-cols-1 md:grid-cols-4 gap-3 mb-4">
              <div class="rounded bg-black/20 ring-1 ring-white/10 p-3">
                <div class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold mb-1">Knowledge scope</div>
                <div class="font-mono text-xs text-gray-200 break-all">{{ retrievalContext.knowledgeScope || '—' }}</div>
              </div>
              <div class="rounded bg-black/20 ring-1 ring-white/10 p-3">
                <div class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold mb-1">Assistant profile</div>
                <div class="font-mono text-xs text-gray-200 break-all">{{ retrievalContext.assistantProfile || '—' }}</div>
              </div>
              <div class="rounded bg-black/20 ring-1 ring-white/10 p-3">
                <div class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold mb-1">Surface</div>
                <div class="font-mono text-xs text-gray-200 break-all">{{ retrievalContext.surface || '—' }}</div>
              </div>
              <div class="rounded bg-black/20 ring-1 ring-white/10 p-3">
                <div class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold mb-1">System type</div>
                <div class="font-mono text-xs text-gray-200 break-all">{{ retrievalContext.systemType || '—' }}</div>
              </div>
            </div>

            <div class="rounded bg-black/20 ring-1 ring-white/10 p-3 mb-4">
              <div class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold mb-2">Collections</div>
              @if (retrievalContext.collections.length === 0) {
                <div class="text-sm text-gray-500">—</div>
              } @else {
                <div class="flex flex-wrap gap-2">
                  @for (collection of retrievalContext.collections; track collection) {
                    <span class="ck-tone-info font-mono text-[11px] px-2 py-1 rounded">
                      {{ collection }}
                    </span>
                  }
                </div>
              }
            </div>

            <div class="grid grid-cols-1 lg:grid-cols-3 gap-3">
              <div class="rounded bg-black/20 ring-1 ring-white/10 p-3">
                <div class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold mb-2">Retrieval defaults</div>
                @if (retrievalDefaultsRows().length === 0) {
                  <div class="text-sm text-gray-500">—</div>
                } @else {
                  <dl class="space-y-1.5">
                    @for (row of retrievalDefaultsRows(); track row.key) {
                      <div class="grid grid-cols-[minmax(0,0.8fr)_minmax(0,1fr)] gap-2 text-xs">
                        <dt class="text-gray-500 font-mono truncate">{{ row.key }}</dt>
                        <dd class="text-gray-200 font-mono break-all">{{ row.value }}</dd>
                      </div>
                    }
                  </dl>
                }
              </div>
              <div class="rounded bg-black/20 ring-1 ring-white/10 p-3">
                <div class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold mb-2">Grounding</div>
                @if (groundingRows().length === 0) {
                  <div class="text-sm text-gray-500">—</div>
                } @else {
                  <dl class="space-y-1.5">
                    @for (row of groundingRows(); track row.key) {
                      <div class="grid grid-cols-[minmax(0,0.8fr)_minmax(0,1fr)] gap-2 text-xs">
                        <dt class="text-gray-500 font-mono truncate">{{ row.key }}</dt>
                        <dd class="text-gray-200 font-mono break-all">{{ row.value }}</dd>
                      </div>
                    }
                  </dl>
                }
              </div>
              <div class="rounded bg-black/20 ring-1 ring-white/10 p-3">
                <div class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold mb-2">Source policy</div>
                @if (sourcePolicyRows().length === 0) {
                  <div class="text-sm text-gray-500">—</div>
                } @else {
                  <dl class="space-y-1.5">
                    @for (row of sourcePolicyRows(); track row.key) {
                      <div class="grid grid-cols-[minmax(0,0.8fr)_minmax(0,1fr)] gap-2 text-xs">
                        <dt class="text-gray-500 font-mono truncate">{{ row.key }}</dt>
                        <dd class="text-gray-200 font-mono break-all">{{ row.value }}</dd>
                      </div>
                    }
                  </dl>
                }
              </div>
            </div>
          </section>
        } @else if (!currentContext()) {
          <div class="ck-surface t-elevated rounded-md p-8 text-center text-gray-400 text-sm">
            No dedicated Context attached. This System runs on the workspace default.
            <div class="mt-3">
              <a
                [navLink]="{ surface: 'contexts' }"
                class="ck-cta inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium"
              >
                <app-icon name="external-link" [size]="12" /> Manage contexts
              </a>
            </div>
          </div>
        } @else {
          <section class="ck-surface t-elevated rounded-md p-5">
            <div class="flex items-center gap-2 mb-4">
              <app-icon name="database" [size]="14" class="ck-accent" />
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
        }
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
          [navLink]="{ surface: 'presets' }"
          class="ck-cta inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium"
        >
          <app-icon name="sliders-horizontal" [size]="12" /> Edit in Settings
        </a>
        <a
          [routerLink]="workspaceAccessRoute()"
          class="ml-2 inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium bg-white/5 hover:bg-white/10 text-gray-200 ring-1 ring-white/10 transition"
        >
          <app-icon name="shield-check" [size]="12" /> Manage IAM
        </a>

        <section class="ck-surface t-elevated rounded-md p-5">
          <h3 class="text-sm font-semibold text-white mb-3 flex items-center gap-1.5">
            <app-icon name="tag" set="phosphor" [size]="14" class="ck-accent" /> Identity
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
        <section class="ck-surface t-elevated rounded-md p-5">
          <h3 class="text-sm font-semibold text-white mb-3 flex items-center gap-1.5">
            <app-icon name="cpu" set="phosphor" [size]="14" class="ck-accent" /> {{ isDemoMode() ? 'Runtime' : 'Model' }}
          </h3>
          <div class="space-y-3 text-sm text-gray-300">
            <div>
              {{ isDemoMode() ? 'Runtime policy:' : 'Default model:' }}
              <span class="text-white font-mono">{{ effectiveModel() }}</span>
              @if (!isDemoMode() && systemDefaults()?.default_model) {
                <span class="ck-pill ck-tone-info ml-1">override</span>
              }
            </div>
            <div>
              Reasoning template:
              <span class="text-white font-mono">{{ isDemoMode() ? 'managed' : (systemDefaults()?.default_prompt_type || 'auto') }}</span>
            </div>
            <div>Temperature: <span class="text-white font-mono">{{ isDemoMode() ? 'managed' : (settings.settings().temperature?.toFixed(2) ?? '—') }}</span></div>
            <div>Max tokens: <span class="text-white font-mono">{{ isDemoMode() ? 'managed' : (settings.settings().maxTokens ?? '—') }}</span></div>
          </div>
        </section>
        <section class="ck-surface t-elevated rounded-md p-5">
          <h3 class="text-sm font-semibold text-white mb-3 flex items-center gap-1.5">
            <app-icon name="database" set="phosphor" [size]="14" class="ck-accent" /> Retrieval
          </h3>
          <div class="space-y-3 text-sm text-gray-300">
            <div>
              Pipeline:
              <span class="text-white font-mono">{{ systemDefaults()?.retrieval_mode_default || settings.ragPipelineMode() || '—' }}</span>
              @if (systemDefaults()?.retrieval_mode_default && systemDefaults()?.retrieval_mode_default !== 'auto') {
                <span class="ck-pill ck-tone-info ml-1">pinned</span>
              }
            </div>
            <div>Top-K: <span class="text-white font-mono">{{ settings.settings().ragTopK ?? '—' }}</span></div>
            <div>Similarity: <span class="text-white font-mono">{{ settings.settings().ragSimilarityThreshold?.toFixed(2) ?? '—' }}</span></div>
            <div class="pt-1">
              <a
                [navLink]="{ surface: 'knowledge' }"
                class="ck-accent inline-flex items-center gap-1 text-xs"
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
      <div class="ck-surface t-elevated rounded-md p-0 overflow-hidden min-h-[520px]">
        <app-chat-panel [systemId]="systemId" />
      </div>
    </ck-panel>
  `,
})
export class SystemViewComponent implements OnInit, OnDestroy {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly store = inject(SystemsStore);
  private readonly api = inject(ApiService);
  private readonly canonical = inject(CanonicalApiService);
  private readonly toast = inject(ToastrService);
  private readonly workspace = inject(WorkspaceService);
  private readonly flowManifest = inject(FlowManifestService);
  readonly i18n = inject(I18nService);
  readonly settings = inject(SettingsService);
  readonly lensService = inject(LensService);
  readonly navigation = inject(ZoomContextService);
  private readonly workApi = inject(WorkApiService);
  readonly workOpenHref = signal(false);
  private systemRouteSubscription: Subscription | null = null;
  private facetRouteSubscription: Subscription | null = null;
  private viewSubscriptions = new Subscription();
  private refreshTimer: ReturnType<typeof setTimeout> | null = null;
  private readonly perspectiveCache = new Map<string, SystemPerspectiveResponse>();
  private readonly workspaceView = new WorkspaceViewContext(
    this.workspace,
    () => this.resetWorkspaceState(),
    () => this.reloadCurrentSystem(),
  );

  readonly runs = signal<Run[]>([]);
  readonly runsLoading = signal(false);
  readonly triggering = signal(false);
  readonly systemOverview = signal<SystemOverview | null>(null);
  readonly systemOverviewLoading = signal(false);
  readonly systemOverviewError = signal(false);

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
  readonly isExpertKnowledgeCapture = computed(() => this.variant() === 'expert_knowledge_capture');
  readonly isTranslationSuite = computed(() => this.variant() === 'translation_suite');
  readonly headerStatusTone = computed<'success' | 'warning' | 'danger' | 'accent'>(() => {
    switch (this.systemOverview()?.readiness.state) {
      case 'ready': return 'success';
      case 'blocked': return 'danger';
      case 'needs_setup': return 'warning';
      default: return 'accent';
    }
  });
  readonly headerStatusLabel = computed(() => {
    if (this.systemOverviewLoading()) return 'Checking';
    if (this.systemOverviewError()) return 'Unavailable';
    return this.systemOverview()?.readiness.label ?? 'Unknown';
  });
  readonly headerEyebrow = computed(() => {
    const type = this.isIntelligence()
      ? 'Systems · Intelligence'
      : this.isExpertKnowledgeCapture()
        ? this.i18n.t('systems.view.capture.eyebrow')
        : this.isTranslationSuite()
          ? 'PMI Sovereign Stack'
          : this.flowChromeActive()
            ? 'Systems · Flow'
            : 'Systems · System';
    if (!this.navigation.navV5Enabled()) return type;
    return this.i18n.t('nav.eyebrow.from_zone', {
      type,
      zone: this.i18n.t(this.navigation.zoneI18nKey()),
    });
  });
  readonly headerFallbackSubtitle = computed(() =>
    this.isIntelligence()
      ? 'Market-signal briefs and continuous monitoring.'
      : this.isExpertKnowledgeCapture()
        ? this.i18n.t('systems.view.capture.subtitle')
        : this.isTranslationSuite()
          ? 'Sovereign DITA translation, replay, agent QA, RBAC and audit-ready delivery.'
          : this.flowChromeActive()
            ? 'A graph the run engine executes, step by step.'
            : 'Configure, run and refine this AI system.',
  );

  /** Side panels — Settings and Chat live here, never as tabs. */
  readonly settingsPanelOpen = signal(false);
  readonly chatPanelOpen = signal(false);
  readonly isDemoMode = computed(() => this.workspace.isDemoSafeMode());
  readonly showSystemSettingsAction = computed(() => !this.isExpertKnowledgeCapture() || !this.isDemoMode());
  readonly flowPublicationEnabled = computed(() => {
    const current = this.workspace.current();
    const effective = current?.effective_features?.['flow_publication_v1'];
    if (typeof effective === 'boolean') return effective;
    const settings = asRecord(current?.settings) ?? {};
    const features = asRecord(settings['features']) ?? {};
    // Match the backend rollout contract: publication is on unless a
    // workspace explicitly stores false. Missing is not an opt-out.
    return features['flow_publication_v1'] !== false;
  });

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
    if (this.isDemoMode()) return 'Managed by workspace';
    const d = this.systemDefaults();
    return d?.default_model || this.settings.settings().defaultModel || '—';
  });

  readonly workspaceAccessRoute = computed(() => {
    const slug = this.workspace.current()?.slug || this.workspace.currentSlug();
    return slug
      ? `/workspace/${encodeURIComponent(slug)}/access`
      : this.navigation.leafUrl('governance-access');
  });

  readonly systemSnapshot = signal<System | null>(null);

  /**
   * Non-null only when the persisted graph proves the run engine walks it.
   * Every facet that would otherwise describe an OmniRAG pipeline reads this
   * first, so a System without that proof keeps its historical rendering.
   */
  readonly flowProfile = computed(() => {
    const system = this.systemSnapshot();
    if (!system) return null;
    const manifest = this.flowManifest.manifest();
    return systemFlowProfile(
      system,
      manifest?.system_id === system.id ? manifest : null,
    );
  });
  /**
   * The System 360 projection owns every facet when it is enabled, so the
   * header must keep naming what the body renders. Naming the graph while the
   * projection is on screen would also make the eyebrow flip once the async
   * manifest lands, and the 360 canary asserts that chrome is invariant.
   */
  readonly flowChromeActive = computed(
    () => !this.system360Enabled() && this.flowProfile() !== null,
  );
  readonly flowPublicationLabel = computed(() =>
    this.flowProfile()?.publishedVersionId ? 'Published' : 'Draft only',
  );
  readonly flowPublicationDetail = computed(() => {
    const flow = this.flowProfile();
    if (!flow) return '';
    if (!flow.publishedVersionId) {
      return 'No published version yet — runs execute the saved draft.';
    }
    const by = flow.publishedBy ? ` by ${flow.publishedBy}` : '';
    const at = flow.publishedAt ? ` on ${flow.publishedAt.slice(0, 10)}` : '';
    return `Published${at}${by}.`;
  });
  readonly flowSummaryLine = computed(() => {
    const flow = this.flowProfile();
    if (!flow) return '';
    const parts = [
      `${flow.nodeCount} ${flow.nodeCount === 1 ? 'step' : 'steps'}`,
      `${flow.edgeCount} ${flow.edgeCount === 1 ? 'connection' : 'connections'}`,
      `${flow.triggers.length} ${flow.triggers.length === 1 ? 'trigger' : 'triggers'}`,
      `${flow.skillSlugs.length} bound ${flow.skillSlugs.length === 1 ? 'skill' : 'skills'}`,
    ];
    return `${parts.join(' · ')}.`;
  });
  readonly perspectives = signal<Partial<Record<ObjectLens, SystemPerspectiveResponse>>>({});
  readonly perspectivesLoading = signal(false);
  readonly perspectivesError = signal(false);
  readonly activeObjectLens = computed<ObjectLens>(() => {
    const lens = this.lensService.lens();
    return isObjectLens(lens) ? lens : 'build';
  });
  readonly system360Enabled = computed(() => {
    const workspaceSettings = asRecord(this.workspace.current()?.settings) ?? {};
    const features = asRecord(workspaceSettings['features']) ?? {};
    const systemSettings = asRecord(this.systemSnapshot()?.settings) ?? {};
    const experience = asRecord(systemSettings['experience']) ?? {};
    return (
      features['cockpit_router_axes_v4'] === true &&
      features['system_360_projection_v1'] === true &&
      experience['system_360_canary'] === 'v1'
    );
  });
  readonly activePerspective = computed(
    () => this.perspectives()[this.activeObjectLens()] ?? null,
  );
  readonly currentContext = signal<import('@app/core/canonical-api.service').Context | null>(null);
  readonly contextLoading = signal(false);
  readonly effectiveRetrievalContext = computed(() => buildEffectiveRetrievalContext(this.systemSnapshot()));
  readonly retrievalDefaultsRows = computed(() =>
    contextRows(this.effectiveRetrievalContext()?.retrievalDefaults),
  );
  readonly groundingRows = computed(() => contextRows(this.effectiveRetrievalContext()?.grounding));
  readonly sourcePolicyRows = computed(() => contextRows(this.effectiveRetrievalContext()?.sourcePolicy));

  readonly permissionsPreview = computed(() => {
    const p = this.currentContext()?.permissions ?? {};
    const keys = Object.keys(p);
    if (!keys.length) return '—';
    return JSON.stringify(p, null, 2);
  });

  /**
   * Object-level KPIs rendered in the persistent `<ck-object-header>`.
   * Values not yet tracked render as `—` — better to show the slot and admit
   * ignorance than fake a number. See mental-model §6.
   *
   * The current lens is threaded in as a hint so future iterations can
   * adapt the *set* of KPIs per lens (e.g. Govern highlights audit
   * deltas); for now all lenses share the same KPI set.
   */
  readonly objectKpis = computed<CkObjectKpi[]>(() => {
    const overview = this.systemOverview();
    const success = overview?.runs.success_rate;
    return [
      {
        label: 'Status',
        value: overview?.readiness.label ?? 'Unknown',
        tone: overview?.readiness.state === 'ready' ? 'pos' : 'neutral',
      },
      {
        label: 'Runs',
        value: overview ? String(overview.runs.total) : '—',
        tone: 'neutral',
      },
      {
        label: 'Success',
        value: success == null ? 'Not measured' : `${success}%`,
        tone: success == null ? 'neutral' : 'cool',
      },
    ];
  });

  loadSystemOverview(): void {
    const systemId = this.systemId;
    if (!systemId) return;
    this.systemOverviewLoading.set(true);
    this.systemOverviewError.set(false);
    const subscription = this.canonical.getSystemOverview(systemId).subscribe({
      next: (overview) => {
        if (systemId !== this.systemId) return;
        this.systemOverview.set(overview);
        this.systemOverviewLoading.set(false);
      },
      error: () => {
        if (systemId !== this.systemId) return;
        this.systemOverview.set(null);
        this.systemOverviewLoading.set(false);
        this.systemOverviewError.set(true);
      },
    });
    this.viewSubscriptions.add(subscription);
  }

  onTabChange(id: string): void {
    this.activeTab.set(id as SystemTabId);
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { facet: id },
      queryParamsHandling: 'merge',
      replaceUrl: true,
    });
  }

  get pipelineStages(): PipelineStage[] {
    if (this.isTranslationSuite()) {
      return [
        {
          key: 'archive',
          name: 'Ingest',
          icon: 'archive',
          description: 'Validate DITA archive, manifest hash and topic inventory.',
          configureLabel: 'Source',
          route: this.navigation.leafUrl('system-flow', { systemId: this.systemId }),
          tone: 'brand',
        },
        {
          key: 'memory',
          name: 'Memory',
          icon: 'database',
          description: 'Retrieve reviewed bilingual examples from sovereign translation memory.',
          configureLabel: 'Knowledge',
          route: this.navigation.surfaceUrl('knowledge'),
          tone: 'violet',
        },
        {
          key: 'pivot',
          name: 'F1 Pivot',
          icon: 'workflow',
          description: 'Normalize source DITA into a deterministic en-GB pivot.',
          configureLabel: 'Flow',
          route: this.navigation.leafUrl('system-flow', { systemId: this.systemId }),
          tone: 'brand',
        },
        {
          key: 'fanout',
          name: 'F2 Fan-out',
          icon: 'globe-2',
          description: 'Translate the pivot into 39 target locales with bounded parallelism.',
          configureLabel: 'Runtime',
          route: this.navigation.leafUrl('system-flow', { systemId: this.systemId }),
          tone: 'violet',
        },
        {
          key: 'qa',
          name: 'J2450 QA',
          icon: 'list-checks',
          description: 'Run seven category agents and supervisor convergence.',
          configureLabel: 'Guardrails',
          route: this.navigation.surfaceUrl('workspace-blueprints'),
          tone: 'emerald',
        },
        {
          key: 'delivery',
          name: 'Gate',
          icon: 'shield-check',
          description: 'Apply CDC E1 guards, CDT approval and ACCEPT_4D delivery evidence.',
          configureLabel: 'Audit',
          route: this.navigation.leafUrl('governance-audit'),
          tone: 'emerald',
        },
      ];
    }
    if (this.isExpertKnowledgeCapture()) {
      return [
        {
          key: 'plan',
          name: this.i18n.t('systems.view.stage.plan'),
          icon: 'list-checks',
          description: this.i18n.t('systems.view.stage.plan.desc'),
          configureLabel: this.i18n.t('systems.view.capture.cta'),
          route: this.navigation.leafUrl('system-capture-page', { systemId: this.systemId }),
          tone: 'brand',
        },
        {
          key: 'voice',
          name: this.i18n.t('systems.view.stage.voice'),
          icon: 'mic',
          description: this.i18n.t('systems.view.stage.voice.desc'),
          configureLabel: this.i18n.t('systems.view.capture.cta'),
          route: this.navigation.leafUrl('system-capture-page', { systemId: this.systemId }),
          tone: 'violet',
        },
        {
          key: 'retrieve',
          name: this.i18n.t('systems.view.stage.sources'),
          icon: 'database',
          description: this.i18n.t('systems.view.stage.sources.desc'),
          configureLabel: this.i18n.t('systems.view.stage.sources'),
          route: this.navigation.surfaceUrl('knowledge'),
          tone: 'brand',
        },
        {
          key: 'proposal',
          name: this.i18n.t('systems.view.stage.report'),
          icon: 'check-circle-2',
          description: this.i18n.t('systems.view.stage.report.desc'),
          configureLabel: this.i18n.t('systems.view.stage.report'),
          route: this.navigation.leafUrl('system-flow', { systemId: this.systemId }),
          tone: 'emerald',
        },
      ];
    }
    return [
      {
        key: 'query',
        name: 'Query',
        icon: 'message-square',
        description: 'User intent parsing, query rewriting and routing.',
        configureLabel: 'System prompt',
        route: this.navigation.surfaceUrl('presets'),
        tone: 'brand',
      },
      {
        key: 'retrieve',
        name: 'Retrieve',
        icon: 'database',
        description: 'Planner-bounded retrieval over your collections.',
        configureLabel: 'Collections',
        route: this.navigation.surfaceUrl('knowledge'),
        tone: 'violet',
      },
      {
        key: 'rerank',
        name: 'Rerank',
        icon: 'filter',
        description: 'Cross-encoder reranking + context filtering.',
        configureLabel: 'Top-K & threshold',
        route: this.navigation.surfaceUrl('presets'),
        tone: 'brand',
      },
      {
        key: 'generate',
        name: 'Generate',
        icon: 'sparkles',
        description: 'LLM synthesis with citations and guardrails.',
        configureLabel: 'Model',
        route: this.navigation.surfaceUrl('presets'),
        tone: 'emerald',
      },
    ];
  }

  goto(path: string): void {
    this.router.navigateByUrl(path);
  }

  ngOnInit(): void {
    if (this.workspace.experienceV1Enabled()) {
      this.workApi.listExperiences().subscribe((result) => {
        this.workOpenHref.set(result.kind === 'ok' && result.items.length > 0);
      });
    }
    this.systemRouteSubscription = this.route.paramMap.pipe(
      map((params) => params.get('systemId') ?? ''),
      distinctUntilChanged(),
    ).subscribe((systemId) => {
      this.workspaceView.invalidate();
      this.cancelViewRequests();
      this.systemId = systemId;
      this.clearSystemData();
      this.reloadCurrentSystem();
    });
    this.facetRouteSubscription = this.route.queryParamMap.pipe(
      map((params) => params.get('facet')),
      distinctUntilChanged(),
    ).subscribe(() => this.applyRequestedFacet());
  }

  ngOnDestroy(): void {
    this.systemRouteSubscription?.unsubscribe();
    this.systemRouteSubscription = null;
    this.facetRouteSubscription?.unsubscribe();
    this.facetRouteSubscription = null;
    this.workspaceView.destroy();
  }

  /**
   * Fetch the canonical System row and derive the variant marker from
   * `flow_definition.variant`. When the URL carries `?facet=<id>`, the
   * matching tab is auto-activated — this is how `/intelligence` opens
   * directly on the News Lab facet without a second click.
   */
  private loadVariantAndApplyFacet(request: WorkspaceViewRequest, systemId: string): void {
    if (!systemId) return;
    const subscription = this.canonical.getSystem(systemId).subscribe({
      next: (sys: System | null) => {
        if (!this.requestIsCurrent(request, systemId)) return;
        this.systemSnapshot.set(sys);
        const flow = (sys?.flow_definition ?? {}) as Record<string, unknown>;
        const variant = String(flow['variant'] ?? '').toLowerCase();
        if (variant === 'intelligence') {
          this.variant.set('intelligence');
        } else if (variant === 'expert_knowledge_capture') {
          this.variant.set('expert_knowledge_capture');
        } else if (variant === 'translation_suite') {
          this.variant.set('translation_suite');
        } else {
          this.variant.set('standard');
        }
        // The runtime sidecar is fetched only once the persisted graph already
        // proves a run-engine flow: it refines that verdict, it never opens it.
        if (isFlowBackedSystem(sys)) this.flowManifest.ensureLoaded(systemId);
        if (this.system360Enabled()) {
          this.loadPerspectives(request, systemId);
        } else {
          this.perspectives.set({});
          this.perspectivesLoading.set(false);
          this.perspectivesError.set(false);
        }
        this.applyRequestedFacet();
      },
      error: () => {
        if (!this.requestIsCurrent(request, systemId)) return;
        this.systemSnapshot.set(null);
        this.applyRequestedFacet();
      },
    });
    this.viewSubscriptions.add(subscription);
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

  private loadContext(request: WorkspaceViewRequest, systemId: string): void {
    if (!systemId) return;
    this.contextLoading.set(true);
    const subscription = this.canonical.listContexts({ system_id: systemId }).subscribe({
      next: (ctxList) => {
        if (!this.requestIsCurrent(request, systemId)) return;
        this.currentContext.set((ctxList ?? [])[0] ?? null);
        this.contextLoading.set(false);
      },
      error: () => {
        if (!this.requestIsCurrent(request, systemId)) return;
        this.currentContext.set(null);
        this.contextLoading.set(false);
      },
    });
    this.viewSubscriptions.add(subscription);
  }

  private loadPerspectives(request: WorkspaceViewRequest, systemId: string): void {
    const workspaceSlug = request.scope.workspaceSlug;
    const window = '30d';
    this.perspectivesLoading.set(true);
    this.perspectivesError.set(false);
    const subscription = forkJoin(
      SYSTEM_OBJECT_LENSES.map((lens) => {
        const cacheKey = this.perspectiveCacheKey(request, systemId, lens, window);
        const cached = this.perspectiveCache.get(cacheKey);
        if (cached) return of(cached);
        return this.api
          .get<SystemPerspectiveResponse>(
            `/systems/${encodeURIComponent(systemId)}/perspective`,
            { lens, window },
            { workspaceSlug },
          )
          .pipe(catchError(() => of(null)));
      }),
    ).subscribe((responses) => {
      if (!this.requestIsCurrent(request, systemId)) return;
      const next: Partial<Record<ObjectLens, SystemPerspectiveResponse>> = {};
      const expectedWorkspaceId = this.systemSnapshot()?.workspace_id;
      for (const [index, response] of responses.entries()) {
        const requestedLens = SYSTEM_OBJECT_LENSES[index];
        if (
          response &&
          response.schema_version === 1 &&
          response.identity?.system_id === systemId &&
          (!expectedWorkspaceId || response.identity.workspace_id === expectedWorkspaceId) &&
          response.lens === requestedLens
        ) {
          next[requestedLens] = response;
          this.perspectiveCache.set(
            this.perspectiveCacheKey(request, systemId, requestedLens, window),
            response,
          );
        }
      }
      this.perspectives.set(next);
      this.perspectivesLoading.set(false);
      this.perspectivesError.set(Object.keys(next).length !== SYSTEM_OBJECT_LENSES.length);
    });
    this.viewSubscriptions.add(subscription);
  }

  private perspectiveCacheKey(
    request: WorkspaceViewRequest,
    systemId: string,
    lens: ObjectLens,
    window: string,
  ): string {
    return [request.scope.epoch, request.scope.workspaceSlug, systemId, lens, window].join(':');
  }

  loadRuns(
    request = this.workspaceView.captureRequest(),
    systemId = this.systemId,
  ): void {
    if (!systemId) return;
    this.runsLoading.set(true);
    const subscription = this.canonical.listRuns({ system_id: systemId }).subscribe({
      next: (list) => {
        if (!this.requestIsCurrent(request, systemId)) return;
        this.runs.set(list ?? []);
        this.runsLoading.set(false);
      },
      error: () => {
        if (!this.requestIsCurrent(request, systemId)) return;
        this.runs.set([]);
        this.runsLoading.set(false);
      },
    });
    this.viewSubscriptions.add(subscription);
  }

  triggerRun(): void {
    if (this.triggering() || !this.systemId || this.isDraft()) return;
    const systemId = this.systemId;
    const expectedFlowSha256 = this.systemSnapshot()?.flow_sha256;
    if (!expectedFlowSha256) {
      this.toast.warning(
        'Reload this System before running it: its Flow revision is unavailable.',
        'Run not triggered',
      );
      return;
    }
    const request = this.workspaceView.captureRequest();
    this.triggering.set(true);
    const inputRef = this.isTranslationSuite()
      ? {
          suite: 'Translation Suite',
          source_lang: 'fr-FR',
          pivot_lang: 'en-GB',
          target_lang_count: 39,
          archive_ref: 'dita://pmi/kangoo3/owner_manual/source/fr-FR/archive.zip',
          manifest_sha256: '7b8d1a9a6c2f76c2f3d6f2d4e16e4b90b2ef9e74fbd0a2f2a6f9f1b8e8c2d01d',
          llm_provider: 'sovereign_vllm',
          model: 'unsloth/gpt-oss-20b-BF16',
          embedding_model: 'BAAI/bge-m3',
          limit_qa_loop: 5,
          num_parallel_topics: 5,
          external_llm_egress: false,
          replay_supported: true,
          cdt_gate_required: true,
        }
      : {};
    const subscription = this.canonical.triggerRun(systemId, {
      trigger: 'manual',
      input_ref: inputRef,
      expected_flow_sha256: expectedFlowSha256,
    }).subscribe({
      next: (run) => {
        if (!this.requestIsCurrent(request, systemId)) return;
        this.triggering.set(false);
        if (!run) {
          this.toast.warning('Could not reach the run engine', 'Run not triggered');
          return;
        }
        this.toast.success(`Run ${run.id.slice(0, 8)} scheduled`, 'Run triggered');
        this.loadRuns(request, systemId);
        // Refresh once the engine has had time to execute the sequence.
        this.refreshTimer = setTimeout(() => {
          this.refreshTimer = null;
          if (this.requestIsCurrent(request, systemId)) this.loadRuns(request, systemId);
        }, 3500);
      },
      error: (error: unknown) => {
        if (!this.requestIsCurrent(request, systemId)) return;
        this.triggering.set(false);
        this.toast.warning(
          apiErrorMessage(error, 'Could not reach the run engine'),
          'Run not triggered',
        );
      },
    });
    this.viewSubscriptions.add(subscription);
  }

  private reloadCurrentSystem(): void {
    const systemId = this.systemId || this.route.snapshot.paramMap.get('systemId') || '';
    if (!systemId) return;
    this.systemId = systemId;
    this.cancelViewRequests();
    const request = this.workspaceView.beginRequest();
    this.settings.refresh();

    const local = this.store.findById(systemId);
    if (local) {
      this.applyAgent(local);
    } else {
      const subscription = this.store.getById(systemId).subscribe({
        next: (agent) => {
          if (!agent || !this.requestIsCurrent(request, systemId)) return;
          this.applyAgent(agent);
        },
        error: () => undefined,
      });
      this.viewSubscriptions.add(subscription);
    }

    this.loadVariantAndApplyFacet(request, systemId);
    this.loadSystemOverview();
    this.loadRuns(request, systemId);
    this.loadContext(request, systemId);
  }

  private applyAgent(agent: import('./systems.store').SystemAgent): void {
    this.agentName.set(agent.name);
    this.agentDescription.set(agent.description || '');
    this.isDraft.set(!!agent.draft);
    this.systemDefaults.set({
      default_prompt_type: agent.default_prompt_type ?? null,
      default_model: agent.default_model ?? null,
      retrieval_mode_default: agent.retrieval_mode_default ?? null,
      execution_mode: (agent as unknown as { execution_mode?: string | null }).execution_mode ?? null,
    });
  }

  private requestIsCurrent(request: WorkspaceViewRequest, systemId: string): boolean {
    return this.workspaceView.isCurrent(request) && systemId === this.systemId;
  }

  private cancelViewRequests(): void {
    this.viewSubscriptions.unsubscribe();
    this.viewSubscriptions = new Subscription();
    if (this.refreshTimer !== null) {
      clearTimeout(this.refreshTimer);
      this.refreshTimer = null;
    }
  }

  private clearSystemData(): void {
    this.agentName.set('System');
    this.agentDescription.set('');
    this.isDraft.set(false);
    this.variant.set('standard');
    this.activeTab.set('overview');
    this.systemDefaults.set(null);
    this.systemSnapshot.set(null);
    this.perspectives.set({});
    this.perspectivesLoading.set(false);
    this.perspectivesError.set(false);
    this.currentContext.set(null);
    this.contextLoading.set(false);
    this.runs.set([]);
    this.runsLoading.set(false);
    this.triggering.set(false);
    this.systemOverview.set(null);
    this.systemOverviewLoading.set(false);
    this.systemOverviewError.set(false);
  }

  private resetWorkspaceState(): void {
    this.cancelViewRequests();
    this.perspectiveCache.clear();
    this.clearSystemData();
    this.settingsPanelOpen.set(false);
    this.chatPanelOpen.set(false);
  }
}

function buildEffectiveRetrievalContext(system: System | null): EffectiveRetrievalContext | null {
  if (!system) return null;
  const settings = asRecord(system.settings) ?? {};
  const flow = asRecord(system.flow_definition) ?? {};
  const chat = asRecord(flow['chat']) ?? {};

  const retrievalDefaults =
    asRecord(settings['retrieval_defaults']) ??
    asRecord(settings['retrieval']) ??
    asRecord(chat['retrieval_defaults']) ??
    asRecord(chat['retrieval']);
  const grounding = asRecord(settings['grounding']) ?? asRecord(chat['grounding']);
  const sourcePolicy =
    asRecord(settings['source_policy']) ??
    asRecord(chat['source_policy']) ??
    asRecord(flow['source_policy']);

  const collections = uniqueStrings([
    ...asStringArray(settings['collection_slugs']),
    ...asStringArray(settings['collections']),
    ...asStringArray(chat['collection_slugs']),
    ...asStringArray(chat['collections']),
    ...asStringArray(flow['collection_slugs']),
    ...asStringArray(flow['collections']),
  ]);

  const context: EffectiveRetrievalContext = {
    knowledgeScope: firstString(settings['knowledge_scope'], chat['knowledge_scope'], flow['knowledge_scope']),
    assistantProfile: firstString(settings['assistant_profile'], chat['assistant_profile'], flow['assistant_profile']),
    surface: firstString(settings['surface'], chat['surface'], flow['surface']),
    systemType: firstString(
      settings['system_type'],
      flow['system_type'],
      (system as unknown as { type?: unknown }).type,
    ),
    collections,
    retrievalDefaults: retrievalDefaults ?? undefined,
    grounding: grounding ?? undefined,
    sourcePolicy: sourcePolicy ?? undefined,
  };

  const hasContext =
    !!context.knowledgeScope ||
    !!context.assistantProfile ||
    !!context.surface ||
    collections.length > 0 ||
    !!retrievalDefaults ||
    !!grounding ||
    !!sourcePolicy;
  return hasContext ? context : null;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

function firstString(...values: unknown[]): string | undefined {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return undefined;
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => {
      if (typeof item === 'string') return item;
      const record = asRecord(item);
      return firstString(record?.['slug'], record?.['collection_slug'], record?.['id'], record?.['name']);
    })
    .filter((item): item is string => !!item && !!item.trim())
    .map((item) => item.trim());
}

function uniqueStrings(values: string[]): string[] {
  return [...new Set(values)];
}

function contextRows(record?: Record<string, unknown>): ContextConfigRow[] {
  if (!record) return [];
  return Object.entries(record).map(([key, value]) => ({
    key,
    value: formatContextValue(value),
  }));
}

function formatContextValue(value: unknown): string {
  if (value == null) return '—';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function perspectiveHeaderValue(fact: PerspectiveFact | undefined, suffix = ''): string {
  if (!fact) return 'Loading';
  if (fact.state === 'not_measured') return 'Not measured';
  if (fact.state === 'not_configured') return 'Not configured';
  if (fact.state === 'restricted') return 'Restricted';
  if (fact.state === 'unavailable') return 'Unavailable';
  if (fact.value == null) return 'Unavailable';
  return `${String(fact.value)}${suffix || fact.unit || ''}`;
}

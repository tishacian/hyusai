/**
 * Canonical `/runs/:runId` detail view.
 *
 * Shows the Run timeline (skill invocations), input/outcome payloads,
 * errors and checkpoints. Replaces the legacy trace drawer — the Run is
 * now a full-page drill-down, reachable from Systems, Runs list, or any
 * Decision trail that references it.
 */
import { ChangeDetectionStrategy, Component, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { Subscription, distinctUntilChanged, map } from 'rxjs';
import { IconComponent } from '@app/shared/ui/icon.component';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import { HelpTooltipComponent, PageFrameComponent, RunOutcomeCardComponent } from '@app/shared/cockpit';
import { CkObjectHeaderComponent, type CkObjectKpi } from '@app/shared/cockpit/object-header.component';
import { CkTabComponent, CkTabsComponent } from '@app/shared/cockpit/tabs.component';
import { ObjectPerspectiveComponent } from '@app/shared/cockpit/object-perspective.component';
import type { ObjectPerspectiveResponse } from '@app/shared/cockpit/object-perspective.models';
import { CanonicalApiService, type RetrievalDecisionTrace, type Run, type SkillInvocation } from '@app/core/canonical-api.service';
import { I18nService } from '@app/core/i18n.service';
import { LensService } from '@app/core/lens';
import { isObjectLens, type ObjectLens } from '@app/core/navigation.catalog';
import {
  ObjectPerspectiveGateRevokedError,
  ObjectPerspectiveStore,
} from '@app/core/object-perspective.store';
import { ZoomContextService } from '@app/core/zoom-context.service';
import { WorkspaceService, type WorkspaceRequestScope } from '@app/core/workspace.service';
import { WorkspaceViewContext, type WorkspaceViewRequest } from '@app/core/workspace-view-context';

@Component({
  selector: 'app-run-view',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    IconComponent,
    EmptyStateComponent,
    PageFrameComponent,
    RunOutcomeCardComponent,
    HelpTooltipComponent,
    CkObjectHeaderComponent,
    CkTabsComponent,
    CkTabComponent,
    ObjectPerspectiveComponent,
  ],
  template: `
    @if (projectionEnabled()) {
      <ck-object-header
        [eyebrow]="i18n.t('runs.detail.eyebrow')"
        [title]="titleLabel()"
        [subtitle]="descriptionLabel()"
        [kpis]="perspectiveKpis()"
      >
        <div actions class="inline-flex items-center gap-2">
          <a routerLink="/runs" class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition">
            <app-icon name="arrow-left" [size]="12" /> {{ i18n.t('runs.detail.all_runs') }}
          </a>
          @if (run()?.system_id) {
            <a
              [routerLink]="navigation.objectUrlTree('system', run()!.system_id, {
                capabilityId: run()!.capability_id || navigation.capabilityId()
              })"
              class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition"
            ><app-icon name="box" [size]="12" /> {{ i18n.t('runs.detail.open_system') }}</a>
          }
          <button type="button" (click)="refresh(true)" [disabled]="loading()" class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition">
            <app-icon name="refresh-cw" [size]="12" [class.animate-spin]="loading()" /> {{ i18n.t('common.refresh') }}
          </button>
        </div>
      </ck-object-header>

      <ck-tabs [active]="activePerspectiveTab()" (activeChange)="onPerspectiveTabChange($event)" [ariaLabel]="i18n.t('runs.detail.facets_aria')">
        <ck-tab id="overview" [label]="i18n.t('runs.detail.tab.overview')">
          <ck-object-perspective [objectLabel]="i18n.t('runs.detail.object_label')" [lens]="activeLens()" facet="overview" [perspective]="activePerspective()" [loading]="perspectivesLoading()" [error]="perspectivesError()" />
        </ck-tab>
        <ck-tab id="invocations" [label]="i18n.t('runs.detail.tab.invocations')">
          <ck-object-perspective [objectLabel]="i18n.t('runs.detail.object_label')" [lens]="activeLens()" facet="invocations" [perspective]="activePerspective()" [loading]="perspectivesLoading()" [error]="perspectivesError()" />
          @if (skillInvocationProjectionEnabled() && skillInvocations().length > 0) {
            <section class="ck-surface rounded-md p-4 mt-4" data-testid="run-skill-invocation-links">
              <h3 class="text-xs font-semibold text-white mb-3">{{ i18n.t('runs.detail.invocations.title') }}</h3>
              <div class="flex flex-col gap-2">
                @for (inv of skillInvocations(); track inv.id || $index) {
                  @if (inv.id) {
                    <a
                      [routerLink]="['/runs', runId(), 'invocations', inv.id]"
                      [queryParams]="{
                        lens: activeLens(),
                        capabilityId: run()!.capability_id || navigation.capabilityId(),
                        systemId: run()!.system_id
                      }"
                      class="flex items-center justify-between gap-3 rounded px-3 py-2 bg-white/[0.03] hover:bg-white/[0.07] ring-1 ring-white/10 text-xs"
                    >
                      <span class="font-mono text-cyan-200">{{ inv.skill_slug || inv.skill_id || inv.id }}</span>
                      <span class="text-gray-400">{{ statusLabel(inv.status || 'unknown') }}</span>
                    </a>
                  }
                }
              </div>
            </section>
          }
        </ck-tab>
        <ck-tab id="payloads" [label]="i18n.t('runs.detail.tab.payloads')">
          <ck-object-perspective [objectLabel]="i18n.t('runs.detail.object_label')" [lens]="activeLens()" facet="payloads" [perspective]="activePerspective()" [loading]="perspectivesLoading()" [error]="perspectivesError()" />
        </ck-tab>
        <ck-tab id="checkpoints" [label]="i18n.t('runs.detail.checkpoints')">
          <ck-object-perspective [objectLabel]="i18n.t('runs.detail.object_label')" [lens]="activeLens()" facet="checkpoints" [perspective]="activePerspective()" [loading]="perspectivesLoading()" [error]="perspectivesError()" />
        </ck-tab>
      </ck-tabs>
    } @else {
    <ck-page-frame
      [eyebrow]="i18n.t('runs.list.eyebrow')"
      [title]="titleLabel()"
      [description]="descriptionLabel()"
      [status]="statusLabel(run()?.status)"
    >
      <div actions [style.display]="'inline-flex'" [style.alignItems]="'center'" [style.gap.px]="6">
        <a
          routerLink="/runs"
          class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition"
        >
          <app-icon name="arrow-left" [size]="12" />
          {{ i18n.t('runs.detail.all_runs') }}
        </a>
        @if (run()?.system_id) {
          <a
            [routerLink]="navigation.objectUrlTree('system', run()!.system_id, {
              capabilityId: run()!.capability_id || navigation.capabilityId()
            })"
            class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition"
          >
            <app-icon name="box" [size]="12" />
            {{ i18n.t('runs.detail.open_system') }}
          </a>
        }
        <button
          type="button"
          class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition"
          (click)="refresh(true)"
          [disabled]="loading()"
        >
          <app-icon name="refresh-cw" [size]="12" [class.animate-spin]="loading()" />
          {{ i18n.t('common.refresh') }}
        </button>
        @if (rerunnable()) {
          <button
            type="button"
            class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition"
            (click)="rerun()"
            [disabled]="rerunning()"
            [title]="i18n.t('runs.detail.rerun_hint')"
          >
            <app-icon name="history" [size]="12" />
            {{ rerunning() ? i18n.t('runs.detail.rerunning') : i18n.t('runs.detail.rerun') }}
          </button>
        }
      </div>

      @if (loading() && !run()) {
        <div class="animate-pulse space-y-3">
          <div class="h-24 bg-white/[0.03] rounded-lg"></div>
          <div class="h-64 bg-white/[0.03] rounded-lg"></div>
        </div>
      } @else if (!run()) {
        <app-empty-state
          icon="alert-triangle"
          [title]="i18n.t('runs.detail.not_found.title')"
          [description]="i18n.t('runs.detail.not_found.description')"
        />
      } @else {
        <!-- Canonical Outcome card — value / cost / confidence / efficiency + decision. -->
        <div class="mb-6">
          <ck-run-outcome-card [run]="run()!" />

          <!-- Operator override strip — live next to the Outcome so operators
               can declare "actual" value when the auto-derivation is off. -->
          <div class="mt-3 rounded-lg border border-white/5 bg-white/[0.02] p-3">
            <div class="flex items-center gap-3 flex-wrap">
              <div class="flex items-center gap-2">
                <span class="text-[10px] uppercase tracking-wider text-gray-500 font-mono">
                  {{ i18n.t('runs.detail.value_source.label') }}
                </span>
                <span
                  class="text-[10px] uppercase tracking-wider font-mono px-1.5 py-0.5 rounded"
                  [class.text-emerald-300]="run()!.outcome?.value_source === 'operator'"
                  [class.bg-emerald-500\\/10]="run()!.outcome?.value_source === 'operator'"
                  [class.text-cyan-300]="run()!.outcome?.value_source === 'auto'"
                  [class.bg-cyan-500\\/10]="run()!.outcome?.value_source === 'auto'"
                  [class.text-gray-400]="!run()!.outcome?.value_source || run()!.outcome?.value_source === 'unset'"
                  [class.bg-white\\/5]="!run()!.outcome?.value_source || run()!.outcome?.value_source === 'unset'"
                >
                  {{ valueSourceLabel() }}
                </span>
              </div>

              @if (!overrideMode()) {
                <div class="ml-auto flex items-center gap-2">
                  <ck-help id="runs.outcome.override" />
                  <button
                    type="button"
                    (click)="enableOverride()"
                    class="inline-flex items-center gap-1.5 px-3 py-1 rounded text-[11px] font-medium bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition font-mono tracking-wider uppercase"
                  >
                    <app-icon name="edit-3" [size]="11" />
                    {{ i18n.t('runs.detail.override.button') }}
                  </button>
                </div>
              } @else {
                <div class="flex items-center gap-2 flex-wrap ml-auto">
                  <input
                    type="number"
                    step="0.01"
                    [value]="overrideValue()"
                    (input)="overrideValue.set(+asInput($event).value)"
                    [placeholder]="i18n.t('runs.detail.override.value_placeholder')"
                    class="font-mono text-xs tabular-nums"
                    style="width:110px; padding:4px 8px; background:var(--ck-bg-inset); border:1px solid var(--ck-stroke-2); border-radius:3px; color:var(--ck-fg-1);"
                  />
                  <input
                    type="text"
                    [value]="overrideNote()"
                    (input)="overrideNote.set(asInput($event).value)"
                    [placeholder]="i18n.t('runs.detail.override.note_placeholder')"
                    class="font-mono text-xs"
                    style="min-width:200px; padding:4px 8px; background:var(--ck-bg-inset); border:1px solid var(--ck-stroke-2); border-radius:3px; color:var(--ck-fg-1);"
                  />
                  <button
                    type="button"
                    (click)="submitOverride()"
                    [disabled]="submittingOverride()"
                    class="inline-flex items-center gap-1.5 px-3 py-1 rounded text-[11px] font-medium font-mono tracking-wider uppercase"
                    style="background:var(--ck-signal-pos); color:var(--ck-on-signal);"
                    [style.opacity]="submittingOverride() ? '0.4' : '1'"
                  >
                    {{ submittingOverride() ? i18n.t('runs.detail.override.saving') : i18n.t('common.save') }}
                  </button>
                  <button
                    type="button"
                    (click)="cancelOverride()"
                    class="inline-flex items-center gap-1.5 px-3 py-1 rounded text-[11px] font-medium bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 font-mono tracking-wider uppercase"
                  >
                    {{ i18n.t('common.cancel') }}
                  </button>
                </div>
              }
            </div>
            @if (run()!.outcome?.operator_value_note) {
              <p class="text-[11px] text-gray-400 mt-2 font-mono">
                <span class="text-gray-500 uppercase">{{ i18n.t('runs.detail.override.note_label') }}</span>
                {{ run()!.outcome!.operator_value_note }}
              </p>
            }
          </div>
        </div>

        <!-- Error banner -->
        @if (run()?.error) {
          <div class="rounded-lg border border-red-500/30 bg-red-500/10 p-3 mb-6">
            <div class="flex items-start gap-2">
              <app-icon name="alert-triangle" [size]="14" class="text-red-400 mt-0.5" />
              <div class="min-w-0">
                <div class="text-xs font-semibold text-red-300 mb-1">
                  {{ i18n.t('runs.detail.error.title') }}
                </div>
                <div class="text-xs font-mono text-red-200/80 break-all">
                  {{ run()!.error }}
                </div>
              </div>
            </div>
          </div>
        }

        @if (retrievalDecisionTrace(); as trace) {
          <section class="rounded-lg border border-emerald-400/20 bg-emerald-400/[0.04] mb-6">
            <header class="px-4 py-2.5 border-b border-emerald-400/10 flex items-center gap-2">
              <app-icon name="git-branch" [size]="14" class="text-emerald-300" />
              <h2 class="text-xs uppercase tracking-wider text-emerald-200 font-semibold">
                {{ i18n.t('runs.detail.retrieval.title') }}
              </h2>
              <span class="ml-auto font-mono text-[10px] text-emerald-300/70">
                {{ trace.trace_source || 'runtime' }}
              </span>
            </header>
            <div class="grid grid-cols-1 gap-3 px-4 py-3 md:grid-cols-4">
              <div>
                <div class="text-[10px] uppercase tracking-wider text-gray-500 font-mono">{{ i18n.t('runs.detail.retrieval.route') }}</div>
                <div class="mt-1 font-mono text-sm text-white">{{ routeLabel(trace) }}</div>
              </div>
              <div>
                <div class="text-[10px] uppercase tracking-wider text-gray-500 font-mono">{{ i18n.t('runs.detail.retrieval.query_type') }}</div>
                <div class="mt-1 font-mono text-sm text-gray-200">{{ trace.query_type || '—' }}</div>
              </div>
              <div>
                <div class="text-[10px] uppercase tracking-wider text-gray-500 font-mono">{{ i18n.t('runs.detail.retrieval.latency') }}</div>
                <div class="mt-1 font-mono text-sm text-gray-200">{{ trace.latency_profile || 'default' }}</div>
              </div>
              <div>
                <div class="text-[10px] uppercase tracking-wider text-gray-500 font-mono">{{ i18n.t('runs.detail.retrieval.controls') }}</div>
                <div class="mt-1 font-mono text-sm text-gray-200">{{ qualityLine(trace) }}</div>
              </div>
            </div>
            <div class="px-4 pb-3 grid gap-2 md:grid-cols-2">
              <div class="rounded border border-white/5 bg-black/20 p-3">
                <div class="text-[10px] uppercase tracking-wider text-gray-500 font-mono">{{ i18n.t('runs.detail.retrieval.reason') }}</div>
                <p class="mt-1 text-sm text-gray-300">{{ trace.route_reason || trace.summary || i18n.t('runs.detail.retrieval.reason_fallback') }}</p>
              </div>
              <div class="rounded border border-white/5 bg-black/20 p-3">
                <div class="text-[10px] uppercase tracking-wider text-gray-500 font-mono">{{ i18n.t('runs.detail.retrieval.tradeoff') }}</div>
                <p class="mt-1 text-sm text-gray-300">{{ trace.tradeoff || i18n.t('runs.detail.retrieval.tradeoff_fallback') }}</p>
              </div>
            </div>
            <details class="mx-4 mb-4 rounded border border-white/5 bg-black/20">
              <summary class="cursor-pointer px-3 py-2 text-[10px] uppercase tracking-wider text-gray-400 font-mono">
                {{ i18n.t('runs.detail.retrieval.json') }}
              </summary>
              <pre class="px-3 pb-3 text-[10px] font-mono text-gray-300 whitespace-pre-wrap break-words">{{ asJson(trace) }}</pre>
            </details>
          </section>
        }

        <!-- Skill timeline -->
        <section class="rounded-lg border border-white/5 bg-white/[0.02] mb-6">
          <header class="px-4 py-2.5 border-b border-white/5 flex items-center gap-2">
            <app-icon name="list-tree" [size]="14" class="text-cyan-400" />
            <h2 class="text-xs uppercase tracking-wider text-gray-300 font-semibold">
              {{ i18n.t('runs.detail.trail.title') }}
            </h2>
            <span class="ml-auto font-mono text-[10px] text-gray-500">
              {{ stepsLabel() }}
            </span>
          </header>
          @if (skillInvocations().length === 0) {
            <div class="px-4 py-8 text-center text-xs text-gray-500 font-mono">
              {{ i18n.t('runs.detail.trail.empty') }}
            </div>
          } @else {
            <ol class="divide-y divide-white/5">
              @for (inv of skillInvocations(); track $index; let idx = $index) {
                <li class="px-4 py-3 flex items-start gap-3">
                  <div class="flex-shrink-0 w-6 h-6 rounded-full bg-white/5 ring-1 ring-white/10 flex items-center justify-center font-mono text-[10px] text-gray-400">
                    {{ idx + 1 }}
                  </div>
                  <div class="flex-1 min-w-0">
                    <div class="flex items-baseline justify-between gap-3">
                      @if (skillInvocationProjectionEnabled() && inv.id) {
                        <a
                          [routerLink]="['/runs', runId(), 'invocations', inv.id]"
                          [queryParams]="{
                            lens: activeLens(),
                            capabilityId: run()!.capability_id || navigation.capabilityId(),
                            systemId: run()!.system_id
                          }"
                          class="font-mono text-sm text-white truncate hover:text-cyan-300"
                        >{{ inv.skill_slug || inv.skill_id || i18n.t('runs.detail.trail.invocation_fallback') }}</a>
                      } @else if (inv.skill_slug) {
                        <a
                          [routerLink]="navigation.objectUrlTree('skill', inv.skill_slug, {
                            capabilityId: navigation.capabilityId(),
                            systemId: run()!.system_id,
                            runId: runId()
                          })"
                          class="font-mono text-sm text-white truncate hover:text-cyan-300"
                        >{{ inv.skill_slug }}</a>
                      } @else {
                        <div class="font-mono text-sm text-white truncate">
                          {{ inv.skill_id || i18n.t('runs.detail.trail.skill_fallback') }}
                        </div>
                      }
                      <div class="flex items-center gap-2 flex-shrink-0">
                        <span
                          class="text-[10px] uppercase tracking-wider font-mono px-1.5 py-0.5 rounded"
                          [class.text-emerald-300]="inv.status === 'completed'"
                          [class.bg-emerald-500\\/10]="inv.status === 'completed'"
                          [class.text-red-300]="inv.status === 'failed'"
                          [class.bg-red-500\\/10]="inv.status === 'failed'"
                          [class.text-cyan-300]="inv.status === 'running'"
                          [class.bg-cyan-500\\/10]="inv.status === 'running'"
                          [class.text-gray-400]="inv.status === 'pending' || !inv.status"
                          [class.bg-white\\/5]="inv.status === 'pending' || !inv.status"
                        >
                          {{ statusLabel(inv.status || 'pending') }}
                        </span>
                        @if (inv.latency_ms != null) {
                          <span class="text-[10px] font-mono text-gray-400 tabular-nums">
                            {{ formatDuration(inv.latency_ms) }}
                          </span>
                        }
                        @if (inv.cost != null && inv.cost > 0) {
                          <span class="text-[10px] font-mono text-amber-300 tabular-nums">
                            \${{ inv.cost.toFixed(4) }}
                          </span>
                        }
                      </div>
                    </div>
                    @if (inv.started_at) {
                      <div class="text-[10px] font-mono text-gray-500 mt-0.5">
                        {{ formatTime(inv.started_at) }}
                      </div>
                    }
                    @if (inv.error) {
                      <div class="mt-2 text-[11px] font-mono text-red-300/90 bg-red-500/5 rounded px-2 py-1.5 break-all">
                        {{ inv.error }}
                      </div>
                    }
                    @if (hasInvocationDetails(inv)) {
                      <details class="mt-2 rounded border border-white/5 bg-black/20">
                        <summary class="cursor-pointer px-2 py-1.5 text-[10px] uppercase tracking-wider text-gray-400 font-mono">
                          {{ i18n.t('runs.detail.trail.audit') }}
                        </summary>
                        <pre class="px-2 pb-2 text-[10px] font-mono text-gray-300 whitespace-pre-wrap break-words">{{ invocationDetailsJson(inv) }}</pre>
                      </details>
                    }
                  </div>
                </li>
              }
            </ol>
          }
        </section>

        <!-- Payloads -->
        <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
          <section class="rounded-lg border border-white/5 bg-white/[0.02]">
            <header class="px-4 py-2.5 border-b border-white/5 flex items-center gap-2">
              <app-icon name="arrow-right-to-line" [size]="14" class="text-cyan-300" />
              <h2 class="text-xs uppercase tracking-wider text-gray-300 font-semibold">{{ i18n.t('runs.detail.input') }}</h2>
            </header>
            <pre class="px-4 py-3 text-[11px] font-mono text-gray-300 whitespace-pre-wrap break-words">{{ inputJson() }}</pre>
          </section>
          <section class="rounded-lg border border-white/5 bg-white/[0.02]">
            <header class="px-4 py-2.5 border-b border-white/5 flex items-center gap-2">
              <app-icon name="target" [size]="14" class="text-emerald-300" />
              <h2 class="text-xs uppercase tracking-wider text-gray-300 font-semibold">{{ i18n.t('runs.detail.outcome') }}</h2>
            </header>
            <pre class="px-4 py-3 text-[11px] font-mono text-gray-300 whitespace-pre-wrap break-words">{{ outcomeJson() }}</pre>
          </section>
        </div>

        @if (checkpoints().length > 0) {
          <section class="rounded-lg border border-white/5 bg-white/[0.02] mt-3">
            <header class="px-4 py-2.5 border-b border-white/5 flex items-center gap-2">
              <app-icon name="bookmark" [size]="14" class="text-sky-300" />
              <h2 class="text-xs uppercase tracking-wider text-gray-300 font-semibold">{{ i18n.t('runs.detail.checkpoints') }}</h2>
              <span class="ml-auto font-mono text-[10px] text-gray-500">{{ checkpoints().length }}</span>
            </header>
            <ul class="divide-y divide-white/5">
              @for (cp of checkpoints(); track $index) {
                <li class="px-4 py-2 text-[11px] font-mono text-gray-300 break-all">
                  {{ asJson(cp) }}
                </li>
              }
            </ul>
          </section>
        }
      }
    </ck-page-frame>
    }
  `,
})
export class RunViewComponent implements OnInit, OnDestroy {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly canonical = inject(CanonicalApiService);
  private readonly workspace = inject(WorkspaceService);
  private readonly lensService = inject(LensService);
  private readonly perspectiveStore = inject(ObjectPerspectiveStore);
  protected readonly navigation = inject(ZoomContextService);
  readonly i18n = inject(I18nService);
  private routeSubscription: Subscription | null = null;
  private facetRouteSubscription: Subscription | null = null;
  private loadSubscription: Subscription | null = null;
  private overrideSubscription: Subscription | null = null;
  private perspectiveSubscription: Subscription | null = null;
  private featureRefreshSubscription: Subscription | null = null;
  private overrideGeneration = 0;
  private projectionFeatureEnabled = false;
  private projectionActivationInFlight = false;
  private requestedFacet: string | null = null;
  private readonly workspaceView = new WorkspaceViewContext(
    this.workspace,
    () => this.resetWorkspaceState(),
    () => this.reloadCurrentRun(),
  );

  readonly runId = signal<string>('');
  readonly run = signal<Run | null>(null);
  readonly loading = signal(false);
  readonly perspectives = signal<Partial<Record<ObjectLens, ObjectPerspectiveResponse>>>({});
  readonly perspectivesLoading = signal(false);
  readonly perspectivesError = signal(false);
  readonly activePerspectiveTab = signal<RunPerspectiveFacet>('overview');
  readonly projectionEnabled = computed(() => this.workspaceFeature('run_360_projection_v1'));
  readonly skillInvocationProjectionEnabled = computed(
    () => this.workspaceFeature('skill_invocation_360_projection_v1'),
  );
  readonly activeLens = computed<ObjectLens>(() => {
    const lens = this.lensService.lens();
    return isObjectLens(lens) ? lens : 'build';
  });
  readonly activePerspective = computed(() => this.perspectives()[this.activeLens()] ?? null);
  readonly perspectiveKpis = computed<CkObjectKpi[]>(() => {
    const header = this.perspectives()['build']?.header;
    return [
      { label: this.i18n.t('runs.detail.kpi.status'), value: this.factValue(header?.['status']) },
      { label: this.i18n.t('runs.detail.kpi.duration'), value: this.msFactValue(header?.['duration']) },
      { label: this.i18n.t('runs.detail.kpi.invocations'), value: this.factValue(header?.['invocation_count']) },
      { label: this.i18n.t('runs.detail.kpi.confidence'), value: this.factValue(header?.['confidence']) },
    ];
  });

  readonly overrideMode = signal(false);
  readonly overrideValue = signal<number>(0);
  readonly overrideNote = signal<string>('');
  readonly submittingOverride = signal(false);

  readonly skillInvocations = computed<SkillInvocation[]>(
    () => this.run()?.skill_invocations ?? [],
  );
  readonly checkpoints = computed<Array<Record<string, unknown>>>(
    () => this.run()?.checkpoints ?? [],
  );

  readonly titleLabel = computed(() => {
    const id = this.runId();
    if (!id) return this.i18n.t('runs.detail.object_label');
    return this.i18n.t('runs.detail.title', { id: id.slice(0, 12) });
  });

  readonly descriptionLabel = computed(() => {
    const r = this.run();
    if (!r) return this.i18n.t('runs.detail.description');
    const bits: string[] = [];
    if (r.trigger) bits.push(this.i18n.t('runs.detail.meta.trigger', { value: r.trigger }));
    if (r.system_id) bits.push(this.i18n.t('runs.detail.meta.system', { value: r.system_id }));
    if (r.started_at) bits.push(this.i18n.t('runs.detail.meta.started', { value: this.formatTime(r.started_at) }));
    return bits.join(' · ') || this.i18n.t('runs.detail.description');
  });

  /** "5 steps" under the Skill trail header — singular and plural are two keys. */
  readonly stepsLabel = computed(() => {
    const count = this.skillInvocations().length;
    return this.i18n.t(
      count === 1 ? 'runs.detail.trail.step' : 'runs.detail.trail.steps',
      { count },
    );
  });

  readonly inputJson = computed(() => {
    const r = this.run() as (Run & { input?: unknown; input_ref?: unknown }) | null;
    return this.asJson(r?.input ?? r?.input_ref ?? {});
  });

  readonly outcomeJson = computed(() => this.asJson(this.run()?.outcome ?? {}));

  readonly retrievalDecisionTrace = computed<RetrievalDecisionTrace | null>(() => {
    const run = this.run();
    if (!run) return null;
    const output = run.output_ref ?? {};
    const direct = this.traceFrom(output);
    if (direct) return direct;
    for (const invocation of run.skill_invocations ?? []) {
      const trace =
        this.traceFrom(invocation.metrics)
        ?? this.traceFrom(invocation.output_ref)
        ?? this.traceFrom(invocation.trace);
      if (trace) return trace;
    }
    return null;
  });

  ngOnInit(): void {
    this.projectionFeatureEnabled = this.projectionEnabled();
    this.featureRefreshSubscription = this.workspace.contextRefresh$.subscribe(
      () => this.onProjectionFeatureRefresh(),
    );
    this.routeSubscription = this.route.paramMap.pipe(
      map((params) => params.get('runId') ?? ''),
      distinctUntilChanged(),
    ).subscribe((id) => {
      if (!id) {
        this.router.navigate(['/runs']);
        return;
      }
      this.runId.set(id);
      this.resetRunResult();
      this.refresh();
    });
    this.facetRouteSubscription = this.route.queryParamMap.pipe(
      map((params) => params.get('facet')),
      distinctUntilChanged(),
    ).subscribe((facet) => {
      this.requestedFacet = facet;
      this.applyRequestedFacet(facet);
    });
  }

  ngOnDestroy(): void {
    this.routeSubscription?.unsubscribe();
    this.routeSubscription = null;
    this.facetRouteSubscription?.unsubscribe();
    this.facetRouteSubscription = null;
    this.perspectiveSubscription?.unsubscribe();
    this.perspectiveSubscription = null;
    this.featureRefreshSubscription?.unsubscribe();
    this.featureRefreshSubscription = null;
    this.workspaceView.destroy();
  }

  /** Only a finished run has something to replay. */
  protected readonly rerunnable = computed(() => {
    const status = this.run()?.status;
    return !!status && status !== 'pending' && status !== 'running';
  });
  protected readonly rerunning = signal(false);

  /**
   * Replay this run and follow the child, so the two executions can be compared
   * by stepping back to the parent. The backend re-uses the parent's flow
   * snapshot, which is what makes the comparison meaningful.
   */
  protected rerun(): void {
    const id = this.runId();
    if (!id || this.rerunning()) return;
    this.rerunning.set(true);
    this.canonical.rerunRun(id).subscribe({
      next: (replay) => {
        this.rerunning.set(false);
        if (replay?.id) void this.router.navigate(['/runs', replay.id]);
      },
      error: () => this.rerunning.set(false),
    });
  }

  refresh(forcePerspectiveRefresh = false): void {
    this.projectionFeatureEnabled = this.projectionEnabled();
    const id = this.runId();
    if (!id) return;
    this.loadSubscription?.unsubscribe();
    this.loadSubscription = null;
    const request = this.workspaceView.beginRequest();
    this.loading.set(true);
    const subscription = this.canonical.getRun(id).subscribe({
      next: (r) => {
        if (!this.workspaceView.isCurrent(request) || id !== this.runId()) return;
        this.run.set(r);
        this.loading.set(false);
      },
      error: () => {
        if (!this.workspaceView.isCurrent(request) || id !== this.runId()) return;
        this.run.set(null);
        this.loading.set(false);
      },
    });
    this.loadSubscription = subscription.closed ? null : subscription;
    this.loadPerspectives(id, request, forcePerspectiveRefresh);
  }

  onPerspectiveTabChange(value: string): void {
    if (!isRunPerspectiveFacet(value)) return;
    this.requestedFacet = value;
    this.activePerspectiveTab.set(value);
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { facet: value },
      queryParamsHandling: 'merge',
    });
  }

  private applyRequestedFacet(facet: string | null): void {
    this.activePerspectiveTab.set(isRunPerspectiveFacet(facet) ? facet : 'overview');
  }

  /**
   * Translate a run or invocation status, falling back to the raw API value
   * when the backend grows a status the dictionary hasn't caught up with — an
   * unknown status must stay visible, not turn into a blank chip.
   */
  statusLabel(status: string | null | undefined): string {
    if (!status) return '';
    const key = `runs.status.${status}`;
    const label = this.i18n.t(key);
    return label === key ? status : label;
  }

  /** Same fallback contract as {@link statusLabel}, for `outcome.value_source`. */
  valueSourceLabel(): string {
    const source = this.run()?.outcome?.value_source || 'unset';
    const key = `runs.detail.value_source.${source}`;
    const label = this.i18n.t(key);
    return label === key ? source : label;
  }

  formatTime(ts: string | undefined): string {
    if (!ts) return '—';
    try {
      return new Date(ts).toLocaleString(undefined, {
        year: 'numeric',
        month: 'short',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      });
    } catch {
      return ts;
    }
  }

  formatDuration(ms: number): string {
    if (!Number.isFinite(ms)) return '—';
    if (ms < 1000) return `${ms.toFixed(0)}ms`;
    return `${(ms / 1000).toFixed(2)}s`;
  }

  asJson(v: unknown): string {
    if (v === undefined || v === null) return '{}';
    try {
      return JSON.stringify(v, null, 2);
    } catch {
      return String(v);
    }
  }

  routeLabel(trace: RetrievalDecisionTrace): string {
    return String(trace.selected_route || 'retrieval').replace(/_/g, ' ');
  }

  qualityLine(trace: RetrievalDecisionTrace): string {
    const quality = this.isRecord(trace.quality_controls) ? trace.quality_controls : {};
    const sparse = quality['sparse_status'] ? `sparse ${quality['sparse_status']}` : null;
    const cross = quality['cross_encoder_status'] ? `cross ${quality['cross_encoder_status']}` : null;
    return [sparse, cross].filter(Boolean).join(' · ') || '—';
  }

  private traceFrom(payload?: Record<string, unknown> | null): RetrievalDecisionTrace | null {
    if (!this.isRecord(payload)) return null;
    if (this.isRecord(payload['retrieval_decision_trace'])) {
      return payload['retrieval_decision_trace'] as RetrievalDecisionTrace;
    }
    const metrics = payload['retrieval_metrics'];
    if (this.isRecord(metrics) && this.isRecord(metrics['retrieval_decision_trace'])) {
      return metrics['retrieval_decision_trace'] as RetrievalDecisionTrace;
    }
    return null;
  }

  private isRecord(value: unknown): value is Record<string, unknown> {
    return !!value && typeof value === 'object' && !Array.isArray(value);
  }

  hasInvocationDetails(inv: SkillInvocation): boolean {
    return !!(
      inv.input_ref ||
      inv.output_ref ||
      inv.metrics ||
      inv.trace
    );
  }

  invocationDetailsJson(inv: SkillInvocation): string {
    return this.asJson({
      input_ref: inv.input_ref ?? {},
      output_ref: inv.output_ref ?? {},
      metrics: inv.metrics ?? {},
      trace: inv.trace ?? {},
    });
  }

  asInput(ev: Event): HTMLInputElement {
    return ev.target as HTMLInputElement;
  }

  enableOverride(): void {
    const current = this.run()?.outcome?.value_estimated ?? 0;
    this.overrideValue.set(Number(current) || 0);
    this.overrideNote.set(this.run()?.outcome?.operator_value_note ?? '');
    this.overrideMode.set(true);
  }

  cancelOverride(): void {
    this.overrideMode.set(false);
  }

  submitOverride(): void {
    const id = this.runId();
    if (!id || this.submittingOverride()) return;
    this.overrideSubscription?.unsubscribe();
    this.overrideSubscription = null;
    const scope = this.workspace.captureRequestScope();
    const generation = ++this.overrideGeneration;
    this.submittingOverride.set(true);
    const subscription = this.canonical
      .overrideRunOutcome(id, {
        value: this.overrideValue(),
        note: this.overrideNote() || undefined,
      })
      .subscribe({
        next: (updated) => {
          if (!this.overrideIsCurrent(scope, generation, id)) return;
          if (updated) this.run.set(updated as unknown as Run);
          this.submittingOverride.set(false);
          this.overrideMode.set(false);
        },
        error: () => {
          if (!this.overrideIsCurrent(scope, generation, id)) return;
          this.submittingOverride.set(false);
        },
      });
    this.overrideSubscription = subscription.closed ? null : subscription;
  }

  private reloadCurrentRun(): void {
    const id = this.runId() || this.route.snapshot.paramMap.get('runId') || '';
    if (!id) return;
    this.runId.set(id);
    this.refresh();
  }

  private loadPerspectives(
    runId: string,
    request: WorkspaceViewRequest,
    forceRefresh = false,
  ): void {
    this.perspectiveSubscription?.unsubscribe();
    this.perspectiveSubscription = null;
    if (!this.projectionEnabled()) {
      this.perspectives.set({});
      this.perspectivesLoading.set(false);
      this.perspectivesError.set(false);
      return;
    }
    this.perspectivesLoading.set(true);
    this.perspectivesError.set(false);
    const subscription = this.perspectiveStore.loadAll({
      objectType: 'run',
      objectId: runId,
      window: '30d',
    }, { forceRefresh }).subscribe({
      next: (payloads) => {
        if (!this.workspaceView.isCurrent(request) || runId !== this.runId()) return;
        this.perspectives.set(payloads);
        this.perspectivesLoading.set(false);
        this.perspectivesError.set(Object.keys(payloads).length !== 4);
        this.projectionActivationInFlight = false;
      },
      error: (error: unknown) => {
        if (!this.workspaceView.isCurrent(request) || runId !== this.runId()) return;
        this.perspectives.set({});
        this.perspectivesLoading.set(false);
        this.perspectivesError.set(
          !(error instanceof ObjectPerspectiveGateRevokedError),
        );
        if (!(error instanceof ObjectPerspectiveGateRevokedError)) {
          this.projectionActivationInFlight = false;
        }
      },
    });
    this.perspectiveSubscription = subscription.closed ? null : subscription;
  }

  private resetRunResult(): void {
    this.loadSubscription?.unsubscribe();
    this.loadSubscription = null;
    this.perspectiveSubscription?.unsubscribe();
    this.perspectiveSubscription = null;
    this.overrideSubscription?.unsubscribe();
    this.overrideSubscription = null;
    this.overrideGeneration += 1;
    this.workspaceView.invalidate();
    this.run.set(null);
    this.loading.set(false);
    this.overrideMode.set(false);
    this.submittingOverride.set(false);
    this.perspectives.set({});
    this.perspectivesLoading.set(false);
    this.perspectivesError.set(false);
    this.projectionActivationInFlight = false;
  }

  private resetWorkspaceState(): void {
    this.loadSubscription?.unsubscribe();
    this.loadSubscription = null;
    this.perspectiveSubscription?.unsubscribe();
    this.perspectiveSubscription = null;
    this.overrideSubscription?.unsubscribe();
    this.overrideSubscription = null;
    this.overrideGeneration += 1;
    this.run.set(null);
    this.loading.set(false);
    this.overrideMode.set(false);
    this.overrideValue.set(0);
    this.overrideNote.set('');
    this.submittingOverride.set(false);
    this.perspectives.set({});
    this.perspectivesLoading.set(false);
    this.perspectivesError.set(false);
    this.projectionActivationInFlight = false;
    this.applyRequestedFacet(this.requestedFacet);
  }

  private onProjectionFeatureRefresh(): void {
    const enabled = this.projectionEnabled();
    const activated = enabled && !this.projectionFeatureEnabled;
    this.projectionFeatureEnabled = enabled;
    if (!enabled) {
      this.perspectiveSubscription?.unsubscribe();
      this.perspectiveSubscription = null;
      this.perspectives.set({});
      this.perspectivesLoading.set(false);
      this.perspectivesError.set(false);
      return;
    }
    if (activated && !this.projectionActivationInFlight) {
      this.projectionActivationInFlight = true;
      this.reloadCurrentRun();
    }
  }

  private workspaceFeature(key: string): boolean {
    return this.workspace.current()?.effective_features?.[key] === true;
  }

  private factValue(fact: { state?: string; value?: unknown } | undefined, suffix = ''): string {
    if (!fact || fact.state !== 'available' || fact.value == null) return '—';
    if (typeof fact.value === 'number') {
      const value = Number.isInteger(fact.value) ? String(fact.value) : fact.value.toFixed(2);
      return `${value}${suffix}`;
    }
    return String(fact.value);
  }

  /**
   * Millisecond facts arrive as raw floats ("652.8888740576804 ms" reached
   * production); operators read whole milliseconds.
   */
  private msFactValue(fact: { state?: string; value?: unknown } | undefined): string {
    if (!fact || fact.state !== 'available' || fact.value == null) return '—';
    const ms = typeof fact.value === 'number' ? fact.value : Number(fact.value);
    if (!Number.isFinite(ms)) return String(fact.value);
    return `${Math.round(ms)} ms`;
  }

  private overrideIsCurrent(
    scope: WorkspaceRequestScope,
    generation: number,
    runId: string,
  ): boolean {
    return (
      generation === this.overrideGeneration
      && runId === this.runId()
      && this.workspace.isRequestScopeCurrent(scope)
    );
  }
}

type RunPerspectiveFacet = 'overview' | 'invocations' | 'payloads' | 'checkpoints';

const RUN_PERSPECTIVE_FACETS: readonly RunPerspectiveFacet[] = [
  'overview',
  'invocations',
  'payloads',
  'checkpoints',
];

function isRunPerspectiveFacet(value: string | null): value is RunPerspectiveFacet {
  return value !== null && (RUN_PERSPECTIVE_FACETS as readonly string[]).includes(value);
}

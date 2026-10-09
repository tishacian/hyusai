import { HelpTooltipComponent } from '@app/shared/cockpit/help-tooltip.component';
import { ChangeDetectionStrategy, Component, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { Subscription, distinctUntilChanged, forkJoin, map } from 'rxjs';
import { CanonicalApiService, RunSystemSummary } from '@app/core/canonical-api.service';
import { I18nService } from '@app/core/i18n.service';
import {
  GlyphComponent,
  KbdComponent,
  LiveDotComponent,
  NavLinkDirective,
  PageFrameComponent,
  StatReadoutComponent,
} from '@app/shared/cockpit';
import { SystemsStore, SystemAgent } from './systems.store';
import { isFlowBackedSystem, isPromotedFromScratchpad, systemCatalogBadge } from './system-flow-profile';
import { activeSystemsKey, filterSystems, systemCategory, systemsPrimaryAction, type SystemCategoryFilter } from './systems-grid.vm';
import { ZoomContextService } from '@app/core/zoom-context.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { WorkspaceViewContext } from '@app/core/workspace-view-context';

interface AgentStats {
  runs: number;
  lastStatus: string;
  lastDurationMs: number | null;
}

interface Template {
  id: string;
  labelKey: string;
  descriptionKey: string;
  promptKey: string;
}

/**
 * Systems grid — catalog of every System deployed in the workspace.
 * Cockpit-grade: eyebrow + title + description via PageFrame, quick-start
 * composer on top, grid of cards below. No legacy section header.
 */
@Component({
  selector: 'app-systems-grid',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [HelpTooltipComponent,
    RouterLink,
    NavLinkDirective,
    FormsModule,
    PageFrameComponent,
    GlyphComponent,
    KbdComponent,
    LiveDotComponent,
    StatReadoutComponent,
  ],
  styles: [`
    .sg-chip {
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      padding: 0 10px;
      border: 1px solid var(--ck-stroke-2);
      border-radius: 99px;
      background: transparent;
      color: var(--ck-fg-3);
      font-family: var(--ck-font-sans);
      font-size: 12px;
      cursor: pointer;
      transition: border-color var(--ck-dur-fast) var(--ck-ease-out), color var(--ck-dur-fast) var(--ck-ease-out);
    }
    .sg-chip:hover { border-color: var(--ck-stroke-3, var(--ck-stroke-2)); color: var(--ck-fg-1); }
    .sg-chip:focus-visible { outline: 2px solid var(--ck-primary); outline-offset: 2px; }
  `],
  template: `

    <ck-page-frame
      [eyebrow]="i18n.t('systems.grid.eyebrow')"
      [title]="i18n.t('systems.grid.title')"
      [description]="i18n.t('systems.grid.description')"
      [status]="loadProblem() ? '' : i18n.t(activeKey(), { count: systems().length })"
    >
      <ck-help titleHelp id="adoption.systems" />
      <!-- One filled button per view: secondary while the empty state leads. -->
      <a
        actions
        [navLink]="{ leaf: 'system-new' }"
        class="ck-btn ck-btn--sm ck-press"
        [class.ck-cta]="primaryAction() === 'header'"
        [class.ck-btn-quiet]="primaryAction() !== 'header'"
        data-testid="systems-new"
      >
        <ck-glyph name="bolt" [size]="12" />
        {{ i18n.t('systems.create') }}
      </a>

      <!-- Quick-start composer -->
      <section
        [style.position]="'relative'"
        [style.padding]="'22px 24px'"
        [style.background]="'var(--ck-bg-panel)'"
        [style.border]="'1px solid var(--ck-stroke-2)'"
        [style.borderRadius.px]="6"
        [style.marginBottom.px]="24"
      >
        <div [style.display]="'flex'" [style.alignItems]="'center'" [style.gap.px]="10" [style.marginBottom.px]="12">
          <span class="ck-label" [style.color]="'var(--ck-signal-cool)'">{{ i18n.t('systems.grid.quick_start') }}</span>
          <ck-live-dot tone="cool" />
        </div>
        <h2
          [style.fontFamily]="'var(--ck-font-display)'"
          [style.fontSize.px]="20"
          [style.fontWeight]="600"
          [style.letterSpacing]="'-0.01em'"
          [style.color]="'var(--ck-fg-1)'"
          [style.margin]="'0 0 6px 0'"
          [style.maxWidth.ch]="64"
        >{{ i18n.t('systems.grid.quick_title') }}</h2>
        <p [style.color]="'var(--ck-fg-3)'" [style.fontSize.px]="12" [style.margin]="'0 0 14px 0'" [style.maxWidth.ch]="72">
          {{ i18n.t('systems.grid.quick_description') }}
        </p>

        <form (ngSubmit)="startFromPrompt()" [style.display]="'flex'" [style.gap.px]="8" [style.maxWidth.px]="720">
          <div [style.position]="'relative'" [style.flex]="'1 1 auto'">
            <span [style.position]="'absolute'" [style.left.px]="10" [style.top.px]="9" [style.pointerEvents]="'none'" [style.color]="'var(--ck-signal-cool)'">
              <ck-glyph name="focus" [size]="14" />
            </span>
            <input
              type="text"
              [(ngModel)]="prompt"
              name="prompt"
              [style.width]="'100%'"
              [style.padding]="'8px 12px 8px 32px'"
              [style.height.px]="32"
              [style.background]="'var(--ck-bg-inset)'"
              [style.border]="'1px solid var(--ck-stroke-2)'"
              [style.borderRadius.px]="4"
              [style.color]="'var(--ck-fg-1)'"
              [style.fontSize.px]="13"
              [placeholder]="i18n.t('systems.grid.prompt_placeholder')"
            />
          </div>
          <button
            type="submit"
            class="ck-btn ck-btn-accent ck-press"
            data-testid="systems-compose"
            [disabled]="!prompt.trim()"
          >{{ i18n.t('systems.grid.compose') }}</button>
        </form>

        <div [style.display]="'flex'" [style.flexWrap]="'wrap'" [style.gap.px]="6" [style.marginTop.px]="14">
          @for (tpl of templates; track tpl.id) {
            <button
              type="button"
              class="sg-chip"
              (click)="applyTemplate(tpl)"
              [title]="i18n.t(tpl.descriptionKey)"
            >{{ i18n.t(tpl.labelKey) }}</button>
          }
        </div>
      </section>

      <div role="group" [attr.aria-label]="i18n.t('systems.grid.category')" style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px">
        @for (category of categories; track category) {
          <button type="button" class="sg-chip" [attr.aria-pressed]="categoryFilter() === category"
            [style.borderColor]="categoryFilter() === category ? 'var(--ck-signal-cool)' : null"
            [attr.data-testid]="'systems-category-' + category" (click)="categoryFilter.set(category)">
            {{ i18n.t('systems.grid.category.' + category) }} · {{ categoryCount(category) }}
          </button>
        }
      </div>
      @if (categoryFilter() === 'model_operations') {
        <p class="ck-label" style="margin-bottom:16px">{{ i18n.t('systems.grid.operations_hint') }}</p>
      }

      @if (recentSystems().length > 0) {
        <div
          [style.display]="'flex'"
          [style.flexWrap]="'wrap'"
          [style.alignItems]="'center'"
          [style.gap.px]="8"
          [style.marginBottom.px]="12"
        >
          <span class="ck-label">{{ i18n.t('systems.grid.recent') }}</span>
          @for (summary of recentSystems(); track summary.system_id) {
            <a
              [navLink]="{ type: 'system', ref: summary.system_id, lens: 'build' }"
              class="sg-chip"
              [attr.data-testid]="'recent-system-' + $index"
            >{{ summary.system_name }} · {{ statusLabel(summary.last_status) }}</a>
          }
        </div>
      }

      <!-- Grid header -->
      <div [style.display]="'flex'" [style.alignItems]="'center'" [style.justifyContent]="'space-between'" [style.marginBottom.px]="12">
        <span class="ck-label ck-tnum" data-testid="systems-count">{{ loadProblem() ? '' : i18n.t('systems.grid.count', { count: systems().length }) }}</span>
        <span class="ck-label" [style.display]="'inline-flex'" [style.alignItems]="'center'" [style.gap.px]="6">
          <ck-kbd>⌘K</ck-kbd> {{ i18n.t('systems.grid.navigate_hint') }}
        </span>
      </div>

      @if (store.loading() && !loadProblem()) {
        <div [style.display]="'grid'" [style.gridTemplateColumns]="'repeat(auto-fill, minmax(320px, 1fr))'" [style.gap.px]="12">
          @for (_ of [0, 1, 2, 3, 4, 5]; track $index) {
            <div
              [style.height.px]="160"
              [style.background]="'var(--ck-bg-panel)'"
              [style.border]="'1px solid var(--ck-stroke-2)'"
              [style.borderRadius.px]="6"
              [style.opacity]="0.5"
            ></div>
          }
        </div>
      } @else if (loadProblem(); as problem) {
        <section role="alert" class="ck-surface" style="padding:24px">
          <p>{{ i18n.t(problem) }}</p>
          <div style="display:flex;align-items:center;gap:16px;margin-top:12px">
            <button type="button" style="padding:8px 16px;border:1px solid var(--ck-stroke-2);border-radius:4px" (click)="reloadCurrentScope()">{{ i18n.t('common.retry') }}</button>
            <a style="text-decoration:underline" [navLink]="{ leaf: 'help-guide', ref: 'systems' }">{{ i18n.t('experience.adoption.help') }}</a>
          </div>
        </section>
      } @else if (systems().length === 0 && store.systems().length > 0) {
        <p style="padding:24px;color:var(--ck-fg-3)" role="status">{{ i18n.t('systems.grid.category_empty') }}</p>
      } @else if (systems().length === 0) {
        <div
          [style.padding]="'48px 32px'"
          [style.background]="'var(--ck-bg-panel)'"
          [style.border]="'1px solid var(--ck-stroke-2)'"
          [style.borderRadius.px]="6"
          [style.textAlign]="'center'"
        >
          <div [style.display]="'inline-flex'" [style.color]="'var(--ck-signal-cool)'"><ck-glyph name="cube" [size]="24" /></div>
          <h3
            [style.fontFamily]="'var(--ck-font-display)'"
            [style.fontSize.px]="18"
            [style.fontWeight]="600"
            [style.color]="'var(--ck-fg-1)'"
            [style.margin]="'12px 0 6px 0'"
          >{{ i18n.t('systems.empty') }}</h3>
          <p [style.color]="'var(--ck-fg-3)'" [style.fontSize.px]="13" [style.margin]="'0 auto 18px'" [style.maxWidth.ch]="54">
            {{ i18n.t('systems.grid.empty_description') }}
          </p>
          <a
            [navLink]="{ leaf: 'system-new' }"
            class="ck-btn ck-cta ck-press"
            data-testid="systems-create-first"
          >
            <ck-glyph name="bolt" [size]="12" />
            {{ i18n.t('systems.grid.create_first') }}
          </a>
        </div>
      } @else {
        <div [style.display]="'grid'" [style.gridTemplateColumns]="'repeat(auto-fill, minmax(min(340px, 100%), 1fr))'" [style.gap.px]="12">
          @for (system of systems(); track system.id) {
            <article
              data-testid="system-card"
              [style.position]="'relative'"
              [style.display]="'flex'"
              [style.flexDirection]="'column'"
              [style.gap.px]="12"
              [style.padding]="'16px'"
              [style.background]="'var(--ck-bg-panel)'"
              [style.border]="'1px solid var(--ck-stroke-2)'"
              [style.borderRadius.px]="6"
              [style.transition]="'border-color 120ms var(--ck-ease-out), transform 120ms'"
              onmouseover="this.style.borderColor='var(--ck-stroke-3)'"
              onmouseout="this.style.borderColor='var(--ck-stroke-2)'"
            >
            <a
              [routerLink]="navigation.objectUrlTree('system', system.id, {
                capabilityId: navigation.capabilityId()
              })"
              class="flex flex-col gap-3 flex-1 min-w-0"
              style="color:inherit; text-decoration:none;"
            >
              <div [style.display]="'flex'" [style.alignItems]="'flex-start'" [style.gap.px]="10">
                <div
                  [style.width.px]="32"
                  [style.height.px]="32"
                  [style.flex]="'0 0 32px'"
                  [style.borderRadius.px]="4"
                  [style.background]="'var(--ck-bg-inset)'"
                  [style.border]="'1px solid var(--ck-stroke-2)'"
                  [style.display]="'inline-flex'"
                  [style.alignItems]="'center'"
                  [style.justifyContent]="'center'"
                  [style.color]="'var(--ck-signal-cool)'"
                >
                  <ck-glyph name="cube" [size]="16" />
                </div>
                <div [style.flex]="'1 1 auto'" [style.minWidth.px]="0">
                  <div [style.display]="'flex'" [style.alignItems]="'center'" [style.gap.px]="8">
                    <span
                      [style.fontFamily]="'var(--ck-font-sans)'"
                      [style.fontSize.px]="14"
                      [style.fontWeight]="500"
                      [style.color]="'var(--ck-fg-1)'"
                      [style.overflow]="'hidden'"
                      [style.textOverflow]="'ellipsis'"
                      [style.whiteSpace]="'nowrap'"
                    >{{ system.name }}</span>
                    @if (system.draft) {
                      <span class="ck-pill ck-tone-warn">{{ i18n.t('systems.grid.draft') }}</span>
                    } @else {
                      <ck-live-dot tone="pos" />
                    }
                  </div>
                  <p
                    [style.fontSize.px]="11"
                    [style.color]="'var(--ck-fg-3)'"
                    [style.margin]="'4px 0 0 0'"
                    [style.lineHeight]="1.5"
                    [style.display]="'-webkit-box'"
                    [style.overflow]="'hidden'"
                    style="-webkit-line-clamp: 2; -webkit-box-orient: vertical;"
                  >{{ system.description || i18n.t('systems.grid.no_description') }}</p>
                </div>
              </div>

              <div [style.display]="'grid'" [style.gridTemplateColumns]="'repeat(3, 1fr)'" [style.gap.px]="8" [style.paddingTop.px]="12" [style.borderTop]="'1px solid var(--ck-stroke-1)'">
                <ck-stat-readout [label]="i18n.t('systems.grid.stat_runs')" [value]="statsFor(system.id).runs > 0 ? statsFor(system.id).runs.toString() : '—'" tone="cool" [size]="14" />
                <ck-stat-readout [label]="i18n.t('systems.grid.stat_last_status')" [value]="statsFor(system.id).lastStatus" tone="pos" [size]="14" />
                <ck-stat-readout [label]="i18n.t('systems.grid.stat_last_duration')" [value]="formatDuration(statsFor(system.id).lastDurationMs)" tone="violet" [size]="14" />
              </div>

              <div [style.display]="'flex'" [style.alignItems]="'center'" [style.justifyContent]="'space-between'">
                <span [style.display]="'inline-flex'" [style.alignItems]="'center'" [style.gap.px]="6">
                  <span class="ck-pill ck-tone-info">{{ badgeFor(system) }}</span>
                  @if (isPromotedScratchpad(system)) {
                    <span class="ck-pill ck-tone-neutral">{{ i18n.t('systems.grid.scratchpad') }}</span>
                  }
                </span>
                <span [style.color]="'var(--ck-fg-4)'">
                  <ck-glyph name="arrow-right" [size]="12" />
                </span>
              </div>
            </a>
            <div style="display:flex;gap:8px;align-items:center;justify-content:flex-end;flex-wrap:wrap">
            @if (system.model_operation; as operation) {
              <a [navLink]="{ leaf: 'model-doc', ref: operation.model_id }" class="ck-btn ck-btn--sm ck-btn-quiet" data-testid="system-card-open-model">
                {{ i18n.t('systems.grid.open_model') }}
              </a>
            }
            @if (hasFlow(system)) {
              <a
                [navLink]="{ leaf: 'system-flow', ref: system.id, lens: 'build' }"
                class="ck-btn ck-btn--sm ck-btn-quiet self-end"
                [attr.aria-label]="i18n.t('systems.design.open_flow_for', { name: system.name })"
                data-testid="system-card-open-flow"
              >
                <ck-glyph name="flow" [size]="12" /> {{ i18n.t('systems.design.open_flow') }}
              </a>
            }
            </div>
            </article>
          }
        </div>
      }
    </ck-page-frame>
  `,
})
export class SystemsGridComponent implements OnInit, OnDestroy {
  protected readonly store = inject(SystemsStore);
  readonly loadProblem = signal<string | null>(null);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly canonical = inject(CanonicalApiService);
  private readonly workspace = inject(WorkspaceService);
  protected readonly navigation = inject(ZoomContextService);
  protected readonly i18n = inject(I18nService);
  private currentCapabilityId: string | null = null;
  private routeSubscription: Subscription | null = null;
  private contextRefreshSubscription: Subscription | null = null;
  private requestSubscription: Subscription | null = null;
  private readonly workspaceView = new WorkspaceViewContext(
    this.workspace,
    () => this.resetWorkspaceState(),
    () => this.reloadCurrentScope(),
  );

  prompt = '';
  private readonly summaries = signal<RunSystemSummary[]>([]);

  readonly categories: SystemCategoryFilter[] = ['business', 'model_operations', 'all'];
  readonly categoryFilter = signal<SystemCategoryFilter>('business');
  readonly recentSystems = computed(() => {
    const visible = new Set(this.systems().map(system => system.id));
    return this.summaries().filter(summary => visible.has(summary.system_id)).slice(0, 3);
  });

  statsFor(id: string): AgentStats {
    const s = this.summaries().find((summary) => summary.system_id === id);
    if (!s) return { runs: 0, lastStatus: '—', lastDurationMs: null };
    return {
      runs: s.run_count,
      lastStatus: this.statusLabel(s.last_status),
      lastDurationMs: s.last_duration_ms,
    };
  }

  statusLabel(status: string | null): string {
    if (!status) return '—';
    const key = `runs.status.${status}`;
    const label = this.i18n.t(key);
    return label === key ? status : label;
  }

  formatDuration(durationMs: number | null): string {
    if (durationMs == null) return '—';
    if (durationMs < 1_000) return `${Math.round(durationMs)}ms`;
    const seconds = durationMs / 1_000;
    if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)}s`;
    const minutes = Math.floor(seconds / 60);
    return `${minutes}m ${Math.round(seconds % 60)}s`;
  }

  readonly systems = computed(() => filterSystems(this.store.systems(), this.categoryFilter()));
  categoryCount(category: SystemCategoryFilter): number { return filterSystems(this.store.systems(), category).length; }
  readonly activeKey = computed(() => activeSystemsKey(this.systems().length));
  readonly primaryAction = computed(() => systemsPrimaryAction({
    loading: this.store.loading(),
    problem: !!this.loadProblem(),
    count: this.store.systems().length,
  }));

  readonly templates: Template[] = [
    { id: 'contract',   labelKey: 'systems.template.contract',   descriptionKey: 'systems.template.contract.desc',   promptKey: 'systems.template.contract.prompt' },
    { id: 'support',    labelKey: 'systems.template.support',    descriptionKey: 'systems.template.support.desc',    promptKey: 'systems.template.support.prompt' },
    { id: 'code',       labelKey: 'systems.template.code',       descriptionKey: 'systems.template.code.desc',       promptKey: 'systems.template.code.prompt' },
    { id: 'research',   labelKey: 'systems.template.research',   descriptionKey: 'systems.template.research.desc',   promptKey: 'systems.template.research.prompt' },
    { id: 'onboarding', labelKey: 'systems.template.onboarding', descriptionKey: 'systems.template.onboarding.desc', promptKey: 'systems.template.onboarding.prompt' },
    { id: 'insights',   labelKey: 'systems.template.insights',   descriptionKey: 'systems.template.insights.desc',   promptKey: 'systems.template.insights.prompt' },
  ];

  ngOnInit(): void {
    this.routeSubscription = this.route.queryParamMap.pipe(
      map((params) => this.effectiveCapabilityId(params.get('capabilityId'))),
      distinctUntilChanged(),
    ).subscribe((capabilityId) => {
      this.currentCapabilityId = capabilityId;
      this.resetResults();
      this.loadScope(capabilityId);
    });
    this.contextRefreshSubscription = this.workspace.contextRefresh$.subscribe(() => {
      const next = this.effectiveCapabilityId(
        this.route.snapshot.queryParamMap.get('capabilityId'),
      );
      if (next === this.currentCapabilityId) return;
      this.currentCapabilityId = next;
      this.resetResults();
      this.loadScope(next);
    });
  }

  ngOnDestroy(): void {
    this.routeSubscription?.unsubscribe();
    this.routeSubscription = null;
    this.contextRefreshSubscription?.unsubscribe();
    this.contextRefreshSubscription = null;
    this.workspaceView.destroy();
  }

  applyTemplate(tpl: Template): void {
    this.prompt = this.i18n.t(tpl.promptKey);
  }

  startFromPrompt(): void {
    const p = this.prompt.trim();
    if (!p) return;
    const tree = this.router.parseUrl(this.navigation.leafUrl('system-new'));
    tree.queryParams = {
      ...tree.queryParams,
      prompt: p,
      name: this.suggestNameFromPrompt(p),
    };
    void this.router.navigateByUrl(tree);
  }

  private suggestNameFromPrompt(p: string): string {
    const words = p.replace(/[^a-zA-Z0-9\s]/g, '').trim().split(/\s+/).slice(0, 4);
    if (words.length === 0) return this.i18n.t('systems.create');
    return words
      .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
      .join(' ');
  }

  systemIcon(system: SystemAgent): string {
    // Legacy helper, retained for back-compat with any remaining callers; the
    // grid now renders a single canonical glyph.
    return 'cube';
  }

  badgeFor(system: SystemAgent): string {
    if (systemCategory(system) === 'model_operations') return this.i18n.t('systems.grid.category.model_operations');
    return systemCatalogBadge(system, system.rag_mode);
  }

  hasFlow(system: SystemAgent): boolean {
    return !system.draft && isFlowBackedSystem(system);
  }

  isPromotedScratchpad(system: SystemAgent): boolean {
    return isPromotedFromScratchpad(system);
  }

  private loadScope(capabilityId: string | null): void {
    this.loadProblem.set(null);
    this.requestSubscription?.unsubscribe();
    this.requestSubscription = null;
    const request = this.workspaceView.beginRequest();
    const subscription = forkJoin({
      systems: this.store.load({ capabilityId }),
      summaries: this.canonical.listRunSummaries(
        capabilityId ? { capability_id: capabilityId } : undefined,
      ),
    }).subscribe({
      next: ({ summaries }) => {
        if (
          !this.workspaceView.isCurrent(request)
          || capabilityId !== this.currentCapabilityId
        ) {
          return;
        }
        this.summaries.set(summaries ?? []);
      },
      error: (error: { status?: number }) => {
        if (
          !this.workspaceView.isCurrent(request)
          || capabilityId !== this.currentCapabilityId
        ) {
          return;
        }
        this.summaries.set([]);
        this.loadProblem.set(error?.status === 403 ? 'experience.adoption.access_denied' : 'experience.adoption.load_failed');
      },
    });
    this.requestSubscription = subscription.closed ? null : subscription;
  }

  private effectiveCapabilityId(capabilityId: string | null): string | null {
    return this.navigation.axesV3Enabled() ? capabilityId : null;
  }

  reloadCurrentScope(): void {
    this.currentCapabilityId = this.effectiveCapabilityId(
      this.route.snapshot.queryParamMap.get('capabilityId'),
    );
    this.loadScope(this.currentCapabilityId);
  }

  private resetResults(): void {
    this.requestSubscription?.unsubscribe();
    this.requestSubscription = null;
    this.workspaceView.invalidate();
    this.summaries.set([]);
  }

  private resetWorkspaceState(): void {
    this.categoryFilter.set('business');
    this.requestSubscription?.unsubscribe();
    this.requestSubscription = null;
    this.summaries.set([]);
  }
}

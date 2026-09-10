import { HelpTooltipComponent } from '@app/shared/cockpit/help-tooltip.component';
import { ChangeDetectionStrategy, Component, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { Subscription, distinctUntilChanged, forkJoin, map } from 'rxjs';
import { CanonicalApiService, Run } from '@app/core/canonical-api.service';
import { I18nService } from '@app/core/i18n.service';
import {
  GlyphComponent,
  KbdComponent,
  LiveDotComponent,
  NavLinkDirective,
  PageFrameComponent,
  StatReadoutComponent,
  TagComponent,
} from '@app/shared/cockpit';
import { SystemsStore, SystemAgent } from './systems.store';
import { isPromotedFromScratchpad, systemCatalogBadge } from './system-flow-profile';
import { ZoomContextService } from '@app/core/zoom-context.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { WorkspaceViewContext } from '@app/core/workspace-view-context';

interface AgentStats {
  runs: number;
  avgLatency: number;
  lastRun: string | null;
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
 * composer on top, grid of mono-labeled cards below. No legacy section header.
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
    TagComponent,
  ],
  template: `

    <ck-page-frame
      [eyebrow]="i18n.t('systems.grid.eyebrow')"
      [title]="i18n.t('systems.grid.title')"
      [description]="i18n.t('systems.grid.description')"
      [status]="loadProblem() ? '' : i18n.t('systems.grid.status_active', { count: systems().length })"
    >
      <ck-help titleHelp id="adoption.systems" />
      <a
        actions
        [navLink]="{ leaf: 'system-new' }"
        [style.display]="'inline-flex'"
        [style.alignItems]="'center'"
        [style.gap.px]="6"
        [style.padding]="'6px 12px'"
        [style.height.px]="28"
        [style.background]="'var(--ck-signal-cool)'"
        [style.color]="'var(--ck-on-signal)'"
        [style.border]="'none'"
        [style.borderRadius.px]="4"
        [style.fontFamily]="'var(--ck-font-mono)'"
        [style.fontSize.px]="11"
        [style.fontWeight]="600"
        [style.letterSpacing]="'0.08em'"
        [style.textTransform]="'uppercase'"
        [style.cursor]="'pointer'"
        [style.textDecoration]="'none'"
      >
        <ck-glyph name="bolt" [size]="12" />
        {{ i18n.t('systems.create') }}
      </a>

      <!-- Quick-start composer -->
      <section
        class="ck-hero-ambient"
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
          [style.fontFamily]="'var(--ck-font-sans)'"
          [style.fontSize.px]="20"
          [style.fontWeight]="500"
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
            [disabled]="!prompt.trim()"
            [style.padding]="'0 14px'"
            [style.height.px]="32"
            [style.background]="'var(--ck-signal-cool)'"
            [style.color]="'var(--ck-on-signal)'"
            [style.border]="'none'"
            [style.borderRadius.px]="4"
            [style.fontFamily]="'var(--ck-font-mono)'"
            [style.fontSize.px]="11"
            [style.fontWeight]="600"
            [style.letterSpacing]="'0.08em'"
            [style.textTransform]="'uppercase'"
            [style.cursor]="prompt.trim() ? 'pointer' : 'not-allowed'"
            [style.opacity]="prompt.trim() ? 1 : 0.4"
          >{{ i18n.t('systems.grid.compose') }}</button>
        </form>

        <div [style.display]="'flex'" [style.flexWrap]="'wrap'" [style.gap.px]="6" [style.marginTop.px]="14">
          @for (tpl of templates; track tpl.id) {
            <button
              type="button"
              (click)="applyTemplate(tpl)"
              [style.padding]="'3px 10px'"
              [style.background]="'transparent'"
              [style.border]="'1px solid var(--ck-stroke-2)'"
              [style.borderRadius.px]="99"
              [style.color]="'var(--ck-fg-3)'"
              [style.fontFamily]="'var(--ck-font-mono)'"
              [style.fontSize.px]="10"
              [style.letterSpacing]="'0.08em'"
              [style.textTransform]="'uppercase'"
              [style.cursor]="'pointer'"
              [title]="i18n.t(tpl.descriptionKey)"
            >{{ i18n.t(tpl.labelKey) }}</button>
          }
        </div>
      </section>

      <!-- Grid header -->
      <div [style.display]="'flex'" [style.alignItems]="'center'" [style.justifyContent]="'space-between'" [style.marginBottom.px]="12">
        <span class="ck-label">{{ loadProblem() ? '' : i18n.t('systems.grid.count', { count: systems().length }) }}</span>
        <span class="ck-mono" [style.fontSize.px]="10" [style.color]="'var(--ck-fg-4)'" [style.letterSpacing]="'0.10em'">
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
            [style.fontFamily]="'var(--ck-font-sans)'"
            [style.fontSize.px]="18"
            [style.fontWeight]="500"
            [style.color]="'var(--ck-fg-1)'"
            [style.margin]="'12px 0 6px 0'"
          >{{ i18n.t('systems.empty') }}</h3>
          <p [style.color]="'var(--ck-fg-3)'" [style.fontSize.px]="13" [style.margin]="'0 auto 18px'" [style.maxWidth.ch]="54">
            {{ i18n.t('systems.grid.empty_description') }}
          </p>
          <a
            [navLink]="{ leaf: 'system-new' }"
            [style.display]="'inline-flex'"
            [style.alignItems]="'center'"
            [style.gap.px]="6"
            [style.padding]="'6px 14px'"
            [style.height.px]="30"
            [style.background]="'var(--ck-signal-cool)'"
            [style.color]="'var(--ck-on-signal)'"
            [style.borderRadius.px]="4"
            [style.fontFamily]="'var(--ck-font-mono)'"
            [style.fontSize.px]="11"
            [style.fontWeight]="600"
            [style.letterSpacing]="'0.08em'"
            [style.textTransform]="'uppercase'"
            [style.textDecoration]="'none'"
          >
            <ck-glyph name="bolt" [size]="12" />
            {{ i18n.t('systems.grid.create_first') }}
          </a>
        </div>
      } @else {
        <div [style.display]="'grid'" [style.gridTemplateColumns]="'repeat(auto-fill, minmax(340px, 1fr))'" [style.gap.px]="12">
          @for (system of systems(); track system.id) {
            <a
              [routerLink]="navigation.objectUrlTree('system', system.id, {
                capabilityId: navigation.capabilityId()
              })"
              [style.position]="'relative'"
              [style.display]="'flex'"
              [style.flexDirection]="'column'"
              [style.gap.px]="12"
              [style.padding]="'16px'"
              [style.background]="'var(--ck-bg-panel)'"
              [style.border]="'1px solid var(--ck-stroke-2)'"
              [style.borderRadius.px]="6"
              [style.color]="'inherit'"
              [style.textDecoration]="'none'"
              [style.transition]="'border-color 120ms var(--ck-ease-out), transform 120ms'"
              onmouseover="this.style.borderColor='var(--ck-stroke-3)'"
              onmouseout="this.style.borderColor='var(--ck-stroke-2)'"
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
                      <ck-tag tone="warn" variant="outline">DRAFT</ck-tag>
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
                <ck-stat-readout [label]="i18n.t('systems.grid.stat_runs')"   [value]="statsFor(system.id).runs > 0 ? statsFor(system.id).runs.toString() : '—'" tone="cool" [size]="14" />
                <ck-stat-readout [label]="i18n.t('systems.grid.stat_avg_ms')" [value]="statsFor(system.id).avgLatency > 0 ? statsFor(system.id).avgLatency.toString() : '—'" tone="pos" [size]="14" />
                <ck-stat-readout [label]="i18n.t('systems.grid.stat_last')"   [value]="statsFor(system.id).lastRun ?? '—'" tone="violet" [size]="14" />
              </div>

              <div [style.display]="'flex'" [style.alignItems]="'center'" [style.justifyContent]="'space-between'">
                <span [style.display]="'inline-flex'" [style.alignItems]="'center'" [style.gap.px]="6">
                  <ck-tag tone="cool" variant="soft">
                    {{ badgeFor(system) }}
                  </ck-tag>
                  @if (isPromotedScratchpad(system)) {
                    <ck-tag tone="neutral" variant="outline">SCRATCHPAD</ck-tag>
                  }
                </span>
                <span [style.color]="'var(--ck-fg-4)'">
                  <ck-glyph name="arrow-right" [size]="12" />
                </span>
              </div>
            </a>
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
  private readonly runs = signal<Run[]>([]);

  readonly statsByAgent = computed<Record<string, AgentStats>>(() => {
    const out: Record<string, AgentStats> = {};
    for (const r of this.runs()) {
      const id = r.system_id ?? '';
      if (!id) continue;
      const cur = out[id] ?? { runs: 0, avgLatency: 0, lastRun: null };
      cur.runs += 1;
      if (r.duration_ms) {
        cur.avgLatency =
          cur.runs === 1
            ? Math.round(r.duration_ms)
            : Math.round(((cur.avgLatency * (cur.runs - 1)) + r.duration_ms) / cur.runs);
      }
      const ts = r.ended_at ?? r.started_at ?? null;
      if (ts && (!cur.lastRun || ts > cur.lastRun)) cur.lastRun = ts;
      out[id] = cur;
    }
    return out;
  });

  statsFor(id: string): AgentStats {
    const s = this.statsByAgent()[id];
    if (!s) return { runs: 0, avgLatency: 0, lastRun: null };
    return { ...s, lastRun: s.lastRun ? this.formatRelative(s.lastRun) : null };
  }

  private formatRelative(iso: string): string {
    const t = Date.parse(iso);
    if (Number.isNaN(t)) return '';
    const diff = Date.now() - t;
    const minute = 60_000;
    const hour = 60 * minute;
    const day = 24 * hour;
    if (diff < minute) return 'now';
    if (diff < hour) return Math.round(diff / minute) + 'm';
    if (diff < day) return Math.round(diff / hour) + 'h';
    return Math.round(diff / day) + 'd';
  }

  readonly systems = this.store.systems;

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
    return systemCatalogBadge(system, system.rag_mode);
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
      // Canonical `/runs` — the legacy `/traces/traces` alias is deprecated.
      runs: this.canonical.listRuns(capabilityId ? { capability_id: capabilityId } : undefined),
    }).subscribe({
      next: ({ runs }) => {
        if (
          !this.workspaceView.isCurrent(request)
          || capabilityId !== this.currentCapabilityId
        ) {
          return;
        }
        this.runs.set(runs ?? []);
      },
      error: (error: { status?: number }) => {
        if (
          !this.workspaceView.isCurrent(request)
          || capabilityId !== this.currentCapabilityId
        ) {
          return;
        }
        this.runs.set([]);
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
    this.runs.set([]);
  }

  private resetWorkspaceState(): void {
    this.requestSubscription?.unsubscribe();
    this.requestSubscription = null;
    this.runs.set([]);
  }
}

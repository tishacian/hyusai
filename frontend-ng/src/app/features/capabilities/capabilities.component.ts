import { HelpTooltipComponent } from '@app/shared/cockpit/help-tooltip.component';
import { ChangeDetectionStrategy, Component, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { Subscription, distinctUntilChanged, forkJoin, map } from 'rxjs';
import { CanonicalApiService, type Capability, type Run, type Skill } from '@app/core/canonical-api.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { WorkspaceViewContext } from '@app/core/workspace-view-context';
import { ZoomContextService } from '@app/core/zoom-context.service';
import {
  GlyphComponent,
  KbdComponent,
  MicroBarComponent,
  NavLinkDirective,
  PageFrameComponent,
  RunOutcomeCardComponent,
  RuntimeStatusBadgeComponent,
  StatReadoutComponent,
  TagComponent,
} from '@app/shared/cockpit';

type TierFilter = 'all' | 'universal' | 'industry' | 'client';

@Component({
  selector: 'app-capabilities',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [HelpTooltipComponent,
    PageFrameComponent,
    GlyphComponent,
    StatReadoutComponent,
    MicroBarComponent,
    TagComponent,
    KbdComponent,
    RunOutcomeCardComponent,
    RuntimeStatusBadgeComponent,
    NavLinkDirective,
    RouterLink,
  ],
  template: `

    <ck-page-frame
      eyebrow="Catalog · Capabilities"
      title="Universal · Industry · Client"
      description="Browse and configure the canonical capabilities your systems can compose. Each capability bundles certified skills, pricing and SLA."
    >
      <ck-help titleHelp id="adoption.systems" />
      <a
        actions
        [navLink]="{ leaf: 'capability-curation' }"
        class="ck-mono"
        style="padding:6px 12px; border-radius:4px; font-size:10px; letter-spacing:0.14em; text-transform:uppercase; background:var(--ck-bg-inset); color:var(--ck-fg-2); border:1px solid var(--ck-stroke-soft); text-decoration:none;"
        title="Which skills this workspace sees, and the lever behind every exclusion"
      >
        Catalog coverage →
      </a>

      <div class="flex flex-col gap-6">
        <!-- Filter bar -->
        <div class="flex items-center justify-between flex-wrap gap-4">
          <div class="flex items-center gap-1 ck-surface rounded-md" style="padding:4px;">
            @for (t of tiers; track t.id) {
              <button
                type="button"
                (click)="tier.set(t.id)"
                class="ck-mono"
                style="padding:6px 12px; border-radius:4px; font-size:10px; letter-spacing:0.14em; text-transform:uppercase;"
                [style.background]="tier() === t.id ? 'var(--ck-bg-inset)' : 'transparent'"
                [style.color]="tier() === t.id ? 'var(--ck-fg-1)' : 'var(--ck-fg-4)'"
                [style.boxShadow]="tier() === t.id ? 'inset 0 0 0 1px var(--ck-stroke-strong)' : 'none'"
              >
                {{ t.label }}
                @if (tier() === t.id) {
                  <span class="ck-tnum" style="margin-left:6px; color:var(--ck-fg-3);">
                    {{ filtered().length }}
                  </span>
                }
              </button>
            }
          </div>
          <div class="flex items-center gap-2">
            <ck-kbd>⌘F</ck-kbd>
            <input
              type="search"
              [value]="query()"
              (input)="query.set(asInput($event).value)"
              placeholder="Filter capabilities…"
              class="ck-mono"
              style="padding:6px 12px; font-size:11px; border-radius:4px; background:var(--ck-bg-inset); border:1px solid var(--ck-stroke-soft); color:var(--ck-fg-1); width:220px;"
            />
          </div>
        </div>

        <!-- Grid -->
        @if (loading()) {
          <div class="ck-mono" style="font-size:11px; color:var(--ck-fg-4); text-align:center; padding:40px;">
            Loading catalog…
          </div>
        } @else if (!filtered().length) {
          <div class="ck-surface rounded-md" style="padding:40px; text-align:center;">
            <div class="ck-mono" style="font-size:10px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4);">
              NO CAPABILITY MATCHES
            </div>
          </div>
        } @else {
          <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            @for (c of filtered(); track c.id) {
              <article
                class="ck-surface rounded-md"
                style="padding: 18px 20px; display:flex; flex-direction:column; gap:14px; cursor:pointer;"
                [style.boxShadow]="selected()?.id === c.id ? 'var(--ck-glow-cool)' : 'none'"
                [style.borderColor]="selected()?.id === c.id ? 'var(--ck-stroke-strong)' : 'var(--ck-stroke-soft)'"
                (click)="selectCapability(selected()?.id === c.id ? null : c)"
              >
                <header class="flex items-start justify-between gap-3">
                  <div class="flex flex-col gap-1 min-w-0">
                    <div class="flex items-center gap-2">
                      <ck-tag [tone]="tierTone(c.tier)" variant="soft">{{ c.tier || 'UNIV' }}</ck-tag>
                      @if (c.industry) {
                        <ck-tag tone="violet" variant="outline">{{ c.industry }}</ck-tag>
                      }
                    </div>
                    <h3 class="text-base font-medium text-white truncate">{{ c.name }}</h3>
                    <span class="ck-mono" style="font-size:10px; color:var(--ck-fg-4);">{{ c.slug }}</span>
                  </div>
                  <ck-glyph name="cube" [size]="16" />
                </header>

                <p class="ck-mono" style="font-size:11px; color:var(--ck-fg-3); line-height:1.6; display:-webkit-box; -webkit-line-clamp:3; -webkit-box-orient:vertical; overflow:hidden;">
                  {{ c.description || '—' }}
                </p>

                <div [style.display]="'grid'" [style.grid-template-columns]="hideRoi() ? '1fr 1fr' : '1fr 1fr 1fr'" style="gap:10px;">
                  <ck-stat-readout label="COST" [value]="formatPrice(c.pricing?.unit_price)" tone="cool" [size]="13" />
                  <ck-stat-readout label="VALUE" [value]="formatPrice(c.value_per_outcome)" tone="pos" [size]="13" />
                  @if (!hideRoi()) {
                    <ck-stat-readout label="ROI" [value]="projectedRoi(c)" tone="violet" [size]="13" />
                  }
                </div>

                <footer class="pt-3" style="border-top:1px solid var(--ck-hair);">
                  <div class="flex items-center justify-between">
                    <span class="ck-mono" style="font-size:9px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-4);">
                      {{ c.skill_ids?.length || 0 }} SKILLS · {{ c.input_unit || '—' }} → {{ c.output_unit || '—' }}
                    </span>
                    <div class="flex items-center gap-2">
                      @if (c.confidence_threshold != null) {
                        <span class="ck-mono ck-tnum" style="font-size:10px; color:var(--ck-fg-3);">
                          τ{{ c.confidence_threshold.toFixed(2) }}
                        </span>
                      }
                      <a
                        [routerLink]="navigation.objectUrlTree('capability', c.id)"
                        (click)="$event.stopPropagation()"
                        class="ck-mono"
                        style="font-size:10px; letter-spacing:0.12em; text-transform:uppercase; color:var(--ck-fg-3); border:1px solid var(--ck-stroke-soft); padding:3px 8px; border-radius:3px; text-decoration:none;"
                        title="Open capability detail"
                      >Open →</a>
                    </div>
                  </div>
                </footer>
              </article>
            }
          </div>
        }

        <!-- Drill-down panel -->
        @if (selected(); as cap) {
          <section class="ck-surface rounded-md relative overflow-hidden" style="padding:24px 28px;">
            <div class="flex items-start justify-between gap-4 mb-4">
              <div>
                <div class="ck-mono flex items-center gap-2" style="font-size:10px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4);">
                  <ck-glyph name="cube" [size]="12" />
                  CAPABILITY DRILL-DOWN
                </div>
                <h3 class="text-xl font-medium text-white mt-2">{{ cap.name }}</h3>
              </div>
              <button
                type="button"
                (click)="selectCapability(null)"
                class="ck-mono"
                style="padding:6px 10px; border-radius:4px; font-size:10px; letter-spacing:0.14em; text-transform:uppercase; background:var(--ck-bg-inset); color:var(--ck-fg-3); border:1px solid var(--ck-stroke-soft);"
              >
                CLOSE
              </button>
            </div>

            <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
              <div class="md:col-span-2 flex flex-col gap-4">
                <div>
                  <div class="ck-mono" style="font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4); margin-bottom:6px;">
                    OBJECTIVE
                  </div>
                  <p class="text-sm text-white" style="line-height:1.6;">{{ cap.description }}</p>
                </div>

                <div>
                  <div class="ck-mono" style="font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4); margin-bottom:8px;">
                    BUNDLED SKILLS · {{ bundledSkills(cap).length }}
                  </div>
                  <ul style="display:flex; flex-direction:column; gap:4px;">
                    @for (sk of bundledSkills(cap); track sk.id) {
                      <li style="display:grid; grid-template-columns: 70px 90px 1fr 70px 70px; gap:10px; align-items:center; padding:8px 12px; border-radius:4px; background:var(--ck-bg-inset);">
                        <ck-tag [tone]="certTone(sk.certification_level)" variant="outline">
                          {{ (sk.certification_level || 'basic').slice(0, 4).toUpperCase() }}
                        </ck-tag>
                        <ck-runtime-status [status]="sk.runtime_status" />
                        <div class="min-w-0">
                          <div class="text-sm text-white font-medium">{{ sk.name }}</div>
                          <div class="ck-mono" style="font-size:10px; color:var(--ck-fg-4);">{{ sk.slug }}</div>
                        </div>
                        <span class="ck-mono" style="font-size:10px; color:var(--ck-fg-3); text-align:right;">
                          {{ sk.type || '—' }}
                        </span>
                        <span class="ck-mono ck-tnum" style="font-size:10px; color:var(--ck-fg-2); text-align:right;">
                          {{ formatPrice(sk.pricing?.unit_price) }}
                        </span>
                      </li>
                    }
                  </ul>
                </div>
              </div>

              <div class="flex flex-col gap-4">
                <div>
                  <div class="ck-mono" style="font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4); margin-bottom:6px;">
                    ECONOMICS
                  </div>
                  <div class="flex flex-col gap-3">
                    <ck-stat-readout label="UNIT PRICE" [value]="formatPrice(cap.pricing?.unit_price)" tone="cool" [size]="16" />
                    <ck-stat-readout label="VALUE / OUTCOME" [value]="formatPrice(cap.value_per_outcome)" tone="pos" [size]="16" />
                    @if (!hideRoi()) {
                      <ck-stat-readout label="PROJECTED ROI" [value]="projectedRoi(cap)" tone="violet" [size]="16" />
                    }
                  </div>
                </div>

                @if (cap.confidence_threshold != null) {
                  <div>
                    <div class="ck-mono" style="font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4); margin-bottom:6px;">
                      CONFIDENCE FLOOR
                    </div>
                    <div style="display:flex; align-items:center; gap:10px;">
                      <ck-micro-bar
                        [value]="cap.confidence_threshold * 100"
                        [max]="100"
                        [width]="120"
                        tone="warn"
                      />
                      <span class="ck-mono ck-tnum" style="font-size:11px; color:var(--ck-fg-2);">
                        {{ (cap.confidence_threshold * 100).toFixed(0) }}%
                      </span>
                    </div>
                    <p class="ck-mono" style="font-size:10px; color:var(--ck-fg-4); margin-top:4px;">
                      Below this threshold, the Control policy escalates to HITL.
                    </p>
                  </div>
                }

                <div>
                  <div class="ck-mono" style="font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4); margin-bottom:6px;">
                    SLA
                  </div>
                  <pre class="ck-mono" style="font-size:10px; color:var(--ck-fg-2); margin:0; background:var(--ck-bg-inset); padding:8px 10px; border-radius:4px; white-space:pre-wrap;">{{ formatJson(cap.sla) }}</pre>
                </div>
              </div>
            </div>

            <!-- Recent execution evidence for this capability. -->
            <div class="grid grid-cols-1 gap-4 mt-6">
              <div>
                <div class="ck-mono flex items-center gap-2" style="font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4); margin-bottom:8px;">
                  <ck-glyph name="crosshair" [size]="12" />
                  LATEST RUN OUTCOME
                </div>
                @if (latestRun()) {
                  <ck-run-outcome-card [run]="latestRun()!" />
                } @else {
                  <div class="ck-surface rounded-md ck-mono" style="padding:20px; font-size:11px; text-align:center; color:var(--ck-fg-4);">
                    NO RUN RECORDED FOR THIS CAPABILITY YET
                  </div>
                }
              </div>
            </div>
          </section>
        }
      </div>
    </ck-page-frame>
  `,
})
export class CapabilitiesComponent implements OnInit, OnDestroy {
  private readonly canonical = inject(CanonicalApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly workspace = inject(WorkspaceService);
  protected readonly navigation = inject(ZoomContextService);
  private focusSubscription: Subscription | null = null;
  private catalogSubscription: Subscription | null = null;
  private latestRunSubscription: Subscription | null = null;
  private latestRunGeneration = 0;
  private currentFocus: string | null = null;
  private readonly workspaceView = new WorkspaceViewContext(
    this.workspace,
    () => this.resetWorkspaceState(),
    () => this.reloadCatalog(),
  );

  readonly hideRoi = computed(() => this.workspace.isBuilderMode());

  readonly tiers: { id: TierFilter; label: string }[] = [
    { id: 'all', label: 'ALL' },
    { id: 'universal', label: 'UNIVERSAL' },
    { id: 'industry', label: 'INDUSTRY' },
    { id: 'client', label: 'CLIENT' },
  ];

  readonly capabilities = signal<Capability[]>([]);
  readonly skills = signal<Skill[]>([]);
  readonly loading = signal(true);

  readonly tier = signal<TierFilter>('all');
  readonly query = signal('');
  readonly selected = signal<Capability | null>(null);
  readonly latestRun = signal<Run | null>(null);

  readonly filtered = computed(() => {
    const t = this.tier();
    const q = this.query().trim().toLowerCase();
    return this.capabilities().filter((c) => {
      if (t !== 'all' && c.tier !== t) return false;
      if (!q) return true;
      return (
        c.name.toLowerCase().includes(q) ||
        (c.slug || '').toLowerCase().includes(q) ||
        (c.description || '').toLowerCase().includes(q) ||
        (c.industry || '').toLowerCase().includes(q)
      );
    });
  });

  ngOnInit(): void {
    this.focusSubscription = this.route.queryParamMap.pipe(
      map((params) => params.get('focus')),
      distinctUntilChanged(),
    ).subscribe((focus) => {
      this.currentFocus = focus;
      this.applyFocusedCapability();
    });
    this.reloadCatalog();
  }

  ngOnDestroy(): void {
    this.focusSubscription?.unsubscribe();
    this.focusSubscription = null;
    this.workspaceView.destroy();
  }

  selectCapability(capability: Capability | null): void {
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: {
        focus: capability?.id ?? null,
        // `focus` becomes the routed Capability leaf. Descendants from a
        // previously scoped list must not survive and outrank it in graph
        // resolution.
        scope: null,
        capabilityId: null,
        systemId: null,
        runId: null,
        skillRef: null,
      },
      queryParamsHandling: 'merge',
    });
  }

  private applySelectedCapability(capability: Capability | null): void {
    this.cancelLatestRunRequest();
    this.selected.set(capability);
    this.latestRun.set(null);
    if (!capability) return;

    const scope = this.workspace.captureRequestScope();
    const generation = ++this.latestRunGeneration;
    const capabilityId = capability.id;
    const subscription = this.canonical.listRuns({ capability_id: capabilityId }).subscribe({
      next: (runs) => {
        if (
          generation !== this.latestRunGeneration
          || !this.workspace.isRequestScopeCurrent(scope)
          || this.selected()?.id !== capabilityId
        ) {
          return;
        }
        this.latestRun.set(runs?.[0] ?? null);
      },
      error: () => {
        if (
          generation !== this.latestRunGeneration
          || !this.workspace.isRequestScopeCurrent(scope)
          || this.selected()?.id !== capabilityId
        ) {
          return;
        }
        this.latestRun.set(null);
      },
    });
    this.latestRunSubscription = subscription.closed ? null : subscription;
  }

  bundledSkills(cap: Capability): Skill[] {
    const ids = new Set(cap.skill_ids || []);
    return this.skills().filter((s) => ids.has(s.id));
  }

  projectedRoi(cap: Capability): string {
    const cost = cap.pricing?.unit_price;
    const value = cap.value_per_outcome;
    if (!cost || !value) return '—';
    const roi = (value - cost) / cost;
    return `${(roi * 100).toFixed(0)}%`;
  }

  formatPrice(v: number | null | undefined): string {
    if (v == null) return '—';
    if (v < 0.01) return `$${v.toFixed(4)}`;
    if (v < 1) return `$${v.toFixed(3)}`;
    return `$${v.toFixed(2)}`;
  }

  formatJson(v: Record<string, unknown> | undefined): string {
    if (!v || Object.keys(v).length === 0) return '—';
    return JSON.stringify(v, null, 2);
  }

  tierTone(tier: string | undefined): 'pos' | 'cool' | 'violet' | 'warn' {
    switch (tier) {
      case 'industry': return 'violet';
      case 'client':   return 'cool';
      case 'universal':
      default:         return 'pos';
    }
  }

  certTone(cert: string | undefined): 'pos' | 'cool' | 'violet' {
    if (cert === 'enterprise') return 'violet';
    if (cert === 'production') return 'pos';
    return 'cool';
  }

  asInput(ev: Event): HTMLInputElement {
    return ev.target as HTMLInputElement;
  }

  private reloadCatalog(): void {
    this.catalogSubscription?.unsubscribe();
    this.catalogSubscription = null;
    const request = this.workspaceView.beginRequest();
    this.loading.set(true);
    const subscription = forkJoin({
      capabilities: this.canonical.listCapabilities(),
      skills: this.canonical.listSkills(),
    }).subscribe({
      next: ({ capabilities, skills }) => {
        if (!this.workspaceView.isCurrent(request)) return;
        this.capabilities.set(capabilities ?? []);
        this.skills.set(skills ?? []);
        this.loading.set(false);
        this.applyFocusedCapability();
      },
      error: () => {
        if (!this.workspaceView.isCurrent(request)) return;
        this.capabilities.set([]);
        this.skills.set([]);
        this.loading.set(false);
        this.applySelectedCapability(null);
      },
    });
    this.catalogSubscription = subscription.closed ? null : subscription;
  }

  private applyFocusedCapability(): void {
    const capability = this.currentFocus
      ? this.capabilities().find((item) => item.id === this.currentFocus) ?? null
      : null;
    this.applySelectedCapability(capability);
  }

  private cancelLatestRunRequest(): void {
    this.latestRunGeneration += 1;
    this.latestRunSubscription?.unsubscribe();
    this.latestRunSubscription = null;
  }

  private resetWorkspaceState(): void {
    this.catalogSubscription?.unsubscribe();
    this.catalogSubscription = null;
    this.cancelLatestRunRequest();
    this.capabilities.set([]);
    this.skills.set([]);
    this.selected.set(null);
    this.latestRun.set(null);
    this.loading.set(true);
  }
}

import {
  ChangeDetectionStrategy,
  Component,
  OnDestroy,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { Subscription, distinctUntilChanged, map } from 'rxjs';
import {
  CanonicalApiService,
  type SkillInvocation,
} from '@app/core/canonical-api.service';
import { I18nService } from '@app/core/i18n.service';
import { ZoomContextService } from '@app/core/zoom-context.service';
import { LensService } from '@app/core/lens';
import { isObjectLens, type ObjectLens } from '@app/core/navigation.catalog';
import {
  ObjectPerspectiveGateRevokedError,
  ObjectPerspectiveStore,
} from '@app/core/object-perspective.store';
import { WorkspaceService } from '@app/core/workspace.service';
import {
  WorkspaceViewContext,
  type WorkspaceViewRequest,
} from '@app/core/workspace-view-context';
import { NavLinkDirective } from '@app/shared/cockpit';
import {
  CkObjectHeaderComponent,
  type CkObjectKpi,
} from '@app/shared/cockpit/object-header.component';
import { CkTabComponent, CkTabsComponent } from '@app/shared/cockpit/tabs.component';
import { ObjectPerspectiveComponent } from '@app/shared/cockpit/object-perspective.component';
import type { ObjectPerspectiveResponse } from '@app/shared/cockpit/object-perspective.models';
import { recordedModelExecution } from '@app/core/model-catalog';
import { ModelExecutionComponent } from '@app/shared/cockpit/model-execution.component';
import { observabilityText } from '../observability/observability-labels';
import {
  arrivalProvenanceLabel,
  readArrivalProvenance,
  type ArrivalProvenance,
} from './arrival-provenance';

@Component({
  selector: 'app-skill-invocation-view',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    NavLinkDirective,
    CkObjectHeaderComponent,
    CkTabsComponent,
    CkTabComponent,
    ObjectPerspectiveComponent,
    ModelExecutionComponent,
  ],
  template: `
    <ck-object-header
      [eyebrow]="objectEyebrow(i18n.t('runs.invocation.eyebrow'))"
      [title]="title()"
      [subtitle]="i18n.t('runs.invocation.subtitle')"
      [kpis]="kpis()"
    >
      <div actions class="inline-flex items-center gap-2">
        <a [navLink]="{ type: 'run', ref: runId(), lens: activeLens() }" class="px-3 py-1.5 rounded text-xs bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200">
          {{ i18n.t('runs.invocation.back') }}
        </a>
        @if (invocation()?.skill_slug; as skillSlug) {
          <a [navLink]="{ type: 'skill', ref: skillSlug, lens: 'build' }" class="px-3 py-1.5 rounded text-xs bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200">
            {{ i18n.t('runs.invocation.open_skill') }}
          </a>
        }
      </div>
    </ck-object-header>

    @if (arrivalChipLabel(); as chip) {
      <a
        class="arrival-chip"
        data-testid="invocation-arrival-provenance"
        [attr.href]="arrivalBackHref() || null"
        (click)="onArrivalBack($event)"
      >{{ chip }}</a>
    }

    @if (modelExecution(); as model) {
      <section class="ck-surface rounded-md p-4 mb-4"><app-model-execution [resolution]="model" /></section>
    }

    @if (!projectionEnabled()) {
      <section class="ck-surface rounded-md p-4" data-testid="skill-invocation-audit" aria-live="polite">
        @if (loading()) {
          <p>{{ i18n.t('common.loading') }}</p>
        } @else if (error() || !invocation()) {
          <p role="status">{{ i18n.t('observability.codes.reason.invocation_unavailable') }}</p>
          <button type="button" class="mt-3 px-3 py-2 rounded bg-white/5 ring-1 ring-white/10" (click)="retry()">{{ i18n.t('common.retry') }}</button>
        } @else {
          <h2 class="text-sm font-semibold mb-3">{{ i18n.t('runs.detail.trail.audit') }}</h2>
          <pre class="text-xs font-mono whitespace-pre-wrap break-words">{{ auditJson() }}</pre>
        }
      </section>
    } @else {
      <ck-tabs [active]="activeTab()" (activeChange)="onTabChange($event)" [ariaLabel]="i18n.t('runs.invocation.facets_aria')">
        <ck-tab id="overview" [label]="i18n.t('runs.invocation.tab.overview')">
          <ck-object-perspective [objectLabel]="i18n.t('runs.invocation.object_label')" [lens]="activeLens()" facet="overview" [perspective]="activePerspective()" [loading]="loading()" [error]="error()" />
        </ck-tab>
        <ck-tab id="io" [label]="i18n.t('runs.invocation.tab.io')">
          <ck-object-perspective [objectLabel]="i18n.t('runs.invocation.object_label')" [lens]="activeLens()" facet="io" [perspective]="activePerspective()" [loading]="loading()" [error]="error()" />
        </ck-tab>
        <ck-tab id="runtime" [label]="i18n.t('runs.invocation.tab.runtime')">
          <ck-object-perspective [objectLabel]="i18n.t('runs.invocation.object_label')" [lens]="activeLens()" facet="runtime" [perspective]="activePerspective()" [loading]="loading()" [error]="error()" />
        </ck-tab>
        <ck-tab id="governance" [label]="i18n.t('runs.invocation.tab.governance')">
          <ck-object-perspective [objectLabel]="i18n.t('runs.invocation.object_label')" [lens]="activeLens()" facet="governance" [perspective]="activePerspective()" [loading]="loading()" [error]="error()" />
        </ck-tab>
      </ck-tabs>
    }
  `,
  styles: [`
    .arrival-chip {
      display: inline-flex;
      align-items: center;
      margin: 12px 32px 0;
      font-family: var(--ck-font-mono);
      font-size: 11px;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--ck-fg-3);
      text-decoration: none;
    }
    .arrival-chip:hover { color: var(--ck-fg-1); }
  `],
})
export class SkillInvocationViewComponent implements OnInit, OnDestroy {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly api = inject(CanonicalApiService);
  private readonly lensService = inject(LensService);
  private readonly store = inject(ObjectPerspectiveStore);
  private readonly workspace = inject(WorkspaceService);
  readonly i18n = inject(I18nService);
  protected readonly navigation = inject(ZoomContextService);

  objectEyebrow(type: string): string {
    if (!this.navigation.navV5Enabled()) return type;
    return this.i18n.t('nav.eyebrow.from_zone', {
      type,
      zone: this.i18n.t(this.navigation.zoneI18nKey()),
    });
  }
  private routeSubscription: Subscription | null = null;
  private facetRouteSubscription: Subscription | null = null;
  private invocationSubscription: Subscription | null = null;
  private perspectiveSubscription: Subscription | null = null;
  private featureRefreshSubscription: Subscription | null = null;
  private projectionFeatureEnabled = false;
  private requestedFacet: string | null = null;
  private readonly workspaceView = new WorkspaceViewContext(
    this.workspace,
    () => this.resetWorkspaceState(),
    () => this.reload(),
  );

  readonly arrival = signal<ArrivalProvenance | null>(null);
  readonly arrivalChipLabel = computed(() => {
    const provenance = this.arrival();
    return provenance ? arrivalProvenanceLabel(provenance, (key, params) => this.i18n.t(key, params)) : null;
  });
  readonly arrivalBackHref = computed(() => this.arrival()?.backUrl || '');
  readonly runId = signal('');
  readonly invocationId = signal('');
  readonly invocation = signal<SkillInvocation | null>(null);
  readonly modelExecution = computed(() => this.invocation() ? recordedModelExecution(this.invocation()!) : null);
  readonly perspectives = signal<Partial<Record<ObjectLens, ObjectPerspectiveResponse>>>({});
  readonly loading = signal(false);
  readonly error = signal(false);
  readonly activeTab = signal<InvocationFacet>('overview');
  readonly projectionEnabled = computed(() => this.workspaceFeature('skill_invocation_360_projection_v1'));
  readonly activeLens = computed<ObjectLens>(() => {
    const lens = this.lensService.lens();
    return isObjectLens(lens) ? lens : 'build';
  });
  readonly activePerspective = computed(() => this.perspectives()[this.activeLens()] ?? null);
  readonly title = computed(() => this.invocation()?.skill_slug
    || this.invocation()?.skill_id
    || this.i18n.t('runs.invocation.title', { id: this.invocationId().slice(0, 12) }));
  readonly auditJson = computed(() => {
    const inv = this.invocation();
    if (!inv) return '';
    return JSON.stringify({ input_ref: inv.input_ref ?? {}, output_ref: inv.output_ref ?? {},
      metrics: inv.metrics ?? {}, trace: inv.trace ?? {} }, null, 2);
  });
  readonly kpis = computed<CkObjectKpi[]>(() => {
    if (!this.projectionEnabled()) {
      const inv = this.invocation();
      return [
        { label: this.i18n.t('runs.invocation.kpi.status'), value: inv ? observabilityText(this.i18n, 'status', inv.status) : '—' },
        { label: this.i18n.t('runs.invocation.kpi.latency'), value: this.msFactValue({ state: 'available', value: inv?.latency_ms }) },
      ];
    }
    const header = this.perspectives()['build']?.header;
    return [
      { label: this.i18n.t('runs.invocation.kpi.status'), value: this.factValue(header?.['status']) },
      { label: this.i18n.t('runs.invocation.kpi.latency'), value: this.msFactValue(header?.['latency']) },
      { label: this.i18n.t('runs.invocation.kpi.cost'), value: this.factValue(header?.['cost']) },
      { label: this.i18n.t('runs.invocation.kpi.skill_version'), value: this.factValue(header?.['skill_version']) },
    ];
  });

  ngOnInit(): void {
    this.projectionFeatureEnabled = this.projectionEnabled();
    this.arrival.set(readArrivalProvenance());
    this.featureRefreshSubscription = this.workspace.contextRefresh$.subscribe(
      () => this.onProjectionFeatureRefresh(),
    );
    this.routeSubscription = this.route.paramMap.pipe(
      map((params) => ({
        runId: params.get('runId') ?? '',
        invocationId: params.get('invocationId') ?? '',
      })),
      distinctUntilChanged((left, right) => left.runId === right.runId && left.invocationId === right.invocationId),
    ).subscribe(({ runId, invocationId }) => {
      this.runId.set(runId);
      this.invocationId.set(invocationId);
      this.resetResult();
      this.reload();
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
    this.featureRefreshSubscription?.unsubscribe();
    this.featureRefreshSubscription = null;
    this.workspaceView.destroy();
  }

  onArrivalBack(event: MouseEvent): void {
    const href = this.arrivalBackHref();
    if (!href) return;
    if (
      event.defaultPrevented
      || event.button !== 0
      || event.metaKey
      || event.ctrlKey
      || event.shiftKey
      || event.altKey
    ) {
      return;
    }
    event.preventDefault();
    void this.router.navigateByUrl(href);
  }

  onTabChange(value: string): void {
    if (!isInvocationFacet(value)) return;
    this.requestedFacet = value;
    this.activeTab.set(value);
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { facet: value },
      queryParamsHandling: 'merge',
    });
  }

  private applyRequestedFacet(facet: string | null): void {
    this.activeTab.set(isInvocationFacet(facet) ? facet : 'overview');
  }

  private reload(): void {
    this.projectionFeatureEnabled = this.projectionEnabled();
    const runId = this.runId();
    const invocationId = this.invocationId();
    if (!runId || !invocationId) return;
    const request = this.workspaceView.beginRequest();
    this.loading.set(true);
    this.error.set(false);
    // The Run endpoint already filters readable invocations and redacts held I/O.
    // The 360 flag gates richer projections, not this existing Run audit.
    if (!this.projectionEnabled()) {
      const subscription = this.api.getRun(runId).subscribe({
        next: (run) => {
          if (!this.current(request, runId, invocationId)) return;
          const invocation = run?.id === runId
            ? run.skill_invocations?.find((item) => item.id === invocationId) ?? null
            : null;
          this.invocation.set(invocation);
          this.error.set(!invocation);
          this.loading.set(false);
        },
        error: () => {
          if (!this.current(request, runId, invocationId)) return;
          this.error.set(true);
          this.loading.set(false);
        },
      });
      this.invocationSubscription = subscription.closed ? null : subscription;
      return;
    }
    const invocationSubscription = this.api.getSkillInvocation(runId, invocationId).subscribe({
      next: (value) => {
        if (!this.current(request, runId, invocationId)) return;
        this.invocation.set(value);
      },
      error: () => {
        if (!this.current(request, runId, invocationId)) return;
        this.error.set(true);
      },
    });
    this.invocationSubscription = invocationSubscription.closed ? null : invocationSubscription;
    this.loadPerspectives(request, runId, invocationId);
  }

  private loadPerspectives(request: WorkspaceViewRequest, runId: string, invocationId: string): void {
    if (!this.projectionEnabled()) {
      this.loading.set(false);
      return;
    }
    const subscription = this.store.loadAll({
      objectType: 'skill_invocation',
      objectId: invocationId,
      runId,
      window: '30d',
    }).subscribe({
      next: (payloads) => {
        if (!this.current(request, runId, invocationId)) return;
        this.perspectives.set(payloads);
        this.loading.set(false);
        this.error.set(Object.keys(payloads).length !== 4);
      },
      error: (error: unknown) => {
        if (!this.current(request, runId, invocationId)) return;
        this.perspectives.set({});
        this.loading.set(false);
        this.error.set(!(error instanceof ObjectPerspectiveGateRevokedError));
      },
    });
    this.perspectiveSubscription = subscription.closed ? null : subscription;
  }

  private current(request: WorkspaceViewRequest, runId: string, invocationId: string): boolean {
    return this.workspaceView.isCurrent(request)
      && runId === this.runId()
      && invocationId === this.invocationId();
  }

  private resetResult(): void {
    this.invocationSubscription?.unsubscribe();
    this.invocationSubscription = null;
    this.perspectiveSubscription?.unsubscribe();
    this.perspectiveSubscription = null;
    this.workspaceView.invalidate();
    this.invocation.set(null);
    this.perspectives.set({});
    this.loading.set(false);
    this.error.set(false);
  }

  private resetWorkspaceState(): void {
    this.invocationSubscription?.unsubscribe();
    this.invocationSubscription = null;
    this.perspectiveSubscription?.unsubscribe();
    this.perspectiveSubscription = null;
    this.invocation.set(null);
    this.perspectives.set({});
    this.loading.set(false);
    this.error.set(false);
    this.applyRequestedFacet(this.requestedFacet);
  }

  retry(): void {
    this.resetResult();
    this.reload();
  }

  private onProjectionFeatureRefresh(): void {
    const enabled = this.projectionEnabled();
    if (enabled === this.projectionFeatureEnabled) return;
    this.projectionFeatureEnabled = enabled;
    this.retry();
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
}

type InvocationFacet = 'overview' | 'io' | 'runtime' | 'governance';

const INVOCATION_FACETS: readonly InvocationFacet[] = [
  'overview',
  'io',
  'runtime',
  'governance',
];

function isInvocationFacet(value: string | null): value is InvocationFacet {
  return value !== null && (INVOCATION_FACETS as readonly string[]).includes(value);
}

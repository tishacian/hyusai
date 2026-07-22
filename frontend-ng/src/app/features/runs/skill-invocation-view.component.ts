import {
  ChangeDetectionStrategy,
  Component,
  OnDestroy,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { Subscription, distinctUntilChanged, map } from 'rxjs';
import {
  CanonicalApiService,
  type SkillInvocation,
} from '@app/core/canonical-api.service';
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
import {
  CkObjectHeaderComponent,
  type CkObjectKpi,
} from '@app/shared/cockpit/object-header.component';
import { CkTabComponent, CkTabsComponent } from '@app/shared/cockpit/tabs.component';
import { ObjectPerspectiveComponent } from '@app/shared/cockpit/object-perspective.component';
import type { ObjectPerspectiveResponse } from '@app/shared/cockpit/object-perspective.models';

@Component({
  selector: 'app-skill-invocation-view',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    CkObjectHeaderComponent,
    CkTabsComponent,
    CkTabComponent,
    ObjectPerspectiveComponent,
  ],
  template: `
    <ck-object-header
      eyebrow="Runs · Skill invocation"
      [title]="title()"
      subtitle="One concrete execution of a catalog Skill inside a Run."
      [kpis]="kpis()"
    >
      <div actions class="inline-flex items-center gap-2">
        <a [routerLink]="['/runs', runId()]" [queryParams]="{ lens: activeLens() }" class="px-3 py-1.5 rounded text-xs bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200">
          Back to Run
        </a>
        @if (invocation()?.skill_slug) {
          <a [routerLink]="['/skills', invocation()!.skill_slug]" [queryParams]="{ lens: 'build', runId: runId() }" class="px-3 py-1.5 rounded text-xs bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200">
            Open catalog Skill
          </a>
        }
      </div>
    </ck-object-header>

    @if (!projectionEnabled()) {
      <div class="ck-surface rounded-md p-6 text-center text-sm text-gray-400" data-testid="skill-invocation-projection-disabled">
        SkillInvocation perspectives are not enabled for this workspace.
      </div>
    } @else {
      <ck-tabs [active]="activeTab()" (activeChange)="onTabChange($event)" ariaLabel="Skill invocation facets">
        <ck-tab id="overview" label="Overview">
          <ck-object-perspective objectLabel="SkillInvocation" [lens]="activeLens()" facet="overview" [perspective]="activePerspective()" [loading]="loading()" [error]="error()" />
        </ck-tab>
        <ck-tab id="io" label="I/O">
          <ck-object-perspective objectLabel="SkillInvocation" [lens]="activeLens()" facet="io" [perspective]="activePerspective()" [loading]="loading()" [error]="error()" />
        </ck-tab>
        <ck-tab id="runtime" label="Runtime">
          <ck-object-perspective objectLabel="SkillInvocation" [lens]="activeLens()" facet="runtime" [perspective]="activePerspective()" [loading]="loading()" [error]="error()" />
        </ck-tab>
        <ck-tab id="governance" label="Governance">
          <ck-object-perspective objectLabel="SkillInvocation" [lens]="activeLens()" facet="governance" [perspective]="activePerspective()" [loading]="loading()" [error]="error()" />
        </ck-tab>
      </ck-tabs>
    }
  `,
})
export class SkillInvocationViewComponent implements OnInit, OnDestroy {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly api = inject(CanonicalApiService);
  private readonly lensService = inject(LensService);
  private readonly store = inject(ObjectPerspectiveStore);
  private readonly workspace = inject(WorkspaceService);
  private routeSubscription: Subscription | null = null;
  private facetRouteSubscription: Subscription | null = null;
  private invocationSubscription: Subscription | null = null;
  private perspectiveSubscription: Subscription | null = null;
  private featureRefreshSubscription: Subscription | null = null;
  private projectionFeatureEnabled = false;
  private projectionActivationInFlight = false;
  private requestedFacet: string | null = null;
  private readonly workspaceView = new WorkspaceViewContext(
    this.workspace,
    () => this.resetWorkspaceState(),
    () => this.reload(),
  );

  readonly runId = signal('');
  readonly invocationId = signal('');
  readonly invocation = signal<SkillInvocation | null>(null);
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
  readonly title = computed(() => this.invocation()?.skill_slug || this.invocation()?.skill_id || `Invocation ${this.invocationId().slice(0, 12)}`);
  readonly kpis = computed<CkObjectKpi[]>(() => {
    const header = this.perspectives()['build']?.header;
    return [
      { label: 'Status', value: this.factValue(header?.['status']) },
      { label: 'Latency', value: this.factValue(header?.['latency'], ' ms') },
      { label: 'Cost', value: this.factValue(header?.['cost']) },
      { label: 'Skill version', value: this.factValue(header?.['skill_version']) },
    ];
  });

  ngOnInit(): void {
    this.projectionFeatureEnabled = this.projectionEnabled();
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
        this.projectionActivationInFlight = false;
      },
      error: (error: unknown) => {
        if (!this.current(request, runId, invocationId)) return;
        this.perspectives.set({});
        this.loading.set(false);
        this.error.set(!(error instanceof ObjectPerspectiveGateRevokedError));
        if (!(error instanceof ObjectPerspectiveGateRevokedError)) {
          this.projectionActivationInFlight = false;
        }
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
    this.projectionActivationInFlight = false;
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
      this.loading.set(false);
      this.error.set(false);
      return;
    }
    if (activated && !this.projectionActivationInFlight) {
      this.projectionActivationInFlight = true;
      this.reload();
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

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
  CkObjectHeaderComponent,
  type CkObjectKpi,
} from '@app/shared/cockpit/object-header.component';
import { CkTabsComponent, CkTabComponent } from '@app/shared/cockpit/tabs.component';
import { CkPanelComponent } from '@app/shared/cockpit/panel.component';
import { ObjectPerspectiveComponent } from '@app/shared/cockpit/object-perspective.component';
import type { ObjectPerspectiveResponse } from '@app/shared/cockpit/object-perspective.models';
import { CanonicalApiService } from '@app/core/canonical-api.service';
import { LensService } from '@app/core/lens';
import {
  ObjectPerspectiveGateRevokedError,
  ObjectPerspectiveStore,
} from '@app/core/object-perspective.store';
import { isObjectLens, type ObjectLens } from '@app/core/navigation.catalog';
import { WorkspaceService } from '@app/core/workspace.service';
import {
  WorkspaceViewContext,
  type WorkspaceViewRequest,
} from '@app/core/workspace-view-context';

/**
 * `CapabilityViewComponent` — detail page for a single Capability.
 *
 * Follows the `<ck-object-header>` + `<ck-tabs>` pattern. The tab set is
 * constant across lenses; content adapts via `LensService.lens()`. See
 * docs/mental-model.md §5bis.5.
 *
 * Tabs (max 4 visible, ordered by canonical importance):
 *   Overview · Systems · Outcomes · Policies
 *
 * This first wave wires the contract visually; concrete data projections
 * (aggregate ROI, policy bindings, outcome rollups) land in the follow-up
 * lens-aware data wave.
 */
@Component({
  selector: 'app-capability-view',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    CkObjectHeaderComponent,
    CkTabsComponent,
    CkTabComponent,
    CkPanelComponent,
    ObjectPerspectiveComponent,
  ],
  template: `
    <ck-object-header
      eyebrow="Capabilities · Capability"
      [title]="title()"
      subtitle="A capability defines an outcome promise delivered by one or more Systems."
      [kpis]="kpis()"
    >
      <button
        actions
        type="button"
        (click)="policiesPanelOpen.set(true)"
        class="inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition"
      >
        Policies
      </button>
    </ck-object-header>

    <ck-tabs
      [active]="activeTab()"
      (activeChange)="onTabChange($event)"
      ariaLabel="Capability facets"
    >
      <ck-tab id="overview" label="Overview">
        @if (projectionEnabled()) {
          <ck-object-perspective
            objectLabel="Capability"
            [lens]="activeLens()"
            facet="overview"
            [perspective]="activePerspective()"
            [loading]="perspectivesLoading()"
            [error]="perspectivesError()"
          />
        } @else {
          <div class="space-y-4">
          <section class="ck-surface t-elevated rounded-md p-5">
            <h3 class="text-sm font-semibold text-white mb-2">Purpose</h3>
            <p class="text-xs text-gray-400">
              This capability is the pact between the business outcome and the {{ brand() }} engine.
              Use it to promise an outcome (SLO, measurable result), not a list of features.
            </p>
            <p class="text-xs text-gray-500 mt-2">
              Lens context: <span class="font-mono text-[11px] text-cyan-300">{{ lens() }}</span>
              — projections will adapt per-lens in a follow-up wave.
            </p>
          </section>
          <section class="ck-surface rounded-md p-5">
            <h3 class="text-sm font-semibold text-white mb-2">Explore related</h3>
            <div class="flex items-center gap-2 flex-wrap text-xs">
              <a routerLink="/capabilities" class="px-3 py-1.5 rounded bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition">
                Back to catalog
              </a>
              <a routerLink="/systems" class="px-3 py-1.5 rounded bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition">
                Systems bound to this capability
              </a>
            </div>
          </section>
          </div>
        }
      </ck-tab>

      <ck-tab id="systems" label="Systems">
        @if (projectionEnabled()) {
          <ck-object-perspective
            objectLabel="Capability"
            [lens]="activeLens()"
            facet="systems"
            [perspective]="activePerspective()"
            [loading]="perspectivesLoading()"
            [error]="perspectivesError()"
          />
        } @else {
          <div class="ck-surface rounded-md p-5 text-center text-gray-400 text-sm">
          Systems that implement this capability will be listed here.
          <div class="mt-3">
            <a
              routerLink="/systems"
              class="inline-flex items-center gap-1 px-3 py-1.5 rounded text-xs font-medium bg-cyan-500 hover:bg-cyan-600 text-white transition"
            >
              Open Systems catalog
            </a>
          </div>
          </div>
        }
      </ck-tab>

      <ck-tab id="outcomes" label="Outcomes">
        @if (projectionEnabled()) {
          <ck-object-perspective
            objectLabel="Capability"
            [lens]="activeLens()"
            facet="outcomes"
            [perspective]="activePerspective()"
            [loading]="perspectivesLoading()"
            [error]="perspectivesError()"
          />
        } @else {
          <div class="ck-surface rounded-md p-5 text-center text-gray-400 text-sm">
            Aggregated Outcome rollup across every run of every system bound to
            this capability. Wires to the canonical "runs.outcome" block.
          </div>
        }
      </ck-tab>

      <ck-tab id="policies" label="Policies">
        @if (projectionEnabled()) {
          <ck-object-perspective
            objectLabel="Capability"
            [lens]="activeLens()"
            facet="policies"
            [perspective]="activePerspective()"
            [loading]="perspectivesLoading()"
            [error]="perspectivesError()"
          />
        } @else {
          <div class="ck-surface rounded-md p-5 text-center text-gray-400 text-sm">
            Adaptive and Control policies targeting this capability. Open the
            side panel for a quick edit.
          </div>
        }
      </ck-tab>
    </ck-tabs>

    <ck-panel
      [open]="policiesPanelOpen()"
      (openChange)="policiesPanelOpen.set($event)"
      position="side"
      eyebrow="Capability · panel"
      title="Policies quick edit"
      width="420px"
    >
      <p class="text-xs text-gray-400">
        Adjust Adaptive and Control policies without leaving the canvas.
        Full editor lives under Govern.
      </p>
    </ck-panel>
  `,
})
export class CapabilityViewComponent implements OnInit, OnDestroy {
  /** Screen copy names the product by its brand in this workspace. */
  protected readonly brand = inject(WorkspaceService).brandName;
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly canonical = inject(CanonicalApiService);
  private readonly workspace = inject(WorkspaceService);
  private readonly perspectiveStore = inject(ObjectPerspectiveStore);
  readonly lensService = inject(LensService);
  private routeSubscription: Subscription | null = null;
  private facetRouteSubscription: Subscription | null = null;
  private requestSubscription: Subscription | null = null;
  private perspectiveSubscription: Subscription | null = null;
  private featureRefreshSubscription: Subscription | null = null;
  private projectionFeatureEnabled = false;
  private projectionActivationInFlight = false;
  private requestedFacet: string | null = null;
  private readonly workspaceView = new WorkspaceViewContext(
    this.workspace,
    () => this.resetWorkspaceState(),
    () => this.reloadCurrentCapability(),
  );

  capabilityId = '';
  readonly title = signal('Capability');
  readonly activeTab = signal<CapabilityTabId>('overview');
  readonly policiesPanelOpen = signal(false);

  readonly lens = this.lensService.lens;
  readonly perspectives = signal<Partial<Record<ObjectLens, ObjectPerspectiveResponse>>>({});
  readonly perspectivesLoading = signal(false);
  readonly perspectivesError = signal(false);
  readonly projectionEnabled = computed(() => this.workspaceFeature('capability_360_projection_v1'));
  readonly activeLens = computed<ObjectLens>(() => {
    const lens = this.lens();
    return isObjectLens(lens) ? lens : 'build';
  });
  readonly activePerspective = computed(() => this.perspectives()[this.activeLens()] ?? null);

  readonly kpis = computed<CkObjectKpi[]>(() => {
    if (!this.projectionEnabled()) {
      return [
        { label: 'Systems', value: '—', hint: 'Number of Systems bound to this Capability.' },
        { label: 'ROI', value: '—', tone: 'neutral', hint: 'Aggregated ROI — upcoming.' },
        { label: 'Yield', value: '—', tone: 'neutral', hint: 'Composite success rate across runs.' },
        { label: 'Policies', value: '—', tone: 'neutral', hint: 'Active Adaptive + Control policies.' },
      ];
    }
    const header = this.perspectives()['build']?.header;
    return [
      { label: 'Systems', value: this.factValue(header?.['system_count']), hint: 'Number of Systems bound to this Capability.' },
      { label: 'ROI', value: this.factValue(header?.['roi'], '%'), tone: 'neutral', hint: 'Measured aggregate ROI.' },
      { label: 'Yield', value: this.factValue(header?.['success_rate'], '%'), tone: 'neutral', hint: 'Composite success rate across runs.' },
      { label: 'Policies', value: '—', tone: 'neutral', hint: 'Open the Policies facet for authoritative bindings.' },
    ];
  });

  ngOnInit(): void {
    this.projectionFeatureEnabled = this.projectionEnabled();
    this.featureRefreshSubscription = this.workspace.contextRefresh$.subscribe(
      () => this.onProjectionFeatureRefresh(),
    );
    this.routeSubscription = this.route.paramMap.pipe(
      map((params) => params.get('capabilityId') ?? ''),
      distinctUntilChanged(),
    ).subscribe((capabilityId) => {
      this.capabilityId = capabilityId;
      this.resetCapabilityResult();
      this.reloadCurrentCapability();
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

  onTabChange(id: string): void {
    if (!isCapabilityFacet(id)) return;
    this.requestedFacet = id;
    this.activeTab.set(id);
    if (!this.projectionEnabled()) return;
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { facet: id },
      queryParamsHandling: 'merge',
    });
  }

  private applyRequestedFacet(facet: string | null): void {
    if (!this.projectionEnabled()) return;
    this.activeTab.set(isCapabilityFacet(facet) ? facet : 'overview');
  }

  private reloadCurrentCapability(): void {
    this.projectionFeatureEnabled = this.projectionEnabled();
    const capabilityId = this.capabilityId || this.route.snapshot.paramMap.get('capabilityId') || '';
    if (!capabilityId) {
      this.title.set('Capability');
      return;
    }
    this.capabilityId = capabilityId;
    const request = this.workspaceView.beginRequest();
    const subscription = this.canonical.getCapability(capabilityId).subscribe({
      next: (capability) => {
        if (!this.workspaceView.isCurrent(request) || capabilityId !== this.capabilityId) return;
        if (capability) this.title.set(capability.name);
      },
      error: () => {
        if (!this.workspaceView.isCurrent(request) || capabilityId !== this.capabilityId) return;
        this.title.set(`Capability · ${capabilityId.slice(0, 8)}`);
      },
    });
    this.requestSubscription = subscription.closed ? null : subscription;
    this.loadPerspectives(capabilityId, request);
  }

  private loadPerspectives(capabilityId: string, request: WorkspaceViewRequest): void {
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
      objectType: 'capability',
      objectId: capabilityId,
      window: '30d',
    }).subscribe({
      next: (payloads) => {
        if (!this.workspaceView.isCurrent(request) || capabilityId !== this.capabilityId) return;
        this.perspectives.set(payloads);
        this.perspectivesLoading.set(false);
        this.perspectivesError.set(Object.keys(payloads).length !== 4);
        this.projectionActivationInFlight = false;
      },
      error: (error: unknown) => {
        if (!this.workspaceView.isCurrent(request) || capabilityId !== this.capabilityId) return;
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

  private resetCapabilityResult(): void {
    this.requestSubscription?.unsubscribe();
    this.requestSubscription = null;
    this.perspectiveSubscription?.unsubscribe();
    this.perspectiveSubscription = null;
    this.workspaceView.invalidate();
    this.title.set(
      this.capabilityId ? `Capability · ${this.capabilityId.slice(0, 8)}` : 'Capability',
    );
    this.perspectives.set({});
    this.perspectivesLoading.set(false);
    this.perspectivesError.set(false);
    this.projectionActivationInFlight = false;
    this.applyRequestedFacet(this.requestedFacet);
  }

  private resetWorkspaceState(): void {
    this.requestSubscription?.unsubscribe();
    this.requestSubscription = null;
    this.perspectiveSubscription?.unsubscribe();
    this.perspectiveSubscription = null;
    this.title.set(
      this.capabilityId ? `Capability · ${this.capabilityId.slice(0, 8)}` : 'Capability',
    );
    this.policiesPanelOpen.set(false);
    this.perspectives.set({});
    this.perspectivesLoading.set(false);
    this.perspectivesError.set(false);
    this.projectionActivationInFlight = false;
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
      this.reloadCurrentCapability();
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

type CapabilityTabId = 'overview' | 'systems' | 'outcomes' | 'policies';

const CAPABILITY_FACETS: readonly CapabilityTabId[] = [
  'overview',
  'systems',
  'outcomes',
  'policies',
];

function isCapabilityFacet(value: string | null): value is CapabilityTabId {
  return value !== null && (CAPABILITY_FACETS as readonly string[]).includes(value);
}

import { Injectable, OnDestroy, computed, inject, signal } from '@angular/core';
import { NavigationEnd, Router, type UrlTree } from '@angular/router';
import { Subscription, filter, forkJoin, of, switchMap } from 'rxjs';
import {
  CanonicalApiService,
  type Capability,
  type Run,
  type Skill,
  type System,
} from './canonical-api.service';
import {
  navigationLensUrl,
  navigationObjectUrl,
  navigationPortfolioUrl,
  navigationRouteContext,
  navigationScopeUrl,
  type CockpitLens,
  type CockpitRouteContext,
  type CockpitSection,
  type HierarchyObjectType,
  type NavigationAncestry,
  type NavigationObjectUrlOptions,
} from './navigation.catalog';
import { WorkspaceService, type WorkspaceRequestScope } from './workspace.service';

export type ZoomHierarchyKey = 'portfolio' | HierarchyObjectType;

export interface ZoomGraphNode {
  key: ZoomHierarchyKey;
  id: string | null;
  label: string;
  sub: string;
  href: string;
}

export interface ZoomRouteProjection {
  route: CockpitRouteContext;
  ancestry: NavigationAncestry;
  nodes: readonly ZoomGraphNode[];
  loading: boolean;
}

interface ResolvedGraph {
  capability: Capability | null;
  system: System | null;
  run: Run | null;
  skill: Skill | null;
}

const EMPTY_ANCESTRY: NavigationAncestry = {
  capabilityId: null,
  systemId: null,
  runId: null,
  skillRef: null,
};

/**
 * Read-only semantic navigation projection.
 *
 * The Router is the sole owner of identity, scope and lens. Canonical APIs
 * only hydrate and validate the graph represented by that URL; they never
 * become a second navigation store. Components therefore cannot imperatively
 * set or clear a Capability, System, Run or Skill.
 */
@Injectable({ providedIn: 'root' })
export class ZoomContextService implements OnDestroy {
  private readonly router = inject(Router);
  private readonly canonical = inject(CanonicalApiService);
  private readonly workspace = inject(WorkspaceService);

  /** Visible rollout gate. Showcase enables it first, then the internal canary. */
  readonly axesV3Enabled = computed(() => {
    const features = this.workspace.current()?.settings?.['features'];
    return Boolean(
      features &&
      typeof features === 'object' &&
      !Array.isArray(features) &&
      (features as Record<string, unknown>)['cockpit_router_axes_v3'] === true,
    );
  });

  private generation = 0;
  private graphSubscription = new Subscription();
  private readonly subscriptions = new Subscription();
  private readonly unregisterContextReset: () => void;
  private readonly state = signal<ZoomRouteProjection>(
    this.provisional(navigationRouteContext(this.router.url || '/')),
  );

  readonly projection = this.state.asReadonly();
  readonly route = computed(() => this.projection().route);
  readonly lens = computed(() => this.route().lens);
  readonly scope = computed(() => this.route().scope);
  readonly nodes = computed(() => this.projection().nodes);
  readonly loading = computed(() => this.projection().loading);

  readonly capabilityId = computed(() => this.projection().ancestry.capabilityId);
  readonly systemId = computed(() => this.projection().ancestry.systemId);
  readonly runId = computed(() => this.projection().ancestry.runId);
  readonly skillRef = computed(() => this.projection().ancestry.skillRef);

  readonly capabilityLabel = computed(() => this.node('capability')?.label ?? null);
  readonly systemLabel = computed(() => this.node('system')?.label ?? null);
  readonly runLabel = computed(() => this.node('run')?.label ?? null);
  readonly skillLabel = computed(() => this.node('skill')?.label ?? null);

  readonly deepestResolvedType = computed<HierarchyObjectType | null>(() => {
    const nodes = this.nodes();
    if (nodes.some((node) => node.key === 'skill')) return 'skill';
    if (nodes.some((node) => node.key === 'run')) return 'run';
    if (nodes.some((node) => node.key === 'system')) return 'system';
    if (nodes.some((node) => node.key === 'capability')) return 'capability';
    return null;
  });

  constructor() {
    this.subscriptions.add(
      this.router.events.pipe(
        filter((event): event is NavigationEnd => event instanceof NavigationEnd),
      ).subscribe((event) => this.resolve(event.urlAfterRedirects)),
    );
    this.subscriptions.add(
      this.workspace.contextRefresh$.subscribe(() => this.resolve(this.router.url || '/')),
    );

    this.unregisterContextReset = this.workspace.registerContextReset((transition) => {
      this.cancelGraphResolution();
      const route = this.routeContext(this.router.url || '/');
      this.state.set(this.provisional(route, true));
      queueMicrotask(() => {
        if (
          this.workspace.currentSlug() === transition.nextSlug &&
          this.workspace.contextEpoch() === transition.nextEpoch
        ) {
          this.resolve(this.router.url || '/');
        }
      });
    });

    this.resolve(this.router.url || '/');
  }

  urlForLens(targetLens: CockpitLens, fallbackRoute: string): string {
    if (!this.axesV3Enabled()) return fallbackRoute;
    // A list route carries its identity only in query parameters. Until those
    // parents are proven, changing lens with an empty provisional ancestry
    // would silently turn a scoped canvas into a global one. Keep the current
    // URL as a strict no-op; detail paths remain safe because their leaf id is
    // owned by the path itself.
    if (this.loading() && this.route().selectedType === null) {
      return this.route().url;
    }
    return navigationLensUrl(
      this.route().url,
      targetLens,
      fallbackRoute,
      this.projection().ancestry,
    );
  }

  urlTreeForLens(targetLens: CockpitLens, fallbackRoute: string): UrlTree {
    return this.router.parseUrl(this.urlForLens(targetLens, fallbackRoute));
  }

  urlForScope(section: CockpitSection): string {
    if (!this.axesV3Enabled()) {
      return section.key === 'flows' && this.systemId()
        ? `/systems/${encodeURIComponent(this.systemId()!)}/flow`
        : section.route;
    }
    // Scope destinations are list routes, so every hierarchy id would be
    // lost if a user clicked before canonical graph hydration completed.
    if (this.loading()) return this.route().url;
    return navigationScopeUrl(section, this.projection().ancestry, this.lens());
  }

  urlTreeForScope(section: CockpitSection): UrlTree {
    return this.router.parseUrl(this.urlForScope(section));
  }

  objectUrl(
    type: HierarchyObjectType,
    ref: string,
    options: NavigationObjectUrlOptions = {},
  ): string {
    const axesEnabled = this.axesV3Enabled();
    return navigationObjectUrl(type, ref, {
      capabilityId: axesEnabled ? options.capabilityId : null,
      systemId: axesEnabled ? options.systemId : null,
      runId: axesEnabled ? options.runId : null,
      skillRef: axesEnabled ? options.skillRef : null,
      lens: axesEnabled
        ? (options.lens === undefined ? this.lens() : options.lens)
        : null,
      tab: options.tab,
      scope: axesEnabled ? options.scope : null,
    });
  }

  objectUrlTree(
    type: HierarchyObjectType,
    ref: string,
    options: NavigationObjectUrlOptions = {},
  ): UrlTree {
    return this.router.parseUrl(this.objectUrl(type, ref, options));
  }

  ngOnDestroy(): void {
    this.unregisterContextReset();
    this.cancelGraphResolution();
    this.subscriptions.unsubscribe();
  }

  private resolve(url: string): void {
    const generation = ++this.generation;
    const requestScope = this.workspace.captureRequestScope();
    const route = this.routeContext(url);
    const needsGraph = Boolean(
      route.capabilityId || route.systemId || route.runId || route.skillRef,
    );
    this.graphSubscription.unsubscribe();
    this.graphSubscription = new Subscription();
    this.state.set(this.provisional(route));
    if (!needsGraph) return;

    // The selected path object is the leaf authority. Query parameters may
    // only describe its parents (Skill) or a list scope; they can never
    // replace it with a descendant from another branch.
    const mayUseQueryAncestry = route.selectedType === null || route.selectedType === 'skill';
    const runId = route.selectedType === 'run'
      ? route.selectedRef
      : (mayUseQueryAncestry ? route.runId : null);
    const directSystemId = route.selectedType === 'system'
      ? route.selectedRef
      : (mayUseQueryAncestry && !runId ? route.systemId : null);
    const directCapabilityId = route.selectedType === 'capability'
      ? route.selectedRef
      : (mayUseQueryAncestry && !runId && !directSystemId ? route.capabilityId : null);
    const skillRef = route.selectedType === 'skill'
      ? route.selectedRef
      : (route.selectedType === null ? route.skillRef : null);

    const run$ = runId ? this.canonical.getRun(runId) : of(null);
    this.graphSubscription = run$.pipe(
      switchMap((run) => {
        // When a Run was requested but cannot be resolved, do not fall back
        // to unverified parent hints from the URL.
        const systemId = runId ? run?.system_id : directSystemId;
        return forkJoin({
          run: of(run),
          system: systemId ? this.canonical.getSystem(systemId) : of(null),
          skill: skillRef ? this.canonical.getSkill(skillRef) : of(null),
        });
      }),
      switchMap(({ run, system, skill }) => {
        // The real System edge wins. A direct Capability hint is only valid
        // when no deeper object was requested.
        const capabilityId = system?.capability_id
          || (run && !run.system_id ? run.capability_id : null)
          || directCapabilityId;
        return forkJoin({
          run: of(run),
          system: of(system),
          skill: of(skill),
          capability: capabilityId
            ? this.canonical.getCapability(capabilityId)
            : of(null),
        });
      }),
    ).subscribe((graph) => {
      if (!this.isCurrent(generation, requestScope, url)) return;
      this.state.set(this.resolvedProjection(route, graph));
    });
  }

  private routeContext(url: string): CockpitRouteContext {
    const enabled = this.axesV3Enabled();
    const route = navigationRouteContext(url, enabled);
    if (enabled) return route;

    // Outside the canary, axis query parameters are inert. Direct object
    // paths still hydrate labels for the legacy breadcrumb, but deep links
    // copied from a canary cannot activate routed lenses or scoped lists.
    return {
      ...route,
      query: Object.fromEntries(
        Object.entries(route.query).filter(([key]) =>
          !['lens', 'scope', 'capabilityId', 'systemId', 'runId', 'skillRef'].includes(key),
        ),
      ),
      scope: null,
      capabilityId: route.selectedType === 'capability' ? route.selectedRef : null,
      systemId: route.selectedType === 'system' ? route.selectedRef : null,
      runId: route.selectedType === 'run' ? route.selectedRef : null,
      skillRef: route.selectedType === 'skill' ? route.selectedRef : null,
    };
  }

  private provisional(route: CockpitRouteContext, reset = false): ZoomRouteProjection {
    return {
      route,
      // URL refs remain visible in `route`, but they do not become scope
      // until the workspace-scoped APIs prove the graph.
      ancestry: EMPTY_ANCESTRY,
      nodes: [this.portfolioNode(
        reset,
        this.axesV3Enabled() ? route.lens : null,
      )],
      loading: !reset && Boolean(
        route.capabilityId || route.systemId || route.runId || route.skillRef,
      ),
    };
  }

  private resolvedProjection(
    route: CockpitRouteContext,
    graph: ResolvedGraph,
  ): ZoomRouteProjection {
    let capability = graph.capability;
    let system = graph.system;
    let run = graph.run;
    let skill = graph.skill;

    if (route.selectedType === 'capability') {
      capability = capability?.id === route.selectedRef ? capability : null;
      system = null;
      run = null;
      skill = null;
    } else if (route.selectedType === 'system') {
      system = system?.id === route.selectedRef ? system : null;
      if (!system) capability = null;
      run = null;
      skill = null;
    } else if (route.selectedType === 'run') {
      run = run?.id === route.selectedRef ? run : null;
      if (!run) {
        system = null;
        capability = null;
      }
      skill = null;
    } else if (route.selectedType === 'skill') {
      skill = skill?.slug === route.selectedRef ? skill : null;
    }

    if (run?.system_id && system?.id !== run.system_id) {
      system = null;
      capability = null;
    }
    if (system?.capability_id && capability?.id !== system.capability_id) {
      capability = null;
    }

    // A Skill is validated against its deepest requested parent. Presence on
    // a System cannot masquerade as an invocation inside a specific Run.
    if (route.skillRef && skill) {
      let attached = true;
      if (route.runId) {
        attached = Boolean(
          run?.id === route.runId &&
          (run.skill_invocations ?? []).some((invocation) =>
            invocation.skill_slug === skill!.slug || invocation.skill_id === skill!.id,
          ),
        );
      } else if (route.systemId) {
        attached = Boolean(
          system?.id === route.systemId && (system.skill_ids ?? []).includes(skill.id),
        );
      } else if (route.capabilityId) {
        attached = Boolean(
          capability?.id === route.capabilityId &&
          (capability.skill_ids ?? []).includes(skill.id),
        );
      }
      if (!attached) {
        capability = null;
        system = null;
        run = null;
      }
    }

    const capabilityId = capability?.id ?? null;
    const systemId = system?.id ?? null;
    const runId = run?.id ?? null;
    const skillRef = skill?.slug ?? null;
    const ancestry: NavigationAncestry = { capabilityId, systemId, runId, skillRef };
    const projectedLens = this.axesV3Enabled() ? route.lens : null;
    const nodes: ZoomGraphNode[] = [this.portfolioNode(false, projectedLens)];

    if (capability) {
      nodes.push({
        key: 'capability',
        id: capability.id,
        label: capability.name,
        sub: `Capability · ${capability.slug}`,
        href: navigationObjectUrl('capability', capability.id, { lens: projectedLens }),
      });
    }
    if (system) {
      nodes.push({
        key: 'system',
        id: system.id,
        label: system.name,
        sub: 'System',
        href: navigationObjectUrl('system', system.id, {
          capabilityId: capability?.id ?? null,
          lens: projectedLens,
        }),
      });
    }
    if (run) {
      nodes.push({
        key: 'run',
        id: run.id,
        label: `Run · ${this.shortRef(run.id)}`,
        sub: `Run · ${run.status}`,
        href: navigationObjectUrl('run', run.id, {
          capabilityId: capability?.id ?? null,
          systemId: system?.id ?? run.system_id,
          lens: projectedLens,
        }),
      });
    }
    if (skill) {
      nodes.push({
        key: 'skill',
        id: skill.id,
        label: skill.name,
        sub: `Skill · ${skill.slug}`,
        href: navigationObjectUrl('skill', skill.slug, {
          capabilityId: capability?.id ?? null,
          systemId: system?.id ?? null,
          runId: run?.id ?? null,
          lens: projectedLens,
        }),
      });
    }

    return { route, ancestry, nodes, loading: false };
  }

  private portfolioNode(
    neutral = false,
    lens: CockpitLens | null = null,
  ): ZoomGraphNode {
    const workspace = neutral ? null : this.workspace.current();
    return {
      key: 'portfolio',
      id: workspace?.id ?? null,
      label: 'Portfolio',
      sub: workspace?.name || 'Workspace portfolio',
      href: navigationPortfolioUrl(lens),
    };
  }

  private node(key: HierarchyObjectType): ZoomGraphNode | null {
    return this.nodes().find((node) => node.key === key) ?? null;
  }

  private shortRef(value: string): string {
    return value.length > 12 ? `${value.slice(0, 12)}…` : value;
  }

  private isCurrent(
    generation: number,
    scope: WorkspaceRequestScope,
    url: string,
  ): boolean {
    return (
      generation === this.generation &&
      this.workspace.isRequestScopeCurrent(scope) &&
      navigationRouteContext(this.router.url || '/').url === navigationRouteContext(url).url
    );
  }

  private cancelGraphResolution(): void {
    this.generation += 1;
    this.graphSubscription.unsubscribe();
    this.graphSubscription = new Subscription();
  }
}

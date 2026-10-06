import { Injectable, OnDestroy, computed, inject, signal } from '@angular/core';
import { NavigationEnd, Router, type UrlTree } from '@angular/router';
import { Subscription, filter, forkJoin, of, switchMap } from 'rxjs';
import {
  CanonicalApiService,
  type Capability,
  type Context,
  type Run,
  type Skill,
  type SkillInvocation,
  type System,
} from './canonical-api.service';
import {
  matchAgentiumSurface,
  navigationLeafUrl,
  navigationLensUrl,
  navigationObjectUrl,
  navigationPortfolioUrl,
  navigationRouteContext,
  navigationScopeUrl,
  navigationSurfaceUrl,
  navigationZoneSurfaceUrl,
  resolveNavLink,
  type CockpitLens,
  type CockpitDestination,
  type CockpitRouteContext,
  type CockpitSection,
  type HierarchyObjectType,
  type NavLinkInput,
  type NavLinkResolution,
  type NavigationAncestry,
  type NavigationObjectUrlOptions,
} from './navigation.catalog';
import { I18nService } from './i18n.service';
import { WorkspaceService, workspaceSettingFeature, type WorkspaceRequestScope } from './workspace.service';
import { arrivalProvenanceState } from '@app/shared/cockpit/arrival-provenance';

export type ZoomHierarchyKey =
  | 'portfolio'
  | 'business_apps'
  | 'conversations'
  | 'ellipsis'
  | HierarchyObjectType;

export interface ZoomGraphNode {
  key: ZoomHierarchyKey;
  id: string | null;
  label: string;
  sub: string;
  href: string;
  /** Optional mono suffix (ids / slugs) rendered after the translated label. */
  mono?: string | null;
}

export interface ZoomRouteProjection {
  route: CockpitRouteContext;
  ancestry: NavigationAncestry;
  nodes: readonly ZoomGraphNode[];
  loading: boolean;
  /** Soft badge for shared contexts / linked conversation objects (L9). */
  badge: string | null;
}

interface ResolvedGraph {
  capability: Capability | null;
  system: System | null;
  run: Run | null;
  invocation: SkillInvocation | null;
  skill: Skill | null;
}

const EMPTY_ANCESTRY: NavigationAncestry = {
  capabilityId: null,
  systemId: null,
  runId: null,
  skillInvocationId: null,
  skillRef: null,
};

function pathOnly(value: string): string {
  return (value || '/').split('?')[0].split('#')[0] || '/';
}

/**
 * Read-only semantic navigation projection.
 *
 * The Router is the sole owner of identity, scope and lens. Canonical APIs
 * only hydrate and validate the graph represented by that URL; they never
 * become a second navigation store. Components therefore cannot imperatively
 * set or clear a Capability, System, Run, SkillInvocation or Skill.
 */
@Injectable({ providedIn: 'root' })
export class ZoomContextService implements OnDestroy {
  private readonly router = inject(Router);
  private readonly canonical = inject(CanonicalApiService);
  private readonly workspace = inject(WorkspaceService);
  private readonly i18n = inject(I18nService);

  /** Visible rollout gate. Showcase enables it first, then the internal canary. */
  readonly axesV3Enabled = computed(() => {
    const workspace = this.workspace.current();
    return (
      workspaceSettingFeature(workspace, 'cockpit_router_axes_v3', true) ||
      workspaceSettingFeature(workspace, 'cockpit_router_axes_v4', true)
    );
  });

  /** Axes v4 separates the Portfolio home from the four object lenses. */
  readonly axesV4Enabled = computed(() =>
    workspaceSettingFeature(this.workspace.current(), 'cockpit_router_axes_v4', true),
  );

  readonly experienceV1Enabled = computed(() => {
    const features = this.workspace.current()?.settings?.['features'];
    return Boolean(
      features &&
      typeof features === 'object' &&
      !Array.isArray(features) &&
      (features as Record<string, unknown>)['experience_v1'] === true,
    );
  });

  readonly navV5Enabled = computed(() =>
    workspaceSettingFeature(this.workspace.current(), 'cockpit_nav_v5', true),
  );

  readonly experienceStudioV1Enabled = computed(() => {
    const features = this.workspace.current()?.settings?.['features'];
    return Boolean(
      features
      && typeof features === 'object'
      && !Array.isArray(features)
      && (features as Record<string, unknown>)['experience_v1'] === true
      && (features as Record<string, unknown>)['experience_studio_v1'] !== false,
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
  readonly badge = computed(() => this.projection().badge);
  /** Crumbs shown in the title bar (middle levels collapse past four). */
  readonly visibleNodes = computed(() => this.collapseNodes(this.nodes()));

  readonly capabilityId = computed(() => this.projection().ancestry.capabilityId);
  readonly systemId = computed(() => this.projection().ancestry.systemId);
  readonly runId = computed(() => this.projection().ancestry.runId);
  readonly skillInvocationId = computed(
    () => this.projection().ancestry.skillInvocationId,
  );
  readonly skillRef = computed(() => this.projection().ancestry.skillRef);

  readonly capabilityLabel = computed(() => this.node('capability')?.label ?? null);
  readonly systemLabel = computed(() => this.node('system')?.label ?? null);
  readonly runLabel = computed(() => this.node('run')?.label ?? null);
  readonly skillInvocationLabel = computed(
    () => this.node('skill_invocation')?.label ?? null,
  );
  readonly skillLabel = computed(() => this.node('skill')?.label ?? null);

  zoneI18nKey(): `experience.adoption.nav.${CockpitLens}` {
    return `experience.adoption.nav.${this.lens()}`;
  }

  private workspaceMode(): string | undefined {
    return this.workspace.current()?.mode ?? this.workspace.mode?.();
  }

  readonly deepestResolvedType = computed<HierarchyObjectType | null>(() => {
    const nodes = this.nodes();
    const order: HierarchyObjectType[] = [
      'skill_invocation',
      'skill',
      'run',
      'business_app',
      'conversation',
      'context',
      'collection',
      'dataset',
      'model',
      'system',
      'capability',
    ];
    for (const key of order) {
      if (nodes.some((node) => node.key === key)) return key;
    }
    return null;
  });

  /** Current depth / total for the command bar (visible crumbs). */
  depthPair(): { depth: number; total: number } {
    const total = Math.max(1, this.visibleNodes().length);
    return { depth: total, total };
  }

  zoomParentHint(): string {
    const nodes = this.nodes();
    if (nodes.length <= 1) return this.i18n.t('nav.zoom.hint_at_top');
    const parent = nodes[nodes.length - 2];
    if (parent.key === 'portfolio') return this.i18n.t('nav.zoom.hint_to_portfolio');
    const label = parent.key === 'conversations'
      ? this.i18n.t('nav.conversations')
      : parent.key === 'business_apps'
        ? this.i18n.t('nav.business_apps')
        : parent.label;
    return this.i18n.t('nav.zoom.hint_to_parent', { parent: label });
  }

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

  urlForLens(targetLens: CockpitDestination, fallbackRoute: string): string {
    if (!this.axesV3Enabled()) return fallbackRoute;
    if (this.axesV4Enabled() && targetLens === 'hypervisor') {
      return navigationPortfolioUrl(null, true);
    }
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
      this.axesV4Enabled(),
    );
  }

  urlTreeForLens(targetLens: CockpitDestination, fallbackRoute: string): UrlTree {
    return this.router.parseUrl(this.urlForLens(targetLens, fallbackRoute));
  }

  /**
   * `history.state` when leaving an object toward Impact (UX-006).
   * Side rail / verb nav attach this; the URL stays Portfolio (`urlForLens`).
   */
  arrivalStateForLens(targetLens: CockpitDestination): Record<string, unknown> | null {
    if (!this.axesV4Enabled() || targetLens !== 'hypervisor') return null;
    const route = this.route();
    if (route.selectedType !== 'system' || !route.selectedRef) return null;
    const label = this.node('system')?.label || route.selectedRef;
    return arrivalProvenanceState({
      kind: 'system',
      label,
      systemId: route.selectedRef,
      backUrl: this.router.url || route.url,
    });
  }

  urlForScope(section: CockpitSection): string {
    if (this.navV5Enabled()) {
      if (section.key === 'flows') {
        // Wait for workspace-scoped hydration before linking a System's graph.
        // A flat list has no selected System and keeps the free draft action.
        if (this.loading()) return this.route().url;
        const systemId = this.systemId();
        if (systemId) {
          return navigationLeafUrl('system-flow', { systemId }, {
            lens: 'build',
            capabilityId: this.capabilityId(),
          });
        }
      }
      return navigationZoneSurfaceUrl(section, this.lens(), this.route().url);
    }
    if (!this.axesV3Enabled()) {
      const systemId = section.key === 'flows' ? this.systemId() : null;
      return systemId
        ? navigationLeafUrl('system-flow', { systemId })
        : section.route;
    }
    // Scope destinations are list routes, so every hierarchy id would be
    // lost if a user clicked before canonical graph hydration completed.
    if (this.loading()) return this.route().url;
    return navigationScopeUrl(
      section,
      this.projection().ancestry,
      this.lens(),
    );
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
      runId: type === 'skill_invocation'
        ? options.runId
        : axesEnabled ? options.runId : null,
      skillInvocationId: null,
      skillRef: axesEnabled ? options.skillRef : null,
      lens: axesEnabled
        ? (options.lens === undefined ? this.lens() : options.lens)
        : null,
      tab: options.tab,
      facet: options.facet,
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

  surfaceUrl(surfaceId: string, options: NavigationObjectUrlOptions = {}): string {
    return navigationSurfaceUrl(surfaceId, this.linkOptions(options));
  }

  surfaceUrlTree(surfaceId: string, options: NavigationObjectUrlOptions = {}): UrlTree {
    return this.router.parseUrl(this.surfaceUrl(surfaceId, options));
  }

  leafUrl(
    leafId: string,
    params: Record<string, string> = {},
    options: NavigationObjectUrlOptions = {},
  ): string {
    return navigationLeafUrl(leafId, params, this.linkOptions(options));
  }

  leafUrlTree(
    leafId: string,
    params: Record<string, string> = {},
    options: NavigationObjectUrlOptions = {},
  ): UrlTree {
    return this.router.parseUrl(this.leafUrl(leafId, params, options));
  }

  resolveLink(input: NavLinkInput): NavLinkResolution {
    const axesEnabled = this.axesV3Enabled();
    return resolveNavLink(input, {
      lens: axesEnabled ? this.lens() : null,
      ancestry: axesEnabled ? this.projection().ancestry : EMPTY_ANCESTRY,
      currentUrl: this.route().url,
    });
  }

  /** Breadcrumb parent, else the list surface of a non-hierarchy object. */
  parentUrl(): string {
    const parent = this.parentNode();
    if (parent) return parent.href;
    const path = this.route().path;
    const surface = matchAgentiumSurface(path);
    if (surface && pathOnly(surface.route) !== path) {
      return this.surfaceUrl(surface.id);
    }
    return navigationPortfolioUrl(this.axesV3Enabled() ? this.lens() : null);
  }

  parentLabel(): string {
    const parent = this.parentNode();
    if (parent) {
      if (parent.key === 'portfolio') return this.i18n.t('nav.zoom.portfolio');
      if (parent.key === 'conversations') return this.i18n.t('nav.conversations');
      if (parent.key === 'business_apps') return this.i18n.t('nav.business_apps');
      return parent.label;
    }
    const path = this.route().path;
    const surface = matchAgentiumSurface(path);
    if (surface && pathOnly(surface.route) !== path) {
      // The catalog label is the English reference; the rail's key speaks
      // the reader's language (« ← Systèmes » on /systems/new).
      const key = `nav.${surface.id}`;
      const label = this.i18n.t(key);
      return label === key ? surface.label : label;
    }
    return this.i18n.t('nav.zoom.portfolio');
  }

  parentNode(): ZoomGraphNode | null {
    const nodes = this.nodes();
    return nodes.length >= 2 ? nodes[nodes.length - 2] : null;
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
    const leafType = this.leafSelectedType(route.selectedType);
    const needsGraph = Boolean(
      route.capabilityId
      || route.systemId
      || route.runId
      || route.skillInvocationId
      || route.skillRef
      || leafType,
    );
    this.graphSubscription.unsubscribe();
    this.graphSubscription = new Subscription();
    this.state.set(this.provisional(route));
    if (!needsGraph) return;

    if (leafType && route.selectedRef) {
      this.resolveLeaf(generation, requestScope, url, route, leafType, route.selectedRef);
      return;
    }

    // The selected path object is the leaf authority. Query parameters may
    // only describe its parents (Skill) or a list scope; they can never
    // replace it with a descendant from another branch.
    const mayUseQueryAncestry = route.selectedType === null || route.selectedType === 'skill';
    const runId = route.selectedType === 'run'
      ? route.selectedRef
      : route.selectedType === 'skill_invocation'
        ? route.runId
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
    const invocationId = route.selectedType === 'skill_invocation'
      ? route.skillInvocationId
      : null;

    const run$ = runId ? this.canonical.getRun(runId) : of(null);
    this.graphSubscription = run$.pipe(
      switchMap((run) => {
        // When a Run was requested but cannot be resolved, do not fall back
        // to unverified parent hints from the URL.
        const systemId = runId ? run?.system_id : directSystemId;
        // Run membership is already authorized, including when 360 is disabled.
        const recordedInvocation = run?.id === runId
          ? run?.skill_invocations?.find((item) => item.id === invocationId)
          : null;
        return forkJoin({
          run: of(run),
          system: systemId ? this.canonical.getSystem(systemId) : of(null),
          invocation: of(recordedInvocation && run
            ? { ...recordedInvocation, run_id: recordedInvocation.run_id ?? run.id }
            : null),
          skill: skillRef ? this.canonical.getSkill(skillRef) : of(null),
        });
      }),
      switchMap(({ run, system, invocation, skill }) => {
        // The real System edge wins. A direct Capability hint is only valid
        // when no deeper object was requested.
        const capabilityId = system?.capability_id
          || (run && !run.system_id ? run.capability_id : null)
          || directCapabilityId;
        return forkJoin({
          run: of(run),
          system: of(system),
          invocation: of(invocation),
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

  private leafSelectedType(
    selected: HierarchyObjectType | null,
  ): Exclude<HierarchyObjectType, 'capability' | 'system' | 'run' | 'skill' | 'skill_invocation'> | null {
    if (
      selected === 'collection'
      || selected === 'dataset'
      || selected === 'model'
      || selected === 'context'
      || selected === 'conversation'
      || selected === 'business_app'
    ) {
      return selected;
    }
    return null;
  }

  private resolveLeaf(
    generation: number,
    requestScope: WorkspaceRequestScope,
    url: string,
    route: CockpitRouteContext,
    type: Exclude<HierarchyObjectType, 'capability' | 'system' | 'run' | 'skill' | 'skill_invocation'>,
    ref: string,
  ): void {
    if (type === 'collection') {
      this.graphSubscription = this.canonical.getCollection(ref).subscribe((collection) => {
        if (!this.isCurrent(generation, requestScope, url)) return;
        this.state.set(this.leafProjection(route, {
          key: 'collection',
          id: ref,
          label: this.i18n.t('nav.zoom.collection_named', {
            name: collection?.name || ref,
          }),
          href: navigationObjectUrl('collection', ref, {
            lens: this.axesV3Enabled() ? route.lens : null,
          }),
        }));
      });
      return;
    }
    if (type === 'dataset') {
      this.graphSubscription = this.canonical.getDataset(ref).subscribe((dataset) => {
        if (!this.isCurrent(generation, requestScope, url)) return;
        this.state.set(this.leafProjection(route, {
          key: 'dataset',
          id: ref,
          label: this.i18n.t('nav.zoom.dataset_named', {
            name: dataset?.name || ref,
          }),
          href: navigationObjectUrl('dataset', ref, {
            lens: this.axesV3Enabled() ? route.lens : null,
          }),
        }));
      });
      return;
    }
    if (type === 'model') {
      this.graphSubscription = this.canonical.getMlModel(ref).subscribe((model) => {
        if (!this.isCurrent(generation, requestScope, url)) return;
        this.state.set(this.leafProjection(route, {
          key: 'model',
          id: ref,
          label: this.i18n.t('nav.zoom.model_named', {
            name: model?.name || ref,
            version: String(model?.version ?? 1),
          }),
          href: navigationObjectUrl('model', ref, {
            lens: this.axesV3Enabled() ? route.lens : null,
          }),
        }));
      });
      return;
    }
    if (type === 'business_app') {
      this.graphSubscription = this.canonical.getExperienceSummary(ref).subscribe((app) => {
        if (!this.isCurrent(generation, requestScope, url)) return;
        const projectedLens = this.axesV3Enabled() ? route.lens : null;
        const nodes: ZoomGraphNode[] = [
          this.portfolioNode(false, projectedLens),
          {
            key: 'business_apps',
            id: null,
            label: this.i18n.t('nav.business_apps'),
            sub: '',
            href: navigationSurfaceUrl('create-apps', { lens: projectedLens }),
          },
          {
            key: 'business_app',
            id: ref,
            label: app?.name || ref,
            sub: '',
            href: navigationObjectUrl('business_app', ref, { lens: projectedLens }),
          },
        ];
        this.state.set({
          route,
          ancestry: EMPTY_ANCESTRY,
          nodes,
          loading: false,
          badge: null,
        });
      });
      return;
    }
    if (type === 'conversation') {
      this.graphSubscription = this.canonical.getChatSessionSummary(ref).subscribe((session) => {
        if (!this.isCurrent(generation, requestScope, url)) return;
        const title = session?.title || ref;
        const systemId = session?.system_id ?? null;
        const finish = (badge: string | null) => {
          this.state.set({
            route,
            ancestry: EMPTY_ANCESTRY,
            nodes: [
              {
                key: 'conversations',
                id: null,
                label: this.i18n.t('nav.conversations'),
                sub: '',
                href: '/conversations',
              },
              {
                key: 'conversation',
                id: ref,
                label: title,
                sub: '',
                href: navigationObjectUrl('conversation', ref),
              },
            ],
            loading: false,
            badge,
          });
        };
        if (!systemId) {
          finish(null);
          return;
        }
        this.canonical.getSystem(systemId).subscribe((system) => {
          if (!this.isCurrent(generation, requestScope, url)) return;
          finish(
            system?.name
              ? this.i18n.t('nav.zoom.linked_to', { name: system.name })
              : null,
          );
        });
      });
      return;
    }
    // context
    this.graphSubscription = forkJoin({
      context: this.canonical.getContext(ref),
      systems: this.canonical.listSystems(),
    }).subscribe(({ context, systems }) => {
      if (!this.isCurrent(generation, requestScope, url)) return;
      this.state.set(this.contextProjection(route, ref, context, systems ?? []));
    });
  }

  private leafProjection(
    route: CockpitRouteContext,
    leaf: { key: HierarchyObjectType; id: string; label: string; href: string },
  ): ZoomRouteProjection {
    const projectedLens = this.axesV3Enabled() ? route.lens : null;
    return {
      route,
      ancestry: EMPTY_ANCESTRY,
      nodes: [
        this.portfolioNode(false, projectedLens),
        {
          key: leaf.key,
          id: leaf.id,
          label: leaf.label,
          sub: '',
          href: leaf.href,
        },
      ],
      loading: false,
      badge: null,
    };
  }

  private contextProjection(
    route: CockpitRouteContext,
    ref: string,
    context: Context | null,
    systems: System[],
  ): ZoomRouteProjection {
    const projectedLens = this.axesV3Enabled() ? route.lens : null;
    const name = context?.name || ref;
    const leafLabel = this.i18n.t('nav.zoom.context_named', { name });
    const leafHref = navigationObjectUrl('context', ref, { lens: projectedLens });
    const leafNode: ZoomGraphNode = {
      key: 'context',
      id: ref,
      label: leafLabel,
      sub: '',
      href: leafHref,
    };
    const linked = systems.filter((system) => system.context_id === ref);
    const bySystemId = context?.system_id
      ? systems.find((system) => system.id === context.system_id) ?? null
      : null;
    const parentSystem = bySystemId
      ?? (linked.length === 1 ? linked[0] : null);
    const nodes: ZoomGraphNode[] = [this.portfolioNode(false, projectedLens)];
    let badge: string | null = null;
    if (parentSystem) {
      nodes.push({
        key: 'system',
        id: parentSystem.id,
        label: parentSystem.name,
        sub: this.i18n.t('nav.zoom.system'),
        href: navigationObjectUrl('system', parentSystem.id, {
          capabilityId: parentSystem.capability_id ?? null,
          lens: projectedLens,
        }),
      });
    } else if (linked.length > 1) {
      badge = this.i18n.t('nav.zoom.used_by_systems', { count: String(linked.length) });
    }
    nodes.push(leafNode);
    return {
      route,
      ancestry: {
        ...EMPTY_ANCESTRY,
        systemId: parentSystem?.id ?? null,
      },
      nodes,
      loading: false,
      badge,
    };
  }

  private linkOptions(options: NavigationObjectUrlOptions): NavigationObjectUrlOptions {
    const axesEnabled = this.axesV3Enabled();
    return {
      capabilityId: axesEnabled
        ? (options.capabilityId !== undefined ? options.capabilityId : this.capabilityId())
        : null,
      systemId: axesEnabled
        ? (options.systemId !== undefined ? options.systemId : this.systemId())
        : null,
      runId: axesEnabled
        ? (options.runId !== undefined ? options.runId : this.runId())
        : null,
      skillRef: axesEnabled
        ? (options.skillRef !== undefined ? options.skillRef : this.skillRef())
        : null,
      lens: axesEnabled
        ? (options.lens === undefined ? this.lens() : options.lens)
        : null,
      tab: options.tab,
      facet: options.facet,
      doc: options.doc,
      scope: axesEnabled ? options.scope : null,
    };
  }

  private routeContext(url: string): CockpitRouteContext {
    const enabled = this.axesV3Enabled();
    const route = navigationRouteContext(url, enabled);
    if (enabled) return route;

    // Outside the canary, axis query parameters are inert. Direct object
    // paths still hydrate breadcrumb labels, but deep links copied from a
    // canary cannot activate routed lenses or scoped lists.
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
      runId: route.selectedType === 'run' || route.selectedType === 'skill_invocation'
        ? route.runId
        : null,
      skillInvocationId: route.selectedType === 'skill_invocation'
        ? route.selectedRef
        : null,
      skillRef: route.selectedType === 'skill' ? route.selectedRef : null,
    };
  }

  private provisional(route: CockpitRouteContext, reset = false): ZoomRouteProjection {
    const leaf = this.leafSelectedType(route.selectedType);
    return {
      route,
      // URL refs remain visible in `route`, but they do not become scope
      // until the workspace-scoped APIs prove the graph.
      ancestry: EMPTY_ANCESTRY,
      nodes: leaf === 'conversation'
        ? [{
            key: 'conversations',
            id: null,
            label: this.i18n.t('nav.conversations'),
            sub: '',
            href: '/conversations',
          }]
        : [this.portfolioNode(
          reset,
          this.axesV3Enabled() ? route.lens : null,
          route,
        )],
      loading: !reset && Boolean(
        route.capabilityId
        || route.systemId
        || route.runId
        || route.skillInvocationId
        || route.skillRef
        || leaf,
      ),
      badge: null,
    };
  }

  private resolvedProjection(
    route: CockpitRouteContext,
    graph: ResolvedGraph,
  ): ZoomRouteProjection {
    let capability = graph.capability;
    let system = graph.system;
    let run = graph.run;
    let invocation = graph.invocation;
    let skill = graph.skill;

    if (route.selectedType === 'capability') {
      capability = capability?.id === route.selectedRef ? capability : null;
      system = null;
      run = null;
      invocation = null;
      skill = null;
    } else if (route.selectedType === 'system') {
      system = system?.id === route.selectedRef ? system : null;
      if (!system) capability = null;
      run = null;
      invocation = null;
      skill = null;
    } else if (route.selectedType === 'run') {
      run = run?.id === route.selectedRef ? run : null;
      if (!run) {
        system = null;
        capability = null;
      }
      skill = null;
      invocation = null;
    } else if (route.selectedType === 'skill_invocation') {
      invocation = invocation?.id === route.selectedRef ? invocation : null;
      run = run?.id === route.runId ? run : null;
      if (!run || !invocation || invocation.run_id !== run.id) {
        capability = null;
        system = null;
        run = null;
        invocation = null;
      }
      skill = null;
    } else if (route.selectedType === 'skill') {
      skill = skill?.slug === route.selectedRef ? skill : null;
    }

    if (run?.system_id && system?.id !== run.system_id) {
      system = null;
      capability = null;
    }
    if (invocation && (!run || invocation.run_id !== run.id)) {
      invocation = null;
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
    const skillInvocationId = invocation?.id ?? null;
    const skillRef = skill?.slug ?? null;
    const ancestry: NavigationAncestry = {
      capabilityId,
      systemId,
      runId,
      skillInvocationId,
      skillRef,
    };
    const projectedLens = this.axesV3Enabled() ? route.lens : null;
    const nodes: ZoomGraphNode[] = [
      this.portfolioNode(false, projectedLens, route),
    ];

    if (capability) {
      nodes.push({
        key: 'capability',
        id: capability.id,
        label: capability.name,
        sub: this.i18n.t('nav.zoom.capability'),
        href: navigationObjectUrl('capability', capability.id, { lens: projectedLens }),
      });
    }
    if (system) {
      nodes.push({
        key: 'system',
        id: system.id,
        label: system.name,
        sub: this.i18n.t('nav.zoom.system'),
        href: navigationObjectUrl('system', system.id, {
          capabilityId: capability?.id ?? null,
          lens: projectedLens,
        }),
      });
    }
    if (run) {
      const shortId = this.shortRef(run.id);
      nodes.push({
        key: 'run',
        id: run.id,
        label: this.i18n.t('nav.zoom.run'),
        sub: this.i18n.t('nav.zoom.run'),
        href: navigationObjectUrl('run', run.id, {
          capabilityId: capability?.id ?? null,
          systemId: system?.id ?? run.system_id,
          lens: projectedLens,
        }),
        mono: shortId,
      });
    }
    const runtimeInvocationId = invocation?.id;
    if (invocation && runtimeInvocationId && run) {
      const skillName = invocation.skill_slug || invocation.skill_id || this.shortRef(runtimeInvocationId);
      nodes.push({
        key: 'skill_invocation',
        id: runtimeInvocationId,
        label: this.i18n.t('nav.zoom.skill'),
        sub: this.i18n.t('nav.zoom.skill'),
        href: navigationObjectUrl('skill_invocation', runtimeInvocationId, {
          capabilityId: capability?.id ?? null,
          systemId: system?.id ?? run.system_id,
          runId: run.id,
          lens: projectedLens,
        }),
        mono: skillName,
      });
    }
    if (skill) {
      nodes.push({
        key: 'skill',
        id: skill.id,
        label: this.i18n.t('nav.zoom.skill'),
        sub: this.i18n.t('nav.zoom.skill'),
        href: navigationObjectUrl('skill', skill.slug, {
          capabilityId: capability?.id ?? null,
          systemId: system?.id ?? null,
          runId: run?.id ?? null,
          lens: projectedLens,
        }),
        mono: skill.slug,
      });
    }

    return { route, ancestry, nodes, loading: false, badge: null };
  }

  private portfolioNode(
    neutral = false,
    lens: CockpitLens | null = null,
    route?: CockpitRouteContext,
  ): ZoomGraphNode {
    const workspace = neutral ? null : this.workspace.current();
    return {
      key: 'portfolio',
      id: workspace?.id ?? null,
      label: this.i18n.t('nav.zoom.portfolio'),
      sub: workspace?.name || '',
      href: route?.selectedType === 'system'
        ? navigationSurfaceUrl('systems', { lens })
        : this.navV5Enabled() && this.workspaceMode() === 'builder'
        ? navigationSurfaceUrl('create')
        : navigationPortfolioUrl(lens, this.axesV4Enabled()),
    };
  }

  private collapseNodes(nodes: readonly ZoomGraphNode[]): ZoomGraphNode[] {
    if (nodes.length <= 4) return [...nodes];
    return [
      nodes[0],
      {
        key: 'ellipsis',
        id: null,
        label: this.i18n.t('nav.zoom.ellipsis'),
        sub: nodes.slice(1, -2).map((node) => node.label).join(' › '),
        href: '',
      },
      nodes[nodes.length - 2],
      nodes[nodes.length - 1],
    ];
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

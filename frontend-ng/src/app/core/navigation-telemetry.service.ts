import { Injectable, OnDestroy, inject } from '@angular/core';
import {
  NavigationCancel,
  NavigationCancellationCode,
  NavigationEnd,
  NavigationError,
  NavigationStart,
  Router,
} from '@angular/router';
import { Subscription } from 'rxjs';
import { ApiService } from './api.service';
import {
  AGENTIUM_SURFACE_ROUTES,
  matchAgentiumSurface,
  navigationRouteContext,
  type HierarchyObjectType,
} from './navigation.catalog';
import { WorkspaceService } from './workspace.service';

export const NAVIGATION_RESOLVED_EVENT = 'navigation.resolved';
export const NAVIGATION_TRANSITION_EVENT = 'navigation.transition';

export type NavigationTransitionTrigger =
  | 'rail'
  | 'minirail'
  | 'breadcrumb'
  | 'inpage'
  | 'palette'
  | 'history'
  | 'redirect';

export interface NavigationTransitionDetails {
  schema_version: 2;
  from_surface: string;
  to_surface: string;
  trigger: NavigationTransitionTrigger;
  zone_changed: boolean;
  depth_delta: number;
  facet_changed: boolean;
}

export type NavigationResolutionOwner =
  | 'angular_router'
  | 'navigation_resolver';

export type NavigationRedirectReason =
  | 'direct'
  | 'angular_route_redirect'
  | 'business_profile_disallowed'
  | 'business_knowledge_compatibility'
  | 'business_system_capture_compatibility'
  | 'workspace_default_route'
  | 'workspace_extension_unavailable'
  | 'legacy_hypervisor_object_lens'
  | 'legacy_focus_query'
  | 'legacy_tab_query'
  | 'workspace_mode_home'
  | 'workspace_settings_entrypoint';

export interface NavigationRedirectDecision {
  requestedRoute: string;
  resolvedRoute: string;
  owner: 'navigation_resolver';
  reason: Exclude<NavigationRedirectReason, 'direct' | 'angular_route_redirect'>;
}

export interface NavigationResolvedDetails {
  schema_version: 1;
  requested_route: string;
  resolved_route: string;
  effective_workspace: string;
  effective_surface: string;
  redirect_owner: NavigationResolutionOwner;
  redirect_reason: NavigationRedirectReason;
  redirected: boolean;
}

type DeferredNavigationDetails = Omit<NavigationResolvedDetails, 'effective_workspace'>;

// The surface catalog owns canonical entries. These additional templates are
// privacy masks for parameterized child routes exposed by Angular; they do not
// resolve navigation and carry no runtime values.
const NAVIGATION_PRIVACY_TEMPLATES = [
  ...AGENTIUM_SURFACE_ROUTES.map((surface) => surface.route),
  '/auth/:view',
  '/hypervisor/mission-room/:view',
  '/hypervisor/mission-room/agenda/meeting/:eventId',
  '/systems/new',
  '/systems/:systemId/flow',
  '/systems/:systemId',
  '/capabilities/:capabilityId',
  '/skills/:skillId',
  '/knowledge/:knowledgeId',
  '/runs/:runId',
  '/steering/contexts/:contextId',
  '/presets/evaluation',
  '/presets/:presetId',
  '/workspace/:slug/settings',
  '/workspace/:slug/chat-knowledge',
  '/workspace/:slug/members',
  '/workspace/:slug/access',
  '/workspace/:slug/danger',
  '/account/profile',
  '/account/password',
  '/account/security',
  '/account/sessions',
  '/account/danger',
  '/governance/audit',
  '/governance/experiences',
  '/governance/access',
  '/governance/chat-history',
  '/governance/surface-map',
  '/governance/blueprints',
  '/governance/workspace-apps',
  '/governance/canonical-answers',
  '/workspace-app-unavailable',
  '/workspace-app-repair',
  '/observability/quality',
  '/observability/performance',
].sort((left, right) => {
  const leftSegments = left.split('/').filter(Boolean);
  const rightSegments = right.split('/').filter(Boolean);
  return (
    rightSegments.length - leftSegments.length ||
    rightSegments.filter((segment) => !segment.startsWith(':')).length -
      leftSegments.filter((segment) => !segment.startsWith(':')).length
  );
});

/**
 * Keep navigation telemetry privacy-safe and aggregation-friendly.
 *
 * Query strings and fragments may contain free text, search terms or user
 * identifiers, so the audit contract deliberately records paths only. UUIDs
 * and e-mail-shaped path segments are redacted as a second line of defence.
 */
export function privacySafeNavigationRoute(value: string): string {
  const rawPath = (value || '/').split('?')[0].split('#')[0] || '/';
  const path = rawPath.startsWith('/') ? rawPath : `/${rawPath}`;
  const segments = path.split('/').filter(Boolean).map((segment) => {
    let decoded = segment;
    try {
      decoded = decodeURIComponent(segment);
    } catch {
      // Keep the original segment; malformed escaping must not break routing.
    }
    if (/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(decoded)) {
      return ':id';
    }
    if (/^[^/\s@]+@[^/\s@]+\.[^/\s@]+$/i.test(decoded)) {
      return ':redacted';
    }
    return decoded;
  });
  if (!segments.length) return '/';

  let bestTemplate: string[] | null = null;
  for (const template of NAVIGATION_PRIVACY_TEMPLATES) {
    const templateSegments = template.split('/').filter(Boolean);
    if (segments.length < templateSegments.length) continue;
    const matches = templateSegments.every((segment, index) =>
      segment.startsWith(':') || segment === segments[index],
    );
    if (matches) {
      bestTemplate = templateSegments;
      break;
    }
  }
  if (bestTemplate) {
    return `/${[
      ...bestTemplate,
      ...segments.slice(bestTemplate.length).map(() => ':segment'),
    ].join('/')}`;
  }

  const knownRoots = new Set(
    NAVIGATION_PRIVACY_TEMPLATES
      .map((template) => template.split('/').filter(Boolean)[0])
      .filter((segment): segment is string => Boolean(segment) && !segment.startsWith(':')),
  );
  const safeSegments = knownRoots.has(segments[0])
    ? [segments[0], ...segments.slice(1).map(() => ':segment')]
    : segments.map(() => ':segment');
  return `/${safeSegments.join('/')}`;
}

/** Resolve a stable surface id from the existing Agentium surface catalog. */
export function navigationSurfaceForRoute(value: string): string {
  const path = privacySafeNavigationRoute(value);
  return matchAgentiumSurface(path)?.id ?? 'unknown';
}

const DEPTH_BY_TYPE: Record<HierarchyObjectType, number> = {
  capability: 2,
  system: 3,
  run: 4,
  skill_invocation: 5,
  skill: 5,
  collection: 2,
  dataset: 2,
  model: 2,
  context: 3,
  conversation: 2,
  business_app: 3,
};

/** Hierarchy depth 1–5. Zone lists and homes sit at 1 (Portfolio). */
export function navigationDepthForRoute(value: string): number {
  const selected = navigationRouteContext(value, false).selectedType;
  return selected ? DEPTH_BY_TYPE[selected] : 1;
}

function navigationFacetToken(value: string): string {
  const query = navigationRouteContext(value, false).query;
  const token = query['facet'] || query['tab'] || '';
  return /^[a-z0-9][a-z0-9._-]{0,63}$/i.test(token) ? token.toLowerCase() : '';
}

function navigationZoneForRoute(value: string): string {
  return navigationRouteContext(value).lens;
}

/**
 * Emits one best-effort audit event after each authenticated navigation has
 * resolved. Explicit redirect owners register their decision before invoking
 * the Router; ordinary and static Angular redirects are inferred from
 * NavigationStart/NavigationEnd.
 */
@Injectable({ providedIn: 'root' })
export class NavigationTelemetryService implements OnDestroy {
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);
  private readonly workspace = inject(WorkspaceService);

  private subscription: Subscription | null = null;
  private requestedRoute = '/';
  private pendingRedirect: NavigationRedirectDecision | null = null;
  private pendingTrigger: NavigationTransitionTrigger | null = null;
  private lastNavigationTrigger: 'imperative' | 'popstate' | 'hashchange' | null = null;
  private lastResolvedUrl = '/';
  private deferredDetails: DeferredNavigationDetails | null = null;
  private readonly unregisterContextReset: () => void;

  constructor() {
    this.unregisterContextReset = this.workspace.registerContextReset(() => {
      this.pendingRedirect = null;
      this.pendingTrigger = null;
      this.deferredDetails = null;
      this.requestedRoute = privacySafeNavigationRoute(this.router.url || '/');
      this.lastResolvedUrl = this.router.url || '/';
    });
  }

  start(): void {
    if (this.subscription) return;
    this.requestedRoute = privacySafeNavigationRoute(this.router.url || '/');
    this.lastResolvedUrl = this.router.url || '/';
    this.subscription = this.router.events.subscribe((event) => {
      if (event instanceof NavigationStart) {
        const requestedRoute = privacySafeNavigationRoute(event.url);
        // A UrlTree redirect produces a replacement NavigationStart. Retain an
        // explicit decision only for that exact destination; any other start
        // proves the redirect was abandoned or superseded.
        if (this.pendingRedirect && this.pendingRedirect.resolvedRoute !== requestedRoute) {
          this.pendingRedirect = null;
        }
        this.requestedRoute = requestedRoute;
        this.lastNavigationTrigger = event.navigationTrigger ?? 'imperative';
      } else if (event instanceof NavigationEnd) {
        this.emitResolved(event);
      } else if (event instanceof NavigationCancel) {
        // A superseded navigation is followed by the replacement
        // NavigationStart, just like a UrlTree redirect. Keep the explicit
        // decision until that start can prove whether the winning destination
        // is the one that was registered. Guard/resolver/abort cancellations
        // have no replacement and must still purge it immediately.
        if (
          event.code !== NavigationCancellationCode.Redirect &&
          event.code !== NavigationCancellationCode.SupersededByNewNavigation
        ) {
          this.pendingRedirect = null;
        }
      } else if (event instanceof NavigationError) {
        this.pendingRedirect = null;
      }
    });
  }

  /** Chrome registers the control that initiated the next navigation. Consumed once. */
  registerTrigger(trigger: NavigationTransitionTrigger): void {
    this.pendingTrigger = trigger;
  }

  registerRedirect(decision: NavigationRedirectDecision): void {
    this.pendingRedirect = {
      ...decision,
      requestedRoute: privacySafeNavigationRoute(decision.requestedRoute),
      resolvedRoute: privacySafeNavigationRoute(decision.resolvedRoute),
    };
  }

  /** Flush the initial resolved route once WorkspaceService has loaded. */
  flushDeferred(): void {
    const workspaceSlug = this.workspace.currentSlug();
    if (!workspaceSlug || !this.deferredDetails) return;
    const details = this.deferredDetails;
    this.deferredDetails = null;
    this.emitAudit(details, workspaceSlug);
  }

  ngOnDestroy(): void {
    this.subscription?.unsubscribe();
    this.subscription = null;
    this.unregisterContextReset();
  }

  private emitResolved(event: NavigationEnd): void {
    const resolvedRoute = privacySafeNavigationRoute(event.urlAfterRedirects || event.url);
    if (resolvedRoute === '/auth' || resolvedRoute.startsWith('/auth/') || resolvedRoute.startsWith('/deposit/')) {
      this.pendingRedirect = null;
      this.deferredDetails = null;
      return;
    }

    const explicit = this.pendingRedirect;
    this.pendingRedirect = null;
    const requestedRoute = explicit?.requestedRoute || this.requestedRoute;
    // An explicit decision identifies who initiated the redirect and why, but
    // Angular remains authoritative for the destination that actually won. Its
    // target may itself pass through a static redirect or another resolver.
    const destination = resolvedRoute;
    const redirected = Boolean(explicit) || requestedRoute !== destination;
    const details: DeferredNavigationDetails = {
      schema_version: 1,
      requested_route: requestedRoute,
      resolved_route: destination,
      effective_surface: navigationSurfaceForRoute(destination),
      redirect_owner: explicit?.owner || 'angular_router',
      redirect_reason: explicit?.reason || (redirected ? 'angular_route_redirect' : 'direct'),
      redirected,
    };

    const workspaceSlug = this.workspace.currentSlug();
    if (!workspaceSlug) {
      // Keep only the latest successful resolution. The Shell calls
      // flushDeferred() immediately after loadWorkspaces establishes the
      // authoritative active slug, avoiding a fabricated or stale workspace.
      this.deferredDetails = details;
      return;
    }
    this.deferredDetails = null;
    this.emitAudit(details, workspaceSlug);
    this.emitTransition(event.urlAfterRedirects || event.url, Boolean(explicit));
  }

  private emitAudit(details: DeferredNavigationDetails, workspaceSlug: string): void {
    this.api.post('/audit', {
      event_type: NAVIGATION_RESOLVED_EVENT,
      details: {
        ...details,
        effective_workspace: workspaceSlug,
      } satisfies NavigationResolvedDetails,
      severity: 'info',
    }).subscribe({
      next: () => {
        // Telemetry never blocks navigation.
      },
      error: () => {
        // Audit ingestion is intentionally best-effort.
      },
    });
  }

  private telemetryV2Enabled(): boolean {
    const features = this.workspace.current()?.settings?.['features'];
    return Boolean(
      features
      && typeof features === 'object'
      && !Array.isArray(features)
      && (features as Record<string, unknown>)['navigation_telemetry_v2'] === true,
    );
  }

  private consumeTrigger(redirected: boolean): NavigationTransitionTrigger {
    const registered = this.pendingTrigger;
    this.pendingTrigger = null;
    if (redirected) return 'redirect';
    if (this.lastNavigationTrigger === 'popstate') return 'history';
    return registered ?? 'inpage';
  }

  private emitTransition(rawUrl: string, redirected: boolean): void {
    const fromUrl = this.lastResolvedUrl || rawUrl;
    const trigger = this.consumeTrigger(redirected);
    this.lastResolvedUrl = rawUrl;
    if (!this.telemetryV2Enabled() || !this.workspace.currentSlug()) return;
    const details: NavigationTransitionDetails = {
      schema_version: 2,
      from_surface: navigationSurfaceForRoute(fromUrl),
      to_surface: navigationSurfaceForRoute(rawUrl),
      trigger,
      zone_changed: navigationZoneForRoute(fromUrl) !== navigationZoneForRoute(rawUrl),
      depth_delta: navigationDepthForRoute(rawUrl) - navigationDepthForRoute(fromUrl),
      facet_changed: navigationFacetToken(fromUrl) !== navigationFacetToken(rawUrl),
    };
    this.api.post('/audit', {
      event_type: NAVIGATION_TRANSITION_EVENT,
      details,
      severity: 'info',
    }).subscribe({
      next: () => {
        // Telemetry never blocks navigation.
      },
      error: () => {
        // Audit ingestion is intentionally best-effort.
      },
    });
  }
}

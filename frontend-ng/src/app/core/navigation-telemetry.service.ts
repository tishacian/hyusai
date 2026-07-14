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
import { AGENTIUM_SURFACE_ROUTES } from './navigation.catalog';
import { WorkspaceService } from './workspace.service';

export const NAVIGATION_RESOLVED_EVENT = 'navigation.resolved';

export type NavigationResolutionOwner =
  | 'angular_router'
  | 'navigation_profile'
  | 'workspace_shell'
  | 'workspace_entrypoint';

export type NavigationRedirectReason =
  | 'direct'
  | 'angular_route_redirect'
  | 'business_profile_disallowed'
  | 'business_knowledge_compatibility'
  | 'business_system_capture_compatibility'
  | 'workspace_default_route'
  | 'workspace_settings_entrypoint';

export interface NavigationRedirectDecision {
  requestedRoute: string;
  resolvedRoute: string;
  owner: Exclude<NavigationResolutionOwner, 'angular_router'>;
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
  '/governance/access',
  '/governance/chat-history',
  '/governance/surface-map',
  '/governance/blueprints',
  '/governance/canonical-answers',
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

  // These workbenches own a route family whose catalog entry is a concrete
  // canonical entry point rather than the common prefix.
  if (path === '/hypervisor/mission-room' || path.startsWith('/hypervisor/mission-room/')) {
    return 'mission-room';
  }
  if (/^\/systems\/[^/]+\/capture(?:\/|$)/.test(path)) return 'system-capture';

  const pathSegments = path.split('/').filter(Boolean);
  const catalog = [...AGENTIUM_SURFACE_ROUTES].sort(
    (left, right) => right.route.split('/').length - left.route.split('/').length,
  );
  for (const surface of catalog) {
    const routeSegments = surface.route.split('/').filter(Boolean);
    if (pathSegments.length < routeSegments.length) continue;
    const matches = routeSegments.every((segment, index) =>
      segment.startsWith(':') || segment === pathSegments[index],
    );
    if (matches) return surface.id;
  }
  return 'unknown';
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
  private deferredDetails: DeferredNavigationDetails | null = null;

  start(): void {
    if (this.subscription) return;
    this.requestedRoute = privacySafeNavigationRoute(this.router.url || '/');
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
}

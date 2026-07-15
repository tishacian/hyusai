import { Injectable, inject } from '@angular/core';
import { NavigationProfileService } from './navigation-profile.service';
import type { NavigationRedirectDecision } from './navigation-telemetry.service';
import { WorkspaceService } from './workspace.service';
import { agentiumSurfaceRoute } from './navigation.catalog';

const DEFAULT_BUSINESS_ROUTE = agentiumSurfaceRoute('chat');
const DEFAULT_DEMO_ROUTE = agentiumSurfaceRoute('mission-room');

/**
 * Single owner for policy-driven navigation redirects.
 *
 * Angular remains responsible for executing the returned destination and for
 * its static route aliases. Components and shells must not duplicate these
 * decisions: they consume the workspace/profile state only for rendering.
 */
@Injectable({ providedIn: 'root' })
export class NavigationResolverService {
  private readonly navigationProfile = inject(NavigationProfileService);
  private readonly workspace = inject(WorkspaceService);

  resolve(requestedRoute: string): NavigationRedirectDecision | null {
    return (
      this.resolveBusinessProfile(requestedRoute) ||
      this.resolveDemoEntrypoint(requestedRoute) ||
      this.resolveWorkspaceEntrypoint(requestedRoute)
    );
  }

  /**
   * Terminal fallback when the membership list cannot be loaded twice.
   * Keeping this decision here preserves the single redirect-policy owner;
   * the guard only executes the returned URL tree.
   */
  resolveWorkspaceLoadFailure(requestedRoute: string): NavigationRedirectDecision | null {
    if (this.pathOnly(requestedRoute) !== '/workspace') return null;
    return this.decision(
      requestedRoute,
      agentiumSurfaceRoute('hypervisor'),
      'workspace_settings_entrypoint',
    );
  }

  /** Activate a workspace carried by a deep link before any routed component exists. */
  activateWorkspaceFromRoute(requestedRoute: string): NavigationRedirectDecision | null {
    const match = this.pathOnly(requestedRoute).match(/^\/workspace\/([^/]+)(?:\/|$)/);
    if (!match?.[1]) return null;
    let slug: string;
    try {
      slug = decodeURIComponent(match[1]);
    } catch {
      return this.invalidWorkspaceFallback(requestedRoute);
    }
    if (slug === this.workspace.currentSlug()) return null;
    if (this.workspace.switchWorkspace(slug)) return null;
    return this.invalidWorkspaceFallback(requestedRoute);
  }

  private resolveBusinessProfile(requestedRoute: string): NavigationRedirectDecision | null {
    if (!this.navigationProfile.businessShellActive()) return null;

    const path = this.pathOnly(requestedRoute);
    if (this.navigationProfile.isBusinessAllowedPath(path)) return null;

    if (path === agentiumSurfaceRoute('knowledge')) {
      return this.decision(
        requestedRoute,
        agentiumSurfaceRoute('knowledge-capture'),
        'business_knowledge_compatibility',
      );
    }

    const systemCapture = path.match(/^\/systems\/([^/]+)\/capture$/);
    if (systemCapture?.[1]) {
      return this.decision(
        requestedRoute,
        `${agentiumSurfaceRoute('knowledge-capture')}?systemId=${encodeURIComponent(systemCapture[1])}`,
        'business_system_capture_compatibility',
      );
    }

    const configuredDefault = this.absoluteRoute(this.navigationProfile.effective().defaultRoute);
    const resolvedRoute = configuredDefault && this.navigationProfile.isBusinessAllowedPath(configuredDefault)
      ? configuredDefault
      : DEFAULT_BUSINESS_ROUTE;
    return this.decision(requestedRoute, resolvedRoute, 'business_profile_disallowed');
  }

  private resolveDemoEntrypoint(requestedRoute: string): NavigationRedirectDecision | null {
    if (
      !this.workspace.isDemoMode() ||
      this.pathOnly(requestedRoute) !== agentiumSurfaceRoute('hypervisor')
    ) return null;

    const configuredDefault = this.absoluteRoute(
      this.workspace.current()?.settings?.['default_route'],
    );
    const resolvedRoute = configuredDefault || DEFAULT_DEMO_ROUTE;
    const resolvedPath = this.pathOnly(resolvedRoute);
    // `/` is the Angular alias of `/hypervisor`; redirecting between the two
    // would form a cross-owner loop even though neither URL is textually equal.
    if (resolvedPath === '/' || resolvedPath === agentiumSurfaceRoute('hypervisor')) return null;
    return this.decision(requestedRoute, resolvedRoute, 'workspace_default_route');
  }

  private resolveWorkspaceEntrypoint(requestedRoute: string): NavigationRedirectDecision | null {
    if (this.pathOnly(requestedRoute) !== '/workspace') return null;
    const slug = this.workspace.current()?.slug || this.workspace.currentSlug();
    if (!slug) return null;
    return this.decision(
      requestedRoute,
      `/workspace/${encodeURIComponent(slug)}/settings`,
      'workspace_settings_entrypoint',
    );
  }

  private invalidWorkspaceFallback(requestedRoute: string): NavigationRedirectDecision | null {
    const currentSlug = this.workspace.current()?.slug || this.workspace.currentSlug();
    if (!currentSlug) return null;
    return this.decision(
      requestedRoute,
      `/workspace/${encodeURIComponent(currentSlug)}/settings`,
      'workspace_settings_entrypoint',
    );
  }

  private decision(
    requestedRoute: string,
    resolvedRoute: string,
    reason: NavigationRedirectDecision['reason'],
  ): NavigationRedirectDecision | null {
    if (this.routesAreEquivalent(requestedRoute, resolvedRoute)) return null;
    return {
      requestedRoute,
      resolvedRoute,
      owner: 'navigation_resolver',
      reason,
    };
  }

  private routesAreEquivalent(left: string, right: string): boolean {
    return this.pathOnly(left) === this.pathOnly(right);
  }

  private absoluteRoute(value: unknown): string | null {
    if (typeof value !== 'string') return null;
    const route = value.trim();
    return route.startsWith('/') ? route : null;
  }

  private pathOnly(value: string): string {
    return (value || '/').split('?')[0].split('#')[0] || '/';
  }
}

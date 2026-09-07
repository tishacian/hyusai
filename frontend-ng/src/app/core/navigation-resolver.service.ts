import { Injectable, inject } from '@angular/core';
import { NavigationProfileService } from './navigation-profile.service';
import type { NavigationRedirectDecision } from './navigation-telemetry.service';
import { WorkspaceService, workspaceSettingFeature } from './workspace.service';
import { agentiumSurfaceRoute } from './navigation.catalog';
import {
  MISSION_ROOM_EXTENSION,
  missionRoomExtensionState,
} from '@app/features/mission-room/mission-room.extension';

const DEFAULT_BUSINESS_ROUTE = agentiumSurfaceRoute('chat');

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
      this.resolveLegacyHypervisorObjectLens(requestedRoute) ||
      this.resolveLegacyQueryAliases(requestedRoute) ||
      this.resolveBusinessProfile(requestedRoute) ||
      this.resolveModeHome(requestedRoute) ||
      this.resolveStaleWorkspaceAppUnavailable(requestedRoute) ||
      this.resolveUnavailableWorkspaceExtension(requestedRoute) ||
      this.resolveDemoEntrypoint(requestedRoute) ||
      this.resolveWorkspaceEntrypoint(requestedRoute)
    );
  }

  /** Axes v4 makes Hypervisor a Portfolio destination, never an object lens. */
  private resolveLegacyHypervisorObjectLens(
    requestedRoute: string,
  ): NavigationRedirectDecision | null {
    if (!this.axesV4Enabled()) return null;
    const path = this.pathOnly(requestedRoute);
    if (!/^\/(?:capabilities|systems|runs|skills)(?:\/|$)/.test(path)) return null;
    const rawQuery = requestedRoute.includes('?')
      ? requestedRoute.slice(requestedRoute.indexOf('?') + 1).split('#')[0]
      : '';
    if (new URLSearchParams(rawQuery).get('lens') !== 'hypervisor') return null;
    return this.decision(
      requestedRoute,
      agentiumSurfaceRoute('hypervisor'),
      'legacy_hypervisor_object_lens',
    );
  }

  /** Builder + `cockpit_nav_v5`: Portfolio home is `/create` (D4). */
  private resolveModeHome(requestedRoute: string): NavigationRedirectDecision | null {
    if (!this.navV5Enabled()) return null;
    if (this.workspace.current()?.mode !== 'builder') return null;
    const path = this.pathOnly(requestedRoute);
    if (path !== '/' && path !== agentiumSurfaceRoute('hypervisor')) return null;
    return this.decision(requestedRoute, agentiumSurfaceRoute('create'), 'workspace_mode_home');
  }

  /** `?focus=` / `?tab=` become object paths and `?facet=` (L6.1). */
  private resolveLegacyQueryAliases(
    requestedRoute: string,
  ): NavigationRedirectDecision | null {
    const path = this.pathOnly(requestedRoute);
    const rawQuery = requestedRoute.includes('?')
      ? requestedRoute.slice(requestedRoute.indexOf('?') + 1).split('#')[0]
      : '';
    const params = new URLSearchParams(rawQuery);
    const focus = params.get('focus');
    if (path === agentiumSurfaceRoute('capabilities') && focus) {
      params.delete('focus');
      const query = params.toString();
      return this.decision(
        requestedRoute,
        `/capabilities/${encodeURIComponent(focus)}${query ? `?${query}` : ''}`,
        'legacy_focus_query',
      );
    }
    const tab = params.get('tab');
    if (tab && !params.get('facet')) {
      params.set('facet', tab);
      params.delete('tab');
      const query = params.toString();
      const resolvedRoute = query ? `${path}?${query}` : path;
      if (resolvedRoute === requestedRoute) return null;
      return {
        requestedRoute,
        resolvedRoute,
        owner: 'navigation_resolver',
        reason: 'legacy_tab_query',
      };
    }
    return null;
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
    const pathMatch = this.pathOnly(requestedRoute).match(/^\/workspace\/([^/]+)(?:\/|$)/);
    const rawQuery = requestedRoute.includes('?')
      ? requestedRoute.slice(requestedRoute.indexOf('?') + 1).split('#')[0]
      : '';
    const encoded = pathMatch?.[1] || new URLSearchParams(rawQuery).get('workspace');
    if (!encoded) return null;
    let slug: string;
    try {
      slug = decodeURIComponent(encoded);
    } catch {
      return this.invalidWorkspaceFallback(requestedRoute);
    }
    if (!slug.trim()) return null;
    if (slug === this.workspace.currentSlug()) return null;
    if (this.workspace.switchWorkspace(slug)) return null;
    return this.invalidWorkspaceFallback(requestedRoute);
  }

  private resolveBusinessProfile(requestedRoute: string): NavigationRedirectDecision | null {
    const experience = this.navigationProfile.resolveWorkspaceExperience(requestedRoute);
    if (experience) {
      if (experience.shellKind === 'workspace_app_unavailable') {
        const routeResolution = experience.routeResolution;
        if (routeResolution.redirectReason === 'none') return null;
        return this.decision(
          requestedRoute,
          routeResolution.resolvedRoute,
          routeResolution.redirectReason,
        );
      }
      if (!experience.business.active) return null;
      const routeResolution = experience.routeResolution;
      if (routeResolution.redirectReason === 'none') return null;
      let resolvedRoute = routeResolution.resolvedRoute;
      if (routeResolution.redirectReason === 'business_system_capture_compatibility') {
        const systemId = this.systemCaptureId(requestedRoute);
        if (systemId) {
          resolvedRoute = `${agentiumSurfaceRoute('knowledge-capture')}?systemId=${encodeURIComponent(systemId)}`;
        }
      }
      return this.decision(requestedRoute, resolvedRoute, routeResolution.redirectReason);
    }

    if (!this.navigationProfile.businessShellActive()) return null;

    const path = this.pathOnly(requestedRoute);
    if (this.navigationProfile.isBusinessAllowedPath(path)) return null;

    if (
      path === agentiumSurfaceRoute('knowledge')
      && this.navigationProfile.businessSurfaceEnabled('knowledge-capture')
    ) {
      return this.decision(
        requestedRoute,
        agentiumSurfaceRoute('knowledge-capture'),
        'business_knowledge_compatibility',
      );
    }

    const systemId = this.systemCaptureId(requestedRoute);
    if (systemId && this.navigationProfile.businessSurfaceEnabled('knowledge-capture')) {
      return this.decision(
        requestedRoute,
        `${agentiumSurfaceRoute('knowledge-capture')}?systemId=${encodeURIComponent(systemId)}`,
        'business_system_capture_compatibility',
      );
    }

    const configuredDefault = this.absoluteRoute(this.navigationProfile.effective().defaultRoute);
    const resolvedRoute = configuredDefault && this.navigationProfile.isBusinessAllowedPath(configuredDefault)
      ? configuredDefault
      : this.navigationProfile.appEntitlementsEnabled()
        ? '/account/profile'
        : DEFAULT_BUSINESS_ROUTE;
    return this.decision(requestedRoute, resolvedRoute, 'business_profile_disallowed');
  }

  private resolveUnavailableWorkspaceExtension(
    requestedRoute: string,
  ): NavigationRedirectDecision | null {
    const path = this.pathOnly(requestedRoute);
    if (
      path !== MISSION_ROOM_EXTENSION.routeRoot
      && !path.startsWith(`${MISSION_ROOM_EXTENSION.routeRoot}/`)
    ) return null;
    if (missionRoomExtensionState(this.workspace.current()).enabled) return null;
    return this.decision(
      requestedRoute,
      agentiumSurfaceRoute('hypervisor'),
      'workspace_extension_unavailable',
    );
  }

  /** The safety page is reachable only while the current runtime is invalid. */
  private resolveStaleWorkspaceAppUnavailable(
    requestedRoute: string,
  ): NavigationRedirectDecision | null {
    if (this.pathOnly(requestedRoute) !== '/workspace-app-unavailable') return null;
    if (this.navigationProfile.workspaceAppUnavailable()) return null;
    const experience = this.navigationProfile.resolveWorkspaceExperience(requestedRoute);
    return this.decision(
      requestedRoute,
      experience?.homeRoute || agentiumSurfaceRoute('hypervisor'),
      'workspace_default_route',
    );
  }

  private resolveDemoEntrypoint(requestedRoute: string): NavigationRedirectDecision | null {
    if (
      !this.workspace.isDemoMode() ||
      this.pathOnly(requestedRoute) !== agentiumSurfaceRoute('hypervisor')
    ) return null;
    // Explicit v4 (not the graduated default) keeps Hypervisor as Portfolio.
    // Demo workspaces without the stored flag still bounce to Mission Room.
    if (this.axesV4Enabled()) return null;

    const configuredDefault = this.absoluteRoute(
      this.workspace.current()?.settings?.['default_route'],
    );
    const extension = missionRoomExtensionState(this.workspace.current());
    const safeConfiguredDefault = configuredDefault && (
      extension.enabled || !this.isMissionRoomRoute(configuredDefault)
    ) ? configuredDefault : null;
    const resolvedRoute = safeConfiguredDefault || (
      extension.enabled ? MISSION_ROOM_EXTENSION.defaultRoute : agentiumSurfaceRoute('hypervisor')
    );
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

  private systemCaptureId(value: string): string | null {
    const encoded = this.pathOnly(value).match(/^\/systems\/([^/]+)\/capture$/)?.[1];
    if (!encoded) return null;
    try {
      return decodeURIComponent(encoded);
    } catch {
      return encoded;
    }
  }

  private pathOnly(value: string): string {
    return (value || '/').split('?')[0].split('#')[0] || '/';
  }

  private navV5Enabled(): boolean {
    return workspaceSettingFeature(this.workspace.current(), 'cockpit_nav_v5', true);
  }

  private axesV4Enabled(): boolean {
    return workspaceSettingFeature(this.workspace.current(), 'cockpit_router_axes_v4', false);
  }

  private isMissionRoomRoute(value: string): boolean {
    const path = this.pathOnly(value);
    return (
      path === MISSION_ROOM_EXTENSION.routeRoot ||
      path.startsWith(`${MISSION_ROOM_EXTENSION.routeRoot}/`)
    );
  }
}

import { Injectable, inject } from '@angular/core';
import { NavigationProfileService } from './navigation-profile.service';
import type { NavigationRedirectDecision } from './navigation-telemetry.service';
import { WorkspaceService, workspaceSettingFeature } from './workspace.service';
import { agentiumSurfaceRoute, matchAgentiumSurface, workspaceFamily } from './navigation.catalog';
import {
  missionRoomImpactTarget,
  missionRoomImpactUrl,
} from '@app/features/mission-room/mission-room-redirects';
import { arrivalProvenanceState } from '@app/shared/cockpit/arrival-provenance';

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
      this.resolveGenericHome(requestedRoute) ||
      this.resolveCustomerSurface(requestedRoute) ||
      this.resolveLegacyHypervisorObjectLens(requestedRoute) ||
      this.resolveLegacyQueryAliases(requestedRoute) ||
      this.resolvePresentationThemeAlias(requestedRoute) ||
      this.resolveBusinessProfile(requestedRoute) ||
      this.resolveModeHome(requestedRoute) ||
      this.resolveStaleWorkspaceAppUnavailable(requestedRoute) ||
      this.resolveMissionRoomCompat(requestedRoute) ||
      this.resolveWorkspaceEntrypoint(requestedRoute)
    );
  }

  private resolveGenericHome(requestedRoute: string): NavigationRedirectDecision | null {
    if (this.pathOnly(requestedRoute) !== '/') return null;
    const current = this.workspace.current();
    const adoption = workspaceSettingFeature(current, 'adoption_experience_v1', true);
    if (!adoption) {
      const profile = this.resolveBusinessProfile(requestedRoute);
      return profile || this.decision(requestedRoute,
        current?.mode === 'builder' && this.navV5Enabled() ? agentiumSurfaceRoute('create') : agentiumSurfaceRoute('hypervisor'), 'workspace_mode_home');
    }
    const experience = this.navigationProfile.resolveWorkspaceExperience(requestedRoute);
    if (experience?.shellKind === 'workspace_app_unavailable') return this.resolveBusinessProfile(requestedRoute);
    const profileSettings = current?.settings?.['navigation_profile'] as Record<string, unknown> | undefined;
    const configured = this.absoluteRoute(profileSettings?.['default_route'] || current?.settings?.['default_route']);
    if (configured && this.pathOnly(configured) !== '/' && matchAgentiumSurface(configured)) {
      const policy = this.resolveBusinessProfile(configured) || this.resolveMissionRoomCompat(configured);
      if (!policy) return this.decision(requestedRoute, configured, 'workspace_default_route');
    }
    if (this.workspace.experienceV1Enabled()) {
      const home = current?.mode === 'builder' && !this.navigationProfile.businessShellActive() ? 'create' : 'work';
      return this.decision(requestedRoute, agentiumSurfaceRoute(home), 'workspace_mode_home');
    }
    return this.resolveBusinessProfile(requestedRoute) || this.decision(requestedRoute,
      current?.mode === 'builder' ? agentiumSurfaceRoute('create') : agentiumSurfaceRoute('hypervisor'), 'workspace_mode_home');
  }

  /**
   * A customer application's surface opened from another family's workspace
   * (a bookmark, a shared link) goes to that workspace's home instead.
   */
  private resolveCustomerSurface(requestedRoute: string): NavigationRedirectDecision | null {
    const families = matchAgentiumSurface(this.pathOnly(requestedRoute))?.families;
    if (!families?.length) return null;
    if (families.includes(workspaceFamily(this.workspace.current()?.settings))) return null;
    return this.decision(requestedRoute, '/', 'workspace_extension_unavailable');
  }

  /**
   * Axes v4: `?lens=hypervisor` on an object is not a Portfolio jump (UX-010).
   * Stay on the object, strip `lens`, keep other params, attach « Voir dans Impact ».
   */
  private resolveLegacyHypervisorObjectLens(
    requestedRoute: string,
  ): NavigationRedirectDecision | null {
    if (!this.axesV4Enabled()) return null;
    const path = this.pathOnly(requestedRoute);
    if (!/^\/(?:capabilities|systems|runs|skills)(?:\/|$)/.test(path)) return null;
    const rawQuery = requestedRoute.includes('?')
      ? requestedRoute.slice(requestedRoute.indexOf('?') + 1).split('#')[0]
      : '';
    const params = new URLSearchParams(rawQuery);
    if (params.get('lens') !== 'hypervisor') return null;
    params.delete('lens');
    const query = params.toString();
    const resolvedRoute = query ? `${path}?${query}` : path;
    if (resolvedRoute === requestedRoute) return null;
    return {
      requestedRoute,
      resolvedRoute,
      owner: 'navigation_resolver',
      reason: 'legacy_hypervisor_object_lens',
      state: arrivalProvenanceState({ kind: 'see_in_impact' }),
    };
  }

  /** Builder + `cockpit_nav_v5`: Portfolio home is `/create` (D4). */
  private resolveModeHome(requestedRoute: string): NavigationRedirectDecision | null {
    if (!this.navV5Enabled()) return null;
    if (this.workspace.current()?.mode !== 'builder') return null;
    const path = this.pathOnly(requestedRoute);
    if (path !== '/' && path !== agentiumSurfaceRoute('hypervisor')) return null;
    return this.decision(requestedRoute, agentiumSurfaceRoute('create'), 'workspace_mode_home');
  }

  /** `?focus=` / `?tab=` / `?system_id=` become object paths, `?facet=`, `?systemId=` (L6.1 / L10). */
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
    const legacySystemId = params.get('system_id');
    if (legacySystemId && !params.get('systemId')) {
      params.set('systemId', legacySystemId);
      params.delete('system_id');
      const query = params.toString();
      const resolvedRoute = query ? `${path}?${query}` : path;
      if (resolvedRoute === requestedRoute) return null;
      return {
        requestedRoute,
        resolvedRoute,
        owner: 'navigation_resolver',
        reason: 'legacy_system_id_query',
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
    if (!['/', '/workspace'].includes(this.pathOnly(requestedRoute))) return null;
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

  /** L13a: Mission Room paths become Impact query params (replaceUrl via guard). */
  private resolveMissionRoomCompat(
    requestedRoute: string,
  ): NavigationRedirectDecision | null {
    const path = this.pathOnly(requestedRoute);
    const target = missionRoomImpactTarget(path);
    if (!target) return null;
    if (target.openPalette && typeof window !== 'undefined') {
      queueMicrotask(() => {
        window.dispatchEvent(new CustomEvent('ck:command-palette:open'));
      });
    }
    const resolved = missionRoomImpactUrl(path);
    if (!resolved) return null;
    return this.decision(requestedRoute, resolved, 'legacy_mission_room_path');
  }

  /** L13a: `?theme=mission` rewrites to `?theme=presentation`. */
  private resolvePresentationThemeAlias(
    requestedRoute: string,
  ): NavigationRedirectDecision | null {
    const path = this.pathOnly(requestedRoute);
    if (path !== agentiumSurfaceRoute('hypervisor') && path !== '/') return null;
    const rawQuery = requestedRoute.includes('?')
      ? requestedRoute.slice(requestedRoute.indexOf('?') + 1).split('#')[0]
      : '';
    const params = new URLSearchParams(rawQuery);
    if (params.get('theme') !== 'mission') return null;
    params.set('theme', 'presentation');
    const query = params.toString();
    const resolvedPath = path === '/' ? agentiumSurfaceRoute('hypervisor') : path;
    return this.decision(
      requestedRoute,
      query ? `${resolvedPath}?${query}` : resolvedPath,
      'legacy_theme_query',
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
    return this.normalizeRoute(left) === this.normalizeRoute(right);
  }

  private normalizeRoute(value: string): string {
    const path = this.pathOnly(value);
    const rawQuery = value.includes('?')
      ? value.slice(value.indexOf('?') + 1).split('#')[0]
      : '';
    if (!rawQuery) return path;
    const params = new URLSearchParams(rawQuery);
    const sorted: Array<[string, string]> = [];
    params.forEach((v, k) => {
      if (v) sorted.push([k, v]);
    });
    sorted.sort(([a], [b]) => a.localeCompare(b));
    if (!sorted.length) return path;
    const query = new URLSearchParams(sorted).toString();
    return `${path}?${query}`;
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
    return workspaceSettingFeature(this.workspace.current(), 'cockpit_router_axes_v4', true);
  }
}

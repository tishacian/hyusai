import { Injectable, computed, inject, signal } from '@angular/core';
import { WorkspaceService } from './workspace.service';
import {
  BUSINESS_NAVIGATION_SURFACE_IDS,
  agentiumSurfaceRoute,
  pathAllowedBySurfaceIds,
  surfaceOfferedToFamily,
  workspaceFamily,
} from './navigation.catalog';
import {
  resolveWorkspaceExperienceV2,
  type WorkspaceExperienceV2,
} from './workspace-experience';

export type NavigationProfileKey = 'standard' | 'business_end_user';
export type NavigationAdvancedAccess = 'admin_only' | 'link' | 'hidden';
export type BusinessNavigationSurfaceId = (typeof BUSINESS_NAVIGATION_SURFACE_IDS)[number];

export interface NavigationProfileConfig {
  key?: NavigationProfileKey | string | null;
  default_route?: string | null;
  primary_surfaces?: string[] | null;
  advanced_access?: NavigationAdvancedAccess | string | null;
}

export interface EffectiveNavigationProfile {
  key: NavigationProfileKey;
  configured: boolean;
  active: boolean;
  preview: boolean;
  admin: boolean;
  defaultRoute: string;
  primarySurfaces: string[];
  advancedAccess: NavigationAdvancedAccess;
}

const DEFAULT_BUSINESS_ROUTE = agentiumSurfaceRoute('chat');
const DEFAULT_BUSINESS_SURFACES = [...BUSINESS_NAVIGATION_SURFACE_IDS];
const PREVIEW_STORAGE_KEY = 'agentium_business_navigation_preview_slugs';

@Injectable({ providedIn: 'root' })
export class NavigationProfileService {
  private readonly workspace = inject(WorkspaceService);
  private readonly previewSlugs = signal<string[]>(this.readPreviewSlugs());

  readonly config = computed<NavigationProfileConfig>(() => {
    const raw = this.workspace.current()?.settings?.['navigation_profile'];
    return raw && typeof raw === 'object' && !Array.isArray(raw)
      ? raw as NavigationProfileConfig
      : {};
  });

  readonly configuredBusinessProfile = computed(() => this.config().key === 'business_end_user');
  readonly family = computed(() => workspaceFamily(this.workspace.current()?.settings));
  readonly admin = computed(() => this.workspace.isAdmin());
  readonly workspaceExperienceV2Enabled = computed(() =>
    this.featureEnabled('workspace_experience_v2'),
  );
  readonly workspaceAppPlatformEnabled = computed(() =>
    this.featureEnabled('workspace_app_platform_v1'),
  );
  readonly appEntitlementsEnabled = computed(() =>
    this.featureEnabled('app_entitlements_v1') || this.workspaceAppPlatformEnabled(),
  );
  readonly preview = computed(() => {
    const slug = this.workspace.currentSlug();
    return Boolean(
      slug &&
      this.admin() &&
      this.configuredBusinessProfile() &&
      this.previewSlugs().includes(slug),
    );
  });
  private readonly workspaceExperienceV2 = computed(() =>
    this.resolveWorkspaceExperience('/chat'),
  );
  readonly workspaceAppUnavailable = computed(() =>
    this.workspaceExperienceV2()?.shellKind === 'workspace_app_unavailable',
  );
  readonly businessShellActive = computed(() => {
    const experience = this.workspaceExperienceV2();
    return experience
      ? experience.business.active
      : this.configuredBusinessProfile() && (!this.admin() || this.preview());
  });

  readonly effective = computed<EffectiveNavigationProfile>(() => {
    const experience = this.workspaceExperienceV2();
    if (experience) {
      return {
        key: experience.business.configured ? 'business_end_user' : 'standard',
        configured: experience.business.configured,
        active: experience.business.active,
        preview: experience.business.preview,
        admin: experience.business.admin,
        defaultRoute: experience.homeRoute,
        primarySurfaces: [...experience.primarySurfaceIds],
        advancedAccess: experience.advancedAccess,
      };
    }

    const config = this.config();
    const configured = config.key === 'business_end_user';
    const configuredDefault = this.normalizeRoute(config.default_route) || DEFAULT_BUSINESS_ROUTE;
    const declaredSurfaces = Array.isArray(config.primary_surfaces) && config.primary_surfaces.length
      ? config.primary_surfaces.filter((item): item is string => typeof item === 'string' && item.trim().length > 0)
      : DEFAULT_BUSINESS_SURFACES;
    // Before app entitlements are enabled the business shell contract remains
    // exactly the historical three applications, even if a stale/partial
    // navigation_profile payload is present. The flag is the only boundary
    // allowed to make those links membership-specific.
    // A customer application's surface stays in its own families, whatever
    // the flags: the historical default lists ANDRITZ's apps for everyone.
    const primarySurfaces = (this.appEntitlementsEnabled()
      ? this.entitledBusinessSurfaces(declaredSurfaces)
      : [...DEFAULT_BUSINESS_SURFACES]
    ).filter((surfaceId) => surfaceOfferedToFamily(surfaceId, this.family()));
    const defaultRoute = this.appEntitlementsEnabled()
      ? this.entitledDefaultRoute(configuredDefault, primarySurfaces)
      : configuredDefault;
    const advancedAccess = this.normalizeAdvancedAccess(config.advanced_access);
    return {
      key: configured ? 'business_end_user' : 'standard',
      configured,
      active: this.businessShellActive(),
      preview: this.preview(),
      admin: this.admin(),
      defaultRoute,
      primarySurfaces,
      advancedAccess,
    };
  });

  setBusinessPreview(enabled: boolean): void {
    const slug = this.workspace.currentSlug();
    if (!slug) return;
    const next = new Set(this.previewSlugs());
    if (enabled) next.add(slug);
    else next.delete(slug);
    const value = [...next].sort();
    this.previewSlugs.set(value);
    localStorage.setItem(PREVIEW_STORAGE_KEY, JSON.stringify(value));
  }

  isBusinessAllowedPath(path: string): boolean {
    return pathAllowedBySurfaceIds(
      this.pathOnly(path),
      [...this.effective().primarySurfaces, 'account'],
    );
  }

  businessSurfaceEnabled(surfaceId: BusinessNavigationSurfaceId): boolean {
    return this.effective().primarySurfaces.includes(surfaceId);
  }

  resolveWorkspaceExperience(requestedRoute: string): WorkspaceExperienceV2 | null {
    const workspace = this.workspace.current();
    if (
      !workspace
      || (!this.workspaceExperienceV2Enabled() && !this.workspaceAppPlatformEnabled())
    ) return null;
    return resolveWorkspaceExperienceV2({
      workspace: {
        slug: workspace.slug,
        mode: workspace.mode,
        settings: workspace.settings,
        appEntitlements: workspace.app_entitlements,
        appRuntime: workspace.workspace_app_runtime,
      },
      scenario: {
        role: workspace.role,
        roleTemplate: workspace.role_template,
        businessPreview: this.preview(),
        requestedRoute,
      },
    });
  }

  businessProfileConfig(enabled: boolean): NavigationProfileConfig | null {
    if (!enabled) return null;
    return {
      key: 'business_end_user',
      default_route: DEFAULT_BUSINESS_ROUTE,
      primary_surfaces: DEFAULT_BUSINESS_SURFACES,
      advanced_access: 'admin_only',
    };
  }

  private normalizeRoute(value: unknown): string | null {
    if (typeof value !== 'string') return null;
    const trimmed = value.trim();
    return trimmed.startsWith('/') ? trimmed : null;
  }

  private normalizeAdvancedAccess(value: unknown): NavigationAdvancedAccess {
    return value === 'link' || value === 'hidden' || value === 'admin_only'
      ? value
      : 'admin_only';
  }

  private featureEnabled(feature: string): boolean {
    const raw = this.workspace.current()?.settings?.['features'];
    return Boolean(raw && typeof raw === 'object' && !Array.isArray(raw) && (
      raw as Record<string, unknown>
    )[feature] === true);
  }

  private entitledBusinessSurfaces(declaredSurfaces: readonly string[]): string[] {
    if (!this.appEntitlementsEnabled()) return [...declaredSurfaces];
    const grants = new Set(this.workspace.current()?.app_entitlements ?? []);
    const declared = new Set(declaredSurfaces);
    return BUSINESS_NAVIGATION_SURFACE_IDS.filter((surfaceId) =>
      grants.has(surfaceId) && declared.has(surfaceId));
  }

  private entitledDefaultRoute(configuredRoute: string, primarySurfaces: readonly string[]): string {
    if (pathAllowedBySurfaceIds(configuredRoute, [...primarySurfaces, 'account'])) {
      return configuredRoute;
    }
    const firstSurface = primarySurfaces[0];
    return firstSurface ? agentiumSurfaceRoute(firstSurface) : '/account/profile';
  }

  private pathOnly(value: string): string {
    return (value || '/').split('?')[0].split('#')[0] || '/';
  }

  private readPreviewSlugs(): string[] {
    try {
      const parsed = JSON.parse(localStorage.getItem(PREVIEW_STORAGE_KEY) || '[]');
      return Array.isArray(parsed)
        ? parsed.filter((item): item is string => typeof item === 'string')
        : [];
    } catch {
      return [];
    }
  }
}

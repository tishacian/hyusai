import { Injectable, computed, inject, signal } from '@angular/core';
import { WorkspaceService } from './workspace.service';

export type NavigationProfileKey = 'standard' | 'business_end_user';
export type NavigationAdvancedAccess = 'admin_only' | 'link' | 'hidden';

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

const DEFAULT_BUSINESS_ROUTE = '/chat';
const DEFAULT_BUSINESS_SURFACES = ['chat', 'client360-pdr', 'knowledge-capture'];
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
  readonly admin = computed(() => this.workspace.isAdmin());
  readonly preview = computed(() => {
    const slug = this.workspace.currentSlug();
    return Boolean(
      slug &&
      this.admin() &&
      this.configuredBusinessProfile() &&
      this.previewSlugs().includes(slug),
    );
  });
  readonly businessShellActive = computed(() =>
    this.configuredBusinessProfile() && (!this.admin() || this.preview()),
  );

  readonly effective = computed<EffectiveNavigationProfile>(() => {
    const config = this.config();
    const configured = config.key === 'business_end_user';
    const defaultRoute = this.normalizeRoute(config.default_route) || DEFAULT_BUSINESS_ROUTE;
    const primarySurfaces = Array.isArray(config.primary_surfaces) && config.primary_surfaces.length
      ? config.primary_surfaces.filter((item): item is string => typeof item === 'string' && item.trim().length > 0)
      : DEFAULT_BUSINESS_SURFACES;
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
    const normalized = this.pathOnly(path);
    return (
      normalized === '/chat' ||
      normalized === '/client360' ||
      normalized.startsWith('/client360/') ||
      normalized === '/knowledge/capture' ||
      normalized === '/account' ||
      normalized.startsWith('/account/')
    );
  }

  businessRedirectFor(path: string): string | null {
    if (!this.businessShellActive()) return null;
    const normalized = this.pathOnly(path);
    if (this.isBusinessAllowedPath(normalized)) return null;
    if (normalized === '/knowledge') return '/knowledge/capture';

    const systemCapture = normalized.match(/^\/systems\/([^/]+)\/capture$/);
    if (systemCapture?.[1]) {
      return `/knowledge/capture?systemId=${encodeURIComponent(systemCapture[1])}`;
    }

    return this.effective().defaultRoute;
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

/**
 * Optional tenant identity for the platform chrome.
 *
 * A workspace that declares a logo and a name carries its own brand in the
 * title bar and the browser tab, while keeping the platform navigation and its
 * vocabulary (Build, Operate, Flow Builder, Skills). Absent the setting, the
 * chrome stays Agentium, which is the case for every workspace but the ones
 * explicitly white-labelled.
 *
 * This is deliberately not `workspace_app_brand`: that key already means "brand
 * of the immersive workspace app" and is consumed by the Mission Room shell and
 * the governed workspace-experience projection.
 */

/** The name the product goes by when no tenant brand is declared. */
export const DEFAULT_BRAND_NAME = 'Agentium';

export interface PlatformBrand {
  label: string;
  emblem: string;
  /**
   * Optional second artwork for light surfaces. A customer wordmark is often
   * delivered as an opaque file drawn for a dark background; on a light chrome
   * it reads as a plate rather than a mark. A tenant that has a keyed-out or
   * light-surface variant declares it here and the chrome picks it up when the
   * resolved theme is light. Absent, the single `emblem` is used in both
   * themes, which is every other tenant's case.
   */
  emblemLight: string | null;
  /** Where the emblem returns to, typically the workspace's own business app. */
  home: string | null;
}

export function platformBrand(
  settings: Readonly<Record<string, unknown>> | null | undefined,
): PlatformBrand | null {
  const raw = settings?.['platform_brand'];
  if (raw === null || typeof raw !== 'object' || Array.isArray(raw)) return null;
  const declared = raw as Record<string, unknown>;
  const label = text(declared['label']);
  const emblem = text(declared['emblem']);
  // Half a brand is a mixed brand: a tenant name on our mark, or our name on a
  // tenant logo, is worse than no white-labelling at all.
  if (!label || !emblem) return null;
  const home = text(declared['home']);
  // Purely an alternate rendering of a brand that is already whole: it never
  // takes part in the completeness check above.
  const emblemLight = text(declared['emblem_light']);
  return { label, emblem, emblemLight, home: home?.startsWith('/') ? home : null };
}

function text(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

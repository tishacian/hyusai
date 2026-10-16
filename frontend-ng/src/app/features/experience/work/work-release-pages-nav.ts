import { localizeDocument, textFallback } from '../runtime/model';
import { liveHref, workPageHref } from './work-catalog';

/** A specialized host may serve one declared page at another segment of this app. */
export interface HostedWorkPage {
  pageId: string;
  routeSegment: string;
}

export interface WorkReleasePageLink {
  id: string;
  title: string;
  href: string;
  active: boolean;
}

function routeSegment(value: unknown): value is string {
  return typeof value === 'string' && !!value.trim() && value !== '.' && value !== '..';
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

function declaredPages(raw: unknown): Record<string, unknown>[] {
  return isRecord(raw) && Array.isArray(raw['pages'])
    ? raw['pages'].filter(page => isRecord(page) && routeSegment(page['id'])) : [];
}

/**
 * A release's live_href is its entry page, which is the first declared page.
 * A single same-app segment outside the declared pages may host that entry
 * with its own renderer. Real page destinations and external application
 * launches keep their existing meaning; they are never repurposed as hosts.
 */
export function hostedWorkPage(
  raw: unknown,
  slug: string,
  theme: Record<string, unknown> | null = null,
  explicit: HostedWorkPage | null = null,
): HostedWorkPage | null {
  const pages = declaredPages(raw);
  const pageIds = new Set(pages.map(page => page['id'] as string));
  const valid = (host: HostedWorkPage): boolean => pageIds.has(host.pageId)
    && routeSegment(host.routeSegment)
    && (!pageIds.has(host.routeSegment) || host.routeSegment === host.pageId);
  if (explicit) return valid(explicit) ? explicit : null;
  if (!routeSegment(slug) || !pages.length) return null;
  const href = liveHref(theme);
  const match = href?.match(/^\/work\/([^/?#;]+)\/([^/?#;]+)$/);
  if (!match) return null;
  try {
    const routeSlug = decodeURIComponent(match[1]!);
    const segment = decodeURIComponent(match[2]!);
    if (routeSlug !== slug || /[\u0000-\u001f\u007f/?#;\\%\s]/.test(segment)
      || segment === 'validations' || pageIds.has(segment)) return null;
    const host = { pageId: pages[0]!['id'] as string, routeSegment: segment };
    return valid(host) ? host : null;
  } catch {
    return null;
  }
}

/** Shared by the page menu, canonical entry redirects and creator return links. */
export function workReleasePageHref(slug: string, pageId: string, hostedPage: HostedWorkPage | null): string {
  return workPageHref(slug, hostedPage?.pageId === pageId ? hostedPage.routeSegment : pageId);
}

/** Navigation uses the resolved release, never a client-side list of app features. */
export function workReleasePageLinks(
  raw: unknown,
  slug: string,
  locale: string,
  activePage: string | null,
  hostedPage: HostedWorkPage | null = null,
  theme: Record<string, unknown> | null = null,
): WorkReleasePageLink[] {
  if (!routeSegment(slug) || !isRecord(raw) || !Array.isArray(raw['pages'])) return [];
  // The runtime can synthesize an id for preview. Navigation must not invent a
  // URL for a legacy page that never declared an address in its release.
  const explicitPages = declaredPages(raw);
  const document = localizeDocument({ ...raw, pages: explicitPages }, locale);
  const host = hostedWorkPage(raw, slug, theme, hostedPage);
  const seen = new Set<string>();
  return document.pages.filter(page => {
    if (seen.has(page.id)) return false;
    seen.add(page.id);
    return true;
  }).map(page => ({
    id: page.id,
    title: textFallback(page.title).trim() || page.id,
    href: workReleasePageHref(slug, page.id, host),
    active: page.id === activePage,
  }));
}

import { localizeDocument, textFallback } from '../runtime/model';
import { workPageHref } from './work-catalog';

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

/** Navigation uses the resolved release, never a client-side list of app features. */
export function workReleasePageLinks(
  raw: unknown,
  slug: string,
  locale: string,
  activePage: string | null,
  hostedPage: HostedWorkPage | null = null,
): WorkReleasePageLink[] {
  if (!routeSegment(slug) || !isRecord(raw) || !Array.isArray(raw['pages'])) return [];
  // The runtime can synthesize an id for preview. Navigation must not invent a
  // URL for a legacy page that never declared an address in its release.
  const explicitPages = raw['pages'].filter(page => isRecord(page) && routeSegment(page['id']));
  const document = localizeDocument({ ...raw, pages: explicitPages }, locale);
  const seen = new Set<string>();
  return document.pages.filter(page => {
    if (seen.has(page.id)) return false;
    seen.add(page.id);
    return true;
  }).map(page => ({
    id: page.id,
    title: textFallback(page.title).trim() || page.id,
    href: workPageHref(slug, hostedPage?.pageId === page.id && routeSegment(hostedPage.routeSegment)
      ? hostedPage.routeSegment : page.id),
    active: page.id === activePage,
  }));
}

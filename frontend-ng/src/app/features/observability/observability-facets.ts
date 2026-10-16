/** Observability facets live in `?facet=` (replaceUrl). Not separate routes. */
export const OBSERVABILITY_FACETS = [
  'operations',
  'activities',
  'quality',
  'performance',
  'traces',
] as const;

export type ObservabilityFacet = (typeof OBSERVABILITY_FACETS)[number];

export function isObservabilityFacet(value: string | null | undefined): value is ObservabilityFacet {
  return value != null && (OBSERVABILITY_FACETS as readonly string[]).includes(value);
}

export function normalizeObservabilityFacet(
  value: string | null | undefined,
): ObservabilityFacet {
  return isObservabilityFacet(value) ? value : 'operations';
}

/** Prefer `systemId` (L10); accept legacy `system_id` from Quality bookmarks. */
export function observabilitySystemId(
  params: { get(name: string): string | null },
): string {
  return params.get('systemId') || params.get('system_id') || '';
}

export function periodCutoffMs(since: string, now = Date.now()): number {
  const days = since === '24h' ? 1 : since === '30d' ? 30 : 7;
  return now - days * 24 * 60 * 60 * 1000;
}

export function runStartedWithinPeriod(
  startedAt: string | null | undefined,
  since: string,
  now = Date.now(),
): boolean {
  if (!startedAt) return false;
  const t = Date.parse(startedAt);
  return Number.isFinite(t) && t >= periodCutoffMs(since, now) && t < now;
}

/** Explicit quality/performance/traces win; historical activity links remain valid. */
export function resolveObservabilityFacet(params: { get(name: string): string | null }): ObservabilityFacet {
  const facet = normalizeObservabilityFacet(params.get('facet'));
  if (['quality', 'performance', 'traces'].includes(facet)) return facet;
  if (params.get('activityId') || (!params.get('facet') && params.get('scope'))) return 'activities';
  return facet;
}
export function observabilityPeriod(value: string | null): '24h' | '7d' | '30d' {
  return value === '24h' || value === '30d' ? value : '7d';
}
export function observabilityAnchor(value: string | null, fallback = new Date().toISOString()): string {
  const parsed = Date.parse(value || '');
  return Number.isFinite(parsed) ? new Date(parsed).toISOString() : fallback;
}

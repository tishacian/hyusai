/** Observability facets live in `?facet=` (replaceUrl). Not separate routes. */
export const OBSERVABILITY_FACETS = [
  'operations',
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
  const days = since === '30d' ? 30 : 7;
  return now - days * 24 * 60 * 60 * 1000;
}

export function runStartedWithinPeriod(
  startedAt: string | null | undefined,
  since: string,
  now = Date.now(),
): boolean {
  if (!startedAt) return false;
  const t = Date.parse(startedAt);
  return Number.isFinite(t) && t >= periodCutoffMs(since, now);
}

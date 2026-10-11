/** Pure redirect helpers for Observability legacy child paths → `?facet=`. */
export function observabilityFacetRedirectUrl(
  facet: 'quality' | 'performance' | 'traces',
  queryParams: Record<string, string | string[] | undefined | null>,
): { path: string; queryParams: Record<string, string> } {
  const next: Record<string, string> = { facet };
  for (const [key, value] of Object.entries(queryParams)) {
    if (value == null || key === 'facet') continue;
    next[key] = Array.isArray(value) ? String(value[0] ?? '') : String(value);
  }
  return { path: '/observability', queryParams: next };
}

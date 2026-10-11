/**
 * L19 — legacy Capture addresses → System / Collection Capture facets.
 */

export function systemCaptureFacetUrl(systemId: string): string {
  const id = encodeURIComponent(systemId.trim());
  return `/systems/${id}?facet=capture`;
}

export function collectionCaptureFacetUrl(
  collectionSlug: string,
  query: Record<string, string | null | undefined> = {},
): string {
  const slug = encodeURIComponent(collectionSlug.trim());
  const params = new URLSearchParams({ facet: 'documents', capture: '1' });
  for (const [key, value] of Object.entries(query)) {
    if (value == null || key === 'facet' || key === 'collection' || key === 'kbId') continue;
    params.set(key, value);
  }
  return `/knowledge/${slug}?${params.toString()}`;
}

/** Resolve a legacy `/knowledge/capture` query to a facet URL. */
export function knowledgeCaptureRedirectUrl(
  query: Record<string, string | null | undefined>,
): string | null {
  const systemId = String(query['systemId'] || query['system_id'] || '').trim();
  if (systemId) return systemCaptureFacetUrl(systemId);

  const collection = String(
    query['collection'] || query['collectionId'] || query['kbId'] || '',
  ).trim();
  if (collection) return collectionCaptureFacetUrl(collection, query);

  return null;
}

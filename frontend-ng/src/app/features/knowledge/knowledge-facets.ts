/**
 * L19 — Collection Knowledge facets (`?facet=`).
 * Eleven legacy tabs collapse into five FR/EN facets.
 */

export const KNOWLEDGE_FACETS = [
  'overview',
  'documents',
  'content',
  'usage',
  'graph',
] as const;

export type KnowledgeFacetId = (typeof KNOWLEDGE_FACETS)[number];

export const KNOWLEDGE_CONTENT_PANELS = [
  'chunks',
  'structure',
  'facts',
  'ocr',
  'table-facts',
] as const;

export type KnowledgeContentPanel = (typeof KNOWLEDGE_CONTENT_PANELS)[number];

/** Legacy tab / facet query values → L19 facet. */
const LEGACY_TO_FACET: Record<string, KnowledgeFacetId> = {
  overview: 'overview',
  diagnostics: 'overview',
  sources: 'documents',
  documents: 'documents',
  chunks: 'content',
  structure: 'content',
  facts: 'content',
  ocr: 'content',
  'table-facts': 'content',
  content: 'content',
  guides: 'usage',
  bindings: 'usage',
  usage: 'usage',
  graph: 'graph',
  capture: 'documents',
};

const LEGACY_TO_CONTENT: Record<string, KnowledgeContentPanel> = {
  chunks: 'chunks',
  structure: 'structure',
  facts: 'facts',
  ocr: 'ocr',
  'table-facts': 'table-facts',
};

export function isKnowledgeFacet(value: string | null | undefined): value is KnowledgeFacetId {
  return value != null && (KNOWLEDGE_FACETS as readonly string[]).includes(value);
}

export function normalizeKnowledgeFacet(
  value: string | null | undefined,
): KnowledgeFacetId {
  if (!value) return 'overview';
  return LEGACY_TO_FACET[value] ?? 'overview';
}

export function contentPanelFromLegacy(
  value: string | null | undefined,
): KnowledgeContentPanel | null {
  if (!value) return null;
  return LEGACY_TO_CONTENT[value] ?? null;
}

export function knowledgeFacetI18nKey(facet: KnowledgeFacetId): string {
  return `knowledge.facet.${facet}`;
}

export type CollectionIndexTone = 'success' | 'warning' | 'danger' | 'accent';

export function collectionIndexPresentation(status: string | null | undefined): {
  tone: CollectionIndexTone;
  labelKey: string;
} {
  const normalized = String(status || '')
    .trim()
    .toLowerCase();
  switch (normalized) {
    case 'ready':
    case 'indexed':
      return { tone: 'success', labelKey: 'knowledge.collections.indexed' };
    case 'queued':
    case 'running':
    case 'indexing':
    case 'building':
      return { tone: 'warning', labelKey: 'knowledge.collections.indexing' };
    case 'error':
    case 'failed':
      return { tone: 'danger', labelKey: 'knowledge.collections.index_error' };
    case 'created':
    case 'empty':
    case 'external_or_empty':
      return { tone: 'accent', labelKey: 'knowledge.collections.not_indexed' };
    default:
      return {
        tone: normalized ? 'accent' : 'accent',
        labelKey: normalized
          ? 'knowledge.collections.status_unknown'
          : 'knowledge.collections.not_indexed',
      };
  }
}

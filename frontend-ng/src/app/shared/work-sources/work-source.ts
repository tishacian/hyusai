/**
 * L36 — pure rules behind the Work source panel: what a cited source says
 * about itself, what the server confirmed about it, and how the reader moves
 * between an answer's sources. Kept free of Angular so the rules are tested
 * without an injector.
 *
 * Nothing is invented: a source the member can no longer read shows no
 * excerpt at all, and the page preview is offered only when the original
 * exists.
 */

/** A source as the answer stream sent it; every field may be missing. */
export interface CitedSourceLike {
  document_id?: unknown;
  title?: unknown;
  filename?: unknown;
  snippet?: unknown;
  content?: unknown;
  text?: unknown;
  collection?: unknown;
  collection_name?: unknown;
  page?: unknown;
  page_number?: unknown;
  chunk_index?: unknown;
  metadata?: Record<string, unknown> | null;
  [key: string]: unknown;
}

/** One of the answer's sources, numbered as the answer cites it. */
export interface WorkSourceRef {
  /** 1-based, the number of the citation marker. */
  n: number;
  documentId: string | null;
  /** Collection reference the requests use (slug or id). */
  collection: string | null;
  /** Collection name as the reader knows it, when the host knows better than the reference. */
  collectionLabel: string | null;
  title: string;
  filename: string | null;
  page: number | null;
  chunkIndex: number | null;
  /** The passage the answer was given, in full ('' when none was sent). */
  passage: string;
  cited: boolean;
}

/** `GET /documents/{id}/passage` — what the server confirms about a source. */
export interface CitedPassageResponse {
  document_id: string;
  filename: string | null;
  collection?: { id: string | null; slug: string | null; name: string | null } | null;
  passage?: { text: string; truncated?: boolean; chunk_index?: number | null; page?: number | null } | null;
  before?: string | null;
  after?: string | null;
  preview_available?: boolean;
}

export interface WorkSourcePreview {
  documentId: string;
  collection: string;
  filename: string | null;
  page: number | null;
  /** Text the viewer looks for to mark the passage on the page. */
  highlight: string | null;
}

export interface WorkSourceView {
  n: number;
  total: number;
  title: string;
  /** Upper-case file type (« PDF »), from the file name. */
  kind: string | null;
  page: number | null;
  collection: string | null;
  cited: boolean;
  passage: string | null;
  truncated: boolean;
  before: string | null;
  after: string | null;
  preview: WorkSourcePreview | null;
  /** The server could not be asked: the passage shown is the one the answer received. */
  unverified: boolean;
}

export type WorkSourceState =
  | { status: 'loading' }
  | { status: 'ready'; view: WorkSourceView }
  | { status: 'unavailable' };

function text(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

function positiveInt(value: unknown, min: number): number | null {
  if (value === null || value === undefined || value === '' || typeof value === 'boolean') return null;
  const number = typeof value === 'number' ? value : Number(String(value).trim());
  return Number.isInteger(number) && number >= min ? number : null;
}

/** « PDF », « DOCX »… from the file name; `null` without an extension. */
export function documentKind(filename: string | null | undefined): string | null {
  const match = /\.([a-z0-9]{1,6})$/i.exec(filename?.trim() ?? '');
  return match ? match[1]!.toUpperCase() : null;
}

/** Map one streamed source to what the panel needs, reading `metadata` as a fallback. */
export function workSourceRef(
  source: CitedSourceLike,
  n: number,
  options: { cited: boolean; collectionLabel?: string | null },
): WorkSourceRef {
  const meta = (source.metadata ?? {}) as Record<string, unknown>;
  const filename = text(source.filename) ?? text(meta['filename']) ?? text(meta['document_filename']) ?? text(source['document_filename']);
  const documentId = text(source.document_id) ?? text(meta['document_id']);
  return {
    n,
    documentId,
    collection: text(source.collection) ?? text(source.collection_name) ?? text(meta['collection']) ?? text(meta['collection_name']),
    collectionLabel: text(options.collectionLabel),
    title: text(source.title) ?? filename ?? text(meta['title']) ?? documentId ?? 'Source',
    filename,
    page: positiveInt(source.page ?? source.page_number ?? meta['page'] ?? meta['page_number'], 1),
    chunkIndex: positiveInt(source.chunk_index ?? meta['chunk_index'], 0),
    passage: text(source.snippet) ?? text(source.content) ?? text(source.text) ?? '',
    cited: options.cited,
  };
}

/** Query of the passage read; `null` when the source names no readable document. */
export function passageQuery(ref: WorkSourceRef): Record<string, string> | null {
  if (!ref.documentId || !ref.collection) return null;
  const params: Record<string, string> = { collection_name: ref.collection };
  if (ref.chunkIndex !== null) params['chunk_index'] = String(ref.chunkIndex);
  if (ref.page !== null) params['page'] = String(ref.page);
  const hint = ref.passage.replace(/\s+/g, ' ').trim().slice(0, 200);
  if (hint.length >= 12) params['hint'] = hint;
  return params;
}

/** Deleted, moved out of the member's reach, or never readable: say so, show nothing. */
export function isUnavailableStatus(status: number | null | undefined): boolean {
  return status === 403 || status === 404 || status === 410;
}

/**
 * What the panel shows for a source. With the server's answer, its passage,
 * neighbours, page and collection win; without it (`response === null`, the
 * read failed for another reason than access) the passage is the one the
 * answer was given, flagged as not verified, and no page is promised.
 */
export function workSourceView(ref: WorkSourceRef, total: number, response: CitedPassageResponse | null): WorkSourceView {
  const served = response?.passage?.text?.trim() || null;
  const passage = served ?? (ref.passage || null);
  const filename = response?.filename ?? ref.filename;
  const page = positiveInt(response?.passage?.page, 1) ?? ref.page;
  const collection = text(response?.collection?.name) ?? ref.collectionLabel ?? ref.collection;
  const previewable = !!response?.preview_available && !!ref.documentId && !!ref.collection;
  return {
    n: ref.n,
    total,
    title: ref.title !== ref.documentId || !filename ? ref.title : filename,
    kind: documentKind(filename ?? ref.title),
    page,
    collection,
    cited: ref.cited,
    passage,
    truncated: !!served && !!response?.passage?.truncated,
    // Neighbours only frame a passage the server itself located.
    before: served ? text(response?.before) : null,
    after: served ? text(response?.after) : null,
    preview: previewable
      ? {
          documentId: ref.documentId!,
          collection: ref.collection!,
          filename: filename ?? null,
          page,
          highlight: passage && passage.length >= 8 ? passage : null,
        }
      : null,
    unverified: response === null,
  };
}

/** « Source 2 sur 3 » and where previous / next lead (none past the ends). */
export function sourceStep(n: number, total: number): { n: number; total: number; previous: number | null; next: number | null } {
  const safeTotal = Math.max(0, Math.floor(total));
  const current = Math.min(Math.max(1, Math.floor(n)), Math.max(1, safeTotal));
  return {
    n: current,
    total: safeTotal,
    previous: current > 1 ? current - 1 : null,
    next: current < safeTotal ? current + 1 : null,
  };
}

/** Rich preview of the original, as the document viewer reads it (API-relative). */
export function previewPath(preview: WorkSourcePreview): string {
  let path = `/documents/${encodeURIComponent(preview.documentId)}/rich-preview?collection_name=${encodeURIComponent(preview.collection)}`;
  if (preview.filename) path += `&filename=${encodeURIComponent(preview.filename)}`;
  return path;
}

/** The original file, for « Ouvrir le document » (API-relative, read with the member's session). */
export function filePath(preview: WorkSourcePreview): string {
  let path = `/documents/${encodeURIComponent(preview.documentId)}/raw?collection_name=${encodeURIComponent(preview.collection)}&disposition=inline`;
  if (preview.filename) path += `&filename=${encodeURIComponent(preview.filename)}`;
  return path;
}

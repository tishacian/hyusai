/**
 * Locate a retrieval chunk/snippet inside the *rendered* text of a document
 * preview and mark it for highlighting.
 *
 * The snippet that reaches the frontend has been whitespace-collapsed by the
 * backend (``" ".join(value.split())``), truncated to ~1200 chars, and may end
 * with an ``...`` ellipsis. The preview content, on the other hand, keeps its
 * original whitespace and (for HTML) its markup. So we can never rely on an
 * exact substring match — every locator here works on a *normalized* view
 * (whitespace collapsed, lower-cased) and maps the hit back to the original
 * character offsets.
 */

export const HIGHLIGHT_CLASS = 'omnirag-hl';
/** id given to the first mark so the viewer can scroll it into view. */
export const HIGHLIGHT_ANCHOR_ID = 'omnirag-hl-anchor';

export interface MatchRange {
  /** inclusive start index in the original string */
  start: number;
  /** exclusive end index in the original string */
  end: number;
}

const TRAILING_ELLIPSIS = /(\.{3}|…)\s*$/;
const WHITESPACE = /\s/;

/** Drop the trailing ellipsis the backend appends to truncated snippets. */
export function cleanSnippet(snippet: string): string {
  return (snippet || '').replace(TRAILING_ELLIPSIS, '').trim();
}

function normalizeNeedle(needle: string): string {
  return cleanSnippet(needle).replace(/\s+/g, ' ').trim().toLowerCase();
}

/**
 * Whitespace-collapsed, lower-cased snippet used for cheap spreadsheet cell
 * containment checks (a cell is a hit when its trimmed text appears in here).
 */
export function normalizeNeedleForCells(snippet: string | null | undefined): string {
  return normalizeNeedle(snippet || '');
}

/** Whether a spreadsheet cell's text is part of the (already normalized) snippet. */
export function cellMatchesNeedle(cell: string, needleNorm: string): boolean {
  const value = (cell || '').replace(/\s+/g, ' ').trim().toLowerCase();
  return value.length >= 2 && needleNorm.length > 0 && needleNorm.includes(value);
}

/**
 * Leading phrase fed to the pdf.js find controller. A PDF text match cannot
 * straddle a page boundary, so we keep a short opening fragment (cut on a word
 * boundary) which is most likely to sit contiguously on the chunk's page, while
 * still being specific enough to land on the right passage.
 */
export function pdfFindPhrase(snippet: string | null | undefined, maxChars = 64): string {
  const norm = cleanSnippet(snippet || '').replace(/\s+/g, ' ').trim();
  if (norm.length <= maxChars) return norm;
  const cut = norm.slice(0, maxChars);
  const lastSpace = cut.lastIndexOf(' ');
  return lastSpace > 16 ? cut.slice(0, lastSpace) : cut;
}

/**
 * Build a whitespace-collapsed, lower-cased view of ``text`` together with a
 * map from each normalized index to the index of the corresponding character
 * in the ORIGINAL string. Whitespace runs collapse to a single space whose map
 * entry points at the first whitespace char of the run.
 */
function normalizeWithMap(text: string): { norm: string; map: number[] } {
  const out: string[] = [];
  const map: number[] = [];
  let inWhitespace = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (WHITESPACE.test(ch)) {
      if (!inWhitespace) {
        out.push(' ');
        map.push(i);
        inWhitespace = true;
      }
    } else {
      out.push(ch.toLowerCase());
      map.push(i);
      inWhitespace = false;
    }
  }
  return { norm: out.join(''), map };
}

/** Shortest normalized prefix we will accept as a confident anchor. */
const MIN_ANCHOR = 20;

/**
 * Find the chunk text inside ``haystack`` and return its range in the original
 * string, or ``null`` when no confident match exists.
 *
 * The snippet is often truncated and may diverge from the rendered text past
 * some point (different extraction, hyphenation, dropped markup). So instead of
 * requiring a full match we binary-search for the LONGEST leading prefix of the
 * snippet that occurs in the text — monotonic, since any prefix of a matching
 * prefix also matches — and highlight exactly that contiguous run. The longest
 * matching prefix is also the most specific anchor, which keeps us from latching
 * onto a coincidental short fragment elsewhere in the document.
 */
export function findSnippetRange(haystack: string, snippet: string): MatchRange | null {
  const needle = normalizeNeedle(snippet);
  if (needle.length < 8 || !haystack) return null;

  const { norm, map } = normalizeWithMap(haystack);
  if (!norm) return null;

  const minLen = Math.min(MIN_ANCHOR, needle.length);
  if (norm.indexOf(needle.slice(0, minLen)) === -1) return null;

  let lo = minLen;
  let hi = needle.length;
  let bestLen = minLen;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (norm.indexOf(needle.slice(0, mid)) !== -1) {
      bestLen = mid;
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }

  const normStart = norm.indexOf(needle.slice(0, bestLen));
  if (normStart === -1) return null;

  const start = map[normStart];
  const end = map[normStart + bestLen - 1] + 1;
  return { start, end: Math.max(end, start + 1) };
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

/**
 * Escape ``text`` for safe rendering and wrap the matched chunk range in a
 * ``<mark>`` carrying the highlight class + scroll anchor. Returns ``null``
 * when the chunk could not be located, so callers can fall back to the plain
 * (escaped) content.
 */
export function highlightPlainText(text: string, snippet?: string | null): string | null {
  if (!snippet) return null;
  const range = findSnippetRange(text, snippet);
  if (!range) return null;
  const before = escapeHtml(text.slice(0, range.start));
  const hit = escapeHtml(text.slice(range.start, range.end));
  const after = escapeHtml(text.slice(range.end));
  return `${before}<mark id="${HIGHLIGHT_ANCHOR_ID}" class="${HIGHLIGHT_CLASS}">${hit}</mark>${after}`;
}

/** Escape arbitrary text to HTML (no highlighting). */
export function escapeText(text: string): string {
  return escapeHtml(text);
}

/**
 * Walk the text nodes under ``root`` and wrap the chunk range in ``<mark>``
 * elements. The match may straddle element boundaries, so we emit one mark per
 * affected text node (the first one gets the scroll anchor id). Returns whether
 * at least one mark was created. Mutates ``root`` in place.
 */
export function markRangeInDom(root: Element, snippet: string | null | undefined, doc: Document): boolean {
  if (!snippet) return false;
  const walker = doc.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: (node: Node) => {
      const parent = (node as Text).parentElement;
      if (!parent) return NodeFilter.FILTER_REJECT;
      const tag = parent.tagName;
      if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'NOSCRIPT') return NodeFilter.FILTER_REJECT;
      if (!(node as Text).data) return NodeFilter.FILTER_REJECT;
      return NodeFilter.FILTER_ACCEPT;
    },
  });

  const nodes: Text[] = [];
  const starts: number[] = [];
  let combined = '';
  let current: Node | null;
  while ((current = walker.nextNode())) {
    const textNode = current as Text;
    starts.push(combined.length);
    nodes.push(textNode);
    combined += textNode.data;
  }
  if (!combined) return false;

  const range = findSnippetRange(combined, snippet);
  if (!range) return false;

  let created = false;
  for (let i = 0; i < nodes.length; i++) {
    const nodeStart = starts[i];
    const nodeEnd = nodeStart + nodes[i].data.length;
    const from = Math.max(range.start, nodeStart);
    const to = Math.min(range.end, nodeEnd);
    if (from >= to) continue;

    const textNode = nodes[i];
    const middle = textNode.splitText(from - nodeStart);
    middle.splitText(to - from);
    const mark = doc.createElement('mark');
    mark.className = HIGHLIGHT_CLASS;
    if (!created) {
      mark.id = HIGHLIGHT_ANCHOR_ID;
      created = true;
    }
    middle.parentNode?.insertBefore(mark, middle);
    mark.appendChild(middle);
  }
  return created;
}

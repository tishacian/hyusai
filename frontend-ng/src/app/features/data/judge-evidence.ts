/**
 * Readable form of a Judge citation.
 *
 * Citations are exact slices of the evidence the Judge read. Data evidence is
 * serialised JSON (whole objects or fragments carrying document ids, hashes
 * and chunk indexes). The reader needs the words or the facts; the exact
 * slice stays available in a technical fold, unchanged.
 */
export interface ReadableQuote {
  /** Prose to show, when the citation is text. */
  text: string | null;
  /** Label/value facts, when the citation is structured data. */
  fields: Array<{ label: string; value: string }>;
  /** True when the readable form differs from the exact slice. */
  transformed: boolean;
}

/** Plumbing keys a reader never needs in the primary view. */
const TECHNICAL_KEYS = /^(id|document_id|chunk_index|chunk_id|sha256|digest|collection|source|page|version|asset_ref|evidence_id|start|end|score|_.*)$/i;
const PROSE_KEYS = ['content', 'text', 'quote', 'passage', 'excerpt'];
const MAX_FIELDS = 12;

function scalar(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value === 'string') return value.trim() || null;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return null;
}

function label(path: string[]): string {
  return path.filter((part) => !/^\d+$/.test(part)).map((part) => part.replace(/^\/data\//, '').replace(/_/g, ' ')).join(' · ');
}

function collect(value: unknown, path: string[], out: ReadableQuote['fields']): void {
  if (out.length >= MAX_FIELDS) return;
  const leaf = scalar(value);
  if (leaf !== null) {
    const key = path[path.length - 1] ?? '';
    if (!TECHNICAL_KEYS.test(key)) out.push({ label: label(path) || '·', value: leaf });
    return;
  }
  if (Array.isArray(value)) {
    value.forEach((item, index) => collect(item, [...path, String(index)], out));
    return;
  }
  if (value && typeof value === 'object') {
    for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
      if (TECHNICAL_KEYS.test(key)) continue;
      collect(item, [...path, key], out);
    }
  }
}

/** Prose values of `"content": "..."` style keys inside a JSON fragment. */
function proseFromFragment(quote: string): string | null {
  const parts: string[] = [];
  for (const key of PROSE_KEYS) {
    const pattern = new RegExp(`"${key}"\\s*:\\s*"((?:[^"\\\\]|\\\\.)*)"?`, 'g');
    for (const match of quote.matchAll(pattern)) {
      try { parts.push(JSON.parse(`"${match[1]}"`)); } catch { parts.push(match[1]); }
    }
  }
  const text = parts.map((part) => part.trim()).filter(Boolean).join(' … ');
  return text || null;
}

export function readableQuote(quote: string | null | undefined): ReadableQuote {
  const raw = (quote ?? '').trim();
  if (!raw) return { text: null, fields: [], transformed: false };
  if (raw.startsWith('{') || raw.startsWith('[')) {
    try {
      const parsed = JSON.parse(raw) as unknown;
      const fields: ReadableQuote['fields'] = [];
      collect(parsed, [], fields);
      const prose = fields.filter((field) => PROSE_KEYS.some((key) => field.label.endsWith(key)));
      if (prose.length === fields.length && prose.length) {
        return { text: prose.map((field) => field.value).join(' … '), fields: [], transformed: true };
      }
      if (fields.length) return { text: null, fields, transformed: true };
    } catch {
      // A fragment: fall through to prose extraction.
    }
  }
  if (/"[a-z_/]+"\s*:/.test(raw)) {
    const prose = proseFromFragment(raw);
    if (prose) return { text: prose, fields: [], transformed: true };
    const outside = raw.replace(/"[^"]*"\s*:\s*("(?:[^"\\]|\\.)*"|[\d.]+|true|false|null)\s*,?/g, ' ').replace(/[{}[\]]/g, ' ').replace(/\s+/g, ' ').trim();
    if (outside && outside !== raw) return { text: outside, fields: [], transformed: true };
  }
  return { text: raw, fields: [], transformed: false };
}

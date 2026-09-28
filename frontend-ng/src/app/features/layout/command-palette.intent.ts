/**
 * ⌘K entry by intention (L27) — the palette's pure rules.
 *
 * - A query that matches no command still gets one actionable row, « Ask the
 *   agent », first and therefore selected: Enter hands the words to the chat.
 * - A query that names a lexicon term gets « What is {term}? » rows whose
 *   secondary line is the lexicon definition, readable in place.
 *
 * Dependency-free apart from the lexicon (itself dependency-free), so the
 * palette never drags the i18n dictionaries anywhere new and the rules run
 * in plain Node.
 */
import { UI_LEXICON, type LexiconEntry } from '@app/core/i18n.lexicon';

export type PaletteLocale = 'fr' | 'en';

export interface LexiconMatch {
  readonly id: string;
  /** Term in the reader's locale, as the lexicon capitalises it. */
  readonly term: string;
  /** One-line definition in the reader's locale. */
  readonly definition: string;
}

export const LEXICON_ROWS_MAX = 3;

/** Lowercase, no diacritics, typographic apostrophes folded, spaces collapsed. */
export function normalizePaletteQuery(value: string): string {
  return value
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[’‘`]/g, "'")
    .toLowerCase()
    .replace(/\s+/g, ' ')
    .trim();
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * How well a normalized query names a normalized term; 0 = no match.
 * 4 exact · 3 the term starts with the query · 2 the query contains the term
 * as a word (a question such as « qu'est-ce qu'un flow ») · 1 the term
 * contains the query (3 characters or more).
 */
function matchScore(query: string, term: string): number {
  if (!query || !term) return 0;
  if (query === term || query === `${term}s`) return 4;
  if (term.startsWith(query)) return 3;
  if (term.length >= 3) {
    const word = new RegExp(`(^|[^a-z0-9])${escapeRegExp(term)}s?([^a-z0-9]|$)`);
    if (word.test(query)) return 2;
  }
  if (query.length >= 3 && term.includes(query)) return 1;
  return 0;
}

/** Lexicon terms (FR or EN) named by the query, best first. */
export function lexiconMatches(
  query: string,
  locale: PaletteLocale,
  lexicon: readonly LexiconEntry[] = UI_LEXICON,
  limit = LEXICON_ROWS_MAX,
): LexiconMatch[] {
  const q = normalizePaletteQuery(query);
  if (q.length < 2) return [];
  const scored: Array<{ entry: LexiconEntry; score: number; order: number }> = [];
  lexicon.forEach((entry, order) => {
    const score = Math.max(
      matchScore(q, normalizePaletteQuery(entry.en)),
      matchScore(q, normalizePaletteQuery(entry.fr)),
    );
    if (score > 0) scored.push({ entry, score, order });
  });
  // A loose « contains » match only counts when nothing names a term better:
  // « skill » means Skill, not « Wrap a core skill ».
  const best = scored.reduce((max, item) => Math.max(max, item.score), 0);
  return scored
    .filter((item) => best < 2 || item.score >= 2)
    .sort((a, b) => b.score - a.score || a.order - b.order)
    .slice(0, limit)
    .map(({ entry }) => ({
      id: entry.id,
      term: locale === 'fr' ? entry.fr : entry.en,
      definition: locale === 'fr' ? entry.definition.fr : entry.definition.en,
    }));
}

/** French elides « que » before a vowel: « Qu'est-ce qu'Impact ? ». */
export function frenchElides(term: string): boolean {
  return /^[aeiouyàâäéèêëîïôöùûü]/i.test(term.trim());
}

/**
 * Order of the palette rows.
 *
 * - Empty query: every command, capped.
 * - No command matches: the agent row first (selected by default, so Enter
 *   asks the agent), then any lexicon rows.
 * - Otherwise: the matching commands first (Enter keeps doing what experts
 *   expect), the lexicon rows last but never cut by the cap.
 */
export function composePaletteResults<T>(
  query: string,
  matches: readonly T[],
  definitions: readonly T[],
  ask: T | null,
  cap = 40,
): T[] {
  if (!query.trim()) return matches.slice(0, cap);
  if (matches.length === 0) return [...(ask ? [ask] : []), ...definitions].slice(0, cap);
  return [...matches.slice(0, Math.max(0, cap - definitions.length)), ...definitions];
}

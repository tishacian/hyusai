/**
 * Pure view-model for the Flow Builder palette.
 *
 * The palette used to answer "what exists on this platform" — 79 skills plus
 * the primitives, every section expanded, three lines of identity per row. It
 * now answers "what goes here", which needs three decisions kept out of the
 * component so they can be regression-tested without a DOM:
 *
 *   1. **Disclosure levels** mirroring the canonical layers
 *      (`docs/mental-model.md` §4): Capabilities are layer 1, so they are the
 *      default surface; the Skills of one Capability are the drill-in; the
 *      whole registry is layer 3, reachable under Advanced.
 *   2. **Ranking** — one ranked, searchable list (the shell command-palette
 *      motif) instead of a column to scroll, with real workspace invocation
 *      counts as the tiebreaker.
 *   3. **Honest exclusion** — `/skills?include_filtered=true` returns the rows
 *      this workspace cannot see with the rule that excluded each one, so an
 *      empty result explains itself instead of rendering nothing.
 */
import {
  SKILL_PALETTE_CATEGORIES,
  type PaletteItem,
  type SkillPaletteSection,
} from './flow.types';
import type { PreconnectSide } from './flow-preconnect';

/** Where an insertion is being made from, when the palette is contextual. */
export interface PaletteInsertContext {
  /** Which side of the *candidate* node has to accept the connection. */
  side: PreconnectSide;
  /** Schema of the originating port (undefined = implicit, accepts anything). */
  schema?: string;
  /** Label of the node the insertion extends. */
  originLabel: string;
  /** Name of the originating port, when it is an explicit one. */
  originPort?: string;
}

export interface PaletteCapabilityGroup {
  slug: string;
  name: string;
  /** One-line intent shown under the name; may be empty. */
  hint: string;
  items: PaletteItem[];
  /** Summed workspace invocations of the Skills this Capability carries. */
  usageCalls: number;
}

export interface SkillPaletteSectionView {
  category: SkillPaletteSection;
  items: PaletteItem[];
}

/** Minimal shape the palette needs of a Capability row. */
export interface PaletteCapabilitySource {
  slug: string;
  name: string;
  description?: string;
}

/** Group holding the Skills no visible Capability claims. They are reachable
 * here because a workspace override or workspace ownership made them visible,
 * which is exactly the case the Capability layer cannot express. */
export const UNCARRIED_CAPABILITY_SLUG = '__uncarried__';

export function paletteItemSlug(item: PaletteItem): string {
  const slug = item.config?.['skill_slug'];
  return typeof slug === 'string' ? slug : item.type;
}

export function paletteItemUsage(item: PaletteItem): number {
  return item.usageCalls ?? 0;
}

/** Most-used first, then alphabetical. With no invocations anywhere — the
 * common case on a young workspace — this degrades to plain alphabetical. */
function byUsageThenLabel(a: PaletteItem, b: PaletteItem): number {
  return paletteItemUsage(b) - paletteItemUsage(a) || a.label.localeCompare(b.label);
}

function matchScore(haystack: string | undefined, needle: string): number {
  if (!haystack) return 0;
  const hay = haystack.toLowerCase();
  const at = hay.indexOf(needle);
  if (at < 0) return 0;
  if (hay === needle) return 4;
  if (at === 0) return 3;
  return /[\s._\-/]/.test(hay.charAt(at - 1)) ? 2 : 1;
}

function bestScore(values: readonly string[], needle: string): number {
  let best = 0;
  for (const value of values) best = Math.max(best, matchScore(value, needle));
  return best;
}

/**
 * Score one entry against one token. The weights order the fields by how much
 * each says about intent: the name and the slug identify, the taxonomy and the
 * carrying Capability situate, the description only corroborates.
 */
function tokenScore(item: PaletteItem, token: string): number {
  return (
    25 * matchScore(item.label, token) +
    12 * matchScore(paletteItemSlug(item), token) +
    6 * matchScore(item.skillCategory, token) +
    6 * bestScore(item.capabilitySlugs ?? [], token) +
    3 * matchScore(item.description, token) +
    2 * matchScore(item.runtimeStatus ?? item.badge, token)
  );
}

/** Every token must match somewhere, so "search doc" narrows instead of
 * widening. Returns 0 when the entry is not a match at all. */
export function scorePaletteItem(item: PaletteItem, query: string): number {
  const tokens = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (tokens.length === 0) return 0;
  let total = 0;
  for (const token of tokens) {
    const score = tokenScore(item, token);
    if (score === 0) return 0;
    total += score;
  }
  return total;
}

/** Ranked search over one entry set. Ties break on real workspace usage. */
export function searchPaletteItems(
  items: readonly PaletteItem[],
  query: string,
): PaletteItem[] {
  const scored: Array<{ item: PaletteItem; score: number }> = [];
  for (const item of items) {
    const score = scorePaletteItem(item, query);
    if (score > 0) scored.push({ item, score });
  }
  return scored
    .sort((a, b) => b.score - a.score || byUsageThenLabel(a.item, b.item))
    .map((entry) => entry.item);
}

/** Level 1: the Capabilities that actually carry something here. A Capability
 * carrying no visible Skill is not rendered — an empty bucket is the same
 * catalog-inventory problem in another shape. */
export function buildCapabilityGroups(
  items: readonly PaletteItem[],
  capabilities: readonly PaletteCapabilitySource[],
): PaletteCapabilityGroup[] {
  const known = new Map(capabilities.map((cap) => [cap.slug, cap]));
  const grouped = new Map<string, PaletteItem[]>();
  for (const item of items) {
    const carriers = item.capabilitySlugs ?? [];
    if (carriers.length === 0) {
      grouped.set(UNCARRIED_CAPABILITY_SLUG, [
        ...(grouped.get(UNCARRIED_CAPABILITY_SLUG) ?? []),
        item,
      ]);
      continue;
    }
    for (const slug of carriers) {
      grouped.set(slug, [...(grouped.get(slug) ?? []), item]);
    }
  }

  const groups: PaletteCapabilityGroup[] = [];
  for (const [slug, groupItems] of grouped) {
    const source = known.get(slug);
    const uncarried = slug === UNCARRIED_CAPABILITY_SLUG;
    groups.push({
      slug,
      name: uncarried ? 'No capability' : source?.name || humanizeSlug(slug),
      hint: uncarried
        ? 'Visible here without a capability carrying them'
        : (source?.description ?? '').trim(),
      items: [...groupItems].sort(byUsageThenLabel),
      usageCalls: groupItems.reduce((total, item) => total + paletteItemUsage(item), 0),
    });
  }
  return groups.sort((a, b) => {
    if (a.slug === UNCARRIED_CAPABILITY_SLUG) return 1;
    if (b.slug === UNCARRIED_CAPABILITY_SLUG) return -1;
    return b.usageCalls - a.usageCalls || a.name.localeCompare(b.name);
  });
}

export function humanizeSlug(slug: string): string {
  const words = slug.replace(/[_\-.]+/g, ' ').trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : slug;
}

/** Level 3: the full registry in canonical taxonomy order. `Other` is
 * appended only when the set contains uncategorised Skills, and empty
 * categories are dropped. */
export function buildSkillPaletteSections(
  items: readonly PaletteItem[],
): SkillPaletteSectionView[] {
  const categories: SkillPaletteSection[] = [...SKILL_PALETTE_CATEGORIES, 'Other'];
  return categories
    .map((category) => ({
      category,
      items: items
        .filter((item) => (item.skillCategory ?? 'Other') === category)
        .sort(byUsageThenLabel),
    }))
    .filter((section) => section.items.length > 0);
}

/** The shortcut list: what this workspace has actually run. Empty when there
 * is no invocation signal at all, so the section disappears rather than
 * dressing up zeros as a ranking. */
export function mostUsedItems(
  items: readonly PaletteItem[],
  limit: number,
): PaletteItem[] {
  return items
    .filter((item) => paletteItemUsage(item) > 0)
    .sort(byUsageThenLabel)
    .slice(0, limit);
}

/**
 * Turn a backend visibility reason into a sentence.
 *
 * `no_visible_capability` covers two different situations that the `/skills`
 * payload cannot separate: an industry tier this workspace has not enabled
 * (most of them) and a Skill no Capability claims at all. Saying both is the
 * honest reading; the curation surface decomposes it per lever.
 */
export function explainVisibilityReason(reason: string): string {
  switch (reason) {
    case 'no_visible_capability':
      return 'no capability enabled here carries it — usually an industry this workspace has not enabled, sometimes a skill no capability claims at all';
    case 'hidden_override':
      return 'hidden by this workspace’s catalog settings';
    case 'other_workspace':
      return 'defined by another workspace';
    default:
      return reason.replace(/_/g, ' ');
  }
}

/** One sentence for a whole filtered set, from the `catalog.filtered_reasons`
 * histogram the endpoint already returns. */
export function summariseFilteredReasons(reasons: Record<string, number>): string {
  const entries = Object.entries(reasons)
    .filter(([, count]) => count > 0)
    .sort((a, b) => b[1] - a[1]);
  if (entries.length === 0) return '';
  return entries
    .map(([reason, count]) => `${count} because ${explainVisibilityReason(reason)}`)
    .join('; ');
}

/** Hover detail: the operational metadata that used to occupy every row. */
export function paletteItemDetail(item: PaletteItem): string {
  const parts = [item.label, paletteItemSlug(item)];
  if (item.runtimeStatus) parts.push(`runtime ${item.runtimeStatus.replace(/_/g, ' ')}`);
  const usage = paletteItemUsage(item);
  if (usage > 0) parts.push(`${usage} workspace call${usage === 1 ? '' : 's'}`);
  if (item.description && item.description !== paletteItemSlug(item)) {
    parts.push(item.description);
  }
  if (item.unavailableReason) {
    parts.push(`unavailable: ${explainVisibilityReason(item.unavailableReason)}`);
  }
  return parts.join(' · ');
}

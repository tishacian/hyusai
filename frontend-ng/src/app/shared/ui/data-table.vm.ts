/**
 * Tabular rendering contract and its presentation logic, free of Angular.
 *
 * `<ck-data-table>`, the dataset schema tab and every workshop preview read the
 * same numbers, so the mapping from a backend column profile to drawable bars
 * lives here once and is unit-testable without a component harness (see
 * `data-table.vm.spec.ts`).
 *
 * The shapes mirror what the backend's `profile_frame` emits; nothing here
 * recomputes statistics client-side.
 */

export type TabularColumnKind =
  | 'integer'
  | 'float'
  | 'boolean'
  | 'datetime'
  | 'string'
  | 'other';

export interface TabularColumn {
  name: string;
  kind: TabularColumnKind;
  dtype?: string;
  nullable?: boolean;
}

export interface TabularHistogramBin {
  upper: number | null;
  count: number;
}

export interface TabularTopValue {
  value: string | number | boolean | null;
  count: number;
}

export interface TabularColumnStats {
  kind?: TabularColumnKind;
  nulls?: number;
  null_ratio?: number;
  distinct?: number;
  min?: number | string | null;
  max?: number | string | null;
  mean?: number | null;
  std?: number | null;
  histogram?: TabularHistogramBin[];
  top_values?: TabularTopValue[];
}

export type TabularRow = Record<string, unknown>;

export const NUMERIC_COLUMN_KINDS: readonly TabularColumnKind[] = ['integer', 'float'];

/** Glyph shown next to a column name so a schema is readable at a glance. */
export const COLUMN_KIND_GLYPH: Record<TabularColumnKind, string> = {
  integer: '#',
  float: '#.',
  boolean: '01',
  datetime: '⏱',
  string: 'Ab',
  other: '{}',
};

/** One drawable bar of a column profile. */
export interface ProfileBar {
  /** Percentage of the tallest bucket, floored so an empty bucket still reads. */
  height: number;
  title: string;
}

export function isNumericKind(kind: TabularColumnKind | undefined): boolean {
  return !!kind && NUMERIC_COLUMN_KINDS.includes(kind);
}

/**
 * Turn a column profile into normalized bars.
 *
 * Numeric columns draw their histogram (distribution shape); everything else
 * draws its top values (cardinality shape). Heights are relative to the tallest
 * bucket so a sparkline stays readable whatever the absolute counts, with a 6%
 * floor so a zero bucket still reads as a bucket rather than a gap.
 */
export function profileBars(
  stats: TabularColumnStats | null | undefined,
  numeric: boolean,
  nullLabel = 'null',
): ProfileBar[] {
  if (!stats) return [];
  const source = numeric
    ? (stats.histogram ?? []).map((bin) => ({
        count: bin.count,
        label: bin.upper === null || bin.upper === undefined ? '—' : `≤ ${bin.upper}`,
      }))
    : (stats.top_values ?? []).map((entry) => ({
        count: entry.count,
        label:
          entry.value === null || entry.value === undefined
            ? nullLabel
            : String(entry.value),
      }));
  if (!source.length) return [];
  const peak = Math.max(...source.map((item) => item.count), 1);
  return source.map((item) => ({
    height: Math.max(6, Math.round((item.count / peak) * 100)),
    title: `${item.label} · ${item.count}`,
  }));
}

/** Percentage of null cells, rounded for display (0 when the column is clean). */
export function nullPercent(stats: TabularColumnStats | null | undefined): number {
  if (!stats?.null_ratio) return 0;
  return Math.round(stats.null_ratio * 100);
}

/**
 * Human-readable byte size. The UI shows volumes, never raw byte counts, and
 * keeps one decimal below 10 units so "1.4 MB" doesn't collapse to "1 MB".
 */
export function formatBytes(bytes: number | null | undefined, locale = 'fr'): string {
  if (bytes === null || bytes === undefined) return '—';
  if (bytes < 1024) return `${bytes} B`;
  const units = ['kB', 'MB', 'GB', 'TB'];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const digits = value < 10 ? 1 : 0;
  return `${value.toLocaleString(locale, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })} ${units[unit]}`;
}

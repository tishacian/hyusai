export type CkChartTone = 'ink' | 'declared' | 'negative' | 'muted';

export type CkStreamTone = 'ink' | 'ink-soft' | 'declared' | 'declared-soft';

export interface CkChartTick {
  index: number;
  label: string;
  anchor?: 'start' | 'middle' | 'end';
}

/**
 * The four inks of the chart grammar, as `--ck-data-*` tokens. Declared is
 * the primary colour, so a declared mark never relies on it alone: see
 * `ckChartIsDeclared` and the patterns below.
 */
export function ckChartToneVar(tone: CkChartTone | CkStreamTone): string {
  switch (tone) {
    case 'declared':
    case 'declared-soft':
      return 'var(--ck-data-declared)';
    case 'negative':
      return 'var(--ck-data-zero)';
    case 'muted':
      return 'var(--ck-data-muted)';
    default:
      return 'var(--ck-data-measured)';
  }
}

/** True for every tone that paints an estimated (declared) quantity. */
export function ckChartIsDeclared(tone: CkChartTone | CkStreamTone | null | undefined): boolean {
  return tone === 'declared' || tone === 'declared-soft';
}

/**
 * Declared hatch for areas: 1.5-unit lines of the declared ink every 10 user
 * units, tilted 45° (the soft variant tilts -45° so two declared neighbours
 * stay apart). L28 opened it from 2 every 6: on the rivers and the Flux value
 * ribbon the denser hatch read as zebra noise. At 45° a 1.5-unit line still
 * fully covers one device pixel in the worst phase at 1x (≥ 90 % coverage),
 * so its core keeps the ink. The tint under the hatch stays at or below 0.18
 * so the lines keep 3:1 on it in both themes (worst case, light theme at 1x:
 * 3.35:1 computed, see docs/hypervisor-v2-chart-grammar.md).
 */
export const CK_DECLARED_HATCH_PERIOD = 10;
export const CK_DECLARED_HATCH_WIDTH = 1.5;

/**
 * Declared dashes for strokes and bars, where a hatch would not read. `BOLD`
 * is for a round-capped 5-unit stroke: each dash becomes a short pill and each
 * gap stays open. `THIN` is for hairlines and for narrow bars (butt caps).
 */
export const CK_DECLARED_DASH_BOLD = '1 8';
export const CK_DECLARED_DASH_THIN = '3 2.5';

export function ckChartUid(prefix: string): string {
  return `${prefix}-${Math.random().toString(36).slice(2, 10)}`;
}

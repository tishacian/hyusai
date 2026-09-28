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
 * Declared hatch for areas: 2-unit lines of the declared ink every 6 user
 * units, tilted 45° (the soft variant tilts -45° so two declared neighbours
 * stay apart). A thinner line loses its core to anti-aliasing at 1x. The tint
 * under the hatch stays at or below 0.22 so the lines keep 3:1 on it in both
 * themes, measured on the rendered page at 1x and 2x.
 */
export const CK_DECLARED_HATCH_PERIOD = 6;
export const CK_DECLARED_HATCH_WIDTH = 2;

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

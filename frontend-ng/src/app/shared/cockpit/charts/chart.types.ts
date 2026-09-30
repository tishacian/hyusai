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
 * Declared hatch for areas: 1-unit lines of the declared ink every 6 user
 * units, always tilted 45°. The charts draw one viewBox unit per CSS pixel
 * (fluid charts track the host width), so this is a 1 px hairline on a 6 px
 * period on screen. Every declared layer shares the same direction and phase:
 * the 1.5-every-10 hatch with alternating ±45° read as chunky chevrons where
 * two declared layers met. Neighbours are told apart by their tint, a 1 px gap
 * and a 1 px top edge instead (see the stream chart). The hatch is a texture;
 * the meaning is carried by the legend text and `◐`.
 */
export const CK_DECLARED_HATCH_PERIOD = 6;
export const CK_DECLARED_HATCH_WIDTH = 1;

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

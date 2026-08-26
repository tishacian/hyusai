/**
 * The numbers behind the data plane's charts — Angular-free, so they are
 * testable as arithmetic rather than through a rendered component.
 *
 * This module and the components beside it are the *kit*: every chart the data
 * and model surfaces draw comes from here, so a curve on a model card and a
 * curve on a comparison view are the same drawing with different numbers rather
 * than two implementations that drift.
 *
 * Two rendering technologies, chosen per shape rather than uniformly. Curves go
 * through chart.js, which is already in the bundle: they are the plots a viewer
 * interrogates — hovering a ROC to read the operating point it stands for is the
 * question an audience actually asks — and hit-testing a hundred points is what
 * a charting library is for. The confusion matrix and the bar lists are DOM,
 * because a heatmap of four cells and a ranked list of bars are laid out better
 * by CSS grid than by a canvas, and neither has anything to hover for.
 *
 * What lives here either has no home in chart.js (`curveDomain`, for axes in a
 * target's own units) or has to survive a canvas, where `var()` and
 * `color-mix()` do not resolve — hence `tokenAlpha`.
 */

// ---------------------------------------------------------------------------
// Curves
// ---------------------------------------------------------------------------

/** One point of a curve, in the curve's own units. */
export interface CurvePoint {
  x: number;
  y: number;
}

export interface CurveDomain {
  minX: number;
  maxX: number;
  minY: number;
  maxY: number;
}

/** ROC and precision/recall both live in the unit square. */
export const UNIT_DOMAIN: CurveDomain = { minX: 0, maxX: 1, minY: 0, maxY: 1 };

/**
 * The box a set of series fits in, padded to never be degenerate.
 *
 * Needed for the regression fit chart, whose axes are in the target's units:
 * a chart of ARPU predictions cannot assume the unit square the way a ROC can.
 */
export function curveDomain(series: readonly (readonly CurvePoint[])[]): CurveDomain {
  const points = series
    .flat()
    .filter((point) => point && Number.isFinite(point.x) && Number.isFinite(point.y));
  if (!points.length) return UNIT_DOMAIN;
  const xs = points.map((point) => point.x);
  const ys = points.map((point) => point.y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  return {
    minX,
    maxX: maxX > minX ? maxX : minX + 1,
    minY,
    maxY: maxY > minY ? maxY : minY + 1,
  };
}

/**
 * The points a curve can actually be drawn from.
 *
 * Fewer than two survivors returns empty rather than a single point: chart.js
 * would render that one point as a dot, and a dot on an otherwise empty ROC
 * reads as a measurement instead of as missing data.
 */
export function curveSeries(
  points: readonly CurvePoint[] | undefined,
): CurvePoint[] {
  const usable = (points ?? []).filter(
    (point) => point && Number.isFinite(point.x) && Number.isFinite(point.y),
  );
  return usable.length < 2 ? [] : usable.map((point) => ({ x: point.x, y: point.y }));
}

/** What a curve is judged against, in the curve's own units. */
export type CurveReference =
  /** The diagonal of a coin flip, corner to corner. A ROC's baseline. */
  | { kind: 'diagonal' }
  /** A horizontal line — precision at the prevalence of the positive class. */
  | { kind: 'level'; value: number | null }
  /** Another series entirely, as a regression fit is judged against identity. */
  | { kind: 'series'; points: readonly CurvePoint[] }
  | { kind: 'none' };

/**
 * The reference as two or more points, ready to be a second dataset.
 *
 * The reference is not decoration. A ROC without its diagonal cannot be read at
 * all — the shape alone says nothing about whether the model beats chance — and
 * a precision/recall curve without the prevalence line flatters every
 * imbalanced problem. A level outside the visible range is dropped rather than
 * clamped to an edge, where it would claim a value it does not have.
 */
export function referenceSeries(
  reference: CurveReference,
  domain: CurveDomain = UNIT_DOMAIN,
): CurvePoint[] {
  switch (reference.kind) {
    case 'diagonal':
      return [
        { x: domain.minX, y: domain.minY },
        { x: domain.maxX, y: domain.maxY },
      ];
    case 'level': {
      const value = reference.value;
      if (value === null || value === undefined || !Number.isFinite(value)) return [];
      if (value < domain.minY || value > domain.maxY) return [];
      return [
        { x: domain.minX, y: value },
        { x: domain.maxX, y: value },
      ];
    }
    case 'series':
      return curveSeries(reference.points);
    default:
      return [];
  }
}

/**
 * A resolved colour token at a given alpha, as a canvas can use it.
 *
 * The DOM parts of this kit fill with `color-mix(in srgb, var(--ck-accent) 16%,
 * transparent)` and let the browser do the work. A canvas gets a string and
 * nothing else: `var()` is not a colour there, and `color-mix()` is not either.
 * So a component resolves the token through `getComputedStyle` and passes the
 * result here, which is why this takes a colour and not a token name.
 *
 * Unparseable input returns `transparent`, not the colour at full strength: an
 * area fill that silently became opaque would hide the curve it sits under,
 * which is worse than an area fill that is missing.
 */
export function tokenAlpha(color: string, alpha: number): string {
  const bounded = Math.max(0, Math.min(1, Number(alpha) || 0));
  const channels = colorChannels(color);
  if (!channels) return 'transparent';
  const [red, green, blue, existing] = channels;
  return `rgba(${red}, ${green}, ${blue}, ${round(existing * bounded)})`;
}

/** `[r, g, b, a]` from a hex or `rgb()`/`rgba()` string, or `null`. */
function colorChannels(color: string): [number, number, number, number] | null {
  const text = (color ?? '').trim().toLowerCase();
  if (!text) return null;
  const hex = /^#([0-9a-f]{3,8})$/.exec(text);
  if (hex) {
    const digits = hex[1];
    // #rgb and #rgba are shorthand for doubled digits, so expand before slicing.
    const wide =
      digits.length <= 4
        ? digits
            .split('')
            .map((digit) => digit + digit)
            .join('')
        : digits;
    if (wide.length !== 6 && wide.length !== 8) return null;
    const channel = (at: number) => parseInt(wide.slice(at, at + 2), 16);
    const alpha = wide.length === 8 ? channel(6) / 255 : 1;
    return [channel(0), channel(2), channel(4), alpha];
  }
  // Both the legacy comma form and the modern `rgb(r g b / a)` slash form.
  const parts = /^rgba?\(([^)]+)\)$/.exec(text);
  if (!parts) return null;
  const numbers = parts[1]
    .replace(/\//g, ' ')
    .split(/[\s,]+/)
    .filter(Boolean)
    .map((piece) => (piece.endsWith('%') ? Number(piece.slice(0, -1)) / 100 : Number(piece)));
  if (numbers.length < 3 || numbers.some((value) => !Number.isFinite(value))) return null;
  const alpha = numbers.length > 3 ? Math.max(0, Math.min(1, numbers[3])) : 1;
  return [
    Math.round(numbers[0]),
    Math.round(numbers[1]),
    Math.round(numbers[2]),
    alpha,
  ];
}

function round(value: number): number {
  return Math.round(value * 1000) / 1000;
}

/** One stop of the wash under a curve, at `offset` down the plot. */
export interface CurveStop {
  offset: number;
  color: string;
}

/**
 * How the wash under a curve falls off, as `[offset, share of the peak]`.
 *
 * Three stops rather than two because a straight ramp from solid to nothing
 * reads as a flat slab of colour with a soft bottom edge: the eye sees the
 * midpoint, and a linear midpoint is exactly half, which is still a lot of
 * paint. Pulling the middle stop down to two fifths bends the falloff so the
 * colour is concentrated against the curve and the plot floor is genuinely
 * clear — which is what makes the area read as light coming off the line
 * rather than as a filled polygon.
 */
const CURVE_FILL_RAMP: readonly (readonly [number, number])[] = [
  [0, 1],
  [0.45, 0.4],
  [1, 0],
];

/**
 * The wash under a curve, as stops down the height of the plot.
 *
 * A flat fill is the honest thing to do and the wrong thing to look at: the
 * area under a ROC *is* the metric, so it wants to be the loudest object in
 * the panel, and a single alpha either drowns the gridlines or is invisible.
 * A gradient spends its opacity where the curve is and none of it on the
 * floor.
 *
 * Stops rather than a `CanvasGradient` because a gradient needs a canvas
 * context and a laid-out plot area, neither of which exists until chart.js is
 * mid-draw. The arithmetic of the ramp is decided here; the component adds
 * these to whatever gradient the renderer hands it.
 *
 * An unparseable colour yields stops that are all `transparent`, for the same
 * reason {@link tokenAlpha} does: a fill that silently went opaque would hide
 * the curve it sits under.
 */
export function curveFill(color: string, peak = 0.34): CurveStop[] {
  const bounded = Math.max(0, Math.min(1, Number(peak) || 0));
  return CURVE_FILL_RAMP.map(([offset, share]) => ({
    offset,
    color: tokenAlpha(color, bounded * share),
  }));
}

/**
 * How much of a plot is uncovered `elapsed` ms into its reveal.
 *
 * The curves are drawn by wiping left to right rather than by fading in, and
 * the wipe is a clip on the plot area, so the whole entrance is this one
 * number. Left-to-right because a ROC is read that way — the climb out of the
 * origin is the part that says the model separates — and a curve that arrives
 * already finished asks the viewer to reconstruct which end it started from.
 *
 * Eased out, so the wipe is quickest where there is least to see and settles
 * into the top-right corner where the curve flattens. A non-positive duration
 * is a finished reveal rather than a division by zero, which is also how
 * reduced motion is expressed: the caller passes zero and every frame is the
 * final one.
 */
export function revealFraction(elapsed: number, duration: number): number {
  if (!(duration > 0)) return 1;
  const linear = Math.max(0, Math.min(1, (Number(elapsed) || 0) / duration));
  return 1 - (1 - linear) ** 3;
}

// ---------------------------------------------------------------------------
// Confusion matrix
// ---------------------------------------------------------------------------

/** The raw block a training run reports. */
export interface ConfusionBlock {
  labels?: readonly string[];
  matrix?: readonly (readonly number[])[];
}

export interface ConfusionCell {
  actual: string;
  predicted: string;
  count: number;
  /** Share of the actual row, which is what makes an imbalanced matrix readable. */
  share: number;
  correct: boolean;
}

export interface ConfusionView {
  labels: string[];
  rows: { actual: string; total: number; cells: ConfusionCell[] }[];
  total: number;
}

/**
 * Cells carrying their own intensity, as a share of the ACTUAL row.
 *
 * Row-normalized rather than matrix-normalized on purpose: a churn matrix is
 * imbalanced by nature, and shading by the global total would paint the whole
 * grid the colour of the majority class and hide exactly the mistake that
 * matters — the churner the model called loyal.
 */
export function confusionView(
  confusion: ConfusionBlock | undefined | null,
): ConfusionView | null {
  const labels = confusion?.labels ?? [];
  const matrix = confusion?.matrix ?? [];
  if (!labels.length || matrix.length !== labels.length) return null;
  let total = 0;
  const rows = labels.map((actual, rowIndex) => {
    const raw = matrix[rowIndex] ?? [];
    const rowTotal = raw.reduce((sum, cell) => sum + (Number(cell) || 0), 0);
    total += rowTotal;
    return {
      actual,
      total: rowTotal,
      cells: labels.map((predicted, colIndex) => {
        const count = Number(raw[colIndex]) || 0;
        return {
          actual,
          predicted,
          count,
          share: rowTotal ? count / rowTotal : 0,
          correct: rowIndex === colIndex,
        };
      }),
    };
  });
  return { labels: [...labels], rows, total };
}

/**
 * The background for one cell: the diagonal in green, the mistakes in red.
 *
 * Alpha carries the share rather than a colour ramp, so the grid reads as one
 * quantity seen at different strengths. The floor keeps an occupied cell from
 * disappearing into the panel — a rare confusion is still a confusion, and a
 * cell showing `3` with no tint at all reads as an empty one.
 */
export function confusionShade(share: number, correct: boolean): string {
  const bounded = Math.max(0, Math.min(1, Number(share) || 0));
  const alpha = bounded === 0 ? 0 : Math.max(0.08, bounded * 0.55);
  const token = correct ? '--ck-signal-pos' : '--ck-signal-neg';
  const fallback = correct ? '#4ade80' : '#ef5a6f';
  return `color-mix(in srgb, var(${token}, ${fallback}) ${Math.round(alpha * 100)}%, transparent)`;
}

// ---------------------------------------------------------------------------
// Bars
// ---------------------------------------------------------------------------

/** One row of a horizontal bar list, already scaled to its widest sibling. */
export interface VizBar {
  label: string;
  /** The number the bar stands for, formatted by the caller. */
  display: string;
  /** 0–100, relative to the widest bar of the set. */
  width: number;
  /** Bars that point the other way: a feature that actively hurt the fit. */
  negative: boolean;
  /** Bars worth emphasising — the majority class, the strongest feature. */
  emphasis: boolean;
}

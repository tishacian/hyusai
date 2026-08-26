/**
 * The geometry behind the data plane's charts — Angular-free, so it is testable
 * as arithmetic rather than through a rendered component.
 *
 * This module and the components beside it are the *kit*: every chart the data
 * and model surfaces draw comes from here, so a curve on a model card and a
 * curve on a comparison view are the same drawing with different numbers rather
 * than two implementations that drift.
 *
 * Everything is plain SVG. Not for want of a charting library — one is in the
 * dependency tree already — but because these are small, fixed-shape plots with
 * no zooming, panning or legend interaction, and an SVG path is server-
 * renderable, styleable from the `--ck-*` tokens, and assertable in a unit test
 * as a string. A canvas chart is none of those three.
 */

// ---------------------------------------------------------------------------
// Curves
// ---------------------------------------------------------------------------

/** One point of a curve, in the curve's own units. */
export interface CurvePoint {
  x: number;
  y: number;
}

export interface CurveBox {
  width: number;
  height: number;
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
 * An SVG path for one curve, y flipped so a better model climbs.
 *
 * Returns `''` for fewer than two points rather than a degenerate path: an
 * empty `d` renders nothing, whereas a one-point path renders a dot that reads
 * as data.
 */
export function curvePath(
  points: readonly CurvePoint[] | undefined,
  box: CurveBox,
  domain: CurveDomain = UNIT_DOMAIN,
): string {
  const usable = (points ?? []).filter(
    (point) => point && Number.isFinite(point.x) && Number.isFinite(point.y),
  );
  if (usable.length < 2) return '';
  const spanX = domain.maxX - domain.minX || 1;
  const spanY = domain.maxY - domain.minY || 1;
  return usable
    .map((point, index) => {
      const x = ((point.x - domain.minX) / spanX) * box.width;
      const y = box.height - ((point.y - domain.minY) / spanY) * box.height;
      return `${index === 0 ? 'M' : 'L'}${round(x)},${round(y)}`;
    })
    .join(' ');
}

/**
 * The same curve closed along the baseline, so the area under it can be filled.
 *
 * The fill is what makes two ROCs comparable at a glance — the eye compares
 * areas far better than it compares two thin lines — which is the whole reason
 * a model card shows a curve rather than only the AUC beside it.
 */
export function curveArea(
  points: readonly CurvePoint[] | undefined,
  box: CurveBox,
  domain: CurveDomain = UNIT_DOMAIN,
): string {
  const line = curvePath(points, box, domain);
  if (!line) return '';
  const usable = (points ?? []).filter(
    (point) => point && Number.isFinite(point.x) && Number.isFinite(point.y),
  );
  const spanX = domain.maxX - domain.minX || 1;
  const first = usable[0];
  const last = usable[usable.length - 1];
  const startX = round(((first.x - domain.minX) / spanX) * box.width);
  const endX = round(((last.x - domain.minX) / spanX) * box.width);
  return `${line} L${endX},${box.height} L${startX},${box.height} Z`;
}

/** Where a horizontal reference sits in the box, or `null` if outside it. */
export function referenceY(
  value: number | null | undefined,
  box: CurveBox,
  domain: CurveDomain = UNIT_DOMAIN,
): number | null {
  if (value === null || value === undefined || !Number.isFinite(value)) return null;
  if (value < domain.minY || value > domain.maxY) return null;
  const spanY = domain.maxY - domain.minY || 1;
  return round(box.height - ((value - domain.minY) / spanY) * box.height);
}

function round(value: number): number {
  return Math.round(value * 100) / 100;
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

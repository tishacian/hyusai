export interface SvgPoint {
  x: number;
  y: number;
}

export interface SvgSegment {
  x: number;
  y: number;
  height: number;
}

export interface StackedBand {
  lower: number[];
  upper: number[];
}

export interface RadialSpokeEnds {
  start: SvgPoint;
  mid: SvgPoint;
  end: SvgPoint;
}

export interface RadialSpokeInput {
  cx: number;
  cy: number;
  angle: number;
  innerRadius: number;
  length: number;
  measuredShare?: number;
  startPad?: number;
}

function fmt(value: number): string {
  const rounded = Math.round(value * 10) / 10;
  return Object.is(rounded, -0) ? '0' : String(rounded);
}

export function cubicSmoothPath(points: readonly SvgPoint[]): string {
  if (!points.length) return '';
  const first = points[0];
  let d = `M${fmt(first.x)},${fmt(first.y)}`;
  for (let i = 1; i < points.length; i += 1) {
    const prev = points[i - 1];
    const next = points[i];
    const cx = (prev.x + next.x) / 2;
    d += `C${fmt(cx)},${fmt(prev.y)} ${fmt(cx)},${fmt(next.y)} ${fmt(next.x)},${fmt(next.y)}`;
  }
  return d;
}

export function cubicSmoothAreaPath(
  upper: readonly SvgPoint[],
  lower?: readonly SvgPoint[] | null,
  baselineY?: number,
): string {
  if (upper.length < 2) return '';
  const top = cubicSmoothPath(upper);
  if (lower && lower.length >= 2) {
    return `${top}L${cubicSmoothPath([...lower].reverse()).slice(1)}Z`;
  }
  const first = upper[0];
  const last = upper[upper.length - 1];
  const base = baselineY ?? lower?.[0]?.y ?? last.y;
  return `${top}L${fmt(last.x)},${fmt(base)}L${fmt(first.x)},${fmt(base)}Z`;
}

export function sankeyRibbonPath(source: SvgSegment, target: SvgSegment): string {
  const x0 = source.x;
  const y0 = source.y;
  const h0 = source.height;
  const x1 = target.x;
  const y1 = target.y;
  const h1 = target.height;
  const xm = (x0 + x1) / 2;
  return (
    `M${fmt(x0)},${fmt(y0)}C${fmt(xm)},${fmt(y0)} ${fmt(xm)},${fmt(y1)} ${fmt(x1)},${fmt(y1)}` +
    `L${fmt(x1)},${fmt(y1 + h1)}C${fmt(xm)},${fmt(y1 + h1)} ${fmt(xm)},${fmt(y0 + h0)} ${fmt(x0)},${fmt(y0 + h0)}Z`
  );
}

export function radialPoint(cx: number, cy: number, radius: number, angle: number): SvgPoint {
  return {
    x: cx + radius * Math.cos(angle),
    y: cy + radius * Math.sin(angle),
  };
}

export function radialDayAngle(index: number, dayCount = 30): number {
  const count = dayCount > 0 ? dayCount : 30;
  return -Math.PI / 2 + index * ((2 * Math.PI) / count);
}

export function radialSpokeLength(
  value: number,
  maxValue: number,
  innerRadius: number,
  outerRadius: number,
): number {
  const max = maxValue > 0 ? maxValue : 1;
  const amount = value > 0 ? value : 0;
  return (outerRadius - innerRadius) * (amount / max);
}

export function radialSpokeEndpoints(input: RadialSpokeInput): RadialSpokeEnds {
  const startPad = input.startPad ?? 3;
  const share = input.measuredShare ?? 0.45;
  return {
    start: radialPoint(input.cx, input.cy, input.innerRadius + startPad, input.angle),
    mid: radialPoint(input.cx, input.cy, input.innerRadius + input.length * share, input.angle),
    end: radialPoint(input.cx, input.cy, input.innerRadius + input.length, input.angle),
  };
}

/** A round gridline step (1, 2, 2.5, 5 × 10ⁿ) giving about four lines up to `max`. */
export function niceStep(max: number): number {
  if (!(max > 0)) return 1;
  const rough = max / 4;
  const power = 10 ** Math.floor(Math.log10(rough));
  for (const factor of [1, 2, 2.5, 5, 10]) {
    if (factor * power >= rough) return factor * power;
  }
  return 10 * power;
}

/**
 * Push overlapping label rows apart while keeping them inside `[min, max]`.
 * Returns one y per input, in input order; ties keep input order.
 */
export function spreadLabelRows(
  desired: readonly number[],
  minGap: number,
  min: number,
  max: number,
): number[] {
  const order = desired.map((y, index) => ({ y, index })).sort((a, b) => a.y - b.y || a.index - b.index);
  const placed = order.map((item) => Math.min(Math.max(item.y, min), max));
  for (let i = 1; i < placed.length; i += 1) {
    placed[i] = Math.max(placed[i], placed[i - 1] + minGap);
  }
  const overflow = placed.length ? placed[placed.length - 1] - max : 0;
  if (overflow > 0) {
    for (let i = 0; i < placed.length; i += 1) placed[i] -= overflow;
    placed[0] = Math.max(placed[0], min);
    for (let i = 1; i < placed.length; i += 1) {
      placed[i] = Math.max(placed[i], placed[i - 1] + minGap);
    }
  }
  const out = new Array<number>(desired.length);
  order.forEach((item, i) => {
    out[item.index] = placed[i];
  });
  return out;
}

export function accumulateStackedSeries(
  series: readonly (readonly number[])[],
): StackedBand[] {
  if (!series.length) return [];
  const n = series.reduce((len, row) => Math.max(len, row.length), 0);
  const bands: StackedBand[] = [];
  let lower = Array.from({ length: n }, () => 0);
  for (const row of series) {
    const upper = lower.map((lo, i) => lo + (Number.isFinite(row[i]) ? row[i] : 0));
    bands.push({ lower: lower.slice(), upper });
    lower = upper;
  }
  return bands;
}

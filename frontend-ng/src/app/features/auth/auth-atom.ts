/**
 * Geometry of the sign-in atom: three dashed rings, an electron on each, in
 * a 400 × 400 frame. The rings drift slowly, their dashes flow along them,
 * and the electrons speed up as the pointer comes near. How each point then
 * bends under the pointer's gravity lives in `gravity.ts`. Pure math, no DOM.
 */

export interface Ring {
  rx: number;
  ry: number;
  /** Rotation of the ellipse, in degrees. */
  rotation: number;
  /** One turn of its electron at rest, in seconds; negative turns the other way. */
  periodS: number;
  /** Opacity of the ring at rest. */
  alpha: number;
  /** Speed of the dashes along the ring, in frame units per second; the sign is the direction. */
  flow: number;
}

/** The three rings of the sign-in atom. */
export const ATOM_RINGS: readonly Ring[] = [
  { rx: 188, ry: 72, rotation: -24, periodS: 46, alpha: 0.8, flow: 4.3 },
  { rx: 160, ry: 62, rotation: 20, periodS: -61, alpha: 0.55, flow: -5.3 },
  { rx: 128, ry: 112, rotation: -6, periodS: 78, alpha: 0.35, flow: 3.4 },
];

/** Dash pattern of the rings, in frame units: a short dash every 8. */
export const DASH_PERIOD = 8;
export const DASH_LENGTH = 2;
/** One full drift of the whole atom, in seconds. */
export const DRIFT_PERIOD_S = 240;
export const ATOM_NEAR_RADIUS_PX = 420;
/** An electron turns this much faster when the pointer is on the atom. */
export const ATOM_ELECTRON_BOOST = 3.5;

/** A point of `ring` at parameter `angle` (radians), turned by `extraDeg` around (cx, cy). */
export function ringPoint(ring: Ring, angle: number, cx = 200, cy = 200, extraDeg = 0): { x: number; y: number } {
  const theta = ((ring.rotation + extraDeg) * Math.PI) / 180;
  const ex = Math.cos(angle) * ring.rx;
  const ey = Math.sin(angle) * ring.ry;
  return {
    x: cx + ex * Math.cos(theta) - ey * Math.sin(theta),
    y: cy + ex * Math.sin(theta) + ey * Math.cos(theta),
  };
}

export interface ArcTable {
  /** Cumulative arc length at each parameter step. */
  lengths: Float64Array;
  /** Perimeter of the ring, in frame units. */
  total: number;
  steps: number;
}

/** Arc length along an ellipse, tabulated so dashes can be spaced evenly. */
export function arcTable(ring: Ring, steps = 720): ArcTable {
  const lengths = new Float64Array(steps + 1);
  let previous = ringPoint(ring, 0, 0, 0);
  for (let i = 1; i <= steps; i++) {
    const point = ringPoint(ring, (i / steps) * Math.PI * 2, 0, 0);
    lengths[i] = lengths[i - 1] + Math.hypot(point.x - previous.x, point.y - previous.y);
    previous = point;
  }
  return { lengths, total: lengths[steps], steps };
}

/** The parameter angle at arc distance `s` along the ring (wrapping around). */
export function angleAtLength(table: ArcTable, s: number): number {
  const target = ((s % table.total) + table.total) % table.total;
  let low = 0;
  let high = table.steps;
  while (high - low > 1) {
    const mid = (low + high) >> 1;
    if (table.lengths[mid] <= target) low = mid;
    else high = mid;
  }
  const span = table.lengths[high] - table.lengths[low] || 1;
  const fraction = (target - table.lengths[low]) / span;
  return ((low + fraction) / table.steps) * Math.PI * 2;
}

/** 0 far from the atom, 1 on it, easing smoothly in between. */
export function nearness(distance: number, radius = ATOM_NEAR_RADIUS_PX): number {
  if (distance >= radius) return 0;
  const closeness = 1 - Math.max(0, distance) / radius;
  return closeness * closeness * (3 - 2 * closeness);
}

/** Angular speed of a ring's electron, in radians per second. */
export function electronSpeed(ring: Ring, near: number, boost = ATOM_ELECTRON_BOOST): number {
  return ((Math.PI * 2) / ring.periodS) * (1 + (boost - 1) * Math.min(1, Math.max(0, near)));
}

/**
 * Points of the braided bridge from an electron at (ex, ey) to the pointer at
 * (px, py): a thread that sags to one side by `sag` × its length, sampled
 * every `step` px. Each point carries the distance along the thread, as the
 * pointer wake does, so the same braid can be drawn along it.
 */
export function bridgePoints(
  ex: number,
  ey: number,
  px: number,
  py: number,
  t: number,
  sag = 0.18,
  step = 5,
): { x: number; y: number; t: number; d: number }[] {
  const length = Math.hypot(px - ex, py - ey);
  if (length < 1) return [];
  const nx = -(py - ey) / length;
  const ny = (px - ex) / length;
  const cx = (ex + px) / 2 + nx * sag * length;
  const cy = (ey + py) / 2 + ny * sag * length;
  const count = Math.max(2, Math.ceil(length / step));
  const points: { x: number; y: number; t: number; d: number }[] = [];
  let travelled = 0;
  for (let i = 0; i <= count; i++) {
    const f = i / count;
    const x = (1 - f) * (1 - f) * ex + 2 * (1 - f) * f * cx + f * f * px;
    const y = (1 - f) * (1 - f) * ey + 2 * (1 - f) * f * cy + f * f * py;
    const previous = points[points.length - 1];
    if (previous) travelled += Math.hypot(x - previous.x, y - previous.y);
    points.push({ x, y, t, d: travelled });
  }
  return points;
}

/** How strongly the bridge shows: 0 beyond `radius`, 1 at half of it and closer. */
export function bridgeStrength(distance: number, mass: number, radius = 190): number {
  if (distance >= radius) return 0;
  return Math.min(1, (radius - distance) / (radius * 0.5)) * Math.min(1, Math.max(0, mass));
}

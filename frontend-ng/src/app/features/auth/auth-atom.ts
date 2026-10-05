/**
 * Geometry of the sign-in atom, in a 400 × 400 frame. There are no drawn
 * orbits: each electron draws its own, a long braided trail behind it that
 * covers most of the turn and fades toward its tail — the same double helix
 * as the pointer wake. The electrons speed up as the pointer comes near. How
 * each point then bends under the pointer's gravity lives in `gravity.ts`.
 * Pure math, no DOM.
 */

export interface Ring {
  rx: number;
  ry: number;
  /** Rotation of the ellipse, in degrees. */
  rotation: number;
  /** One turn of its electron at rest, in seconds; negative turns the other way. */
  periodS: number;
  /** Opacity of the ring's braid at rest. */
  alpha: number;
}

/** The three rings of the sign-in atom. */
export const ATOM_RINGS: readonly Ring[] = [
  { rx: 188, ry: 72, rotation: -24, periodS: 46, alpha: 0.85 },
  { rx: 160, ry: 62, rotation: 20, periodS: -61, alpha: 0.65 },
  { rx: 128, ry: 112, rotation: -6, periodS: 78, alpha: 0.5 },
];

/** Share of its orbit an electron's braid covers behind it. */
export const TRAIL_FRACTION = 0.78;
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

/** Keeps only the last `maxLength` px of a trail, measured along it from its head. */
export function pruneByLength(points: { d: number }[], maxLength: number): void {
  const head = points[points.length - 1];
  if (!head) return;
  let expired = 0;
  while (expired < points.length && head.d - points[expired].d > maxLength) expired++;
  if (expired) points.splice(0, expired);
}

export interface BraidOptions {
  /** Offset from the trail at its head, in px. */
  amplitude: number;
  /** Distance between two crossings, in px. */
  wavelength: number;
  /** Stroke width at the head, in px. */
  width: number;
  /** How much wider the braid opens at the tail: 1 doubles the offset. */
  spread: number;
}

export interface BraidSample {
  x: number;
  y: number;
  /** 1 at the head, 0 at the end of the trail. */
  life: number;
  width: number;
}

/**
 * One strand of an electron's braid: the trail offset along its normal by a
 * sine of the distance travelled (stable while the electron moves on), opening
 * toward the tail and fading with the distance from the head, so the orbit
 * reads as the trace of its electron.
 */
export function orbitBraid(
  points: readonly { x: number; y: number; d: number }[],
  phase: number,
  maxLength: number,
  options: BraidOptions,
): BraidSample[] {
  const count = points.length;
  const head = points[count - 1];
  if (!head) return [];
  const samples: BraidSample[] = [];
  for (let i = 0; i < count; i++) {
    const point = points[i];
    const prev = points[Math.max(0, i - 1)];
    const next = points[Math.min(count - 1, i + 1)];
    let nx = -(next.y - prev.y);
    let ny = next.x - prev.x;
    const length = Math.hypot(nx, ny) || 1;
    nx /= length;
    ny /= length;
    const behind = Math.min(1, Math.max(0, (head.d - point.d) / Math.max(1, maxLength)));
    const life = 1 - behind;
    const offset =
      Math.sin((point.d / options.wavelength) * Math.PI * 2 + phase) * options.amplitude * (1 + options.spread * behind);
    samples.push({
      x: point.x + nx * offset,
      y: point.y + ny * offset,
      life,
      width: options.width * (0.35 + 0.65 * life),
    });
  }
  return samples;
}

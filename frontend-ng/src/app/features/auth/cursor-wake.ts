/**
 * Cursor wake of the sign-in page: two fine strands braid behind the pointer
 * and fade, like a wake that widens behind a boat. Pure geometry, no DOM.
 *
 * Each point keeps the distance travelled when it was recorded, so a strand
 * stays where it was drawn while it fades instead of wriggling as the
 * pointer moves on.
 */

export interface WakePoint {
  x: number;
  y: number;
  /** Time the point was recorded, in ms. */
  t: number;
  /** Distance travelled by the pointer up to this point, in px. */
  d: number;
}

export interface WakeSample {
  x: number;
  y: number;
  /** 0 (gone) to 1 (fresh). */
  alpha: number;
  width: number;
}

export interface StrandOptions {
  lifetimeMs: number;
  /** Offset from the path at the oldest end, in px. */
  amplitude: number;
  /** Distance between two crossings of the braid, in px. */
  wavelength: number;
  /** Stroke width of a fresh point, in px. */
  width: number;
}

export const WAKE_LIFETIME_MS = 900;
export const WAKE_MAX_POINTS = 160;
export const WAKE_MIN_STEP_PX = 3;
/** Longest gap between two points: a fast stroke is filled in so the braid stays smooth. */
export const WAKE_MAX_GAP_PX = 6;

export const WAKE_STRAND: StrandOptions = {
  lifetimeMs: WAKE_LIFETIME_MS,
  amplitude: 7,
  wavelength: 40,
  width: 2,
};

/**
 * Records a pointer sample at the head of the wake. Moves under `minStep`
 * pixels are skipped (hand jitter), a stroke longer than `maxGap` is filled
 * in with evenly spaced points, and the oldest points drop once the wake
 * holds `max` points. Returns whether the sample was kept.
 */
export function pushPoint(
  points: WakePoint[],
  x: number,
  y: number,
  t: number,
  minStep = WAKE_MIN_STEP_PX,
  max = WAKE_MAX_POINTS,
  maxGap = WAKE_MAX_GAP_PX,
): boolean {
  const last = points[points.length - 1];
  if (!last) {
    points.push({ x, y, t, d: 0 });
    return true;
  }
  const step = Math.hypot(x - last.x, y - last.y);
  if (step < minStep) return false;
  const parts = Math.max(1, Math.ceil(step / maxGap));
  for (let k = 1; k <= parts; k++) {
    const f = k / parts;
    points.push({
      x: last.x + (x - last.x) * f,
      y: last.y + (y - last.y) * f,
      t: last.t + (t - last.t) * f,
      d: last.d + step * f,
    });
  }
  if (points.length > max) points.splice(0, points.length - max);
  return true;
}

/** Drops the points older than `lifetimeMs` from the tail of the wake. */
export function prune(points: WakePoint[], now: number, lifetimeMs = WAKE_LIFETIME_MS): void {
  let expired = 0;
  while (expired < points.length && now - points[expired].t >= lifetimeMs) expired++;
  if (expired) points.splice(0, expired);
}

/**
 * One strand of the braid: the path offset along its normal by a sine of the
 * distance travelled. Two strands half a turn apart (`phase` 0 and π) cross
 * and recross. The offset widens toward the oldest end; opacity and width
 * fade with age.
 */
export function strand(
  points: readonly WakePoint[],
  now: number,
  phase: number,
  options: StrandOptions = WAKE_STRAND,
): WakeSample[] {
  const count = points.length;
  const samples: WakeSample[] = [];
  for (let i = 0; i < count; i++) {
    const point = points[i];
    const prev = points[Math.max(0, i - 1)];
    const next = points[Math.min(count - 1, i + 1)];
    let nx = -(next.y - prev.y);
    let ny = next.x - prev.x;
    const length = Math.hypot(nx, ny) || 1;
    nx /= length;
    ny /= length;

    const life = Math.max(0, 1 - (now - point.t) / options.lifetimeMs);
    // 0 at the oldest point, 1 at the pointer.
    const head = count > 1 ? i / (count - 1) : 1;
    const spread = options.amplitude * (0.2 + 0.8 * (1 - head));
    const offset = Math.sin((point.d / options.wavelength) * Math.PI * 2 + phase) * spread;

    samples.push({
      x: point.x + nx * offset,
      y: point.y + ny * offset,
      alpha: life * life,
      width: options.width * (0.3 + 0.7 * life),
    });
  }
  return samples;
}

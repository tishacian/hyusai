/**
 * A shell of points around the sign-in orb. At rest they sit on a small
 * sphere. As the pointer approaches, the points facing it travel outward;
 * when it leaves, every point returns to the same radius.
 */

export interface SwarmPoint {
  x: number;
  y: number;
  z: number;
}

export interface SwarmDot {
  x: number;
  y: number;
  radius: number;
  alpha: number;
}

export const SWARM_COUNT = 48;
export const SWARM_REST_PX = 20;
export const SWARM_FULL_PX = 62;

/** Fibonacci sphere, unit length, stable order. */
export function swarmLayout(count = SWARM_COUNT): SwarmPoint[] {
  const points: SwarmPoint[] = [];
  const golden = Math.PI * (3 - Math.sqrt(5));
  for (let i = 0; i < count; i++) {
    const y = count === 1 ? 0 : 1 - (i / (count - 1)) * 2;
    const ring = Math.sqrt(Math.max(0, 1 - y * y));
    const theta = golden * i;
    points.push({ x: Math.cos(theta) * ring, y, z: Math.sin(theta) * ring });
  }
  return points;
}

export function swarmFrame(
  points: readonly SwarmPoint[],
  open: number,
  aimX: number,
  aimY: number,
  timeSeconds: number,
  rest = SWARM_REST_PX,
  full = SWARM_FULL_PX,
): SwarmDot[] {
  const amount = Math.min(1, Math.max(0, open));
  const aim = Math.hypot(aimX, aimY) || 1;
  const ax = aimX / aim;
  const ay = aimY / aim;
  const spin = timeSeconds * 0.4;
  const cos = Math.cos(spin);
  const sin = Math.sin(spin);
  return points.map((point) => {
    const x = point.x * cos - point.z * sin;
    const z = point.x * sin + point.z * cos;
    const y = point.y;
    const facing = amount === 0 ? 0 : Math.max(0, x * ax + y * ay);
    const reach = rest + (full - rest) * amount * (0.28 + 0.72 * facing);
    const depth = 0.45 + 0.55 * ((z + 1) / 2);
    return {
      x: x * reach,
      y: y * reach,
      radius: 1.1 + 1.15 * depth,
      alpha: 0.28 + 0.72 * depth,
    };
  });
}

/**
 * The sign-in atom behaves like a physical instrument: it tilts toward the
 * pointer like a gyroscope, its rings sit on planes of different depth, and
 * the electron on each ring speeds up as the pointer comes near. The atom
 * never deforms: every ring keeps its shape, only the whole instrument moves.
 * Pure math, no DOM.
 */

export interface AtomPose {
  /** Tilt around the horizontal axis, in degrees. */
  rx: number;
  /** Tilt around the vertical axis, in degrees. */
  ry: number;
  /** 0 when the pointer is far, 1 when it is on the atom. */
  near: number;
}

export interface Ring {
  rx: number;
  ry: number;
  /** Rotation of the ellipse, in degrees. */
  rotation: number;
  /** One turn of its electron at rest, in seconds; negative turns the other way. */
  periodS: number;
  /** Plane of the ring along the depth axis, in px. */
  depth: number;
}

export const ATOM_MAX_TILT_X_DEG = 7;
export const ATOM_MAX_TILT_Y_DEG = 9;
export const ATOM_NEAR_RADIUS_PX = 420;
/** How fast the pose follows its target: about 0.5 s to settle. */
export const ATOM_STIFFNESS_PER_S = 5;
/** An electron turns this much faster when the pointer is on the atom. */
export const ATOM_ELECTRON_BOOST = 3.5;

/** The three rings of the sign-in atom, in the 400 × 400 SVG frame. */
export const ATOM_RINGS: readonly Ring[] = [
  { rx: 188, ry: 72, rotation: -24, periodS: 46, depth: 36 },
  { rx: 160, ry: 62, rotation: 20, periodS: -61, depth: 0 },
  { rx: 128, ry: 112, rotation: -6, periodS: 78, depth: -36 },
];

export const REST_POSE: AtomPose = { rx: 0, ry: 0, near: 0 };

/**
 * The pose the atom turns toward for a pointer at (dx, dy) from its centre.
 * The tilt follows the pointer across the whole page (`reachX`, `reachY` are
 * the distances of full tilt); `near` only rises close to the atom.
 */
export function targetPose(
  dx: number,
  dy: number,
  reachX: number,
  reachY: number,
  nearRadius = ATOM_NEAR_RADIUS_PX,
): AtomPose {
  const nx = clamp(dx / Math.max(1, reachX), -1, 1);
  const ny = clamp(dy / Math.max(1, reachY), -1, 1);
  const distance = Math.hypot(dx, dy);
  const closeness = distance >= nearRadius ? 0 : 1 - distance / nearRadius;
  return {
    // `0 -` keeps a pointer on the axis at +0, not -0.
    rx: 0 - ny * ATOM_MAX_TILT_X_DEG,
    ry: nx * ATOM_MAX_TILT_Y_DEG,
    near: closeness * closeness * (3 - 2 * closeness),
  };
}

/** Eases `current` toward `target`, the same way whatever the frame rate. */
export function settle(
  current: AtomPose,
  target: AtomPose,
  dtMs: number,
  stiffness = ATOM_STIFFNESS_PER_S,
): AtomPose {
  const k = 1 - Math.exp(-(Math.max(0, dtMs) / 1000) * stiffness);
  return {
    rx: current.rx + (target.rx - current.rx) * k,
    ry: current.ry + (target.ry - current.ry) * k,
    near: current.near + (target.near - current.near) * k,
  };
}

/** A point of `ring`, centred at (cx, cy), at `angle` radians along it. */
export function ringPoint(ring: Ring, angle: number, cx = 200, cy = 200): { x: number; y: number } {
  const theta = (ring.rotation * Math.PI) / 180;
  const ex = Math.cos(angle) * ring.rx;
  const ey = Math.sin(angle) * ring.ry;
  return {
    x: cx + ex * Math.cos(theta) - ey * Math.sin(theta),
    y: cy + ex * Math.sin(theta) + ey * Math.cos(theta),
  };
}

/** Angular speed of a ring's electron, in radians per second. */
export function electronSpeed(ring: Ring, near: number, boost = ATOM_ELECTRON_BOOST): number {
  return ((Math.PI * 2) / ring.periodS) * (1 + (boost - 1) * clamp(near, 0, 1));
}

/** The CSS transform of the whole atom for a pose. */
export function atomTransform(pose: AtomPose): string {
  return `perspective(1100px) rotateX(${pose.rx.toFixed(2)}deg) rotateY(${pose.ry.toFixed(2)}deg)`;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

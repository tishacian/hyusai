/**
 * The space around the sign-in atom is an elastic membrane and the pointer
 * is a gravity well. Each node of the membrane is a damped spring pulled
 * toward the well and tied to its four neighbours, so a fast sweep sends a
 * soft ripple through it. Anything drawn in that space — a dash of an orbit,
 * an electron, a dot of the thinking orb — reads the membrane's displacement
 * at its own position: every point moves on its own, under the same physics.
 * Pure math, no DOM.
 */

export interface Well {
  x: number;
  y: number;
  /** 0 no pull, 1 full pull. */
  mass: number;
}

export interface GravityOptions {
  /** Largest pull of a point, in px, right next to the well. */
  maxShift: number;
  /** Distance at which the pull is halved, in px. */
  softening: number;
  /** Spring toward the pulled position, per s². */
  stiffness: number;
  /** Velocity damping, per s. */
  damping: number;
  /** Tie to the neighbours, per s²: carries ripples across the membrane. */
  coupling: number;
}

export const GRAVITY: GravityOptions = {
  maxShift: 42,
  softening: 120,
  // About 2.2 Hz, slightly under-damped: points overshoot a little and settle.
  stiffness: 190,
  damping: 15,
  coupling: 70,
};

/** Integration step: small enough to stay stable at any frame rate. */
const SUBSTEP_S = 1 / 120;

/**
 * Where a point at rest at (x, y) is pulled by the well: toward it, by a
 * softened inverse-square amount, and never past half the distance to it so
 * points gather around the pointer instead of jumping over it.
 */
export function pull(x: number, y: number, well: Well | null, options: GravityOptions = GRAVITY): [number, number] {
  if (!well || well.mass <= 0) return [0, 0];
  const dx = well.x - x;
  const dy = well.y - y;
  const distance = Math.hypot(dx, dy);
  if (distance < 1e-6) return [0, 0];
  const soft = options.softening * options.softening;
  const magnitude = Math.min(
    options.maxShift * well.mass * (soft / (distance * distance + soft)),
    distance * 0.45,
  );
  return [(dx / distance) * magnitude, (dy / distance) * magnitude];
}

export class Membrane {
  readonly cols: number;
  readonly rows: number;
  readonly dx: Float32Array;
  readonly dy: Float32Array;
  private readonly vx: Float32Array;
  private readonly vy: Float32Array;
  private carry = 0;

  /** A membrane covering `width` × `height` px from the origin, one node every `spacing` px. */
  constructor(
    readonly width: number,
    readonly height: number,
    readonly spacing: number,
  ) {
    this.cols = Math.max(2, Math.ceil(width / spacing) + 1);
    this.rows = Math.max(2, Math.ceil(height / spacing) + 1);
    const count = this.cols * this.rows;
    this.dx = new Float32Array(count);
    this.dy = new Float32Array(count);
    this.vx = new Float32Array(count);
    this.vy = new Float32Array(count);
  }

  /**
   * Advances the membrane by `dtMs` under `well`. The border nodes stay
   * pinned, so the deformation always fades out before the edge.
   */
  step(well: Well | null, dtMs: number, options: GravityOptions = GRAVITY): void {
    this.carry += Math.min(0.1, Math.max(0, dtMs / 1000));
    while (this.carry >= SUBSTEP_S) {
      this.carry -= SUBSTEP_S;
      this.substep(well, SUBSTEP_S, options);
    }
  }

  /** The displacement at (x, y), interpolated between the four nearest nodes. */
  sample(x: number, y: number): [number, number] {
    const gx = x / this.spacing;
    const gy = y / this.spacing;
    if (gx <= 0 || gy <= 0 || gx >= this.cols - 1 || gy >= this.rows - 1) return [0, 0];
    const c = Math.floor(gx);
    const r = Math.floor(gy);
    const fx = gx - c;
    const fy = gy - r;
    const i = r * this.cols + c;
    const j = i + this.cols;
    const w00 = (1 - fx) * (1 - fy);
    const w10 = fx * (1 - fy);
    const w01 = (1 - fx) * fy;
    const w11 = fx * fy;
    return [
      this.dx[i] * w00 + this.dx[i + 1] * w10 + this.dx[j] * w01 + this.dx[j + 1] * w11,
      this.dy[i] * w00 + this.dy[i + 1] * w10 + this.dy[j] * w01 + this.dy[j + 1] * w11,
    ];
  }

  /** Total motion left in the membrane, in px: 0 at rest. */
  activity(): number {
    let total = 0;
    for (let i = 0; i < this.dx.length; i++) {
      total += Math.abs(this.dx[i]) + Math.abs(this.dy[i]) + (Math.abs(this.vx[i]) + Math.abs(this.vy[i])) * 0.05;
    }
    return total;
  }

  private substep(well: Well | null, dt: number, options: GravityOptions): void {
    const { cols, rows, spacing, dx, dy, vx, vy } = this;
    const { stiffness, damping, coupling } = options;
    for (let r = 1; r < rows - 1; r++) {
      for (let c = 1; c < cols - 1; c++) {
        const i = r * cols + c;
        const [tx, ty] = pull(c * spacing, r * spacing, well, options);
        const lx = dx[i - 1] + dx[i + 1] + dx[i - cols] + dx[i + cols] - 4 * dx[i];
        const ly = dy[i - 1] + dy[i + 1] + dy[i - cols] + dy[i + cols] - 4 * dy[i];
        vx[i] += (stiffness * (tx - dx[i]) + coupling * lx - damping * vx[i]) * dt;
        vy[i] += (stiffness * (ty - dy[i]) + coupling * ly - damping * vy[i]) * dt;
      }
    }
    for (let i = 0; i < dx.length; i++) {
      dx[i] += vx[i] * dt;
      dy[i] += vy[i] * dt;
    }
  }
}

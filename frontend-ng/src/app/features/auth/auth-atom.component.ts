import {
  afterNextRender,
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  inject,
  input,
  viewChild,
} from '@angular/core';
import type { CkOrbState } from '@app/shared/cockpit';
import { MODE_DRAWS } from '@app/shared/cockpit/thinking-orb/vendor/engine/registry';
import { resolvePreset, type Resolved } from '@app/shared/cockpit/thinking-orb/vendor/presets';
import {
  arcTable,
  ATOM_RINGS,
  bridgePoints,
  bridgeStrength,
  DRIFT_PERIOD_S,
  electronSpeed,
  nearness,
  orbitBraid,
  pruneByLength,
  ringPoint,
  TRAIL_FRACTION,
  type BraidOptions,
  type BraidSample,
} from './auth-atom';
import { pushPoint, strand, type StrandOptions, type WakePoint, type WakeSample } from './cursor-wake';
import { Membrane, type Well } from './gravity';

/** The canvas reaches past the atom so a bent point never meets its edge. */
const BLEED_PX = 120;
const MEMBRANE_SPACING_PX = 20;
const ORB_SIZE = 64;
/** Where each electron starts on its ring, in radians. */
const ELECTRON_START = [0.55, 2.6, 4.3];
const ELECTRON_RADIUS = [3.5, 3, 2.5];
const ELECTRON_ALPHA = [0.95, 0.85, 0.75];
/** How fast the well follows the pointer (per s), and gains or loses its mass. */
const WELL_FOLLOW_PER_S = 18;
const WELL_MASS_PER_S = 4;
/** The braid each electron draws behind it: its orbit, as a trace. */
const ORBIT_BRAID: BraidOptions = { amplitude: 2.4, wavelength: 30, width: 1.25, spread: 1.4 };
/** Opacity levels a braid is drawn in: few strokes per frame, smooth enough to the eye. */
const BRAID_LEVELS = 10;
/** Between the nearest electron and the hand, when the hand comes close. */
const BRIDGE: StrandOptions = { lifetimeMs: 1000, amplitude: 4, wavelength: 28, width: 1.3 };
const BRIDGE_ALPHA = 0.6;
/** The bridge's braid turns slowly on itself, in radians per second. */
const BRIDGE_TWIST_PER_S = 2.4;

/**
 * The atom of the sign-in panel, drawn in one canvas. No orbit is drawn as
 * such: each electron braids its own trail behind it, the same double helix
 * as the pointer wake, and that trail is its orbit. The pointer is a gravity
 * well bending an elastic membrane (`gravity.ts`); every point of every braid,
 * each electron and every dot of the thinking orb is displaced by the
 * membrane at its own position, so the whole atom bends smoothly under the
 * hand and springs back after it. When the hand comes near, a braided thread
 * stretches from the nearest electron to it. Under `prefers-reduced-motion`
 * it draws one still frame.
 */
@Component({
  selector: 'app-auth-atom',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="atom-glow" aria-hidden="true"></div>
    <canvas #canvas class="atom-canvas" aria-hidden="true"></canvas>
  `,
  styles: [
    `
      :host {
        --near: 0;
        display: block;
      }
      .atom-canvas {
        position: absolute;
        left: -120px;
        top: -120px;
        width: calc(100% + 240px);
        height: calc(100% + 240px);
        pointer-events: none;
      }
      .atom-glow {
        position: absolute;
        left: 50%;
        top: 50%;
        width: 220px;
        height: 220px;
        margin: -110px 0 0 -110px;
        background: radial-gradient(circle closest-side, rgba(125, 211, 252, 0.16), transparent 65%);
        filter: blur(6px);
        opacity: calc(0.75 + 0.25 * var(--near));
        transform: scale(calc(1 + 0.12 * var(--near)));
      }
    `,
  ],
})
export class AuthAtomComponent {
  readonly orbState = input.required<CkOrbState>();

  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private readonly canvas = viewChild.required<ElementRef<HTMLCanvasElement>>('canvas');

  constructor() {
    const destroyRef = inject(DestroyRef);
    afterNextRender(() => {
      const reduced = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
      const stop = startAtom(this.host.nativeElement, this.canvas().nativeElement, () => this.orbState(), reduced);
      destroyRef.onDestroy(stop);
    });
  }
}

interface Palette {
  /** The neutral strand of every braid. */
  neutral: string;
  electrons: [string, string, string];
  dark: boolean;
}

function startAtom(
  host: HTMLElement,
  canvas: HTMLCanvasElement,
  orbState: () => CkOrbState,
  reduced: boolean,
): () => void {
  const context = canvas.getContext('2d');
  if (!context) return () => undefined;
  const ctx: CanvasRenderingContext2D = context;

  const perimeters = ATOM_RINGS.map((ring) => arcTable(ring).total);
  const angles = [...ELECTRON_START];
  /** Each electron's trail, at rest (before gravity), in canvas px. */
  const trails: WakePoint[][] = ATOM_RINGS.map(() => []);
  const presets = new Map<CkOrbState, Resolved>();
  const buckets: number[][] = Array.from({ length: BRAID_LEVELS }, () => []);
  let size = 0;
  let span = 0;
  let ratio = 1;
  let membrane = new Membrane(1, 1, MEMBRANE_SPACING_PX);
  let palette = readPalette(host);
  let pointer: { x: number; y: number } | null = null;
  const well: Well = { x: 0, y: 0, mass: 0 };
  let drift = 0;
  let orbClock = 0;
  let last = performance.now();
  let frame = 0;

  /** Frame units (0–400) to canvas px. */
  const toCanvas = (x: number, y: number): [number, number] => {
    const scale = size / 400;
    return [BLEED_PX + x * scale, BLEED_PX + y * scale];
  };
  const trailLength = (i: number) => TRAIL_FRACTION * perimeters[i] * (size / 400);

  /** Rebuilds each trail as if its electron had been turning at rest speed. */
  const prefill = (now: number) => {
    const driftRate = 360 / DRIFT_PERIOD_S;
    ATOM_RINGS.forEach((ring, i) => {
      const omega = electronSpeed(ring, 0);
      const history: { x: number; y: number; t: number }[] = [];
      let travelled = 0;
      let previous: [number, number] | null = null;
      for (let tau = 0; tau < Math.abs(ring.periodS) && travelled <= trailLength(i) + 4; tau += 0.1) {
        const point = ringPoint(ring, angles[i] - omega * tau, 200, 200, drift - driftRate * tau);
        const xy = toCanvas(point.x, point.y);
        if (previous) travelled += Math.hypot(xy[0] - previous[0], xy[1] - previous[1]);
        previous = xy;
        history.push({ x: xy[0], y: xy[1], t: now - tau * 1000 });
      }
      trails[i].length = 0;
      for (let k = history.length - 1; k >= 0; k--) {
        pushPoint(trails[i], history[k].x, history[k].y, history[k].t, 0.5, 2000, 4);
      }
      pruneByLength(trails[i], trailLength(i));
    });
  };

  const resize = () => {
    size = host.clientWidth;
    span = size + BLEED_PX * 2;
    ratio = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(span * ratio);
    canvas.height = Math.round(span * ratio);
    membrane = new Membrane(span, span, MEMBRANE_SPACING_PX);
    if (size >= 10) prefill(performance.now());
  };

  const preset = (state: CkOrbState): Resolved => {
    let resolved = presets.get(state);
    if (!resolved) {
      resolved = resolvePreset(state, ORB_SIZE);
      presets.set(state, resolved);
    }
    return resolved;
  };

  /** A braid strand bent by gravity, stroked in a few opacity levels. */
  const drawBraid = (samples: BraidSample[], color: string, alpha: number) => {
    for (const bucket of buckets) bucket.length = 0;
    let px = 0;
    let py = 0;
    samples.forEach((sample, i) => {
      const [dx, dy] = membrane.sample(sample.x, sample.y);
      const x = sample.x + dx;
      const y = sample.y + dy;
      if (i > 0) {
        const level = Math.min(BRAID_LEVELS - 1, Math.floor(sample.life * BRAID_LEVELS));
        buckets[level].push(px, py, x, y);
      }
      px = x;
      py = y;
    });
    ctx.strokeStyle = color;
    buckets.forEach((segments, level) => {
      if (!segments.length) return;
      const life = (level + 0.5) / BRAID_LEVELS;
      ctx.globalAlpha = alpha * Math.pow(life, 1.4);
      ctx.lineWidth = ORBIT_BRAID.width * (0.35 + 0.65 * life);
      ctx.beginPath();
      for (let s = 0; s < segments.length; s += 4) {
        ctx.moveTo(segments[s], segments[s + 1]);
        ctx.lineTo(segments[s + 2], segments[s + 3]);
      }
      ctx.stroke();
    });
  };

  const drawStrand = (samples: WakeSample[], color: string, alpha: number) => {
    ctx.strokeStyle = color;
    for (let i = 1; i < samples.length; i++) {
      const from = samples[i - 1];
      const to = samples[i];
      ctx.globalAlpha = to.alpha * alpha;
      ctx.lineWidth = to.width;
      ctx.beginPath();
      ctx.moveTo(from.x, from.y);
      ctx.lineTo(to.x, to.y);
      ctx.stroke();
    }
  };

  /** `nowMs` is null for the still frame of reduced motion: no bridge, no motion. */
  const draw = (dt: number, near: number, nowMs: number | null) => {
    const scale = size / 400;
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, span, span);
    ctx.lineCap = 'round';

    // Each electron moves on, extends its trail, and its braid is its orbit.
    const electrons = ATOM_RINGS.map((ring, i) => {
      angles[i] += electronSpeed(ring, near) * dt;
      const point = ringPoint(ring, angles[i], 200, 200, drift);
      const [x, y] = toCanvas(point.x, point.y);
      if (nowMs !== null) {
        pushPoint(trails[i], x, y, nowMs, 1.2, 2000, 4);
        pruneByLength(trails[i], trailLength(i));
      }
      const [dx, dy] = membrane.sample(x, y);
      return { x: x + dx, y: y + dy };
    });
    ATOM_RINGS.forEach((ring, i) => {
      const length = trailLength(i);
      const alpha = Math.min(1, ring.alpha + 0.25 * near);
      drawBraid(orbitBraid(trails[i], 0, length, ORBIT_BRAID), palette.electrons[i], alpha);
      drawBraid(orbitBraid(trails[i], Math.PI, length, ORBIT_BRAID), palette.neutral, alpha * 0.8);
    });
    electrons.forEach((electron, i) => {
      ctx.globalAlpha = ELECTRON_ALPHA[i];
      ctx.fillStyle = palette.electrons[i];
      ctx.beginPath();
      ctx.arc(electron.x, electron.y, ELECTRON_RADIUS[i] * scale * (1 + 0.5 * near), 0, Math.PI * 2);
      ctx.fill();
    });

    // The bridge: a braided thread from the nearest electron to the hand.
    if (nowMs !== null && well.mass > 0.02) {
      let nearest = 0;
      let best = Infinity;
      electrons.forEach((electron, i) => {
        const distance = Math.hypot(electron.x - well.x, electron.y - well.y);
        if (distance < best) {
          best = distance;
          nearest = i;
        }
      });
      const strength = bridgeStrength(best, well.mass);
      if (strength > 0.02) {
        const from = electrons[nearest];
        const thread = bridgePoints(from.x, from.y, well.x, well.y, nowMs, 0.18, 3).map((point) => {
          const [dx, dy] = membrane.sample(point.x, point.y);
          return { ...point, x: point.x + dx, y: point.y + dy };
        });
        const twist = (nowMs / 1000) * BRIDGE_TWIST_PER_S;
        const human = nearest === 0 ? palette.neutral : palette.electrons[0];
        drawStrand(strand(thread, nowMs, twist, BRIDGE), palette.electrons[nearest], BRIDGE_ALPHA * strength);
        drawStrand(strand(thread, nowMs, twist + Math.PI, BRIDGE), human, BRIDGE_ALPHA * strength);
      }
    }
    ctx.globalAlpha = 1;

    // The thinking orb: its own painter, every dot bent at its own position.
    const resolved = preset(orbState());
    orbClock += dt * resolved.speed * (1 + 0.25 * near);
    const ox = BLEED_PX + size / 2 - ORB_SIZE / 2;
    const oy = BLEED_PX + size / 2 - ORB_SIZE / 2;
    ctx.setTransform(ratio, 0, 0, ratio, ox * ratio, oy * ratio);
    const bent = warpedContext(ctx, (x, y) => {
      const [dx, dy] = membrane.sample(ox + x, oy + y);
      return [x + dx, y + dy];
    });
    MODE_DRAWS[resolved.mode](bent, ORB_SIZE, orbClock, palette.dark, resolved.opts);
  };

  const render = (now: number) => {
    // The first frame's timestamp can precede `last`: time never runs backwards here.
    const dt = Math.max(0, Math.min(64, now - last)) / 1000;
    last = Math.max(last, now);
    if (size < 10) {
      frame = requestAnimationFrame(render);
      return;
    }
    if (pointer) {
      const box = canvas.getBoundingClientRect();
      const tx = pointer.x - box.left;
      const ty = pointer.y - box.top;
      if (well.mass < 0.01) {
        well.x = tx;
        well.y = ty;
      } else {
        const follow = 1 - Math.exp(-dt * WELL_FOLLOW_PER_S);
        well.x += (tx - well.x) * follow;
        well.y += (ty - well.y) * follow;
      }
    }
    well.mass += ((pointer ? 1 : 0) - well.mass) * (1 - Math.exp(-dt * WELL_MASS_PER_S));
    membrane.step(well.mass > 0.002 ? well : null, dt * 1000);
    const near = nearness(Math.hypot(well.x - span / 2, well.y - span / 2)) * well.mass;
    host.style.setProperty('--near', near.toFixed(3));
    drift += (360 * dt) / DRIFT_PERIOD_S;
    draw(dt, near, last);
    frame = requestAnimationFrame(render);
  };

  const onMove = (event: PointerEvent) => {
    if (event.pointerType === 'touch') return;
    pointer = { x: event.clientX, y: event.clientY };
  };
  const onLeave = (event: MouseEvent) => {
    if (!event.relatedTarget) pointer = null;
  };
  const onTheme = () => {
    palette = readPalette(host);
    if (reduced) draw(0, 0, null);
  };

  resize();
  const resizeObserver = new ResizeObserver(() => {
    resize();
    if (reduced) draw(0, 0, null);
  });
  resizeObserver.observe(host);
  const themeObserver = new MutationObserver(onTheme);
  themeObserver.observe(document.documentElement, {
    attributes: true,
    subtree: true,
    attributeFilter: ['data-theme', 'class'],
  });
  const scheme = matchMedia('(prefers-color-scheme: dark)');
  scheme.addEventListener('change', onTheme);

  if (reduced) {
    draw(0, 0, null);
  } else {
    window.addEventListener('pointermove', onMove, { passive: true });
    document.addEventListener('mouseout', onLeave);
    frame = requestAnimationFrame(render);
  }

  return () => {
    if (frame) cancelAnimationFrame(frame);
    resizeObserver.disconnect();
    themeObserver.disconnect();
    scheme.removeEventListener('change', onTheme);
    window.removeEventListener('pointermove', onMove);
    document.removeEventListener('mouseout', onLeave);
  };
}

/** A drawing context whose arcs are moved by `warp`: the orb's dots all go through `arc`. */
function warpedContext(
  ctx: CanvasRenderingContext2D,
  warp: (x: number, y: number) => [number, number],
): CanvasRenderingContext2D {
  return new Proxy(ctx, {
    get(target, property) {
      if (property === 'arc') {
        return (x: number, y: number, radius: number, start: number, end: number, ccw?: boolean) => {
          const [wx, wy] = warp(x, y);
          target.arc(wx, wy, radius, start, end, ccw);
        };
      }
      const value = Reflect.get(target, property, target);
      return typeof value === 'function' ? value.bind(target) : value;
    },
    set(target, property, value) {
      return Reflect.set(target, property, value, target);
    },
  });
}

function readPalette(host: HTMLElement): Palette {
  const style = getComputedStyle(host);
  const token = (name: string, fallback: string) => style.getPropertyValue(name).trim() || fallback;
  return {
    neutral: token('--ck-fg-5', '#5b6474'),
    electrons: [
      token('--ck-signal-cool', '#1f9db0'),
      token('--ck-fg-3', '#8a94a6'),
      token('--ck-signal-ice', '#9fd8e6'),
    ],
    dark: resolveDark(host),
  };
}

/** Same rule as the thinking orb: the nearest stated theme, then the OS. */
function resolveDark(element: HTMLElement): boolean {
  const stated = element.closest('[data-theme]')?.getAttribute('data-theme');
  if (stated === 'dark' || stated === 'light') return stated === 'dark';
  const classed = element.closest('.dark, .light');
  if (classed) return classed.classList.contains('dark');
  return matchMedia('(prefers-color-scheme: dark)').matches;
}

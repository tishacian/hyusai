import {
  afterNextRender,
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  inject,
  input,
  signal,
  viewChild,
  viewChildren,
} from '@angular/core';
import { ThinkingOrbComponent, type CkOrbState } from '@app/shared/cockpit';
import {
  ATOM_RINGS,
  atomTransform,
  electronSpeed,
  REST_POSE,
  ringPoint,
  settle,
  targetPose,
  type AtomPose,
} from './auth-atom';

/** Where each electron starts on its ring, in radians. */
const ELECTRON_START = [0.55, 2.6, 4.3];
/** The orb thinks a little faster with the pointer on the atom (with hysteresis). */
const ORB_FAST_ABOVE = 0.45;
const ORB_CALM_BELOW = 0.3;

/**
 * The atom of the sign-in panel: three rings on planes of different depth,
 * an electron on each, the thinking orb at the core. It tilts toward the
 * pointer as one instrument, and its electrons speed up as the pointer comes
 * near. Under `prefers-reduced-motion` it stays still.
 */
@Component({
  selector: 'app-auth-atom',
  standalone: true,
  imports: [ThinkingOrbComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div #instrument class="atom" aria-hidden="true">
      @for (ring of rings; track $index) {
        <div class="atom-layer" [style.transform]="'translateZ(' + ring.depth + 'px)'">
          <svg class="atom-rings" viewBox="0 0 400 400" fill="none">
            <ellipse
              [attr.class]="'atom-ring atom-ring-' + ($index + 1)"
              cx="200"
              cy="200"
              [attr.rx]="ring.rx"
              [attr.ry]="ring.ry"
              [attr.transform]="'rotate(' + ring.rotation + ' 200 200)'"
            />
            <circle
              #electron
              [attr.class]="'atom-electron atom-electron-' + ($index + 1)"
              [attr.cx]="starts[$index].x"
              [attr.cy]="starts[$index].y"
              [attr.r]="radii[$index]"
            />
          </svg>
        </div>
      }
      <div class="atom-layer atom-core">
        <div class="atom-glow"></div>
        <ck-thinking-orb class="atom-orb" [state]="orbState()" [size]="64" [speed]="orbSpeed()" />
      </div>
    </div>
  `,
  styles: [
    `
      :host {
        --near: 0;
        display: grid;
        place-items: center;
      }
      .atom {
        position: relative;
        width: 100%;
        height: 100%;
        transform-style: preserve-3d;
        will-change: transform;
      }
      .atom-layer {
        position: absolute;
        inset: 0;
        transform-style: preserve-3d;
      }
      .atom-rings {
        width: 100%;
        height: 100%;
        overflow: visible;
        animation: atom-drift 240s linear infinite;
      }
      @keyframes atom-drift {
        to { transform: rotate(360deg); }
      }
      .atom-ring {
        stroke: var(--ck-fg-5);
        stroke-width: 1.5;
        stroke-dasharray: 2 6;
        stroke-linecap: round;
        transition: opacity 200ms var(--ck-ease-out, ease-out);
      }
      .atom-ring-1 { opacity: calc(0.8 + 0.2 * var(--near)); animation: atom-ring-flow 30s linear infinite; }
      .atom-ring-2 { opacity: calc(0.55 + 0.3 * var(--near)); animation: atom-ring-flow 24s linear infinite reverse; }
      .atom-ring-3 { opacity: calc(0.35 + 0.3 * var(--near)); animation: atom-ring-flow 38s linear infinite; }
      @keyframes atom-ring-flow {
        to { stroke-dashoffset: -128; }
      }
      .atom-electron {
        transform-box: fill-box;
        transform-origin: center;
        transform: scale(calc(1 + 0.5 * var(--near)));
      }
      .atom-electron-1 { fill: var(--ck-signal-cool); opacity: 0.95; }
      .atom-electron-2 { fill: var(--ck-fg-3); opacity: 0.8; }
      .atom-electron-3 { fill: var(--ck-signal-ice); opacity: 0.65; }
      .atom-core {
        display: grid;
        place-items: center;
        transform: translateZ(18px);
      }
      .atom-glow {
        position: absolute;
        width: 220px;
        height: 220px;
        background: radial-gradient(circle closest-side, rgba(125, 211, 252, 0.16), transparent 65%);
        filter: blur(6px);
        opacity: calc(0.75 + 0.25 * var(--near));
        transform: scale(calc(1 + 0.12 * var(--near)));
      }
      .atom-orb { position: relative; }
      @media (prefers-reduced-motion: reduce) {
        .atom-rings,
        .atom-ring-1,
        .atom-ring-2,
        .atom-ring-3 { animation: none; }
      }
    `,
  ],
})
export class AuthAtomComponent {
  readonly orbState = input.required<CkOrbState>();

  protected readonly rings = ATOM_RINGS;
  protected readonly starts = ATOM_RINGS.map((ring, i) => ringPoint(ring, ELECTRON_START[i]));
  protected readonly radii = [3.5, 3, 2.5];
  protected readonly orbSpeed = signal(1);

  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private readonly instrument = viewChild.required<ElementRef<HTMLElement>>('instrument');
  private readonly electrons = viewChildren<ElementRef<SVGCircleElement>>('electron');

  constructor() {
    const destroyRef = inject(DestroyRef);
    afterNextRender(() => {
      if (typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches) return;
      const stop = this.animate();
      destroyRef.onDestroy(stop);
    });
  }

  private animate(): () => void {
    const host = this.host.nativeElement;
    const instrument = this.instrument().nativeElement;
    const electrons = this.electrons().map((ref) => ref.nativeElement);
    const angles = [...ELECTRON_START];
    let pose: AtomPose = REST_POSE;
    let pointer: { x: number; y: number } | null = null;
    let centre = { x: 0, y: 0 };
    let last = performance.now();
    let frame = 0;

    const measure = () => {
      const box = host.getBoundingClientRect();
      centre = { x: box.left + box.width / 2, y: box.top + box.height / 2 };
    };
    const onMove = (event: PointerEvent) => {
      if (event.pointerType === 'touch') return;
      pointer = { x: event.clientX, y: event.clientY };
    };
    const onLeave = (event: MouseEvent) => {
      if (!event.relatedTarget) pointer = null;
    };

    const render = (now: number) => {
      const dt = Math.min(64, now - last);
      last = now;
      const target = pointer
        ? targetPose(pointer.x - centre.x, pointer.y - centre.y, window.innerWidth / 2, window.innerHeight / 2)
        : REST_POSE;
      pose = settle(pose, target, dt);
      instrument.style.transform = atomTransform(pose);
      host.style.setProperty('--near', pose.near.toFixed(3));
      ATOM_RINGS.forEach((ring, i) => {
        angles[i] += (electronSpeed(ring, pose.near) * dt) / 1000;
        const point = ringPoint(ring, angles[i]);
        electrons[i]?.setAttribute('cx', point.x.toFixed(2));
        electrons[i]?.setAttribute('cy', point.y.toFixed(2));
      });
      const speed = this.orbSpeed();
      if (speed === 1 && pose.near > ORB_FAST_ABOVE) this.orbSpeed.set(1.25);
      else if (speed !== 1 && pose.near < ORB_CALM_BELOW) this.orbSpeed.set(1);
      frame = requestAnimationFrame(render);
    };

    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(host);
    window.addEventListener('resize', measure, { passive: true });
    window.addEventListener('scroll', measure, { passive: true });
    window.addEventListener('pointermove', onMove, { passive: true });
    document.addEventListener('mouseout', onLeave);
    frame = requestAnimationFrame(render);

    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      window.removeEventListener('resize', measure);
      window.removeEventListener('scroll', measure);
      window.removeEventListener('pointermove', onMove);
      document.removeEventListener('mouseout', onLeave);
    };
  }
}

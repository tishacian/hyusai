import {
  afterNextRender,
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  inject,
  viewChild,
} from '@angular/core';
import { prune, pushPoint, strand, WAKE_LIFETIME_MS, type WakePoint, type WakeSample } from './cursor-wake';

/** Peak opacity of a fresh strand: the wake accompanies the page, it never covers it. */
const STRAND_ALPHA = 0.75;

/**
 * Decorative wake behind the pointer on the sign-in page: two strands, the
 * brand accent and a neutral one, braid and fade. It draws only while the
 * pointer moves (no frame is scheduled at rest), ignores touch, and is not
 * started at all under `prefers-reduced-motion`.
 */
@Component({
  selector: 'app-cursor-wake',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<canvas #canvas aria-hidden="true"></canvas>`,
  styles: [
    `
      :host {
        position: absolute;
        inset: 0;
        display: block;
        pointer-events: none;
      }
      canvas {
        display: block;
        width: 100%;
        height: 100%;
      }
    `,
  ],
})
export class CursorWakeComponent {
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private readonly canvas = viewChild.required<ElementRef<HTMLCanvasElement>>('canvas');

  constructor() {
    const destroyRef = inject(DestroyRef);
    afterNextRender(() => {
      if (typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches) return;
      const stop = startWake(this.host.nativeElement, this.canvas().nativeElement);
      destroyRef.onDestroy(stop);
    });
  }
}

function startWake(host: HTMLElement, canvas: HTMLCanvasElement): () => void {
  const context = canvas.getContext('2d');
  if (!context) return () => undefined;

  const points: WakePoint[] = [];
  let frame = 0;
  let colors: [string, string] = ['#1f9db0', '#8a94a6'];

  const resize = () => {
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(host.clientWidth * ratio);
    canvas.height = Math.round(host.clientHeight * ratio);
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
  };

  const readColors = () => {
    const style = getComputedStyle(host);
    const accent = style.getPropertyValue('--ck-signal-cool').trim();
    const neutral = style.getPropertyValue('--ck-fg-3').trim();
    colors = [accent || colors[0], neutral || colors[1]];
  };

  const draw = (samples: WakeSample[], color: string) => {
    context.strokeStyle = color;
    for (let i = 1; i < samples.length; i++) {
      const from = samples[i - 1];
      const to = samples[i];
      context.globalAlpha = to.alpha * STRAND_ALPHA;
      context.lineWidth = to.width;
      context.beginPath();
      context.moveTo(from.x, from.y);
      context.lineTo(to.x, to.y);
      context.stroke();
    }
  };

  const render = (now: number) => {
    prune(points, now, WAKE_LIFETIME_MS);
    context.clearRect(0, 0, host.clientWidth, host.clientHeight);
    if (points.length < 2) {
      frame = 0;
      return;
    }
    draw(strand(points, now, 0), colors[0]);
    draw(strand(points, now, Math.PI), colors[1]);
    context.globalAlpha = 1;
    frame = requestAnimationFrame(render);
  };

  const onMove = (event: PointerEvent) => {
    if (event.pointerType === 'touch') return;
    const box = host.getBoundingClientRect();
    if (!pushPoint(points, event.clientX - box.left, event.clientY - box.top, performance.now())) return;
    if (!frame) {
      readColors();
      frame = requestAnimationFrame(render);
    }
  };

  context.lineCap = 'round';
  resize();
  const observer = new ResizeObserver(() => {
    resize();
    context.lineCap = 'round';
  });
  observer.observe(host);
  window.addEventListener('pointermove', onMove, { passive: true });

  return () => {
    window.removeEventListener('pointermove', onMove);
    observer.disconnect();
    if (frame) cancelAnimationFrame(frame);
  };
}

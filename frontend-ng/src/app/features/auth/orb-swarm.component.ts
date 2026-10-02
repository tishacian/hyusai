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
import { swarmFrame, swarmLayout, type SwarmPoint } from './orb-swarm';

/**
 * Points around the sign-in orb. They ease toward the openness the pointer
 * asks for, so a pass opens the shell and leaving lets it gather again.
 */
@Component({
  selector: 'app-auth-orb-swarm',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<canvas #canvas aria-hidden="true"></canvas>`,
  styles: [
    `
      :host {
        position: absolute;
        left: 50%;
        top: 50%;
        width: 168px;
        height: 168px;
        transform: translate(-50%, -50%);
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
export class AuthOrbSwarmComponent {
  readonly open = input(0);
  readonly aimX = input(0);
  readonly aimY = input(0);

  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private readonly canvas = viewChild.required<ElementRef<HTMLCanvasElement>>('canvas');

  constructor() {
    const destroyRef = inject(DestroyRef);
    afterNextRender(() => {
      const canvas = this.canvas().nativeElement;
      const context = canvas.getContext('2d');
      if (!context) return;
      const reduced = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
      const points: SwarmPoint[] = swarmLayout();
      let frame = 0;
      let eased = 0;
      let last = performance.now();

      const resize = () => {
        const ratio = Math.min(window.devicePixelRatio || 1, 2);
        canvas.width = Math.round(this.host.nativeElement.clientWidth * ratio);
        canvas.height = Math.round(this.host.nativeElement.clientHeight * ratio);
        context.setTransform(ratio, 0, 0, ratio, 0, 0);
      };

      const paint = (now: number) => {
        const dt = Math.min(48, now - last);
        last = now;
        const target = reduced ? 0 : this.open();
        eased += (target - eased) * (1 - Math.exp(-dt / 220));
        if (Math.abs(target - eased) < 0.002) eased = target;
        const style = getComputedStyle(this.host.nativeElement);
        const ink = style.getPropertyValue('--ck-signal-cool').trim() || '#1f9db0';
        const width = this.host.nativeElement.clientWidth;
        const height = this.host.nativeElement.clientHeight;
        context.clearRect(0, 0, width, height);
        context.fillStyle = ink;
        const dots = swarmFrame(points, eased, this.aimX(), this.aimY(), reduced ? 0 : now / 1000);
        for (const dot of dots) {
          context.globalAlpha = dot.alpha;
          context.beginPath();
          context.arc(width / 2 + dot.x, height / 2 + dot.y, dot.radius, 0, Math.PI * 2);
          context.fill();
        }
        context.globalAlpha = 1;
      };

      resize();
      const observer = new ResizeObserver(resize);
      observer.observe(this.host.nativeElement);
      const loop = (now: number) => {
        paint(now);
        frame = requestAnimationFrame(loop);
      };
      if (reduced) paint(0);
      else frame = requestAnimationFrame(loop);
      destroyRef.onDestroy(() => {
        observer.disconnect();
        if (frame) cancelAnimationFrame(frame);
      });
    });
  }
}

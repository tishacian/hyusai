/**
 * `ck-thinking-orb` — what a model or an agent is doing, as one dotted orb.
 *
 * A spinner says "wait". These say which kind of work is under way, and the
 * distinction earns its place on screens where several kinds happen in sequence:
 * a workspace chat retrieves, then composes; a run classifies, then waits for a
 * person. Six states, two tuned sizes, monochrome ink that follows the surface
 * it sits on — so the same element works in the dark cockpit and in a tenant's
 * light business app without being restyled.
 *
 * The drawing is upstream's, vendored under `./vendor` (MIT, see its README for
 * why it is copied rather than installed). This file is the part that has to be
 * ours: the canvas, the frame loop, and the theme.
 *
 * Three properties of the loop are deliberate and easy to lose in a rewrite:
 * every instance reads one shared clock (`performance.now`), so orbs on the same
 * screen stay in phase rather than drifting into visual noise; an instance stops
 * when it scrolls out of view or the tab is hidden, so a long page of them costs
 * nothing; and `prefers-reduced-motion` renders a single representative frame,
 * which still has to be painted or the surface would show a hole.
 */
import {
  afterNextRender,
  ChangeDetectionStrategy,
  Component,
  computed,
  DestroyRef,
  effect,
  ElementRef,
  inject,
  input,
  signal,
  viewChild,
} from '@angular/core';
import { MODE_DRAWS } from './vendor/engine/registry';
import { resolvePreset } from './vendor/presets';
import type { OrbSize, OrbState, OrbTheme } from './vendor/types';
import { I18nService } from '@app/core/i18n.service';

export type { OrbSize as CkOrbSize, OrbState as CkOrbState, OrbTheme as CkOrbTheme };

/** Spoken by a screen reader in place of the animation. */
const LABELS: Record<OrbState, string> = {
  working: 'common.orb.working',
  searching: 'common.orb.searching',
  solving: 'common.orb.solving',
  listening: 'common.orb.listening',
  composing: 'common.orb.composing',
  shaping: 'common.orb.shaping',
};

@Component({
  selector: 'ck-thinking-orb',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<canvas
    #canvas
    role="img"
    [attr.aria-label]="label() || fallbackLabel()"
    [style.width.px]="size()"
    [style.height.px]="size()"
  ></canvas>`,
  styles: [
    `
      :host {
        display: inline-block;
        line-height: 0;
      }
      canvas {
        display: block;
      }
    `,
  ],
})
export class ThinkingOrbComponent {
  private readonly i18n = inject(I18nService);
  /** Which kind of work is under way. */
  readonly state = input<OrbState>('working');
  /** 64 for a chat-avatar slot, 20 inline in a line of text. Not a scale factor. */
  readonly size = input<OrbSize>(64);
  /** `auto` follows the nearest `data-theme`, then the OS preference. */
  readonly theme = input<OrbTheme>('auto');
  /** Multiplier over the state's baked speed. */
  readonly speed = input(1);
  /** Freeze on the current frame without unmounting. */
  readonly paused = input(false);
  /** Overrides the per-state screen-reader label. */
  readonly label = input<string>('');

  private readonly host = inject(ElementRef<HTMLElement>);
  private readonly canvas = viewChild<ElementRef<HTMLCanvasElement>>('canvas');

  /** Resolved once the DOM exists, and again whenever the surface flips. */
  private readonly dark = signal(true);
  private readonly reduced = signal(false);

  protected readonly fallbackLabel = computed(() => this.i18n.t(LABELS[this.state()]));

  private stop: (() => void) | null = null;

  constructor() {
    const destroyRef = inject(DestroyRef);

    afterNextRender(() => {
      this.dark.set(this.resolveDark());
      this.reduced.set(matchMedia('(prefers-reduced-motion: reduce)').matches);

      // The theme can flip under a mounted orb: the tenant apps offer a light
      // toggle, and the OS preference changes on its own at dusk.
      const motion = matchMedia('(prefers-reduced-motion: reduce)');
      const scheme = matchMedia('(prefers-color-scheme: dark)');
      const onMotion = () => this.reduced.set(motion.matches);
      const onScheme = () => this.dark.set(this.resolveDark());
      motion.addEventListener('change', onMotion);
      scheme.addEventListener('change', onScheme);

      // `data-theme` is an attribute on an ancestor, so the observer watches the
      // document rather than this element — the ancestor may be several levels up
      // and is not known here.
      const observer = new MutationObserver(() => this.dark.set(this.resolveDark()));
      observer.observe(document.documentElement, {
        attributes: true,
        subtree: true,
        attributeFilter: ['data-theme', 'class'],
      });

      destroyRef.onDestroy(() => {
        motion.removeEventListener('change', onMotion);
        scheme.removeEventListener('change', onScheme);
        observer.disconnect();
        this.stop?.();
      });
    });

    // Every input the painter reads is a dependency: a change restarts the loop
    // rather than mutating it, which keeps the canvas sized correctly when the
    // size preset changes.
    effect(() => this.run());
  }

  /**
   * Dark means light ink. `auto` asks the nearest ancestor that states a theme —
   * the convention the cockpit and the tenant shells already write — and falls
   * back to the OS preference when nothing does.
   */
  private resolveDark(): boolean {
    const pinned = this.theme();
    if (pinned !== 'auto') return pinned === 'dark';
    const element = this.host.nativeElement as HTMLElement;
    const stated = element.closest?.('[data-theme]')?.getAttribute('data-theme');
    if (stated === 'dark' || stated === 'light') return stated === 'dark';
    const classed = element.closest?.('.dark, .light');
    if (classed) return classed.classList.contains('dark');
    return matchMedia('(prefers-color-scheme: dark)').matches;
  }

  private run(): void {
    const state = this.state();
    const size = this.size();
    const speed = this.speed();
    const paused = this.paused();
    const dark = this.dark();
    const reduced = this.reduced();

    this.stop?.();
    this.stop = null;

    const canvas = this.canvas()?.nativeElement;
    const context = canvas?.getContext('2d');
    if (!canvas || !context) return;

    // Capped at 2: past that the extra pixels cost more than they show.
    const ratio = Math.min(2, globalThis.devicePixelRatio || 1);
    canvas.width = Math.round(size * ratio);
    canvas.height = Math.round(size * ratio);

    const { mode, speed: baked, opts } = resolvePreset(state, size);
    const draw = MODE_DRAWS[mode];
    const rate = baked * speed;

    const frame = (seconds: number) => {
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      context.clearRect(0, 0, size, size);
      draw(context, size, seconds, dark, opts);
    };

    if (reduced) {
      // One deterministic frame, chosen upstream as representative of the state.
      frame(0.6);
      return;
    }

    let handle = 0;
    let running = false;
    const loop = () => {
      frame((performance.now() / 1000) * rate);
      if (running) handle = requestAnimationFrame(loop);
    };
    const start = () => {
      if (running || paused) return;
      running = true;
      handle = requestAnimationFrame(loop);
    };
    const halt = () => {
      running = false;
      cancelAnimationFrame(handle);
    };

    // Paint once even while paused or offscreen: an empty canvas reads as a
    // broken component, not as a still one.
    frame((performance.now() / 1000) * rate);

    let onScreen = true;
    const observer = new IntersectionObserver(([entry]) => {
      onScreen = entry.isIntersecting;
      if (onScreen && document.visibilityState !== 'hidden') start();
      else halt();
    });
    observer.observe(canvas);

    const onVisibility = () => {
      if (document.visibilityState === 'hidden') halt();
      else if (onScreen) start();
    };
    document.addEventListener('visibilitychange', onVisibility);

    this.stop = () => {
      halt();
      observer.disconnect();
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }
}

import {
  afterNextRender,
  Component,
  computed,
  DestroyRef,
  ElementRef,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { I18nService } from '@app/core/i18n.service';
import type { I18nKey } from '@app/core/i18n.dict';
import { ThinkingOrbComponent, type CkOrbState } from '@app/shared/cockpit';
import { StatusPulseComponent } from '@app/shared/ui/status-pulse.component';
import { CursorWakeComponent } from './cursor-wake.component';
import {
  magneticInfluence,
  magneticTransform,
  type WakeField,
} from './cursor-wake';

/**
 * The instrument panel walks one abstract system — objective, retrieve,
 * reason, decide, output — and the orb overhead changes state in step, so
 * the first thing a visitor sees is the product's core promise (watchable
 * reasoning) rather than a static illustration. Labels are i18n keys; orb
 * states come from the six vendored presets.
 */
const PANEL_FLOW_STEPS: readonly { label: I18nKey; orb: CkOrbState }[] = [
  { label: 'auth.panel.node_objective', orb: 'shaping' },
  { label: 'auth.panel.node_retrieve', orb: 'searching' },
  { label: 'auth.panel.node_reason', orb: 'solving' },
  { label: 'auth.panel.node_decide', orb: 'working' },
  { label: 'auth.panel.node_output', orb: 'composing' },
];

/** Step cadence. Slow enough to read, fast enough to notice it moves. */
const STEP_INTERVAL_MS = 3600;

/** The frame shown when `prefers-reduced-motion` pins the walk. */
const REDUCED_MOTION_STEP = 3;

/**
 * Cockpit-grade authentication shell, split-screen edition.
 *
 * Left: an instrument panel — brand, live thinking orb inside static orbit
 * rings, the product statement, and a generic five-node flow line whose
 * active node follows the orb's state. Right: the auth card (sign-in,
 * sign-up, reset) over the same `--ck-*` surfaces used across the app.
 * Below 960px the panel yields to a compact brand bar so the card keeps
 * the full width.
 */
@Component({
  selector: 'app-auth-shell',
  standalone: true,
  imports: [RouterOutlet, StatusPulseComponent, ThinkingOrbComponent, CursorWakeComponent],
  template: `
    <div class="ck-auth-shell">
      <!-- Layered ambient backdrop (grid + subtle blooms) -->
      <div class="ck-auth-bg" aria-hidden="true">
        <div class="ck-auth-grid"></div>
        <div class="ck-auth-bloom ck-auth-bloom-cool"></div>
        <div class="ck-auth-bloom ck-auth-bloom-violet"></div>
        <div class="ck-auth-scanline"></div>
        <app-cursor-wake (wakeChange)="wakeChanged($event)" />
      </div>

      <!-- Compact bar, only when the panel is folded away (<960px) -->
      <header class="ck-auth-mobilebar">
        <div class="ck-auth-brand">
          <span class="ck-auth-mark" aria-hidden="true">
            <img src="/assets/brand/agentium-mark.svg" alt="" width="34" height="34" />
          </span>
          <span class="ck-auth-wordmark">Agentium</span>
          <span class="ck-auth-wordmark-dot" aria-hidden="true"></span>
          <span class="ck-auth-tagline">{{ i18n.t('auth.shell.tagline') }}</span>
        </div>
      </header>

      <!-- Left instrument panel -->
      <aside class="ck-auth-panel">
        <div class="ck-auth-panel-top">
          <div class="ck-auth-brand">
            <span class="ck-auth-mark" aria-hidden="true">
              <img src="/assets/brand/agentium-mark.svg" alt="" width="34" height="34" />
            </span>
            <span class="ck-auth-wordmark">Agentium</span>
            <span class="ck-auth-wordmark-dot" aria-hidden="true"></span>
            <span class="ck-auth-tagline">{{ i18n.t('auth.shell.tagline') }}</span>
          </div>
          <div class="ck-auth-telemetry" role="status" [attr.aria-label]="i18n.t('auth.shell.status_aria')">
            <app-status-pulse tone="success" />
            <span class="ck-auth-telemetry-label">{{ i18n.t('auth.shell.status') }}</span>
          </div>
        </div>

        <div class="ck-auth-hero">
          <div #orbit class="ck-auth-orbit" aria-hidden="true">
            <div class="ck-auth-orbit-field" [style.transform]="orbitTransform()">
              <svg class="ck-auth-orbit-rings" viewBox="0 0 400 400" fill="none">
                <g [attr.transform]="ringTransform(0.45)">
                  <ellipse class="ck-auth-ring ck-auth-ring-1" cx="200" cy="200" rx="188" ry="72" transform="rotate(-24 200 200)" />
                </g>
                <g [attr.transform]="ringTransform(0.75)">
                  <ellipse class="ck-auth-ring ck-auth-ring-2" cx="200" cy="200" rx="160" ry="62" transform="rotate(20 200 200)" />
                </g>
                <g [attr.transform]="ringTransform(1.1)">
                  <ellipse class="ck-auth-ring ck-auth-ring-3" cx="200" cy="200" rx="128" ry="112" transform="rotate(-6 200 200)" />
                </g>
                <circle
                  class="ck-auth-mote ck-auth-mote-cool"
                  cx="342" cy="141" r="3.5"
                  [attr.transform]="moteTransform(342, 141, 1)"
                />
                <circle
                  class="ck-auth-mote ck-auth-mote-violet"
                  cx="82" cy="262" r="3"
                  [attr.transform]="moteTransform(82, 262, 0.82)"
                />
                <circle
                  class="ck-auth-mote ck-auth-mote-ice"
                  cx="255" cy="322" r="2.5"
                  [attr.transform]="moteTransform(255, 322, 0.68)"
                />
              </svg>
              <div class="ck-auth-orb-glow" [style.opacity]="orbGlowOpacity()" [style.transform]="orbGlowTransform()"></div>
              <ck-thinking-orb
                class="ck-auth-orb"
                [state]="orbState()"
                [size]="64"
                [speed]="orbSpeed()"
                [style.filter]="orbFilter()"
              />
            </div>
          </div>
          <div class="ck-auth-hero-copy">
            <span class="ck-auth-hero-eyebrow">{{ i18n.t('auth.panel.eyebrow') }}</span>
            <h1 class="ck-auth-hero-title">{{ i18n.t('auth.panel.headline') }}</h1>
          </div>
        </div>

        <div class="ck-auth-flowline">
          <span class="ck-auth-flowline-caption">{{ i18n.t('auth.panel.flow_caption') }}</span>
          <div class="ck-auth-flowline-nodes">
            @for (step of steps; track step.label; let i = $index) {
              @if (i > 0) {
                <span class="ck-auth-flowline-arrow" aria-hidden="true">→</span>
              }
              <span class="ck-auth-flowline-node" [class.is-active]="i === activeStep()">
                <span class="ck-auth-flowline-glyph" aria-hidden="true"></span>
                <span class="ck-auth-flowline-label">{{ i18n.t(step.label) }}</span>
              </span>
            }
          </div>
        </div>
      </aside>

      <!-- Right access column -->
      <main class="ck-auth-main">
        <div class="ck-auth-card">
          <div class="ck-auth-card-rail" aria-hidden="true"></div>
          <router-outlet />
        </div>

        <footer class="ck-auth-footer">
          <span class="ck-auth-footer-chip">
            <span class="ck-live-dot cool" aria-hidden="true"></span>
            {{ i18n.t('auth.shell.encrypted') }}
          </span>
          <span class="ck-auth-footer-sep" aria-hidden="true"></span>
          <span class="ck-auth-footer-chip">{{ i18n.t('auth.shell.soc2') }}</span>
          <span class="ck-auth-footer-sep" aria-hidden="true"></span>
          <span class="ck-auth-footer-chip">{{ i18n.t('auth.shell.sso') }}</span>
        </footer>
      </main>
    </div>
  `,
  styles: [
    `
      :host { display: block; }

      .ck-auth-shell {
        position: relative;
        min-height: 100vh;
        min-height: 100dvh;
        background: var(--ck-bg-void);
        color: var(--ck-fg-1);
        font-family: var(--ck-font-sans);
        display: flex;
        flex-direction: row;
        overflow: hidden;
      }

      /* ---- Backdrop layers ---- */
      .ck-auth-bg {
        position: absolute;
        inset: 0;
        pointer-events: none;
        overflow: hidden;
      }
      .ck-auth-grid {
        position: absolute;
        inset: 0;
        background-image:
          linear-gradient(var(--ck-stroke-1) 1px, transparent 1px),
          linear-gradient(90deg, var(--ck-stroke-1) 1px, transparent 1px);
        background-size: 48px 48px;
        mask-image: radial-gradient(ellipse 80% 70% at 50% 50%, rgba(0, 0, 0, 0.9), transparent 75%);
        -webkit-mask-image: radial-gradient(ellipse 80% 70% at 50% 50%, rgba(0, 0, 0, 0.9), transparent 75%);
        opacity: 0.7;
      }
      .ck-auth-bloom {
        position: absolute;
        width: 720px;
        height: 720px;
        border-radius: 50%;
        filter: blur(150px);
        opacity: 0.28;
      }
      .ck-auth-bloom-cool {
        top: -260px;
        left: -240px;
        background: var(--ck-signal-cool);
      }
      .ck-auth-bloom-violet {
        bottom: -280px;
        right: -260px;
        background: var(--ck-signal-violet);
        opacity: 0.22;
      }
      .ck-auth-scanline {
        position: absolute;
        inset: 0;
        background: repeating-linear-gradient(
          to bottom,
          transparent 0px,
          transparent 3px,
          rgba(255, 255, 255, 0.015) 3px,
          rgba(255, 255, 255, 0.015) 4px
        );
        mix-blend-mode: overlay;
        opacity: 0.35;
      }

      /* ---- Shared brand row ---- */
      .ck-auth-brand {
        display: inline-flex;
        align-items: center;
        gap: 10px;
        min-width: 0;
      }
      .ck-auth-mark {
        position: relative;
        width: 34px;
        height: 34px;
        flex: 0 0 auto;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        border-radius: 8px;
        box-shadow: 0 0 0 1px var(--ck-stroke-hot), var(--ck-glow-cool);
        overflow: hidden;
      }
      .ck-auth-wordmark {
        font-family: var(--ck-font-mono);
        font-size: 14px;
        font-weight: 600;
        letter-spacing: 0.04em;
        color: var(--ck-fg-1);
      }
      .ck-auth-wordmark-dot {
        width: 4px;
        height: 4px;
        border-radius: 50%;
        background: var(--ck-signal-cool);
        box-shadow: 0 0 8px var(--ck-signal-cool);
      }
      .ck-auth-tagline {
        font-family: var(--ck-font-mono);
        font-size: 10px;
        letter-spacing: 0.18em;
        text-transform: uppercase;
        color: var(--ck-fg-4);
        white-space: nowrap;
      }
      .ck-auth-telemetry {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 6px 10px;
        border: 1px solid var(--ck-stroke-2);
        background: var(--ck-bg-panel);
        border-radius: var(--ck-radius-sm);
        flex: 0 0 auto;
      }
      .ck-auth-telemetry-label {
        font-family: var(--ck-font-mono);
        font-size: 9px;
        letter-spacing: 0.18em;
        text-transform: uppercase;
        color: var(--ck-fg-3);
        white-space: nowrap;
      }

      /* ---- Compact bar (panel folded) ---- */
      .ck-auth-mobilebar {
        display: none;
        position: relative;
        z-index: 2;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        padding: 14px 18px;
        border-bottom: 1px solid var(--ck-stroke-1);
      }

      /* ---- Left instrument panel ---- */
      .ck-auth-panel {
        position: relative;
        z-index: 2;
        flex: 1 1 58%;
        min-width: 0;
        display: flex;
        flex-direction: column;
        padding: 26px 44px 30px;
        border-right: 1px solid var(--ck-stroke-1);
      }
      .ck-auth-panel-top {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 16px;
      }

      .ck-auth-hero {
        position: relative;
        flex: 1;
        display: flex;
        flex-direction: column;
        justify-content: center;
        min-height: 0;
      }
      .ck-auth-orbit {
        position: absolute;
        top: 50%;
        right: clamp(-60px, 2vw, 60px);
        transform: translateY(-54%);
        width: clamp(300px, 34vw, 460px);
        aspect-ratio: 1 / 1;
        display: grid;
        place-items: center;
      }
      .ck-auth-orbit-field {
        position: relative;
        width: 100%;
        height: 100%;
        display: grid;
        place-items: center;
        will-change: transform;
      }
      .ck-auth-orbit-rings {
        position: absolute;
        inset: 0;
        width: 100%;
        height: 100%;
        animation: ck-auth-orbit-drift 72s linear infinite;
      }
      @keyframes ck-auth-orbit-drift {
        to { transform: rotate(360deg); }
      }
      @media (prefers-reduced-motion: reduce) {
        .ck-auth-orbit-rings { animation: none; }
      }
      .ck-auth-ring {
        stroke: var(--ck-fg-5);
        stroke-width: 1.5;
        stroke-dasharray: 2 6;
        stroke-linecap: round;
      }
      .ck-auth-ring-1 {
        opacity: 0.8;
        animation: ck-auth-ring-flow 22s linear infinite;
      }
      .ck-auth-ring-2 {
        opacity: 0.55;
        animation: ck-auth-ring-flow 15s linear infinite reverse;
      }
      .ck-auth-ring-3 {
        opacity: 0.35;
        animation: ck-auth-ring-flow 29s linear infinite;
      }
      @keyframes ck-auth-ring-flow {
        to { stroke-dashoffset: -128; }
      }
      @media (prefers-reduced-motion: reduce) {
        .ck-auth-ring,
        .ck-auth-ring-1,
        .ck-auth-ring-2,
        .ck-auth-ring-3 { animation: none; }
      }
      .ck-auth-mote-cool { fill: var(--ck-signal-cool); opacity: 0.9; }
      .ck-auth-mote-violet { fill: var(--ck-signal-violet); opacity: 0.75; }
      .ck-auth-mote-ice { fill: var(--ck-signal-ice); opacity: 0.55; }
      .ck-auth-orb-glow {
        position: absolute;
        width: 220px;
        height: 220px;
        border-radius: 50%;
        background: radial-gradient(circle, rgba(125, 211, 252, 0.16), transparent 65%);
        filter: blur(6px);
      }
      .ck-auth-orb { position: relative; }

      .ck-auth-hero-copy {
        position: relative;
        z-index: 1;
        max-width: min(520px, 62%);
      }
      .ck-auth-hero-eyebrow {
        display: block;
        font-family: var(--ck-font-mono);
        font-size: 10px;
        letter-spacing: 0.24em;
        text-transform: uppercase;
        color: var(--ck-signal-cool);
        margin-bottom: 14px;
      }
      .ck-auth-hero-title {
        margin: 0;
        font-family: var(--ck-font-sans);
        font-size: clamp(30px, 3.4vw, 46px);
        font-weight: 650;
        letter-spacing: -0.02em;
        line-height: 1.12;
        color: var(--ck-fg-1);
        text-wrap: balance;
      }

      /* ---- Flow line ---- */
      .ck-auth-flowline {
        position: relative;
        z-index: 1;
        margin-top: 18px;
      }
      .ck-auth-flowline-caption {
        display: block;
        font-family: var(--ck-font-mono);
        font-size: 9px;
        letter-spacing: 0.22em;
        text-transform: uppercase;
        color: var(--ck-fg-4);
        margin-bottom: 12px;
      }
      .ck-auth-flowline-nodes {
        display: flex;
        align-items: stretch;
        gap: 8px;
        flex-wrap: wrap;
      }
      .ck-auth-flowline-node {
        display: inline-flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        gap: 7px;
        min-width: 86px;
        padding: 12px 14px;
        border: 1px solid var(--ck-stroke-2);
        border-radius: var(--ck-radius-md);
        background: var(--ck-bg-panel);
        transition:
          border-color var(--ck-dur-slow) var(--ck-ease-out),
          box-shadow var(--ck-dur-slow) var(--ck-ease-out),
          background var(--ck-dur-slow) var(--ck-ease-out);
      }
      .ck-auth-flowline-glyph {
        width: 14px;
        height: 14px;
        border-radius: 50%;
        border: 1px solid var(--ck-fg-4);
        display: inline-flex;
        align-items: center;
        justify-content: center;
        transition: border-color var(--ck-dur-slow) var(--ck-ease-out);
      }
      .ck-auth-flowline-glyph::after {
        content: '';
        width: 4px;
        height: 4px;
        border-radius: 50%;
        background: var(--ck-fg-4);
        transition: background var(--ck-dur-slow) var(--ck-ease-out), box-shadow var(--ck-dur-slow) var(--ck-ease-out);
      }
      .ck-auth-flowline-label {
        font-family: var(--ck-font-mono);
        font-size: 9px;
        letter-spacing: 0.14em;
        text-transform: uppercase;
        color: var(--ck-fg-3);
        transition: color var(--ck-dur-slow) var(--ck-ease-out);
        white-space: nowrap;
      }
      .ck-auth-flowline-node.is-active {
        border-color: var(--ck-stroke-hot);
        background: var(--ck-bg-panel-hi);
        box-shadow: var(--ck-glow-cool);
      }
      .ck-auth-flowline-node.is-active .ck-auth-flowline-glyph {
        border-color: var(--ck-signal-cool);
      }
      .ck-auth-flowline-node.is-active .ck-auth-flowline-glyph::after {
        background: var(--ck-signal-cool);
        box-shadow: 0 0 8px var(--ck-signal-cool);
      }
      .ck-auth-flowline-node.is-active .ck-auth-flowline-label {
        color: var(--ck-fg-1);
      }
      .ck-auth-flowline-arrow {
        align-self: center;
        font-family: var(--ck-font-mono);
        font-size: 11px;
        color: var(--ck-fg-5);
      }

      /* ---- Right access column ---- */
      .ck-auth-main {
        position: relative;
        z-index: 2;
        flex: 1 1 42%;
        min-width: 0;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        padding: 32px 28px 40px;
      }
      .ck-auth-card {
        position: relative;
        width: 100%;
        max-width: 420px;
        background: var(--ck-bg-panel);
        border: 1px solid var(--ck-stroke-2);
        border-radius: var(--ck-radius-lg);
        padding: 28px 28px 24px;
        box-shadow: var(--ck-shadow-panel);
      }
      .ck-auth-card-rail {
        position: absolute;
        left: 0;
        top: 16px;
        bottom: 16px;
        width: 2px;
        border-radius: 2px;
        background: linear-gradient(180deg, var(--ck-signal-cool), transparent 70%);
        opacity: 0.55;
      }

      /* ---- Footer chips ---- */
      .ck-auth-footer {
        margin-top: 22px;
        display: inline-flex;
        align-items: center;
        gap: 10px;
        flex-wrap: wrap;
        justify-content: center;
      }
      .ck-auth-footer-chip {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        font-family: var(--ck-font-mono);
        font-size: 9px;
        letter-spacing: 0.18em;
        text-transform: uppercase;
        color: var(--ck-fg-4);
      }
      .ck-auth-footer-sep {
        width: 2px;
        height: 2px;
        border-radius: 50%;
        background: var(--ck-fg-5);
      }

      /* ---- Fold the panel away on narrow viewports ---- */
      @media (max-width: 959px) {
        .ck-auth-shell { flex-direction: column; }
        .ck-auth-panel { display: none; }
        .ck-auth-mobilebar { display: flex; }
        .ck-auth-main { flex: 1; padding: 28px 20px 40px; }
        .ck-auth-card { padding: 22px 20px 20px; }
      }
      @media (max-width: 640px) {
        .ck-auth-tagline { display: none; }
      }
    `,
  ],
})
export class AuthShellComponent {
  protected readonly i18n = inject(I18nService);
  protected readonly steps = PANEL_FLOW_STEPS;
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private readonly orbit = viewChild.required<ElementRef<HTMLElement>>('orbit');

  protected readonly activeStep = signal(REDUCED_MOTION_STEP);
  protected readonly orbState = computed<CkOrbState>(() => PANEL_FLOW_STEPS[this.activeStep()].orb);
  private readonly wake = signal<WakeField | null>(null);
  private readonly magneticField = signal<WakeField | null>(null);
  private readonly orbitBox = signal<{ x: number; y: number; width: number } | null>(null);
  private magneticFrame = 0;
  private readonly destroyRef = inject(DestroyRef);

  private readonly influence = computed(() => {
    const box = this.orbitBox();
    const field = this.magneticField();
    if (!box) return magneticInfluence(null, { x: 0, y: 0 });
    return magneticInfluence(field, { x: box.x, y: box.y });
  });

  protected readonly orbitTransform = computed(() => {
    const influence = this.influence();
    const strength = influence.strength;
    if (strength <= 0) return 'none';
    const shift = 24 * strength;
    const tilt = 2.4 * strength * (this.magneticField()?.vx ?? 0);
    const scale = 1 + 0.05 * strength;
    return `translate3d(${(influence.x * shift).toFixed(2)}px, ${(influence.y * shift).toFixed(2)}px, 0) rotate(${tilt.toFixed(2)}deg) scale(${scale.toFixed(3)})`;
  });

  protected readonly orbSpeed = computed(() => (this.influence().strength > 0.08 ? 1.55 : 1));
  protected readonly orbGlowOpacity = computed(() => (0.78 + 0.22 * this.influence().strength).toFixed(3));
  protected readonly orbGlowTransform = computed(() => {
    const strength = this.influence().strength;
    return `scale(${(1 + 0.3 * strength).toFixed(3)})`;
  });
  protected readonly orbFilter = computed(() => {
    const strength = this.influence().strength;
    return strength <= 0 ? 'none' : `brightness(${(1 + 0.3 * strength).toFixed(3)})`;
  });

  constructor() {
    afterNextRender(() => {
      if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
      this.activeStep.set(0);
      const timer = setInterval(
        () => this.activeStep.update((i) => (i + 1) % PANEL_FLOW_STEPS.length),
        STEP_INTERVAL_MS,
      );
      this.destroyRef.onDestroy(() => clearInterval(timer));

      const measure = () => {
        const shell = this.host.nativeElement.getBoundingClientRect();
        const box = this.orbit().nativeElement.getBoundingClientRect();
        this.orbitBox.set({
          x: box.left - shell.left + box.width / 2,
          y: box.top - shell.top + box.height / 2,
          width: box.width,
        });
      };
      const observer = new ResizeObserver(measure);
      observer.observe(this.orbit().nativeElement);
      window.addEventListener('resize', measure);
      this.destroyRef.onDestroy(() => {
        observer.disconnect();
        window.removeEventListener('resize', measure);
      });
    });
  }

  protected wakeChanged(field: WakeField | null): void {
    this.wake.set(field);
    if (!this.magneticFrame) this.startMagneticRelaxation();
  }

  protected ringTransform(depth: number): string {
    return magneticTransform(this.influence(), this.magneticField(), depth);
  }

  protected moteTransform(x: number, y: number, factor: number): string {
    const box = this.orbitBox();
    const field = this.magneticField();
    if (!box || !field) return '';
    const scale = box.width / 400;
    const local = magneticInfluence(field, {
      x: box.x + (x - 200) * scale,
      y: box.y + (y - 200) * scale,
    }, Math.max(120, box.width * 0.5));
    if (local.strength <= 0) return '';
    const push = 34 * local.strength * factor;
    return `translate(${(local.x * push).toFixed(2)} ${(local.y * push).toFixed(2)})`;
  }

  private startMagneticRelaxation(): void {
    let last = performance.now();

    const step = (now: number) => {
      const dt = Math.min(64, now - last);
      last = now;
      const target = this.wake();
      const current = this.magneticField();
      const rise = 1 - Math.exp(-dt / 80);
      const fall = 1 - Math.exp(-dt / 380);

      if (!target) {
        if (!current) {
          this.magneticFrame = 0;
          return;
        }
        const energy = current.energy * (1 - fall);
        if (energy < 0.002) {
          this.magneticField.set(null);
          this.magneticFrame = 0;
          return;
        }
        this.magneticField.set({ ...current, energy });
        this.magneticFrame = requestAnimationFrame(step);
        return;
      }

      if (!current) {
        this.magneticField.set({ ...target, energy: target.energy * rise });
      } else {
        this.magneticField.set({
          x: current.x + (target.x - current.x) * rise,
          y: current.y + (target.y - current.y) * rise,
          vx: current.vx + (target.vx - current.vx) * rise,
          vy: current.vy + (target.vy - current.vy) * rise,
          energy: current.energy + (target.energy - current.energy) * rise,
        });
      }
      this.magneticFrame = requestAnimationFrame(step);
    };

    this.magneticFrame = requestAnimationFrame(step);
    this.destroyRef.onDestroy(() => {
      if (this.magneticFrame) cancelAnimationFrame(this.magneticFrame);
      this.magneticFrame = 0;
    });
  }
}

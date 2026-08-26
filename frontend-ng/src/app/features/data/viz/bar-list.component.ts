/**
 * `<ck-bar-list>` — a ranked list of labelled bars.
 *
 * Feature importances and class balance are the same picture: a name, a number,
 * and a length that lets the eye rank them without reading any of the numbers.
 * They were two blocks of near-identical markup before this component existed.
 *
 * Widths arrive pre-scaled (`VizBar.width`, 0–100) because the scaling is a
 * decision about the *set* — relative to the strongest feature, relative to the
 * largest class — and that belongs with whoever assembled the set, not with the
 * thing drawing rectangles.
 *
 * The drawing is deliberately the same drawing as the retention board's bars:
 * a two-stop fill so a bar has a direction, a ring and a glow so it sits on its
 * track rather than in it, and a staggered sweep so the ranking arrives in rank
 * order. A model card that puts a flat 5px rule next to a chart.js curve with a
 * gradient under it does not read as one panel, and the bars are the half of
 * the evidence a non-specialist actually reads.
 */
import { ChangeDetectionStrategy, Component, input } from '@angular/core';

import { staggerDelay, type VizBar } from './viz.vm';

@Component({
  selector: 'ck-bar-list',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <ul class="ck-viz-bars">
      @for (bar of bars(); track bar.label; let index = $index) {
        <li class="ck-viz-bars__item">
          <div class="ck-viz-bars__head">
            <span class="ck-viz-bars__label" [title]="bar.label">{{ bar.label }}</span>
            <span class="ck-viz-bars__figure">
              <span class="ck-viz-bars__value">{{ bar.display }}</span>
              @if (bar.share) {
                <span class="ck-viz-bars__share">{{ bar.share }}</span>
              }
            </span>
          </div>
          <div class="ck-viz-bars__track">
            <div
              class="ck-viz-bars__fill"
              [style.width.%]="bar.width"
              [style.--viz-bar-delay]="delay(index) + 'ms'"
              [attr.data-negative]="bar.negative"
              [attr.data-emphasis]="bar.emphasis"
            ></div>
          </div>
        </li>
      }
    </ul>
  `,
  styles: [
    `
      :host {
        display: block;
      }
      .ck-viz-bars {
        display: flex;
        flex-direction: column;
        gap: 10px;
        margin: 0;
        padding: 0;
        list-style: none;
      }
      .ck-viz-bars__head {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: 8px;
        font-family: var(--ck-font-mono, ui-monospace, monospace);
      }
      .ck-viz-bars__label {
        font-size: 11px;
        color: var(--ck-fg-2, #c8cdd4);
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        transition: color var(--ck-dur-fast, 120ms) var(--ck-ease-out, ease);
      }
      .ck-viz-bars__figure {
        display: flex;
        flex-shrink: 0;
        align-items: baseline;
        gap: 5px;
      }
      /* The figure carries the weight the label does not: on a card read from
         across a room, the number is what is being reported and the name of the
         row is how you find it again. */
      .ck-viz-bars__value {
        font-size: 12.5px;
        font-weight: 620;
        color: var(--ck-fg-1, #e6e9ee);
        font-variant-numeric: tabular-nums;
        letter-spacing: -0.01em;
      }
      .ck-viz-bars__share {
        font-size: 10px;
        font-weight: 600;
        color: var(--ck-fg-4, #8891a0);
        font-variant-numeric: tabular-nums;
      }
      .ck-viz-bars__track {
        position: relative;
        height: 9px;
        margin-top: 5px;
        border-radius: 999px;
        background: color-mix(
          in srgb,
          var(--ck-fg-5, #6b7280) 12%,
          transparent
        );
        box-shadow: inset 0 1px 2px rgb(0 0 0 / 16%);
      }
      /* Two stops of one colour — translucent at the origin, solid at the tip —
         so the bar points somewhere. The glow is what lifts it off the track. */
      .ck-viz-bars__fill {
        position: absolute;
        inset: 0 auto 0 0;
        border-radius: 999px;
        background: linear-gradient(
          90deg,
          color-mix(in srgb, var(--viz-bar, var(--ck-accent, #7dd3fc)) 42%, transparent),
          var(--viz-bar, var(--ck-accent, #7dd3fc))
        );
        box-shadow:
          0 0 0 1px
            color-mix(in srgb, var(--viz-bar, var(--ck-accent, #7dd3fc)) 24%, transparent),
          0 1px 8px
            color-mix(in srgb, var(--viz-bar, var(--ck-accent, #7dd3fc)) 28%, transparent);
        /* A zero-width bar would vanish, which reads as a missing row rather
           than as a small number. */
        min-width: 4px;
        transform-origin: left center;
        transition: filter var(--ck-dur-fast, 160ms) var(--ck-ease-out, ease);
        animation: ck-viz-bar-sweep 640ms cubic-bezier(0.22, 1, 0.36, 1) backwards;
        animation-delay: var(--viz-bar-delay, 0ms);
      }
      /* The sheen along the top edge, which is what stops a rounded rectangle
         from looking like a rounded rectangle. Decorative, never text. */
      .ck-viz-bars__fill::after {
        position: absolute;
        content: '';
        inset: 0;
        border-radius: inherit;
        background: linear-gradient(180deg, rgb(255 255 255 / 20%), transparent 60%);
      }
      /* A negative permutation score means the column actively hurt the fit —
         a different fact from "weak", so a different colour. */
      .ck-viz-bars__fill[data-negative='true'] {
        --viz-bar: var(--ck-signal-neg, #ef5a6f);
      }
      .ck-viz-bars__fill[data-emphasis='true'] {
        --viz-bar: var(--ck-signal-warn, #f5b84a);
      }
      .ck-viz-bars__item:hover .ck-viz-bars__fill {
        filter: brightness(1.12) saturate(1.06);
      }
      .ck-viz-bars__item:hover .ck-viz-bars__label {
        color: var(--ck-fg-1, #e6e9ee);
      }
      @keyframes ck-viz-bar-sweep {
        from {
          opacity: 0.3;
          transform: scaleX(0);
        }
        to {
          opacity: 1;
          transform: scaleX(1);
        }
      }
      /* A global reduce-motion rule can collapse a duration but not a delay,
         which on a stagger leaves the later bars blank for a beat. The bars
         carry their real width already, so dropping the animation entirely
         lands every one of them where it belongs on the first frame. */
      @media (prefers-reduced-motion: reduce) {
        .ck-viz-bars__fill {
          animation: none;
        }
      }
    `,
  ],
})
export class BarListComponent {
  readonly bars = input<readonly VizBar[]>([]);

  /**
   * When one bar's sweep starts, so a twenty-row importance list still arrives
   * inside the same budget a two-class balance chart does.
   */
  protected delay(index: number): number {
    return staggerDelay(index, this.bars().length);
  }
}

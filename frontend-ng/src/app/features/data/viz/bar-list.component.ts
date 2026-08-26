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
 */
import { ChangeDetectionStrategy, Component, input } from '@angular/core';

import type { VizBar } from './viz.vm';

@Component({
  selector: 'ck-bar-list',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <ul class="ck-viz-bars">
      @for (bar of bars(); track bar.label) {
        <li class="ck-viz-bars__item">
          <div class="ck-viz-bars__head">
            <span class="ck-viz-bars__label" [title]="bar.label">{{ bar.label }}</span>
            <span class="ck-viz-bars__value">{{ bar.display }}</span>
          </div>
          <div class="ck-viz-bars__track">
            <div
              class="ck-viz-bars__fill"
              [style.width.%]="bar.width"
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
        gap: 6px;
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
        font-size: 10.5px;
      }
      .ck-viz-bars__label {
        color: var(--ck-fg-2, #c8cdd4);
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      .ck-viz-bars__value {
        flex-shrink: 0;
        color: var(--ck-fg-4, #8891a0);
        font-variant-numeric: tabular-nums;
      }
      .ck-viz-bars__track {
        height: 5px;
        margin-top: 3px;
        border-radius: 999px;
        background: var(--ck-bg-inset, rgba(255, 255, 255, 0.04));
        overflow: hidden;
      }
      .ck-viz-bars__fill {
        height: 100%;
        border-radius: 999px;
        background: var(--ck-accent, #7dd3fc);
        /* A zero-width bar would vanish, which reads as a missing row rather
           than as a small number. */
        min-width: 2px;
      }
      /* A negative permutation score means the column actively hurt the fit —
         a different fact from "weak", so a different colour. */
      .ck-viz-bars__fill[data-negative='true'] {
        background: var(--ck-signal-neg, #ef5a6f);
      }
      .ck-viz-bars__fill[data-emphasis='true'] {
        background: var(--ck-signal-warn, #f5b84a);
      }
    `,
  ],
})
export class BarListComponent {
  readonly bars = input<readonly VizBar[]>([]);
}

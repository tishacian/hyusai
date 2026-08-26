/**
 * `<ck-confusion-matrix>` — the confusion matrix as a heat-map grid.
 *
 * CSS Grid rather than a table, and the difference is not cosmetic: a grid whose
 * column count comes from the label count lays out square cells at any number
 * of classes, where a table's columns size themselves to their content and turn
 * a three-class matrix into three columns of different widths. A confusion
 * matrix read at a glance depends on the cells being comparable rectangles.
 *
 * The shading is row-normalized (see `confusionShade`), so the cell that
 * matters in an imbalanced problem — the churner called loyal — is as loud as
 * its share of actual churners rather than as quiet as its share of everyone.
 * That share is also printed under each count when the caller supplies a
 * formatter for it, because the shading encodes a number the reader would
 * otherwise have to hover four cells to recover.
 *
 * The cells arrive in a diagonal wave. It is an entrance, but not only one: the
 * wave crosses the diagonal first, which is where a good model's mass sits and
 * the first thing anyone should look at.
 */
import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import {
  confusionShade,
  staggerDelay,
  type ConfusionCell,
  type ConfusionView,
} from './viz.vm';

@Component({
  selector: 'ck-confusion-matrix',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (view(); as grid) {
      <div
        class="ck-viz-matrix"
        role="table"
        [attr.aria-label]="label()"
        [style.--viz-matrix-columns]="grid.labels.length"
      >
        <div class="ck-viz-matrix__row" role="row">
          <div class="ck-viz-matrix__corner" role="columnheader">
            {{ actualLabel() }} \\ {{ predictedLabel() }}
          </div>
          @for (name of grid.labels; track name) {
            <div class="ck-viz-matrix__head" role="columnheader" [title]="name">
              {{ name }}
            </div>
          }
        </div>
        @for (line of grid.rows; track line.actual; let row = $index) {
          <div class="ck-viz-matrix__row" role="row">
            <div class="ck-viz-matrix__side" role="rowheader" [title]="line.actual">
              {{ line.actual }}
            </div>
            @for (cell of line.cells; track cell.predicted; let column = $index) {
              <div
                class="ck-viz-matrix__cell"
                role="cell"
                [attr.data-correct]="cell.correct"
                [style.background]="shade(cell)"
                [style.--viz-cell-delay]="delay(row, column) + 'ms'"
                [title]="titleFor(cell)"
              >
                <span class="ck-viz-matrix__count">{{ format()(cell.count) }}</span>
                @if (shareOf(cell); as text) {
                  <span class="ck-viz-matrix__share">{{ text }}</span>
                }
              </div>
            }
          </div>
        }
      </div>
    }
  `,
  styles: [
    `
      :host {
        display: block;
      }
      /* One grid, one column track per class plus the row-header track. Cells
         stay square-ish at two classes and at eight, which a table cannot do.
         The column count is a component-local custom property, deliberately
         outside the --ck-* namespace: that prefix is the design system's, and a
         per-instance value has no business in it. */
      .ck-viz-matrix {
        display: grid;
        grid-template-columns: minmax(60px, auto) repeat(
            var(--viz-matrix-columns, 2),
            minmax(52px, 1fr)
          );
        gap: 3px;
        font-family: var(--ck-font-mono, ui-monospace, monospace);
        font-size: 10.5px;
        font-variant-numeric: tabular-nums;
      }
      /* Contents display keeps the semantic rows for a screen reader while
         letting every cell be a direct child of the one grid. */
      .ck-viz-matrix__row {
        display: contents;
      }
      .ck-viz-matrix__corner,
      .ck-viz-matrix__head,
      .ck-viz-matrix__side {
        display: flex;
        align-items: center;
        padding: 4px 6px;
        color: var(--ck-fg-4, #8891a0);
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      .ck-viz-matrix__head {
        justify-content: center;
      }
      .ck-viz-matrix__corner {
        font-size: 9.5px;
      }
      .ck-viz-matrix__cell {
        position: relative;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        gap: 1px;
        padding: 9px 6px;
        border-radius: 6px;
        color: var(--ck-fg-1, #e6e9ee);
        box-shadow: inset 0 0 0 1px var(--ck-stroke-1, rgba(255, 255, 255, 0.05));
        transition:
          transform var(--ck-dur-fast, 140ms) var(--ck-ease-out, ease),
          box-shadow var(--ck-dur-fast, 140ms) var(--ck-ease-out, ease);
        animation: ck-viz-cell-in 420ms cubic-bezier(0.22, 1, 0.36, 1) backwards;
        animation-delay: var(--viz-cell-delay, 0ms);
      }
      /* The top-light every other raised surface in the app has. Without it a
         tinted rectangle reads as a table cell that happens to be coloured. */
      .ck-viz-matrix__cell::before {
        position: absolute;
        content: '';
        inset: 0;
        border-radius: inherit;
        background: linear-gradient(180deg, rgb(255 255 255 / 7%), transparent 55%);
        pointer-events: none;
      }
      .ck-viz-matrix__count {
        position: relative;
        font-size: 13px;
        font-weight: 620;
        letter-spacing: -0.01em;
      }
      /* The row share the shading already encodes, said out loud. Smaller and
         quieter than the count, because it is the gloss and not the datum. */
      .ck-viz-matrix__share {
        position: relative;
        font-size: 9.5px;
        font-weight: 600;
        color: var(--ck-fg-3, #a4acb9);
      }
      /* The diagonal is where a good model's mass sits, so it is the one edge
         drawn brighter — the eye should find it without reading a number. */
      .ck-viz-matrix__cell[data-correct='true'] {
        box-shadow:
          inset 0 0 0 1px
            color-mix(in srgb, var(--ck-signal-pos, #4ade80) 42%, transparent),
          0 1px 10px color-mix(in srgb, var(--ck-signal-pos, #4ade80) 16%, transparent);
      }
      /* Raised, not recoloured: the tint is carrying the share, so a hover that
         changed the background would be a hover that changed the reading. */
      .ck-viz-matrix__cell:hover {
        z-index: 1;
        transform: translateY(-1px);
        box-shadow:
          inset 0 0 0 1px var(--ck-stroke-2, rgba(255, 255, 255, 0.12)),
          0 4px 14px rgb(0 0 0 / 22%);
      }
      @keyframes ck-viz-cell-in {
        from {
          opacity: 0;
          transform: scale(0.92);
        }
        to {
          opacity: 1;
          transform: scale(1);
        }
      }
      /* A delay survives a duration being collapsed, which would leave the far
         corner of the grid blank. Dropping the animation lands every cell on
         the first frame instead. */
      @media (prefers-reduced-motion: reduce) {
        .ck-viz-matrix__cell {
          animation: none;
        }
      }
    `,
  ],
})
export class ConfusionMatrixComponent {
  readonly view = input<ConfusionView | null>(null);
  /** Screen-reader label for the whole grid. */
  readonly label = input.required<string>();
  readonly actualLabel = input('');
  readonly predictedLabel = input('');
  /**
   * Cell text, so the locale's thousands separator is the caller's business and
   * this component stays free of the i18n service.
   */
  readonly format = input<(count: number) => string>((count) => String(count));
  /**
   * The row share under each count, or nothing.
   *
   * Opt-in for the same reason `format` is injected: a percentage needs a locale
   * to be written in. Absent, the cell is a count and the share stays where it
   * was — in the tooltip and in the shading.
   */
  readonly shareFormat = input<((share: number) => string) | null>(null);
  /** Tooltip text for one cell — the caller has the sentence and the locale. */
  readonly describe = input<((cell: ConfusionCell) => string) | null>(null);

  protected shade(cell: ConfusionCell): string {
    return confusionShade(cell.share, cell.correct);
  }

  protected shareOf(cell: ConfusionCell): string {
    const format = this.shareFormat();
    return format ? format(cell.share) : '';
  }

  protected titleFor(cell: ConfusionCell): string {
    const describe = this.describe();
    return describe ? describe(cell) : `${cell.actual} → ${cell.predicted}`;
  }

  /**
   * When one cell arrives: in wavefronts across the diagonal, so the grid is
   * uncovered from the corner a reader starts in. `2n - 1` diagonals share the
   * one budget, which is what keeps an eight-class matrix from taking twice as
   * long to appear as a two-class one.
   */
  protected delay(row: number, column: number): number {
    return staggerDelay(row + column, 2 * this.columns() - 1);
  }

  /** Kept so the template's `[style.--viz-matrix-columns]` has a fallback. */
  protected readonly columns = computed(() => this.view()?.labels.length ?? 0);
}

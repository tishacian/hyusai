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
 */
import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import { confusionShade, type ConfusionCell, type ConfusionView } from './viz.vm';

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
        @for (line of grid.rows; track line.actual) {
          <div class="ck-viz-matrix__row" role="row">
            <div class="ck-viz-matrix__side" role="rowheader" [title]="line.actual">
              {{ line.actual }}
            </div>
            @for (cell of line.cells; track cell.predicted) {
              <div
                class="ck-viz-matrix__cell"
                role="cell"
                [attr.data-correct]="cell.correct"
                [style.background]="shade(cell)"
                [title]="titleFor(cell)"
              >
                {{ format()(cell.count) }}
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
            minmax(44px, 1fr)
          );
        gap: 2px;
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
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 7px 6px;
        border-radius: 3px;
        color: var(--ck-fg-1, #e6e9ee);
        box-shadow: inset 0 0 0 1px var(--ck-stroke-1, rgba(255, 255, 255, 0.05));
      }
      /* The diagonal is where a good model's mass sits, so it is the one edge
         drawn brighter — the eye should find it without reading a number. */
      .ck-viz-matrix__cell[data-correct='true'] {
        box-shadow: inset 0 0 0 1px
          color-mix(in srgb, var(--ck-signal-pos, #4ade80) 35%, transparent);
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
  /** Tooltip text for one cell — the caller has the sentence and the locale. */
  readonly describe = input<((cell: ConfusionCell) => string) | null>(null);

  protected shade(cell: ConfusionCell): string {
    return confusionShade(cell.share, cell.correct);
  }

  protected titleFor(cell: ConfusionCell): string {
    const describe = this.describe();
    return describe ? describe(cell) : `${cell.actual} → ${cell.predicted}`;
  }

  /** Kept so the template's `[style.--viz-matrix-columns]` has a fallback. */
  protected readonly columns = computed(() => this.view()?.labels.length ?? 0);
}

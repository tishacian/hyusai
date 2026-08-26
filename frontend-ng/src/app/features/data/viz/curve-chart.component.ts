/**
 * `<ck-curve-chart>` — one curve in a box, with the reference it is judged
 * against.
 *
 * Every curve a model card shows is this component: a ROC against the diagonal
 * of a coin flip, a precision/recall curve against the prevalence baseline, a
 * predicted-versus-actual scatter path against the identity line. They differ
 * in their numbers and their reference, not in their drawing, so they are one
 * component rather than three copies.
 *
 * The reference line is not decoration. A ROC curve without its diagonal cannot
 * be read at all — the shape alone says nothing about whether the model beats
 * chance — and a precision/recall curve without the prevalence line flatters
 * every imbalanced problem. Whoever renders a curve here has to say what it is
 * being compared to.
 */
import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import {
  UNIT_DOMAIN,
  curveArea,
  curvePath,
  referenceY,
  type CurveBox,
  type CurveDomain,
  type CurvePoint,
} from './viz.vm';

/** What the curve is judged against, and how that is drawn. */
export type CurveReference =
  /** The diagonal of a coin flip: bottom-left to top-right. A ROC's baseline. */
  | { kind: 'diagonal' }
  /** A horizontal line in the curve's own y units — precision at prevalence. */
  | { kind: 'level'; value: number | null }
  /** Another series entirely, as the regression fit is judged against identity. */
  | { kind: 'series'; points: readonly CurvePoint[] }
  | { kind: 'none' };

@Component({
  selector: 'ck-curve-chart',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <svg
      [attr.viewBox]="'0 0 ' + box().width + ' ' + box().height"
      class="ck-viz-curve"
      role="img"
      [attr.aria-label]="label()"
      preserveAspectRatio="none"
    >
      @switch (reference().kind) {
        @case ('diagonal') {
          <line
            [attr.x1]="0"
            [attr.y1]="box().height"
            [attr.x2]="box().width"
            [attr.y2]="0"
            class="ck-viz-curve__ref"
          />
        }
        @case ('level') {
          @if (levelY() !== null) {
            <line
              [attr.x1]="0"
              [attr.y1]="levelY()"
              [attr.x2]="box().width"
              [attr.y2]="levelY()"
              class="ck-viz-curve__ref"
            />
          }
        }
        @case ('series') {
          @if (referencePath()) {
            <path [attr.d]="referencePath()" class="ck-viz-curve__ref" />
          }
        }
      }
      @if (fill() && area()) {
        <path [attr.d]="area()" class="ck-viz-curve__area" />
      }
      <path [attr.d]="path()" class="ck-viz-curve__line" />
    </svg>
  `,
  styles: [
    `
      :host {
        display: block;
      }
      .ck-viz-curve {
        display: block;
        width: 100%;
        height: auto;
        overflow: visible;
      }
      /* The baseline is a fact about the problem, not about this model, so it
         reads as chrome: dashed, dim, and never in the accent colour. */
      .ck-viz-curve__ref {
        fill: none;
        stroke: var(--ck-stroke-2, rgba(255, 255, 255, 0.14));
        stroke-width: 1;
        stroke-dasharray: 3 3;
        vector-effect: non-scaling-stroke;
      }
      .ck-viz-curve__line {
        fill: none;
        stroke: var(--ck-accent, #7dd3fc);
        stroke-width: 1.75;
        stroke-linejoin: round;
        stroke-linecap: round;
        /* preserveAspectRatio=none stretches the box to the container, which
           would stretch the stroke with it and make a wide chart's line thinner
           than a narrow one's. */
        vector-effect: non-scaling-stroke;
      }
      .ck-viz-curve__area {
        fill: color-mix(in srgb, var(--ck-accent, #7dd3fc) 16%, transparent);
        stroke: none;
      }
      :host([data-tone='violet']) .ck-viz-curve__line {
        stroke: var(--ck-signal-violet, #a78bfa);
      }
      :host([data-tone='violet']) .ck-viz-curve__area {
        fill: color-mix(in srgb, var(--ck-signal-violet, #a78bfa) 16%, transparent);
      }
    `,
  ],
  host: { '[attr.data-tone]': 'tone()' },
})
export class CurveChartComponent {
  readonly points = input<readonly CurvePoint[] | undefined>(undefined);
  readonly box = input<CurveBox>({ width: 300, height: 190 });
  readonly domain = input<CurveDomain>(UNIT_DOMAIN);
  readonly reference = input<CurveReference>({ kind: 'none' });
  /** Fill under the curve — on for ROC, where the area *is* the metric. */
  readonly fill = input(false);
  readonly tone = input<'accent' | 'violet'>('accent');
  /** Screen-reader label. Required: a bare `role="img"` announces nothing. */
  readonly label = input.required<string>();

  protected readonly path = computed(() =>
    curvePath(this.points(), this.box(), this.domain()),
  );

  protected readonly area = computed(() =>
    curveArea(this.points(), this.box(), this.domain()),
  );

  protected readonly levelY = computed(() => {
    const reference = this.reference();
    return reference.kind === 'level'
      ? referenceY(reference.value, this.box(), this.domain())
      : null;
  });

  protected readonly referencePath = computed(() => {
    const reference = this.reference();
    return reference.kind === 'series'
      ? curvePath(reference.points, this.box(), this.domain())
      : '';
  });
}

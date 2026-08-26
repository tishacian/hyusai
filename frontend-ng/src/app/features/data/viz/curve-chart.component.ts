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
 * Drawn with chart.js, which the bundle already carries. The reason is the
 * pointer: these curves are the two plots an audience interrogates rather than
 * glances at, and "what does that elbow cost me in false positives" is a
 * question a tooltip answers and a static path does not. Reading an operating
 * point off a hovered ROC is the difference between showing a metric and
 * explaining a trade-off.
 *
 * Canvas has one cost this component absorbs: `var()` and `color-mix()` are not
 * colours there. So the `--ck-*` tokens are resolved off the host element and
 * re-resolved whenever the theme flips, rather than handed to the renderer as
 * text it cannot parse.
 */
import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  computed,
  inject,
  input,
} from '@angular/core';
import type { ChartConfiguration, ChartData } from 'chart.js';
import { BaseChartDirective } from 'ng2-charts';

import { ThemeService } from '@app/core/theme.service';

import {
  UNIT_DOMAIN,
  curveSeries,
  referenceSeries,
  tokenAlpha,
  type CurveDomain,
  type CurvePoint,
  type CurveReference,
} from './viz.vm';

export type { CurveReference } from './viz.vm';

@Component({
  selector: 'ck-curve-chart',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [BaseChartDirective],
  template: `
    <div class="ck-viz-curve" [style.aspect-ratio]="aspect()">
      <canvas
        baseChart
        type="line"
        role="img"
        [attr.aria-label]="label()"
        [data]="data()"
        [options]="options()"
      ></canvas>
    </div>
  `,
  styles: [
    `
      :host {
        display: block;
      }
      .ck-viz-curve {
        position: relative;
        width: 100%;
      }
    `,
  ],
})
export class CurveChartComponent {
  private readonly host = inject(ElementRef<HTMLElement>);
  private readonly theme = inject(ThemeService);

  readonly points = input<readonly CurvePoint[] | undefined>(undefined);
  /** Width over height. The curves are square-ish; a ROC squashed flat lies. */
  readonly aspect = input(16 / 10);
  readonly domain = input<CurveDomain>(UNIT_DOMAIN);
  readonly reference = input<CurveReference>({ kind: 'none' });
  /** Fill under the curve — on for ROC, where the area *is* the metric. */
  readonly fill = input(false);
  readonly tone = input<'accent' | 'violet'>('accent');
  /** Screen-reader label. Required: a bare `role="img"` announces nothing. */
  readonly label = input.required<string>();
  /** Axis names. Empty means no title, for a plot whose axes need no saying. */
  readonly xLabel = input('');
  readonly yLabel = input('');
  /** What a hovered point is called, e.g. "TPR 0.82 at FPR 0.11". */
  readonly pointLabel = input<(point: CurvePoint) => string>((point) =>
    `${format(point.x)}, ${format(point.y)}`,
  );

  /**
   * The token values this chart draws with, re-read when the theme changes.
   *
   * Depending on `theme.resolved()` is what makes the flip work: the signal read
   * is the only thing telling Angular to recompute a value that otherwise looks
   * constant, and without it a chart drawn in the dark theme keeps its dark
   * greys after the switch to light.
   */
  private readonly palette = computed(() => {
    this.theme.resolved();
    const line = this.token(
      this.tone() === 'violet' ? '--ck-signal-violet' : '--ck-accent',
      this.tone() === 'violet' ? '#a78bfa' : '#7dd3fc',
    );
    return {
      line,
      area: tokenAlpha(line, 0.18),
      grid: tokenAlpha(this.token('--ck-stroke-2', 'rgba(255, 255, 255, 0.08)'), 1),
      reference: tokenAlpha(this.token('--ck-fg-4', 'rgba(255, 255, 255, 0.45)'), 0.8),
      text: this.token('--ck-fg-3', 'rgba(255, 255, 255, 0.66)'),
    };
  });

  protected readonly data = computed<ChartData<'line', CurvePoint[]>>(() => {
    const palette = this.palette();
    const reference = referenceSeries(this.reference(), this.domain());
    return {
      datasets: [
        // The reference first, so the curve draws over it rather than under.
        ...(reference.length
          ? [
              {
                data: reference,
                borderColor: palette.reference,
                borderWidth: 1,
                borderDash: [3, 3],
                pointRadius: 0,
                pointHitRadius: 0,
                fill: false,
                tension: 0,
                order: 2,
              },
            ]
          : []),
        {
          data: curveSeries(this.points()),
          borderColor: palette.line,
          backgroundColor: palette.area,
          borderWidth: 1.75,
          pointRadius: 0,
          // Hoverable without being dotted: the points are invisible until the
          // pointer is near one, which is the whole reason this is a canvas.
          pointHoverRadius: 3.5,
          pointHoverBackgroundColor: palette.line,
          pointHitRadius: 8,
          fill: this.fill() ? 'origin' : false,
          tension: 0,
          order: 1,
        },
      ],
    };
  });

  protected readonly options = computed<ChartConfiguration<'line'>['options']>(() => {
    const palette = this.palette();
    const domain = this.domain();
    const describe = this.pointLabel();
    return {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 320 },
      // A ROC is read by pointing at it, and the nearest point in x is the one
      // a reader means — not the nearest in both axes, which on a steep curve
      // is somewhere else entirely.
      interaction: { mode: 'nearest', axis: 'x', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          displayColors: false,
          callbacks: {
            title: () => '',
            label: (item) => describe(item.raw as CurvePoint),
          },
        },
      },
      scales: {
        x: {
          type: 'linear',
          min: domain.minX,
          max: domain.maxX,
          grid: { color: palette.grid, tickColor: 'transparent' },
          border: { color: palette.grid },
          ticks: { color: palette.text, font: { size: 10 }, maxTicksLimit: 5 },
          title: this.xLabel()
            ? { display: true, text: this.xLabel(), color: palette.text, font: { size: 10 } }
            : { display: false },
        },
        y: {
          type: 'linear',
          min: domain.minY,
          max: domain.maxY,
          grid: { color: palette.grid, tickColor: 'transparent' },
          border: { color: palette.grid },
          ticks: { color: palette.text, font: { size: 10 }, maxTicksLimit: 5 },
          title: this.yLabel()
            ? { display: true, text: this.yLabel(), color: palette.text, font: { size: 10 } }
            : { display: false },
        },
      },
    };
  });

  private token(name: string, fallback: string): string {
    const value = getComputedStyle(this.host.nativeElement)
      .getPropertyValue(name)
      .trim();
    return value || fallback;
  }
}

function format(value: number): string {
  return Math.abs(value) < 1
    ? value.toFixed(3).replace(/0+$/, '').replace(/\.$/, '')
    : value.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

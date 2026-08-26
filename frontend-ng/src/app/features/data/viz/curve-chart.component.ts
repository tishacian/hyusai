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
 *
 * Three local plugins do the parts chart.js has no option for: the curve wipes
 * in from the origin, the measured line is lit rather than merely coloured, and
 * a dashed guide follows the pointer down to the axis. They are separate
 * plugins rather than one because each hangs off a different draw phase, and
 * the order they are listed in is the order they have to run.
 */
import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  computed,
  inject,
  input,
} from '@angular/core';
import type {
  Chart,
  ChartConfiguration,
  ChartData,
  Plugin,
  ScriptableContext,
} from 'chart.js';
import { BaseChartDirective } from 'ng2-charts';

import { ThemeService } from '@app/core/theme.service';

import {
  UNIT_DOMAIN,
  curveFill,
  curveSeries,
  referenceSeries,
  revealFraction,
  tokenAlpha,
  type CurveDomain,
  type CurvePoint,
  type CurveReference,
} from './viz.vm';

export type { CurveReference } from './viz.vm';

/** How long a curve takes to draw itself in. */
const REVEAL_MS = 760;

/**
 * Zero when the reader has asked for less motion, which
 * {@link revealFraction} reads as a reveal that is already over.
 *
 * Read per frame rather than once, because the preference can change under a
 * chart that is already on screen — and because there is no window to ask in
 * the unit runner, where the absent `matchMedia` means no animation at all.
 */
function revealDuration(): number {
  if (typeof matchMedia !== 'function') return 0;
  return matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : REVEAL_MS;
}

const revealStarts = new WeakMap<Chart, number>();
const destroyed = new WeakSet<Chart>();

/**
 * How far this chart's reveal has got, on the clock that starts the first time
 * it is laid out into a box with a width.
 *
 * The panels these curves sit in are tabs that render hidden rather than
 * deferred, so a chart is constructed — and drawn, into nothing — long before
 * anyone can see it. Starting the clock on the first draw would spend the whole
 * reveal against `display: none`, and the curve would simply be there when the
 * tab was finally opened. A chart with no width has not begun to arrive.
 */
function revealOf(chart: Chart): number {
  const area = chart.chartArea;
  if (!area || area.right - area.left <= 0) return 1;
  const started = revealStarts.get(chart);
  if (started === undefined) {
    revealStarts.set(chart, performance.now());
    return revealFraction(0, revealDuration());
  }
  return revealFraction(performance.now() - started, revealDuration());
}

/**
 * The entrance: the plot is clipped to a growing rectangle, so the curve and
 * the area under it arrive together, left to right.
 *
 * A clip rather than chart.js's own animation because the two things that have
 * to arrive in step are a line and the wash beneath it, and animating the
 * points would grow the line while the fill — which the Filler plugin derives
 * from the finished path — flickers behind it. Clipping is indifferent to what
 * is being drawn.
 *
 * Kept once per chart instance: the reveal is an arrival, and re-running it
 * whenever the data object changes would replay the entrance on every theme
 * flip.
 */
const revealPlugin: Plugin<'line'> = {
  id: 'ck-reveal',
  beforeDatasetsDraw(chart) {
    const { ctx, chartArea } = chart;
    // Unconditional, so the restore below always has something to undo.
    ctx.save();
    const fraction = revealOf(chart);
    if (fraction >= 1) return;
    ctx.beginPath();
    ctx.rect(
      chartArea.left,
      chartArea.top,
      (chartArea.right - chartArea.left) * fraction,
      chartArea.bottom - chartArea.top,
    );
    ctx.clip();
  },
  afterDatasetsDraw(chart) {
    chart.ctx.restore();
    if (revealOf(chart) >= 1) return;
    requestAnimationFrame(() => {
      if (destroyed.has(chart)) return;
      chart.draw();
    });
  },
  afterDestroy(chart) {
    destroyed.add(chart);
  },
};

/**
 * A curve is lit rather than merely coloured.
 *
 * The shadow is set between the fill and the stroke, which is a real ordering
 * and not a coincidence: chart.js notifies its own registered plugins before a
 * chart's local ones, so the Filler has already painted the area by the time
 * this runs, and only the line and its hover points pick up the glow. A halo
 * around the area polygon would smudge its edge along the axis.
 *
 * References are exempt. A dashed line is a claim about the plot — this is
 * where chance would be — and lighting it would present the baseline as a
 * second result.
 */
const glowPlugin: Plugin<'line'> = {
  id: 'ck-glow',
  beforeDatasetDraw(chart, args) {
    const dataset = chart.data.datasets[args.index] as
      | { borderColor?: unknown; borderDash?: number[] }
      | undefined;
    if (!dataset || dataset.borderDash?.length) return;
    if (typeof dataset.borderColor !== 'string') return;
    chart.ctx.shadowColor = tokenAlpha(dataset.borderColor, 0.5);
    chart.ctx.shadowBlur = 10;
  },
  afterDatasetDraw(chart) {
    chart.ctx.shadowColor = 'transparent';
    chart.ctx.shadowBlur = 0;
  },
};

/**
 * The vertical guide under the pointer.
 *
 * The tooltip already says which point is being read; the crosshair says
 * *where*, which is the half of "0.82 true positives at 0.11 false positives"
 * that a reader was about to trace with a finger. Drawn under nothing — it is
 * the last thing on the canvas — but at one pixel and dashed, so it guides
 * without competing with the curve it is measuring.
 */
const crosshairPlugin: Plugin<'line'> = {
  id: 'ck-crosshair',
  afterDatasetsDraw(chart) {
    const active = chart.tooltip?.getActiveElements() ?? [];
    const { ctx, chartArea } = chart;
    if (!active.length || !chartArea) return;
    const x = active[0]!.element.x;
    ctx.save();
    ctx.beginPath();
    ctx.moveTo(x, chartArea.top);
    ctx.lineTo(x, chartArea.bottom);
    ctx.lineWidth = 1;
    ctx.setLineDash([2, 3]);
    ctx.strokeStyle = axisInk(chart);
    ctx.stroke();
    ctx.restore();
  },
};

/**
 * The colour the axis labels are written in, read back off the chart.
 *
 * A plugin draws with what the canvas gives it, and a canvas cannot resolve
 * `var()`. Rather than resolve `--ck-fg-3` a second time — and risk a
 * crosshair that stays dark after a flip to the light theme — this reads the
 * value the component already resolved and handed to the ticks. The crosshair
 * is then, by construction, the same ink as the numbers it is pointing at.
 */
function axisInk(chart: Chart): string {
  const ticks = (chart.options.scales?.['x'] as { ticks?: { color?: unknown } } | undefined)?.ticks;
  return typeof ticks?.color === 'string' ? ticks.color : 'rgba(148, 163, 184, 0.5)';
}

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
        [plugins]="plugins"
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
      grid: tokenAlpha(this.token('--ck-stroke-2', 'rgba(255, 255, 255, 0.08)'), 1),
      reference: tokenAlpha(this.token('--ck-fg-4', 'rgba(255, 255, 255, 0.45)'), 0.8),
      text: this.token('--ck-fg-3', 'rgba(255, 255, 255, 0.66)'),
      // Opaque on purpose: a tooltip is read over the densest part of the
      // plot, and a translucent card there is a card with a curve through it.
      surface: this.token('--ck-bg-panel-hi', '#11161c'),
      ink: this.token('--ck-fg-1', '#f2f5f8'),
      edge: this.token('--ck-stroke-2', 'rgba(255, 255, 255, 0.08)'),
    };
  });

  /**
   * The wash under the curve, as a gradient down the plot.
   *
   * Scriptable rather than a colour because a `CanvasGradient` needs both the
   * context and a laid-out plot area, and neither exists when the dataset is
   * assembled. chart.js calls this again on every draw, including the first
   * one after layout — which is why returning nothing before `chartArea`
   * exists costs a frame rather than the fill.
   */
  private readonly area = (context: ScriptableContext<'line'>): CanvasGradient | string => {
    const { ctx, chartArea } = context.chart;
    if (!chartArea) return 'transparent';
    const gradient = ctx.createLinearGradient(0, chartArea.top, 0, chartArea.bottom);
    for (const stop of curveFill(this.palette().line)) {
      gradient.addColorStop(stop.offset, stop.color);
    }
    return gradient;
  };

  /**
   * Local to this chart, and in this order: the reveal's clip has to be in
   * place before the Filler paints, and the crosshair is drawn after the clip
   * is released so a pointer resting on a half-drawn curve still gets a whole
   * guide.
   */
  protected readonly plugins = [revealPlugin, glowPlugin, crosshairPlugin];

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
          backgroundColor: this.area,
          borderWidth: 2.25,
          borderJoinStyle: 'round',
          borderCapStyle: 'round',
          pointRadius: 0,
          // Hoverable without being dotted: the points are invisible until the
          // pointer is near one, which is the whole reason this is a canvas.
          pointHoverRadius: 4,
          pointHoverBackgroundColor: palette.line,
          pointHoverBorderColor: palette.surface,
          pointHoverBorderWidth: 2,
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
      // The entrance is the reveal plugin's wipe, and two entrances at once
      // read as a stutter: chart.js would grow the points from the baseline
      // underneath a clip that is already uncovering them.
      animation: false,
      // A ROC is read by pointing at it, and the nearest point in x is the one
      // a reader means — not the nearest in both axes, which on a steep curve
      // is somewhere else entirely.
      interaction: { mode: 'nearest', axis: 'x', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          displayColors: false,
          // chart.js's default tooltip is a black capsule with the browser's
          // fonts, which on a cockpit panel looks like something the page
          // borrowed. These are the same surface, ink and hairline every other
          // popover on the page is built from.
          backgroundColor: palette.surface,
          bodyColor: palette.ink,
          borderColor: palette.edge,
          borderWidth: 1,
          cornerRadius: 8,
          padding: { x: 10, y: 7 },
          bodyFont: { size: 11, weight: 600 },
          caretSize: 5,
          // The gap between the point being read and the card reading it. At
          // chart.js's default of 2px the card sits on the curve, so the line
          // whose value it is quoting disappears under the quote.
          caretPadding: 8,
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

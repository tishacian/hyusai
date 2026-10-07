/**
 * `<ck-forecast-chart>` — what happened, what the model said, and its interval.
 *
 * The forecasting card's main exhibit: the context before the backtest and its
 * actuals as one line, the backtest forecasts over them, and the interval as a
 * wash between its bounds. A reader judges a forecast by pointing at the place
 * it missed, so this is a canvas with a tooltip, like the other model curves.
 *
 * Same token discipline as `<ck-curve-chart>`: canvas cannot resolve `var()`,
 * so the `--ck-*` values are read off the host and re-read on a theme flip.
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
  forecastExtent,
  formatForecastStamp,
  type ForecastChartSeries,
} from './forecast-chart.vm';
import { tokenAlpha } from './viz.vm';

export interface ForecastChartLabels {
  actual: string;
  pred: string;
  interval: string;
}

@Component({
  selector: 'ck-forecast-chart',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [BaseChartDirective],
  template: `
    <div class="ck-viz-forecast" [style.aspect-ratio]="aspect()">
      <canvas
        baseChart
        type="line"
        role="img"
        [attr.aria-label]="label()"
        [data]="data()"
        [options]="options()"
      ></canvas>
    </div>
    <div class="ck-viz-forecast__legend">
      <span><i class="ck-swatch ck-swatch--actual"></i>{{ names().actual }}</span>
      <span><i class="ck-swatch ck-swatch--pred"></i>{{ names().pred }}</span>
      <span><i class="ck-swatch ck-swatch--band"></i>{{ names().interval }}</span>
    </div>
  `,
  styles: [
    `
      :host {
        display: block;
      }
      /* Wide on a desk, never flat on a phone: the aspect sizes it, the floor
         keeps a day's peak readable at 390px. */
      .ck-viz-forecast {
        position: relative;
        width: 100%;
        min-height: 220px;
      }
      .ck-viz-forecast__legend {
        display: flex;
        gap: 14px;
        flex-wrap: wrap;
        margin-top: 6px;
        font-size: 10.5px;
        color: var(--ck-fg-3);
      }
      .ck-viz-forecast__legend span {
        display: inline-flex;
        align-items: center;
        gap: 6px;
      }
      .ck-swatch {
        display: inline-block;
        width: 14px;
        height: 2px;
        border-radius: 1px;
      }
      .ck-swatch--actual {
        background: var(--ck-fg-2);
      }
      .ck-swatch--pred {
        background: var(--ck-accent);
      }
      .ck-swatch--band {
        height: 8px;
        background: color-mix(in srgb, var(--ck-accent) 22%, transparent);
      }
    `,
  ],
})
export class ForecastChartComponent {
  private readonly host = inject(ElementRef<HTMLElement>);
  private readonly theme = inject(ThemeService);

  readonly series = input.required<ForecastChartSeries>();
  /** The pandas frequency the model was fitted on, to name the axis in its unit. */
  readonly frequency = input<string | undefined>(undefined);
  readonly locale = input('fr-FR');
  readonly aspect = input(3);
  /** Screen-reader label. Required: a bare `role="img"` announces nothing. */
  readonly label = input.required<string>();
  readonly names = input<ForecastChartLabels>({ actual: 'Actual', pred: 'Forecast', interval: 'Interval' });
  /** How a value reads in the tooltip, in the forecast column's unit. */
  readonly format = input<(value: number) => string>((value) =>
    value.toLocaleString(undefined, { maximumFractionDigits: 2 }),
  );

  private readonly palette = computed(() => {
    this.theme.resolved();
    const accent = this.token('--ck-accent', '#7dd3fc');
    return {
      actual: this.token('--ck-fg-2', '#c3c9d4'),
      pred: accent,
      band: tokenAlpha(accent, 0.18),
      grid: tokenAlpha(this.token('--ck-stroke-2', 'rgba(255, 255, 255, 0.08)'), 1),
      split: tokenAlpha(this.token('--ck-fg-4', 'rgba(255, 255, 255, 0.45)'), 0.7),
      text: this.token('--ck-fg-3', 'rgba(255, 255, 255, 0.66)'),
      surface: this.token('--ck-bg-panel-hi', '#11161c'),
      ink: this.token('--ck-fg-1', '#f2f5f8'),
      edge: this.token('--ck-stroke-2', 'rgba(255, 255, 255, 0.08)'),
    };
  });

  protected readonly data = computed<ChartData<'line', (number | null)[], string>>(() => {
    const palette = this.palette();
    const series = this.series();
    const line = { pointRadius: 0, pointHitRadius: 6, tension: 0, spanGaps: false, borderJoinStyle: 'round' as const };
    return {
      labels: series.labels,
      datasets: [
        // The band first, as two lines filled between: chart.js fills a dataset
        // to the one before it with '-1', so the upper bound washes down to the
        // lower one and both stay invisible strokes.
        { ...line, label: 'lower', data: series.lower, borderWidth: 0, borderColor: 'transparent', fill: false, pointHoverRadius: 0, order: 3 },
        { ...line, label: 'upper', data: series.upper, borderWidth: 0, borderColor: 'transparent', backgroundColor: palette.band, fill: '-1', pointHoverRadius: 0, order: 3 },
        { ...line, label: 'actual', data: series.actual, borderColor: palette.actual, borderWidth: 1.5, fill: false, pointHoverRadius: 3, order: 2 },
        { ...line, label: 'pred', data: series.pred, borderColor: palette.pred, borderWidth: 2, fill: false, pointHoverRadius: 3, order: 1 },
      ],
    };
  });

  protected readonly options = computed<ChartConfiguration<'line', (number | null)[], string>['options']>(() => {
    const palette = this.palette();
    const series = this.series();
    const extent = forecastExtent(series);
    const frequency = this.frequency();
    const locale = this.locale();
    const format = this.format();
    const names = this.names();
    const stamp = (index: number) => formatForecastStamp(series.labels[index] ?? '', frequency, locale);
    return {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          displayColors: false,
          backgroundColor: palette.surface,
          titleColor: palette.ink,
          bodyColor: palette.ink,
          borderColor: palette.edge,
          borderWidth: 1,
          cornerRadius: 8,
          padding: { x: 10, y: 7 },
          titleFont: { size: 10.5, weight: 500 },
          bodyFont: { size: 11, weight: 600 },
          caretPadding: 8,
          filter: (item) => item.dataset.label !== 'lower' && item.raw !== null,
          callbacks: {
            title: (items) => (items.length ? stamp(items[0].dataIndex) : ''),
            label: (item) => {
              const value = item.raw as number;
              if (item.dataset.label === 'actual') return `${names.actual} ${format(value)}`;
              if (item.dataset.label === 'pred') return `${names.pred} ${format(value)}`;
              const lower = series.lower[item.dataIndex];
              return lower === null ? '' : `${names.interval} ${format(lower)} – ${format(value)}`;
            },
          },
        },
      },
      scales: {
        x: {
          type: 'category',
          grid: { display: false },
          border: { color: palette.grid },
          ticks: {
            color: palette.text,
            font: { size: 10 },
            maxTicksLimit: 7,
            maxRotation: 0,
            autoSkip: true,
            callback: (_value, index) => stamp(index),
          },
        },
        y: {
          type: 'linear',
          min: extent?.min,
          max: extent?.max,
          grid: { color: palette.grid, tickColor: 'transparent' },
          border: { color: palette.grid },
          ticks: { color: palette.text, font: { size: 10 }, maxTicksLimit: 5 },
        },
      },
    };
  });

  private token(name: string, fallback: string): string {
    const value = getComputedStyle(this.host.nativeElement).getPropertyValue(name).trim();
    return value || fallback;
  }
}

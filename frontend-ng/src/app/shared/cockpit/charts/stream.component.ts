import { ChangeDetectionStrategy, Component, Input, booleanAttribute } from '@angular/core';

import { ckChartToneVar, ckChartUid, type CkChartTick, type CkStreamTone } from './chart.types';
import { accumulateStackedSeries, cubicSmoothAreaPath, niceStep, spreadLabelRows } from './svg-path';

export interface CkStreamSeries {
  label: string;
  detail?: string;
  values: number[];
  tone?: CkStreamTone;
}

export interface CkStreamGridLine {
  value: number;
  label: string;
}

export interface CkStreamPeak {
  index: number;
  label: string;
}

interface StreamArea {
  d: string;
  fill: string;
}

interface StreamText {
  x: number;
  y: number;
  text: string;
  fill: string;
  size: number;
  anchor: 'start' | 'middle' | 'end';
  font: 'sans' | 'mono';
  weight?: number;
  opacity?: number;
}

interface StreamBand {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** Vertical room one ribbon label (name + mono total) needs. */
const LABEL_ROW = 24;

@Component({
  selector: 'ck-chart-stream',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <svg
      [attr.viewBox]="'0 0 ' + width + ' ' + height"
      [attr.width]="width"
      [attr.height]="height"
      [style.width]="fluid ? '100%' : null"
      [style.height]="fluid ? 'auto' : null"
      style="display:block;overflow:visible"
    >
      <defs>
        <linearGradient [attr.id]="inkId" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="var(--ck-fg-1)" stop-opacity="0.92" />
          <stop offset="1" stop-color="var(--ck-fg-1)" stop-opacity="0.7" />
        </linearGradient>
        <linearGradient [attr.id]="declaredId" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="var(--ck-signal-cool)" stop-opacity="0.95" />
          <stop offset="1" stop-color="var(--ck-signal-cool)" stop-opacity="0.6" />
        </linearGradient>
        <linearGradient [attr.id]="declaredSoftId" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="var(--ck-signal-cool)" stop-opacity="0.45" />
          <stop offset="1" stop-color="var(--ck-signal-cool)" stop-opacity="0.22" />
        </linearGradient>
      </defs>
      @for (line of grid; track $index) {
        <line
          [attr.x1]="plotLeft"
          [attr.y1]="line.y"
          [attr.x2]="plotLeft + plotWidth"
          [attr.y2]="line.y"
          stroke="var(--ck-fg-1)"
          stroke-opacity="0.12"
          stroke-width="1"
          stroke-dasharray="2 4"
        />
        <text
          [attr.x]="plotLeft + plotWidth + 6"
          [attr.y]="line.y + 3"
          fill="var(--ck-fg-3)"
          font-family="var(--ck-font-mono)"
          font-size="8"
        >{{ line.label }}</text>
      }
      @for (band of weekendBands; track $index) {
        <rect
          [attr.x]="band.x"
          [attr.y]="band.y"
          [attr.width]="band.w"
          [attr.height]="band.h"
          fill="var(--ck-fg-1)"
          fill-opacity="0.04"
        />
      }
      @for (area of areas; track $index) {
        <path [attr.d]="area.d" [attr.fill]="area.fill" />
      }
      @for (label of seriesLabels; track $index) {
        <text
          [attr.x]="label.x"
          [attr.y]="label.y"
          [attr.fill]="label.fill"
          [attr.fill-opacity]="label.opacity ?? 1"
          [attr.font-family]="label.font === 'mono' ? 'var(--ck-font-mono)' : 'var(--ck-font-sans)'"
          [attr.font-size]="label.size"
          [attr.font-weight]="label.weight ?? 400"
          [attr.text-anchor]="label.anchor"
        >{{ label.text }}</text>
      }
      @if (peakMark; as mark) {
        <circle
          [attr.cx]="mark.x"
          [attr.cy]="mark.y"
          r="3.5"
          fill="var(--ck-bg-base)"
          stroke="var(--ck-fg-1)"
          stroke-width="1.5"
        />
        <text
          [attr.x]="mark.x + 9"
          [attr.y]="mark.y + 3.5"
          fill="var(--ck-fg-1)"
          font-family="var(--ck-font-mono)"
          font-size="9"
          [attr.text-anchor]="mark.anchor"
        >{{ mark.label }}</text>
      }
      @for (tick of axisTicks; track $index) {
        <text
          [attr.x]="tick.x"
          [attr.y]="tick.y"
          [attr.fill]="tick.fill"
          [attr.fill-opacity]="tick.opacity ?? 1"
          [attr.font-family]="'var(--ck-font-mono)'"
          [attr.font-size]="tick.size"
          [attr.text-anchor]="tick.anchor"
        >{{ tick.text }}</text>
      }
    </svg>
  `,
  styles: [':host { display: block; }'],
})
export class CkChartStreamComponent {
  @Input() series: CkStreamSeries[] = [];
  @Input() weekendStarts: number[] = [];
  /** Explicit gridlines; when empty, round steps are derived from the maximum. */
  @Input() gridLines: CkStreamGridLine[] = [];
  /** Formats a derived gridline value (e.g. `40 h`). */
  @Input() gridLabel: (value: number) => string = (value) => String(value);
  @Input() ticks: CkChartTick[] = [];
  @Input() peak: CkStreamPeak | null = null;
  @Input() width = 612;
  @Input() height = 196;
  @Input() maxValue: number | null = null;
  /** Scale the drawing to the host width (keeps the 612×196 composition). */
  @Input({ transform: booleanAttribute }) fluid = false;

  readonly inkId = ckChartUid('ck-stream-ink');
  readonly declaredId = ckChartUid('ck-stream-teal');
  readonly declaredSoftId = ckChartUid('ck-stream-teal-soft');

  readonly plotTop = 12;
  readonly plotBottom = 26;
  readonly plotLeft = 6;
  readonly plotRight = 118;

  get plotWidth(): number {
    return this.width - this.plotLeft - this.plotRight;
  }

  get plotHeight(): number {
    return this.height - this.plotTop - this.plotBottom;
  }

  get grid(): Array<{ y: number; label: string }> {
    const max = this.resolvedMax();
    if (this.gridLines.length) {
      return this.gridLines.map((line) => ({ y: this.yOf(line.value, max), label: line.label }));
    }
    if (!this.series.length) return [];
    const step = niceStep(max);
    const lines: Array<{ y: number; label: string }> = [];
    for (let value = step; value < max * 0.98 && lines.length < 6; value += step) {
      lines.push({ y: this.yOf(value, max), label: this.gridLabel(value) });
    }
    return lines;
  }

  get weekendBands(): StreamBand[] {
    const n = this.pointCount();
    if (n < 2) return [];
    const dx = this.plotWidth / (n - 1);
    return this.weekendStarts.map((start) => {
      const x = this.xOf(start) - dx / 2;
      return { x, y: this.plotTop, w: 2 * dx, h: this.plotHeight };
    });
  }

  get areas(): StreamArea[] {
    return this.layout().areas;
  }

  get seriesLabels(): StreamText[] {
    return this.layout().labels;
  }

  get peakMark(): { x: number; y: number; label: string; anchor: 'start' | 'end' } | null {
    const peak = this.peak;
    if (!peak) return null;
    const totals = this.totals();
    if (peak.index < 0 || peak.index >= totals.length) return null;
    const x = this.xOf(peak.index);
    return {
      x,
      y: this.yOf(totals[peak.index], this.resolvedMax()),
      label: peak.label,
      // Near the right edge the label would run into the ribbon names.
      anchor: x > this.plotLeft + this.plotWidth * 0.78 ? 'end' : 'start',
    };
  }

  get axisTicks(): StreamText[] {
    const n = this.pointCount();
    const last = Math.max(0, n - 1);
    return this.ticks.map((tick) => ({
      x: this.xOf(tick.index),
      y: this.height - 8,
      text: tick.label,
      fill: 'var(--ck-fg-3)',
      size: 8.5,
      anchor: tick.anchor ?? (tick.index === 0 ? 'start' : tick.index === last ? 'end' : 'middle'),
      font: 'mono',
    }));
  }

  private layout(): { areas: StreamArea[]; labels: StreamText[] } {
    const series = this.series;
    const n = this.pointCount();
    const areas: StreamArea[] = [];
    const labels: StreamText[] = [];
    if (n < 2 || !series.length) return { areas, labels };
    const max = this.resolvedMax();
    const stacked = accumulateStackedSeries(series.map((row) => row.values));
    const desired: number[] = [];
    stacked.forEach((band, index) => {
      const row = series[index];
      const tone = row.tone ?? 'ink';
      const upper = band.upper.map((value, i) => ({ x: this.xOf(i), y: this.yOf(value, max) }));
      const lower = band.lower.map((value, i) => ({ x: this.xOf(i), y: this.yOf(value, max) }));
      areas.push({
        d: band.lower.every((value) => value === 0)
          ? cubicSmoothAreaPath(upper, null, this.yOf(0, max))
          : cubicSmoothAreaPath(upper, lower),
        fill: this.fillFor(tone),
      });
      desired.push((upper[n - 1].y + lower[n - 1].y) / 2);
    });
    const rows = spreadLabelRows(desired, LABEL_ROW, this.plotTop + 6, this.plotTop + this.plotHeight - 12);
    series.forEach((row, index) => {
      const tone = row.tone ?? 'ink';
      const midY = rows[index];
      labels.push({
        x: this.plotLeft + this.plotWidth + 30,
        y: midY + 3,
        text: row.label,
        fill: ckChartToneVar(tone),
        size: 10.5,
        anchor: 'start',
        font: 'sans',
        weight: 500,
      });
      if (row.detail) {
        labels.push({
          x: this.plotLeft + this.plotWidth + 30,
          y: midY + 14,
          text: row.detail,
          fill: ckChartToneVar(tone),
          size: 9,
          anchor: 'start',
          font: 'mono',
          opacity: 0.75,
        });
      }
    });
    return { areas, labels };
  }

  private fillFor(tone: CkStreamTone): string {
    if (tone === 'declared') return `url(#${this.declaredId})`;
    if (tone === 'declared-soft') return `url(#${this.declaredSoftId})`;
    return `url(#${this.inkId})`;
  }

  private pointCount(): number {
    return this.series.reduce((len, row) => Math.max(len, row.values.length), 0);
  }

  private totals(): number[] {
    const n = this.pointCount();
    const totals = Array.from({ length: n }, () => 0);
    for (const row of this.series) {
      row.values.forEach((value, i) => {
        totals[i] += Number.isFinite(value) ? value : 0;
      });
    }
    return totals;
  }

  private resolvedMax(): number {
    if (this.maxValue != null && this.maxValue > 0) return this.maxValue;
    const peak = Math.max(0, ...this.totals());
    return peak || 1;
  }

  private xOf(index: number): number {
    const n = this.pointCount();
    if (n <= 1) return this.plotLeft;
    return this.plotLeft + index * (this.plotWidth / (n - 1));
  }

  private yOf(value: number, max: number): number {
    return this.plotTop + this.plotHeight - (this.plotHeight * Math.max(0, value)) / max;
  }
}

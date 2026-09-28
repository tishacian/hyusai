import { ChangeDetectionStrategy, Component, ElementRef, Input, inject } from '@angular/core';

import { hostPointerPoint, nearestDayIndex } from './chart-interact';
import { CkChartTipComponent } from './chart-tip.component';
import { ckChartUid } from './chart.types';

export const CK_CHART_PULSE_VALUES: readonly number[] = [1, 2, 1, 2, 1, 2, 1, 0, 0, 0];

@Component({
  selector: 'ck-chart-pulse',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CkChartTipComponent],
  template: `
    @if (points.length >= 2) {
      <svg
        [attr.viewBox]="'0 0 ' + width + ' ' + height"
        [attr.width]="width"
        [attr.height]="height"
        style="display:block;overflow:visible"
        (pointermove)="onMove($event)"
        (pointerleave)="onLeave()"
      >
        <defs>
          <linearGradient [attr.id]="fadeId" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stop-color="var(--ck-data-measured)" stop-opacity="0.22" />
            <stop offset="1" stop-color="var(--ck-data-measured)" stop-opacity="0" />
          </linearGradient>
          <radialGradient [attr.id]="glowId">
            <stop offset="0" stop-color="var(--ck-data-zero)" stop-opacity="0.55" />
            <stop offset="1" stop-color="var(--ck-data-zero)" stop-opacity="0" />
          </radialGradient>
        </defs>
        @if (wash) {
          <rect
            [attr.x]="wash.x"
            [attr.y]="4"
            [attr.width]="wash.w"
            [attr.height]="baselineY - 4"
            rx="4"
            fill="var(--ck-data-zero)"
            fill-opacity="0.07"
          />
        }
        <line
          [attr.x1]="8"
          [attr.y1]="baselineY"
          [attr.x2]="width - 4"
          [attr.y2]="baselineY"
          stroke="var(--ck-fg-1)"
          stroke-opacity="0.15"
          stroke-width="1"
        />
        <path [attr.d]="area" [attr.fill]="'url(#' + fadeId + ')'" />
        <path
          [attr.d]="liveLine"
          fill="none"
          stroke="var(--ck-data-measured)"
          stroke-width="1.5"
          stroke-linejoin="round"
        />
        @if (staleLine) {
          <path
            [attr.d]="staleLine"
            fill="none"
            stroke="var(--ck-data-zero)"
            stroke-width="2.5"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        }
        <circle [attr.cx]="end.x" [attr.cy]="end.y" r="10" [attr.fill]="'url(#' + glowId + ')'" />
        <circle [attr.cx]="end.x" [attr.cy]="end.y" r="3.2" fill="var(--ck-data-zero)" />
        @if (zeroLabel) {
          <text
            [attr.x]="zeroX"
            y="20"
            fill="var(--ck-signal-neg)"
            font-family="var(--ck-font-mono)"
            font-size="9"
            font-weight="600"
            text-anchor="middle"
          >{{ zeroLabel }}</text>
        }
        @if (startLabel) {
          <text
            x="8"
            [attr.y]="height - 3"
            fill="var(--ck-fg-1)"
            fill-opacity="0.45"
            font-family="var(--ck-font-mono)"
            font-size="8"
          >{{ startLabel }}</text>
        }
        @if (endLabel) {
          <text
            [attr.x]="width - 7"
            [attr.y]="height - 3"
            fill="var(--ck-signal-neg)"
            font-family="var(--ck-font-mono)"
            font-size="8"
            text-anchor="end"
          >{{ endLabel }}</text>
        }
      </svg>
      <ck-chart-tip [open]="tipOpen" [title]="tipTitle" [lines]="[]" [x]="tipX" [y]="tipY" />
    }
  `,
  styles: [':host { display: block; position: relative; }'],
})
export class CkChartPulseComponent {
  private readonly host = inject(ElementRef<HTMLElement>);
  @Input() values: number[] = [...CK_CHART_PULSE_VALUES];
  @Input() staleFrom: number | null = null;
  @Input() width = 195;
  @Input() height = 60;
  @Input() startLabel = '';
  @Input() endLabel = '';
  @Input() zeroLabel = '';
  @Input() valueLabel: (value: number, index: number) => string = (value) => String(value);

  tipOpen = false;
  tipTitle = '';
  tipX = 0;
  tipY = 0;

  readonly fadeId = ckChartUid('ck-pulse-fade');
  readonly glowId = ckChartUid('ck-pulse-glow');

  get baselineY(): number {
    return this.height - 16;
  }

  get points(): { x: number; y: number }[] {
    const values = this.values.filter((value) => Number.isFinite(value));
    if (values.length < 2) return [];
    const max = Math.max(0, ...values) || 1;
    const left = 8;
    const right = this.width - 7;
    const peakY = 12;
    const step = (right - left) / (values.length - 1);
    return values.map((value, i) => ({
      x: left + i * step,
      y: this.baselineY - (Math.max(0, value) / max) * (this.baselineY - peakY),
    }));
  }

  get staleIndex(): number {
    if (this.staleFrom != null && this.staleFrom >= 0) {
      return Math.min(this.staleFrom, Math.max(0, this.points.length - 1));
    }
    const values = this.values.filter((value) => Number.isFinite(value));
    let index = values.length;
    for (let i = values.length - 1; i >= 0; i -= 1) {
      if (values[i] === 0) index = i;
      else break;
    }
    return index;
  }

  get area(): string {
    const pts = this.points;
    if (pts.length < 2) return '';
    const live = pts.slice(0, Math.max(2, this.staleIndex + 1));
    const body = live.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x},${p.y}`).join(' ');
    return `${body} L${live[live.length - 1].x},${this.baselineY} L${live[0].x},${this.baselineY} Z`;
  }

  get liveLine(): string {
    const pts = this.points.slice(0, this.staleIndex + 1);
    if (pts.length < 2) return '';
    return pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x},${p.y}`).join(' ');
  }

  get staleLine(): string {
    const pts = this.points.slice(Math.max(0, this.staleIndex));
    if (pts.length < 2) return '';
    return pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x},${p.y}`).join(' ');
  }

  get wash(): { x: number; w: number } | null {
    const pts = this.points;
    const stale = this.staleIndex;
    if (stale >= pts.length - 1) return null;
    const x = Math.max(0, pts[stale].x - 10);
    return { x, w: this.width - x };
  }

  get end(): { x: number; y: number } {
    return this.points[this.points.length - 1] ?? { x: 0, y: 0 };
  }

  get zeroX(): number {
    const wash = this.wash;
    return wash ? wash.x + wash.w / 2 : this.width - 29;
  }

  onMove(event: PointerEvent): void {
    const values = this.values.filter((value) => Number.isFinite(value));
    const index = nearestDayIndex(event.offsetX, 8, this.width - 15, values.length);
    const pt = hostPointerPoint(this.host.nativeElement, event.clientX, event.clientY);
    this.tipX = pt.x;
    this.tipY = pt.y;
    this.tipTitle = this.valueLabel(values[index] ?? 0, index);
    this.tipOpen = true;
  }

  onLeave(): void {
    this.tipOpen = false;
  }
}
